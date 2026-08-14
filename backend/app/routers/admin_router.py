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
from ..auth import get_current_user, require_role
from ..config import settings
from ..database import get_db
from ..services import paging
from ..services import currency
from ..models import AuditLog, Product, User

router = APIRouter(prefix="/api/admin", tags=["admin"])

BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "backups"
BACKUP_KEEP = 20

# Accepted CSV header aliases -> canonical field
HEADER_ALIASES = {
    "nappi": "nappi", "nappi_code": "nappi", "nappicode": "nappi",
    "barcode": "barcode", "ean": "barcode", "gtin": "barcode",
    "name": "name", "description": "name", "product": "name", "product_name": "name",
    "cost": "cost", "cost_price": "cost", "trade_price": "cost", "nett": "cost", "net_price": "cost",
    "price": "price", "selling_price": "price", "retail": "price", "retail_price": "price", "sep": "price",
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
    if not ({"cost", "price"} & field_map.keys()):
        raise HTTPException(status_code=400, detail="CSV needs a cost and/or price column")

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

        line = schemas.PriceImportLine(
            row=index, key=key, product_name=product.name, matched=True,
            old_cost=product.cost_price, old_price=product.unit_price,
        )
        changed = False
        if body.update_cost and new_cost is not None and abs(new_cost - product.cost_price) > 0.005:
            line.new_cost = new_cost
            changed = True
        if body.update_selling and new_price is not None and abs(new_price - product.unit_price) > 0.005:
            line.new_price = new_price
            changed = True

        if not changed:
            line.message = "No change"
        elif body.apply:
            if line.new_cost is not None:
                product.cost_price = line.new_cost
            if line.new_price is not None:
                product.unit_price = line.new_price
            line.message = "Updated"
            updated += 1
        else:
            line.message = "Would update"
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
@router.get("/audit", response_model=list[schemas.AuditLogOut])
def audit_log(
    username: str = "",
    limit: int = 200,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "pharmacist")),
):
    query = db.query(AuditLog)
    if username:
        query = query.filter(AuditLog.username.ilike(f"%{username}%"))
    return query.order_by(AuditLog.created_at.desc()).limit(limit).all()


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
def _db_path() -> Path:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        raise HTTPException(status_code=400, detail="Backups are only supported for SQLite databases")
    return Path(url.split("///")[-1]).resolve()


def create_backup() -> Path:
    """Consistent online backup via the SQLite backup API (safe while running)."""
    BACKUP_DIR.mkdir(exist_ok=True)
    target = BACKUP_DIR / f"rx3000_{datetime.now():%Y%m%d_%H%M%S}.db"
    source = sqlite3.connect(str(_db_path()))
    try:
        dest = sqlite3.connect(str(target))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()

    backups = sorted(BACKUP_DIR.glob("rx3000_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[BACKUP_KEEP:]:
        old.unlink(missing_ok=True)
    return target


@router.post("/backup", response_model=schemas.BackupOut)
def backup_now(_: User = Depends(require_role("admin"))):
    path = create_backup()
    stat = path.stat()
    return schemas.BackupOut(
        filename=path.name, size_bytes=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_mtime),
    )


@router.get("/backups", response_model=list[schemas.BackupOut])
def list_backups(_: User = Depends(require_role("admin"))):
    if not BACKUP_DIR.exists():
        return []
    out = []
    for path in sorted(BACKUP_DIR.glob("rx3000_*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        out.append(schemas.BackupOut(
            filename=path.name, size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime),
        ))
    return out


@router.get("/backups/{filename}/download")
def download_backup(filename: str, _: User = Depends(require_role("admin"))):
    # filenames are server-generated; reject anything that isn't a plain name
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = (BACKUP_DIR / filename).resolve()
    if not path.is_file() or path.parent != BACKUP_DIR.resolve():
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")
