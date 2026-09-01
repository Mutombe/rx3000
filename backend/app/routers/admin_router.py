"""Admin surface: supplier price-file imports, audit log, database backups."""
import csv
import io
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import require_platform_admin, get_current_user, require_role
from ..config import settings
from ..database import get_db
from ..services import paging
from ..services import backup_verify
from ..services import currency
from ..models import AuditLog, Product, User

router = APIRouter(prefix="/api/admin", tags=["admin"])

# One backup folder and one definition of what a backup file is, shared with
# the /api/system/backup route. They used to disagree on both.
from ..services.backup import BACKUP_DIR, existing_backups
BACKUP_KEEP = 20

# Accepted CSV header aliases -> canonical field
HEADER_ALIASES = {
    "nappi": "nappi", "nappi_code": "nappi", "nappicode": "nappi",
    "barcode": "barcode", "ean": "barcode", "gtin": "barcode",
    "name": "name", "description": "name", "product": "name", "product_name": "name",
    "cost": "cost", "cost_price": "cost", "trade_price": "cost", "nett": "cost", "net_price": "cost",
    "price": "price", "selling_price": "price", "retail": "price", "retail_price": "price",
    # SEP is the published maximum, not what to charge. It used to be aliased to
    # "price", so importing a file with a SEP column set every matched product's
    # selling price to the regulatory ceiling — a pricing policy decided by an
    # alias table, and `sep_price` stayed 0 on all 545 products.
    "sep": "sep", "sep_price": "sep", "single_exit_price": "sep",
    "max_price": "sep", "maximum_price": "sep",
    # The reference price for the molecule. pricing.py already caps scheme
    # charges at it, but only when it is greater than zero, which it never was,
    # so `apply_mmap` on a scheme has been silently doing nothing.
    "mmap": "mmap", "mmap_price": "mmap", "reference_price": "mmap",
    # What the medicine actually is. This is the only thing that makes two
    # products interchangeable, and it was recorded on 113 of 534 products
    # because the sole way to set it was to type it into each one. A price file
    # usually carries it, under one of these headings.
    "active_ingredient": "ingredient", "ingredient": "ingredient",
    "generic": "ingredient", "generic_name": "ingredient",
    "molecule": "ingredient", "inn": "ingredient",
    "strength": "strength", "pack": "pack_size", "pack_size": "pack_size",
}


def _to_float(raw: str) -> float | None:
    cleaned = currency.strip_symbols(raw)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---------- supplier price files ----------
@router.post("/price-import", response_model=schemas.PriceImportResult)
def price_import(
    body: schemas.PriceImportRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "pharmacist")),
):
    """Import a supplier price file (CSV). Matches on NAPPI, barcode, then name.

    Run with apply=False first for a preview of exactly what would change.
    """
    text = body.csv_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No CSV content supplied")

    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no header row")

    field_map = {}
    for column in reader.fieldnames:
        canonical = HEADER_ALIASES.get((column or "").strip().lower().replace(" ", "_"))
        if canonical and canonical not in field_map:
            field_map[canonical] = column
    if not ({"nappi", "barcode", "name"} & field_map.keys()):
        raise HTTPException(
            status_code=400,
            detail="CSV needs an identifying column: nappi, barcode or name",
        )
    # A regulated price list carries SEP and MMAP and no trading prices at all,
    # and that is a legitimate file to import. It used to be accepted only
    # because a SEP column was mis-aliased to the selling price; once that was
    # corrected this guard started rejecting it, which the test caught.
    if not ({"cost", "price", "sep", "mmap", "ingredient"} & field_map.keys()):
        raise HTTPException(
            status_code=400,
            detail=("CSV needs at least one column to import: cost, selling "
                    "price, SEP, MMAP, or the active ingredient."),
        )

    lines: list[schemas.PriceImportLine] = []
    matched = updated = 0

    for index, row in enumerate(reader, start=2):
        nappi = (row.get(field_map.get("nappi", ""), "") or "").strip()
        barcode = (row.get(field_map.get("barcode", ""), "") or "").strip()
        name = (row.get(field_map.get("name", ""), "") or "").strip()
        key = nappi or barcode or name
        if not key:
            continue

        product = None
        if nappi:
            product = db.query(Product).filter(Product.nappi_code == nappi).first()
        if not product and barcode:
            product = db.query(Product).filter(Product.barcode == barcode).first()
        if not product and name:
            product = db.query(Product).filter(Product.name.ilike(name)).first()

        if not product:
            lines.append(schemas.PriceImportLine(
                row=index, key=key, matched=False, message="No matching product",
            ))
            continue

        matched += 1
        new_cost = _to_float(row.get(field_map.get("cost", ""), "")) if "cost" in field_map else None
        new_price = _to_float(row.get(field_map.get("price", ""), "")) if "price" in field_map else None
        new_ingredient = (row.get(field_map.get("ingredient", ""), "") or "").strip()
        new_strength = (row.get(field_map.get("strength", ""), "") or "").strip()
        new_pack = (row.get(field_map.get("pack_size", ""), "") or "").strip()
        new_sep = _to_float(row.get(field_map.get("sep", ""), "")) if "sep" in field_map else None
        new_mmap = _to_float(row.get(field_map.get("mmap", ""), "")) if "mmap" in field_map else None

        line = schemas.PriceImportLine(
            row=index, key=key, product_name=product.name, matched=True,
            old_cost=product.cost_price, old_price=product.unit_price,
            old_sep=product.sep_price or None, old_mmap=product.mmap_price or None,
        )
        changed = False
        if body.update_cost and new_cost is not None and abs(new_cost - product.cost_price) > 0.005:
            line.new_cost = new_cost
            changed = True
        if body.update_selling and new_price is not None and abs(new_price - product.unit_price) > 0.005:
            line.new_price = new_price
            changed = True
        # Always taken when the column is present. These are published figures,
        # not a pricing choice, so there is no "update reference prices?" switch
        # to leave off, and a stale ceiling is worse than none, because it reads
        # as though it has been checked.
        if new_sep is not None and abs(new_sep - (product.sep_price or 0)) > 0.005:
            line.new_sep = new_sep
            changed = True
        if new_mmap is not None and abs(new_mmap - (product.mmap_price or 0)) > 0.005:
            line.new_mmap = new_mmap
            changed = True
        # Descriptive fields are filled in where they are missing and left alone
        # where they are not. A price file overwriting a pharmacy's own carefully
        # corrected ingredient with the supplier's spelling of it would make the
        # import something nobody dares run twice.
        filled = []
        for field, value in (("active_ingredient", new_ingredient),
                             ("strength", new_strength),
                             ("pack_size", new_pack)):
            if value and not (getattr(product, field, "") or "").strip():
                filled.append(field.replace("_", " "))
                if body.apply:
                    setattr(product, field, value[:160])
                changed = True

        # Named in the line's message rather than given columns of their own:
        # they are filled in once and then never again, so a column would be
        # empty on every subsequent import of the same file.
        filled_note = f" (filled in {', '.join(filled)})" if filled else ""

        if not changed:
            line.message = "No change"
        elif body.apply:
            if line.new_cost is not None:
                product.cost_price = line.new_cost
            if line.new_price is not None:
                product.unit_price = line.new_price
            if line.new_sep is not None:
                product.sep_price = line.new_sep
            if line.new_mmap is not None:
                product.mmap_price = line.new_mmap
            line.message = "Updated" + filled_note
            updated += 1
        else:
            line.message = "Would update" + filled_note
            updated += 1

        lines.append(line)

    if body.apply:
        db.commit()

    return schemas.PriceImportResult(
        applied=body.apply,
        total_rows=len(lines),
        matched=matched,
        unmatched=len(lines) - matched,
        updated=updated,
        lines=lines[:500],
    )


# ---------- audit log ----------
# GET /audit was here, capped at 200. /audit/paged replaced it, and an audit
# trail that silently stops at two hundred entries is the one list where a
# cap is not an inconvenience but a hole.


@router.get("/audit/paged")
def audit_log_paged(
    username: str = "",
    page: int = 1,
    per_page: int = paging.DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "pharmacist")),
):
    """The audit log, paged.

    The largest truncation in the product: 22,487 entries behind a cap of 200.
    This is the record you reach for when something has gone wrong or a
    transaction is disputed — precisely the moment when "the last 200 events"
    is not an answer. The oldest 99% was unreachable from the screen that exists
    to show it.
    """
    query = db.query(AuditLog)
    if username:
        query = query.filter(AuditLog.username.ilike(f"%{username}%"))
    result = paging.page(query.order_by(AuditLog.created_at.desc()),
                         page=page, per_page=per_page)
    return result.envelope(
        lambda x: schemas.AuditLogOut.model_validate(x, from_attributes=True).model_dump()
    )


# ---------- backups ----------
#
# Platform-level, not a pharmacy's. A backup is the whole database — every
# pharmacy on the deployment, all of their patients, so a customer's own
# administrator downloading one would walk out with every other customer's
# records in a single file. That was harmless while the system served one
# pharmacy and became a complete bypass of the tenancy the moment it served
# two, which is exactly the kind of permission that stops being right without
# anybody changing it.
def _db_path() -> Path:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        raise HTTPException(status_code=400, detail="Backups are only supported for SQLite databases")
    return Path(url.split("///")[-1]).resolve()


def create_backup() -> Path:
    """Consistent online backup via the SQLite backup API (safe while running)."""
    BACKUP_DIR.mkdir(exist_ok=True)
    target = BACKUP_DIR / f"rx5000_{datetime.now():%Y%m%d_%H%M%S}.db"
    source = sqlite3.connect(str(_db_path()))
    try:
        dest = sqlite3.connect(str(target))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()

    # Prove it before trusting it. A file having been written is not a backup;
    # the system we are replacing lists a 0.00 MByte archive beside its good
    # ones and a pharmacy learns which is which on the day it needs to restore.
    verdict = backup_verify.verify_and_record(target, _db_path())

    _prune()
    return target


def _prune() -> None:
    """Keep the most recent backups, but never at the cost of a verified one.

    The obvious retention rule, keep the newest N, quietly does the wrong
    thing the moment backups start failing: three broken nightly runs push the
    last good copy off the end, and the pharmacy is left holding only files that
    cannot be restored. So verified backups are kept in preference to unverified
    ones, and only then by age.
    """
    backups = sorted(
        existing_backups(),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    verified, unverified = [], []
    for path in backups:
        verdict = backup_verify.read_verdict(path)
        (verified if (verdict or {}).get("ok") else unverified).append(path)

    # Newest good ones first, then fill the remainder with the rest.
    keep = verified[:BACKUP_KEEP]
    if len(keep) < BACKUP_KEEP:
        keep += unverified[: BACKUP_KEEP - len(keep)]
    keeping = set(keep)

    for path in backups:
        if path in keeping:
            continue
        path.unlink(missing_ok=True)
        backup_verify.sidecar_for(path).unlink(missing_ok=True)


@router.post("/backup", response_model=schemas.BackupOut)
def backup_now(_: User = Depends(require_platform_admin)):
    path = create_backup()
    stat = path.stat()
    return schemas.BackupOut(
        filename=path.name, size_bytes=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_mtime),
    )


@router.get("/backups", response_model=list[schemas.BackupOut])
def list_backups(_: User = Depends(require_platform_admin)):
    if not BACKUP_DIR.exists():
        return []
    out = []
    for path in sorted(existing_backups(), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        verdict = backup_verify.read_verdict(path)
        out.append(schemas.BackupOut(
            filename=path.name, size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime),
            # A listing that shows only name, date and size cannot tell a good
            # backup from a failed one, which is the whole problem.
            verified=bool((verdict or {}).get("ok")),
            checked_at=(datetime.fromisoformat(verdict["verified_at"])
                        if verdict and verdict.get("verified_at") else None),
            problem=("; ".join(verdict.get("problems", []))
                     if verdict and not verdict.get("ok") else ""),
        ))
    return out


@router.post("/backups/{filename}/verify", response_model=schemas.BackupOut)
def verify_backup(filename: str, _: User = Depends(require_platform_admin)):
    """Re-check an existing backup.

    Worth having on demand as well as on write: a file that verified when it was
    made can still rot on a failing disk, and the point of asking is to find that
    out before the restore rather than during it.
    """
    path = (BACKUP_DIR / filename).resolve()
    if path.parent != BACKUP_DIR.resolve() or not path.exists():
        raise HTTPException(status_code=404, detail="That backup no longer exists.")
    verdict = backup_verify.verify_and_record(path, _db_path())
    stat = path.stat()
    return schemas.BackupOut(
        filename=path.name, size_bytes=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_mtime),
        verified=verdict["ok"],
        checked_at=datetime.fromisoformat(verdict["verified_at"]),
        problem="; ".join(verdict.get("problems", [])),
    )


@router.get("/backups/{filename}/download")
def download_backup(filename: str, _: User = Depends(require_platform_admin)):
    # filenames are server-generated; reject anything that isn't a plain name
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = (BACKUP_DIR / filename).resolve()
    if not path.is_file() or path.parent != BACKUP_DIR.resolve():
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")
