"""One place a scan is resolved, whatever scanned it and wherever it landed.

The till, the stock screen and goods receipt all ask the same question — *what
is this?* — and before this router they each answered it differently. The POS
looked up `barcode` then gave up. Stock searched product names. Receiving had no
scanning at all. Three answers to one question is three places for the answer to
be wrong, and it guarantees that a pack which scans at the till mysteriously
does not scan at the back door.

So there is one endpoint. It takes the raw string, whether it arrived from a
keyboard-wedge scanner on a desktop or a phone camera, and returns the same
shape either way. `context` only changes what extra information comes back —
branch stock for a till, the matching order line for a receipt — never how the
code itself is interpreted.

Not finding something is a first-class result here, not an error. A 404 gives
the operator a dead end; this returns `found: false` along with the closest
candidates and the batch data we did manage to read, so the next tap is a choice
rather than a retype.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import nulls_last, or_
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Product, ProductBarcode, PurchaseOrderItem, StockBatch, User
from ..services import barcodes as bc
from ..services import branches as branch_svc

router = APIRouter(prefix="/api/scan", tags=["scan"], dependencies=[Depends(get_current_user)])


class ScanIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=200)
    # Where the scan happened. Shapes the extras, not the lookup.
    context: str = "pos"          # pos | stock | receive
    branch_id: int | None = None
    order_id: int | None = None   # receiving against a specific purchase order


class LinkIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    product_id: int
    pack_size: int = 1
    label: str = ""


def _product_brief(db: Session, p: Product, branch_id: int | None) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "category": p.category,
        "schedule": p.schedule,
        "strength": p.strength,
        "dosage_form": p.dosage_form,
        "pack_size": p.pack_size,
        "unit_price": p.unit_price,
        "cost_price": p.cost_price,
        "barcode": p.barcode,
        "nappi_code": p.nappi_code,
        "quantity_on_hand": (
            branch_svc.on_hand(db, p.id, branch_id) if branch_id else p.quantity_on_hand
        ),
    }


def _match(db: Session, keys: list[str]) -> tuple[Product | None, int, str]:
    """Find the product, its pack multiplier, and how we recognised it.

    Order matters. The alias table wins over the product's own column because an
    alias can carry a pack size, and an outer carton scanned at goods receipt
    must book in the case rather than a single unit.
    """
    if not keys:
        return None, 1, ""

    alias = (
        db.query(ProductBarcode)
        .filter(ProductBarcode.code.in_(keys))
        .first()
    )
    if alias:
        product = db.query(Product).get(alias.product_id)
        if product:
            return product, max(1, alias.pack_size or 1), (alias.label or "alternate code")

    product = (
        db.query(Product)
        .filter(Product.barcode.in_(keys), Product.barcode != "")
        .first()
    )
    if product:
        return product, 1, "barcode"

    product = (
        db.query(Product)
        .filter(Product.nappi_code.in_(keys), Product.nappi_code != "")
        .first()
    )
    if product:
        return product, 1, "NAPPI code"
    return None, 1, ""


def _suggestions(db: Session, scan: bc.Scan, limit: int = 5) -> list[dict]:
    """What to offer when the code is unknown.

    A bare 'not found' makes the operator start again somewhere else. If the
    scanned string looks like text, it is very likely someone typing a product
    name into the scan box, and a name search is exactly right. If it is digits,
    a partial match catches the case where a code was stored with a typo or a
    supplier prefix.
    """
    text = (scan.code or scan.raw).strip()
    if len(text) < 3:
        return []
    like = f"%{text}%"
    rows = (
        db.query(Product)
        .filter(Product.active)
        .filter(or_(
            Product.name.ilike(like),
            Product.barcode.ilike(like),
            Product.nappi_code.ilike(like),
            Product.active_ingredient.ilike(like),
        ))
        .order_by(Product.name)
        .limit(limit)
        .all()
    )
    return [{"id": p.id, "name": p.name, "barcode": p.barcode} for p in rows]


@router.post("")
def resolve(body: ScanIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    scan = bc.read(body.code)
    branch_id = body.branch_id or branch_svc.default_branch(db).id
    product, pack_multiplier, matched_on = _match(db, scan.keys)

    warnings = list(scan.warnings)
    out: dict = {
        "found": product is not None,
        "code": scan.code,
        "symbology": scan.symbology,
        "matched_on": matched_on,
        "quantity_multiplier": pack_multiplier,
        # Read straight off the pack. Goods receipt uses these to fill its form;
        # the till ignores them.
        "batch_number": scan.batch,
        "expiry_date": scan.expiry.isoformat() if scan.expiry else None,
        "serial": scan.serial,
        "product": None,
        "suggestions": [],
        "warnings": warnings,
    }

    if not product:
        out["suggestions"] = _suggestions(db, scan)
        # The checksum note is noise when we found the item anyway — a pharmacy's
        # own repack labels fail it routinely. It only earns its place here.
        out["message"] = (
            "Nothing is stocked under that code."
            if not out["suggestions"]
            else "Nothing is stocked under that code. Closest matches are below."
        )
        return out

    # A code we recognised but whose checksum disagrees is fine; drop the note
    # so a correct scan never shows a warning.
    out["warnings"] = [w for w in warnings if "check digit" not in w]
    out["product"] = _product_brief(db, product, branch_id)

    if body.context == "pos":
        # The till needs to know it can actually sell this, before the operator
        # has added it and started taking money.
        on_hand = out["product"]["quantity_on_hand"]
        if on_hand <= 0:
            out["warnings"].append("This branch has none of that in stock.")
        if product.schedule >= 5:
            out["warnings"].append(
                f"Schedule {product.schedule}. This must be dispensed against a "
                "prescription and entered in the register, not sold at the till."
            )
    elif body.context in ("stock", "receive"):
        # Offer the batch already on the shelf, so a repeat delivery of the same
        # lot tops up rather than creating a second batch with the same number.
        existing = (
            db.query(StockBatch)
            .filter(StockBatch.product_id == product.id)
            .filter(StockBatch.quantity_remaining > 0)
            # Nearest expiry first, and undated batches last — SQLite and
            # Postgres disagree on where NULLs sort, so it is said explicitly.
            .order_by(nulls_last(StockBatch.expiry_date.asc()))
            .limit(3)
            .all()
        )
        out["open_batches"] = [
            {
                "id": b.id,
                "batch_number": b.batch_number,
                "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
                "quantity_remaining": b.quantity_remaining,
            }
            for b in existing
        ]

    if body.context == "receive" and body.order_id:
        line = (
            db.query(PurchaseOrderItem)
            .filter(PurchaseOrderItem.order_id == body.order_id)
            .filter(PurchaseOrderItem.product_id == product.id)
            .first()
        )
        if line:
            outstanding = max(0, (line.quantity_ordered or 0) - (line.quantity_received or 0))
            out["order_line"] = {
                "id": line.id,
                "quantity_ordered": line.quantity_ordered,
                "quantity_received": line.quantity_received,
                "outstanding": outstanding,
                "unit_cost": line.unit_cost,
            }
            if outstanding == 0:
                out["warnings"].append(
                    "Every unit on this order line has already been booked in. "
                    "Receiving more will over-receive the order."
                )
        else:
            # Not an error. Deliveries routinely include a substitution, and the
            # receiver needs to be told rather than blocked.
            out["warnings"].append(
                "That item is not on this order. It can still be booked in, but "
                "check the delivery note against what was ordered."
            )
    return out


@router.post("/link")
def link(body: LinkIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Teach the system a code it did not know.

    This is the payoff of the miss path. The operator scanned something, we did
    not have it, they picked the product by hand — and that pairing is worth
    keeping, because the next person to scan that pack should not repeat the
    search. A pharmacy that receives from two wholesalers teaches the catalogue
    its second set of codes in about a week of ordinary work, without anyone
    sitting down to do data entry.
    """
    scan = bc.read(body.code)
    if not scan.code:
        raise HTTPException(status_code=400, detail="That code is empty; nothing to save.")

    product = db.query(Product).get(body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="That product no longer exists.")

    existing = (
        db.query(ProductBarcode)
        .filter(ProductBarcode.code.in_(scan.keys or [scan.code]))
        .first()
    )
    if existing:
        if existing.product_id == product.id:
            return {"ok": True, "already": True,
                    "message": f"{product.name} already answers to that code."}
        other = db.query(Product).get(existing.product_id)
        raise HTTPException(
            status_code=409,
            detail=(
                f"That code is already assigned to {other.name if other else 'another product'}. "
                "Remove it there first, or the same scan would mean two things."
            ),
        )
    if db.query(Product).filter(Product.barcode == scan.code, Product.id != product.id).first():
        raise HTTPException(
            status_code=409,
            detail="That code is another product's main barcode. Change it there first.",
        )

    row = ProductBarcode(
        product_id=product.id,
        code=scan.code,
        pack_size=max(1, body.pack_size or 1),
        label=body.label.strip(),
        source="learned",
        created_by=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    # A product with no barcode at all should adopt the first one it is taught,
    # so shelf labels and the product page stop showing a blank.
    if not (product.barcode or "").strip() and row.pack_size == 1:
        product.barcode = scan.code
    db.commit()
    return {
        "ok": True,
        "id": row.id,
        "message": f"That code will now find {product.name}.",
    }


@router.get("/codes/{product_id}")
def codes_for(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).get(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="That product no longer exists.")
    rows = (
        db.query(ProductBarcode)
        .filter(ProductBarcode.product_id == product_id)
        .order_by(ProductBarcode.created_at.asc())
        .all()
    )
    return {
        "primary": product.barcode or "",
        "codes": [
            {
                "id": r.id, "code": r.code, "pack_size": r.pack_size,
                "label": r.label, "source": r.source,
            }
            for r in rows
        ],
    }


@router.delete("/codes/{code_id}")
def remove_code(code_id: int, db: Session = Depends(get_db)):
    row = db.query(ProductBarcode).get(code_id)
    if not row:
        raise HTTPException(status_code=404, detail="That code has already been removed.")
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "That code will no longer find this product."}


class ReceiveLineIn(BaseModel):
    """One scanned pack, booked in against an order."""
    product_id: int
    quantity: int = Field(..., gt=0)
    batch_number: str = ""
    expiry_date: str = ""      # ISO date; blank where the pack carries none
    unit_cost: float | None = None


@router.post("/receive/{order_id}")
def receive_line(
    order_id: int, body: ReceiveLineIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Book in what actually arrived, one line at a time.

    The existing path marks a whole order received and books every line in at
    its full ordered quantity. That is a reasonable shortcut and it stays, but
    it is not what happens at a back door: deliveries arrive short, arrive
    split across two days, and arrive with a substitution. Scanning only helps
    if the count that reaches stock is the count that came off the van.

    Batch and expiry are taken from the request rather than invented, because
    by the time this is called they have usually been read off the pack's
    DataMatrix rather than typed.
    """
    from datetime import date as _date

    from .. import helpers
    from ..models import PurchaseOrder

    order = db.query(PurchaseOrder).get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="That order no longer exists.")
    if order.status == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="This order was cancelled. Reinstate it before booking stock in against it.",
        )

    product = db.query(Product).get(body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="That product no longer exists.")

    expiry = None
    if body.expiry_date:
        try:
            expiry = _date.fromisoformat(body.expiry_date)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"'{body.expiry_date}' is not a date we can read. Use YYYY-MM-DD.",
            )
        if expiry <= _date.today():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"That pack expired on {expiry.isoformat()}. Do not book it in. "
                    "Quarantine it and raise it with the supplier."
                ),
            )

    line = (
        db.query(PurchaseOrderItem)
        .filter(PurchaseOrderItem.order_id == order_id)
        .filter(PurchaseOrderItem.product_id == product.id)
        .first()
    )
    if line:
        line.quantity_received = (line.quantity_received or 0) + body.quantity
        if body.unit_cost:
            line.unit_cost = body.unit_cost
    else:
        # A substitution or an extra. Recorded on the order so the delivery note
        # and the order can still be reconciled afterwards.
        line = PurchaseOrderItem(
            order_id=order_id, product_id=product.id,
            quantity_ordered=0, quantity_received=body.quantity,
            unit_cost=body.unit_cost or product.cost_price or 0.0,
        )
        db.add(line)

    batch = (body.batch_number or "").strip() or f"{order.order_number}-{product.id}"
    if product.category == "airtime":
        helpers.move_stock(db, product, body.quantity, "receive", user.id,
                           reference=order.order_number)
    else:
        helpers.receive_stock_batch(
            db, product, body.quantity, user.id,
            batch_number=batch, expiry_date=expiry,
            unit_cost=body.unit_cost or line.unit_cost or None,
            reference=order.order_number,
        )
    helpers.record_register_entry(db, product, body.quantity, "receive", user.id,
                                  reference=order.order_number)
    if body.unit_cost:
        product.cost_price = body.unit_cost

    if order.status == "draft":
        order.status = "sent"
    db.commit()

    outstanding = sum(
        max(0, (l.quantity_ordered or 0) - (l.quantity_received or 0)) for l in order.items
    )
    return {
        "ok": True,
        "outstanding": outstanding,
        "quantity_received": line.quantity_received,
        "message": (
            f"{body.quantity} × {product.name} booked in on batch {batch}."
            + (" Nothing further is outstanding on this order." if outstanding == 0 else "")
        ),
    }
