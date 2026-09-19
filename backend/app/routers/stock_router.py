from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import auth, helpers, schemas
from ..auth import get_current_user, require_role
from ..database import get_db
from ..services import paging
from ..services import permissions
from ..services import posting
from ..models import (
    Dispensing, PrescriptionItem, Product, PurchaseOrder, PurchaseOrderItem,
    Sale, SaleItem, StockBatch, StockMovement, Supplier, User,
)

router = APIRouter(prefix="/api", tags=["stock"], dependencies=[Depends(get_current_user)])


# ---------- products ----------
def _product_search(db: Session, q: str, category: str, low_stock: bool,
                    category_id: int = 0):
    query = db.query(Product).filter(Product.active)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Product.name.ilike(like),
            Product.barcode.ilike(like),
            Product.nappi_code.ilike(like),
            # The code the shop's own staff know the line by, which is what
            # they read off a shelf label when the name is ambiguous.
            Product.stock_code.ilike(like),
        ))
    if category:
        query = query.filter(Product.category == category)
    if category_id:
        # The pharmacy's own department, which is a different question from
        # `category` above — see StockCategory.
        query = query.filter(Product.category_id == category_id)
    if low_stock:
        query = query.filter(Product.quantity_on_hand <= Product.reorder_level)
    return query.order_by(Product.name)


@router.get("/products", response_model=list[schemas.ProductOut])
def list_products(q: str = "", category: str = "", category_id: int = 0,
                  low_stock: bool = False, limit: int = 300,
                  db: Session = Depends(get_db)):
    """Capped list, for pickers and typeaheads that want a shortlist."""
    return _product_search(db, q, category, low_stock, category_id).limit(limit).all()


@router.delete("/products/{product_id}")
def deactivate_product(product_id: int, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """Retire a product. Deactivates rather than deletes.

    A product that has ever been sold or dispensed cannot be removed: the sale
    line, the batch, the movement and the controlled-register entry all point at
    it, and an auditor asking what was dispensed last March is entitled to a
    name rather than a dangling id. Deactivating takes it out of every picker
    and every reorder list while leaving the history readable, which is what
    "delete this product" actually means in a pharmacy.
    """
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not product.active:
        raise HTTPException(status_code=400,
                            detail=f"{product.name} is already retired.")
    on_hand = product.quantity_on_hand or 0
    product.active = False
    db.commit()
    return {
        "id": product.id,
        "name": product.name,
        "active": False,
        "message": f"{product.name} has been retired. Its history is kept.",
        # Said out loud rather than discovered at the next stock count.
        "warning": (f"{on_hand} unit(s) are still on hand. Write them off or "
                    "transfer them before the next count.") if on_hand else "",
    }


@router.get("/products/paged")
def list_products_paged(
    q: str = "", category: str = "", low_stock: bool = False,
    page: int = 1, per_page: int = paging.DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
):
    """The browse list, which reports how many products there are.

    542 products behind a cap of 300 is not a shorter answer, it is a wrong one:
    242 lines of stock that the screen said nothing about.
    """
    result = paging.page(_product_search(db, q, category, low_stock), page=page, per_page=per_page)
    return result.envelope(
        lambda x: schemas.ProductOut.model_validate(x, from_attributes=True).model_dump()
    )


# Looking a product up by barcode used to be here: one query matching the code
# against two columns. POST /api/scan is the real one — it reads the symbology,
# resolves a pack multiplier, carries its warnings, and knows about the codes a
# product has been taught. A till that used the shallow one would scan an outer
# and sell a single.

@router.get("/products/{product_id}/variants")
def product_variants(product_id: int, db: Session = Depends(get_db)):
    """Other products that are the same medicine.

    A pharmacy stocks one molecule several times over: the brand and two
    generics, the same generic from two importers, 20s and 30s of the same pack.
    They are separate products because they have separate stock and separate
    prices, and they must stay that way, but the person at the counter is
    holding a script for a *medicine*, and needs to see the alternatives before
    telling a patient the price.

    Grouped on the active ingredient, which is the only thing that makes two
    products interchangeable. Not on the name: "Atorvastatin" and "Atorva-Gen"
    share nothing in their names and are the same medicine, while "Panado" and
    "Panadeine" nearly share theirs and are not.

    Strength is reported rather than filtered on. A 10mg and a 20mg atorvastatin
    are the same molecule and the substitution is a clinical judgement about
    halving a tablet, not something this endpoint should make silently.
    """
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="That product no longer exists.")

    molecule = (product.active_ingredient or "").strip()
    if not molecule:
        # Said plainly rather than answered with an empty list. No alternatives
        # and "we cannot tell" are different answers, and only one of them is a
        # reason to go and fill in the field.
        return {
            "product": product.name,
            "molecule": "",
            "known": False,
            "reason": ("No active ingredient is recorded for this product, so "
                       "there is no way to tell what it is interchangeable with."),
            "variants": [],
        }

    rows = (
        db.query(Product)
        .filter(func.lower(Product.active_ingredient) == molecule.lower())
        .filter(Product.id != product.id)
        .filter(Product.active.is_(True))
        .order_by(Product.unit_price)
        .all()
    )
    here = round(product.unit_price or 0, 2)
    return {
        "product": product.name,
        "molecule": molecule,
        "known": True,
        "reason": "",
        "this_price": here,
        "variants": [{
            "id": v.id,
            "name": v.name,
            "strength": v.strength or "",
            "pack_size": v.pack_size or "",
            "manufacturer": v.manufacturer or "",
            "schedule": v.schedule or 0,
            "price": round(v.unit_price or 0, 2),
            # What the patient would save, which is the number the conversation
            # at the counter is actually about.
            "difference": round((v.unit_price or 0) - here, 2),
            "on_hand": v.quantity_on_hand or 0,
            "same_strength": (v.strength or "").strip().lower()
                             == (product.strength or "").strip().lower(),
        } for v in rows],
    }


@router.get("/products/{product_id}/usage")
def product_usage(product_id: int, months: int = 12,
                  db: Session = Depends(get_db)):
    """What has gone out, month by month, and what came in to replace it.

    A stock item's page can say how much is on the shelf today. It cannot say
    whether that is a lot, and the difference between "forty is plenty" and
    "forty is a fortnight" is the whole of buying. The incumbent gives this its
    own tab for the same reason.

    Read off the stock movements rather than off sales and dispensings
    separately: every way a unit leaves the shelf writes one, including the
    ones a sales report never sees — a write-off, a transfer to another branch,
    a correction after a count. A buyer looking at a month that dropped wants
    to know it was breakages and not demand.

    Grouped in Python, not in SQL. `strftime` is SQLite's and `to_char` is
    PostgreSQL's, and this application runs on both; one product over a year is
    a few hundred rows and the portability is worth more than the grouping.
    """
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    months = max(1, min(int(months or 12), 36))
    # From the first of the month, so the earliest bar is a whole month rather
    # than whatever part of one the window happened to start in.
    first = (date.today().replace(day=1)
             - timedelta(days=31 * (months - 1))).replace(day=1)
    rows = (db.query(StockMovement)
            .filter(StockMovement.product_id == product_id,
                    StockMovement.created_at >= datetime(first.year, first.month, 1))
            .order_by(StockMovement.created_at).all())

    buckets: dict[str, dict] = {}
    cursor = first
    while cursor <= date.today():
        buckets[f"{cursor.year:04d}-{cursor.month:02d}"] = {
            "month": f"{cursor.year:04d}-{cursor.month:02d}",
            "out": 0, "in": 0, "adjusted": 0, "written_off": 0, "moved": 0,
        }
        cursor = (cursor.replace(day=28) + timedelta(days=7)).replace(day=1)

    for m in rows:
        when = m.created_at or datetime.utcnow()
        key = f"{when.year:04d}-{when.month:02d}"
        bucket = buckets.get(key)
        if bucket is None:
            continue
        delta = int(m.quantity_delta or 0)
        kind = (m.movement_type or "").lower()
        if kind == "sale":
            bucket["out"] += -delta
        elif kind in ("receive", "purchase"):
            bucket["in"] += delta
        elif kind in ("write_off", "writeoff", "waste"):
            bucket["written_off"] += -delta
        elif kind.startswith("transfer"):
            bucket["moved"] += delta
        else:
            bucket["adjusted"] += delta

    series = list(buckets.values())
    went_out = sum(b["out"] for b in series)
    # The months that have actually happened, so a window longer than the
    # product's history does not divide the average down to nothing.
    counted = max(1, len([b for b in series if any(
        b[k] for k in ("out", "in", "adjusted", "written_off", "moved"))]))
    return {
        "months": series,
        "out_total": went_out,
        "in_total": sum(b["in"] for b in series),
        "written_off_total": sum(b["written_off"] for b in series),
        "a_month": round(went_out / counted, 1),
        "busiest": max(series, key=lambda b: b["out"])["month"] if series else "",
    }


def _branch_of(db: Session, user: User) -> int:
    """Which shelf this person is standing at."""
    if getattr(user, "branch_id", None):
        return int(user.branch_id)
    from ..services import branches as branch_svc
    return branch_svc.default_branch(db).id


@router.get("/products/{product_id}", response_model=schemas.ProductDetail)
def get_product(product_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Everything the product record page needs in one call."""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    batches = (
        db.query(StockBatch)
        .filter(StockBatch.product_id == product_id, StockBatch.quantity_remaining > 0)
        .order_by(StockBatch.expiry_date.is_(None), StockBatch.expiry_date)
        .all()
    )
    movements = (
        db.query(StockMovement)
        .filter(StockMovement.product_id == product_id)
        .order_by(StockMovement.created_at.desc())
        .limit(40)
        .all()
    )
    # Dispensings hang off prescription items, not products directly
    dispensed = (
        db.query(func.coalesce(func.sum(Dispensing.quantity), 0))
        .join(PrescriptionItem, Dispensing.prescription_item_id == PrescriptionItem.id)
        .filter(PrescriptionItem.product_id == product_id)
        .scalar()
    )
    sold = (
        db.query(func.coalesce(func.sum(SaleItem.quantity), 0))
        .join(Sale, SaleItem.sale_id == Sale.id)
        # Both ways a sale is reversed put the goods back, so neither counts as sold.
        .filter(SaleItem.product_id == product_id,
                Sale.status.notin_(("void", "credited")))
        .scalar()
    )
    return {
        "product": product,
        "batches": batches,
        "movements": movements,
        "units_dispensed": int(dispensed or 0),
        "units_sold": int(sold or 0),
        "stock_value": round(product.quantity_on_hand * product.cost_price, 2),
        "shelf": _shelf_figures(db, product, batches, user),
    }


def _shelf_figures(db: Session, product: Product, batches: list, user: User) -> dict:
    """The figures a buyer decides on, rather than the ones a record happens to hold.

    The product page showed what the catalogue stores: a quantity, a cost and a
    price. None of those answers the question somebody opens this page with,
    which is always one of "have I got any", "what did it really cost me" and
    "when do I run out".

      packs and units      the shelf holds units and a buyer orders packs. The
                           incumbent shows both side by side for that reason,
                           and a pharmacy that reads one as the other orders
                           thirty times too many.
      here                 what THIS branch holds, as against the group. The
                           difference between those two has caused more trouble
                           in this system than any other single thing.
      average cost         weighted over the stock actually on the shelf, not
                           the catalogue's idea of cost. Two deliveries at
                           different prices and the catalogue is wrong about
                           both.
      days of cover        on hand divided by what actually goes out. The only
                           figure here that answers "when do I reorder", and
                           the one the record never held.
    """
    per_pack = max(1, product.units_per_pack or 1)
    units = int(product.quantity_on_hand or 0)

    branch_id = _branch_of(db, user)
    here = int(db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
               .filter(StockBatch.product_id == product.id,
                       StockBatch.branch_id == branch_id,
                       StockBatch.quantity_remaining > 0,
                       StockBatch.expiry_date >= date.today()).scalar() or 0)
    here_undated = int(db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
                       .filter(StockBatch.product_id == product.id,
                               StockBatch.branch_id == branch_id,
                               StockBatch.quantity_remaining > 0,
                               StockBatch.expiry_date.is_(None)).scalar() or 0)

    # Weighted over what is left, so a large old batch does not go on setting
    # the average after it has been sold.
    on_shelf = [b for b in batches if (b.quantity_remaining or 0) > 0]
    held = sum(b.quantity_remaining for b in on_shelf)
    avg_cost = (round(sum((b.unit_cost or 0.0) * b.quantity_remaining for b in on_shelf)
                      / held, 4) if held else round(product.unit_cost(), 4))

    on_order = int(db.query(func.coalesce(
        func.sum(PurchaseOrderItem.quantity_ordered - PurchaseOrderItem.quantity_received), 0))
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.order_id)
        .filter(PurchaseOrderItem.product_id == product.id,
                PurchaseOrder.status.notin_(("received", "cancelled"))).scalar() or 0)

    # What actually leaves the shelf, over a window long enough to mean
    # something and short enough to still be true.
    since = datetime.utcnow() - timedelta(days=90)
    out_90 = int(db.query(func.coalesce(func.sum(-StockMovement.quantity_delta), 0))
                 .filter(StockMovement.product_id == product.id,
                         StockMovement.movement_type == "sale",
                         StockMovement.created_at >= since).scalar() or 0)
    a_day = round(out_90 / 90.0, 3) if out_90 > 0 else 0.0

    each = product.per_unit()
    return {
        "units": units,
        "packs": round(units / per_pack, 2),
        "per_pack": per_pack,
        "here": here,
        "here_undated": here_undated,
        "on_order": on_order,
        "avg_cost": avg_cost,
        "unit_cost": round(product.unit_cost(), 4),
        "each": round(each, 4),
        # What the pharmacy makes on it, from the cost the shelf actually
        # carries rather than the one the catalogue remembers.
        "markup_percent": (round(100.0 * (each - avg_cost) / avg_cost, 1)
                           if avg_cost > 0 else None),
        "margin_percent": (round(100.0 * (each - avg_cost) / each, 1)
                           if each > 0 else None),
        "at_cost": round(units * avg_cost, 2),
        "at_retail": round(units * each, 2),
        "a_day": a_day,
        "out_90": out_90,
        # Blank rather than infinity where nothing moves: "never runs out" is
        # not a fact about the medicine, it is the absence of one. Blank too
        # where the record has gone negative, because "minus thirty days of
        # cover" is not a shortage measured, it is a count that needs fixing —
        # and the page says that separately.
        "days_cover": (round(units / a_day) if a_day > 0 and units > 0 else None),
        # The record and the batches behind it disagreeing is worth saying out
        # loud. It is the difference between a shelf that is empty and a shelf
        # nobody has counted, and only one of those is fixed by ordering.
        "disagrees": units != (here + here_undated),
        "reorder_level": int(product.reorder_level or 0),
        "max_level": int(product.max_level or 0),
        "reorder_quantity": int(product.reorder_quantity or 0),
        # How much to order to reach the ceiling. The question that follows
        # "order now", and the one a floor on its own cannot answer.
        "to_max": (max(0, int(product.max_level or 0) - units)
                   if (product.max_level or 0) > 0 else None),
    }


@router.post("/products", response_model=schemas.ProductOut)
def create_product(body: schemas.ProductCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = body.model_dump()
    opening = data.pop("quantity_on_hand", 0)
    product = Product(**data, quantity_on_hand=0)
    db.add(product)
    db.flush()
    if opening > 0 and product.category != "airtime":
        helpers.receive_stock_batch(db, product, opening, user.id, batch_number="OPENING", reference="opening stock")
    elif opening > 0:
        product.quantity_on_hand = opening
    db.commit()
    db.refresh(product)
    return product


@router.put("/products/{product_id}", response_model=schemas.ProductOut)
def update_product(product_id: int, body: schemas.ProductBase, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for key, value in body.model_dump().items():
        setattr(product, key, value)
    db.commit()
    db.refresh(product)
    return product


# ---------- movements / adjustments ----------
@router.post("/stock/upload")
def stock_upload(csv_text: str = Body(..., embed=True),
                 apply: bool = Body(default=False, embed=True),
                 reference: str = Body(default="", embed=True),
                 branch_id: int | None = Body(default=None, embed=True),
                 db: Session = Depends(get_db),
                 user: User = Depends(require_role("admin", "pharmacist", "manager"))):
    """Load a catalogue or a delivery from a spreadsheet.

    Two steps, always: `apply=false` returns exactly what would happen and
    writes nothing. The price import beside this can only update; this one
    creates as well, which is the half a pharmacy needs on the day it arrives
    from another system.
    """
    from ..services import stock_upload as up

    try:
        rows, mapping = up.read(csv_text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    lines = up.plan(db, rows, mapping, branch_id=branch_id)
    counts = {a: sum(1 for l in lines if l.action == a)
              for a in ("create", "update", "skip", "refuse")}
    result = {
        "applied": False,
        "columns_read": sorted(mapping.keys()),
        "columns_ignored": [c for c in (rows[0].keys() if rows else [])
                            if c not in mapping.values()],
        "rows": len(rows),
        **counts,
        "units": sum(l.quantity for l in lines if l.action in ("create", "update")),
        "lines": [{
            "row": l.row, "key": l.key, "name": l.name, "action": l.action,
            "reason": l.reason, "product_id": l.product_id,
            "changes": l.changes, "quantity": l.quantity,
            "batch": l.batch, "expiry": l.expiry,
        } for l in lines[:400]],
        "truncated": len(lines) > 400,
    }
    if not apply:
        return result

    written = up.apply(db, rows, mapping, lines, user_id=user.id,
                       branch_id=branch_id, reference=reference)
    result["applied"] = True
    result.update(written)
    result["message"] = (
        f"{written['created']} product(s) created, {written['updated']} updated, "
        f"{written['units']:,} unit(s) received into {written['batches']} batch(es).")
    return result


@router.post("/stock/adjust")
def adjust_stock(body: schemas.StockAdjust, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user),
                 _may=Depends(auth.requires("stock.adjust"))):
    product = db.get(Product, body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.quantity_on_hand + body.quantity_delta < 0:
        raise HTTPException(status_code=400, detail="Adjustment would make stock negative")

    # A correction and a write-off arrive on the same endpoint, and they are not
    # the same act: one says the count was wrong, the other says goods left the
    # building. They are separate capabilities for that reason, and this is the
    # one place the caller chooses which of the two it is writing. Without this
    # check, widening stock.adjust to the pharmacist — who should be able to
    # correct the shelf they are standing at — would have handed them write-offs
    # as well, through a dropdown, with no screen anywhere looking wrong.
    if body.movement_type == "write_off":
        decision = permissions.check(db, user, "stock.write_off")
        if not decision["allowed"]:
            raise HTTPException(403, decision["why"])

    if product.category == "airtime":
        helpers.move_stock(db, product, body.quantity_delta, body.movement_type, user.id,
                           reference=body.reference, notes=body.notes)
    elif body.quantity_delta > 0:
        helpers.receive_stock_batch(
            db, product, body.quantity_delta, user.id,
            batch_number=body.batch_number, expiry_date=body.expiry_date,
            reference=body.reference, movement_type=body.movement_type, notes=body.notes,
        )
    else:
        # write-offs / stocktake variances may consume expired stock
        helpers.consume_stock_fefo(
            db, product, -body.quantity_delta, body.movement_type, user.id,
            reference=body.reference, notes=body.notes, allow_expired=True,
        )
    entry_type = "receive" if body.quantity_delta > 0 else "adjustment"
    helpers.record_register_entry(db, product, body.quantity_delta, entry_type, user.id, reference=body.reference or body.movement_type)
    db.commit()
    return {"ok": True, "quantity_on_hand": product.quantity_on_hand}


# ---------- batches / expiry ----------
# GET /stock/batches was here, unpaged. /stock/batches/paged replaced it.


@router.get("/stock/batches/paged")
def list_batches_paged(
    product_id: int | None = None,
    expiring_within_days: int | None = None,
    include_empty: bool = False,
    page: int = 1, per_page: int = paging.DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
):
    """Batches on hand, paged.

    1,606 batches behind a cap of 500. Batch records are what an expiry sweep
    and a recall both work from, so a list that stops a third of the way through
    is the wrong tool for the two jobs it exists to do.
    """
    # Every batch row names its medicine, and that was a query a batch: two
    # hundred and forty-eight batches came to a hundred and twelve queries and
    # eleven seconds in production, for a screen an expiry sweep lives on.
    query = db.query(StockBatch).options(joinedload(StockBatch.product))
    if product_id:
        query = query.filter(StockBatch.product_id == product_id)
    if not include_empty:
        query = query.filter(StockBatch.quantity_remaining > 0)
    if expiring_within_days is not None:
        query = query.filter(StockBatch.expiry_date <= date.today() + timedelta(days=expiring_within_days))
    result = paging.page(query.order_by(StockBatch.expiry_date.asc()), page=page, per_page=per_page)
    return result.envelope(
        lambda x: schemas.BatchOut.model_validate(x, from_attributes=True).model_dump()
    )


@router.get("/stock/reconcile")
def stock_reconcile(limit: int = 200, db: Session = Depends(get_db)):
    """Does each product's own count agree with the batches behind it?

    The ledger has had a control-versus-subledger check since it was written.
    Stock is kept in two places the same way and had none.
    """
    from ..services import stock_reconcile as recon
    return recon.reconcile(db, limit=limit)


@router.post("/stock/batches/{batch_id}/write-off")
def write_off_batch(batch_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user),
                    _may=Depends(auth.requires("stock.write_off"))):
    """Write off a batch's remaining stock (expired / damaged)."""
    batch = db.get(StockBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.quantity_remaining <= 0:
        raise HTTPException(status_code=400, detail="Batch has no remaining stock")
    product = batch.product
    qty = batch.quantity_remaining
    batch.quantity_remaining = 0
    # Never below nothing.
    #
    # This subtracted the batch's remainder from the product's own count
    # whether or not the product had ever held that much, and the two are
    # allowed to drift, so writing off a batch could leave a product at minus
    # seven, which every screen then showed to a dispenser as its stock. A
    # negative shelf count is not information, it is arithmetic showing
    # through; /stock/reconcile is where the drift itself is read.
    product.quantity_on_hand = max(0, (product.quantity_on_hand or 0) - qty)
    db.add(StockMovement(
        product_id=product.id, movement_type="adjustment", quantity_delta=-qty,
        balance_after=product.quantity_on_hand,
        reference=f"WRITE-OFF {batch.batch_number}",
        notes=f"batch write-off (exp {batch.expiry_date})", user_id=user.id,
    ))
    helpers.record_register_entry(db, product, -qty, "adjustment", user.id, reference=f"WRITE-OFF {batch.batch_number}")
    db.commit()
    return {"ok": True, "written_off": qty, "quantity_on_hand": product.quantity_on_hand}


# GET /stock/movements was here, capped at 200 against 5,143 rows —
# ninety-six per cent of the stock history unreachable, and nothing said
# so. /stock/movements/paged replaced it.


@router.get("/stock/movements/paged")
def list_movements_paged(
    product_id: int | None = None,
    page: int = 1, per_page: int = paging.DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
):
    """Movement history, paged.

    This was the worst of them: 5,143 movements behind a cap of 200. Ninety-six
    per cent of the stock history was unreachable from the screen that exists to
    show it, and nothing said so.
    """
    # Each row names its medicine, and naming them one at a time is a round trip
    # a row: fifty-five queries for a page of fifty, and sixteen seconds against
    # the hosted database. One more query loads the lot.
    query = db.query(StockMovement).options(selectinload(StockMovement.product))
    if product_id:
        query = query.filter(StockMovement.product_id == product_id)
    result = paging.page(query.order_by(StockMovement.created_at.desc()),
                         page=page, per_page=per_page)
    return result.envelope(
        lambda x: schemas.StockMovementOut.model_validate(x, from_attributes=True).model_dump()
    )


# ---------- suppliers ----------
@router.get("/suppliers", response_model=list[schemas.SupplierOut])
def list_suppliers(db: Session = Depends(get_db)):
    return db.query(Supplier).order_by(Supplier.name).all()


@router.post("/suppliers", response_model=schemas.SupplierOut)
def create_supplier(body: schemas.SupplierBase, db: Session = Depends(get_db)):
    supplier = Supplier(**body.model_dump())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


@router.put("/suppliers/{supplier_id}", response_model=schemas.SupplierOut)
def update_supplier(supplier_id: int, body: dict = Body(...),
                    db: Session = Depends(get_db),
                    _: User = Depends(require_role("admin", "manager"))):
    """Correct a supplier.

    Suppliers could be created and listed and never changed. A wholesaler
    changes its bank account, which they do, and which is exactly the message
    a fraudster imitates, and the pharmacy had nowhere to record the new one
    except a note beside the old one. A payment made against a stale account
    number is not a data-entry problem.
    """
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    if "name" in body:
        name = str(body["name"] or "").strip()
        if not name:
            raise HTTPException(
                status_code=400,
                detail="A supplier needs a name. It is on every order and "
                       "every invoice they send.")
        supplier.name = name[:160]
    for field, width in (("contact_person", 120), ("phone", 30), ("email", 120),
                         ("account_number", 60), ("payment_terms", 60),
                         ("notes", 400)):
        if field in body and hasattr(supplier, field):
            setattr(supplier, field, str(body[field] or "").strip()[:width])
    if "active" in body and hasattr(supplier, "active"):
        supplier.active = bool(body["active"])
    db.commit()
    db.refresh(supplier)
    return supplier


@router.delete("/suppliers/{supplier_id}")
def retire_supplier(supplier_id: int, db: Session = Depends(get_db),
                    _: User = Depends(require_role("admin", "manager"))):
    """Retire a supplier. Never deleted. Their name is on every order.

    Refused while money is still owed. A supplier taken off the list with an
    outstanding balance is a debt that stops appearing on the creditors ageing,
    and a debt nobody can see is one nobody pays.
    """
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if not hasattr(supplier, "active"):
        raise HTTPException(
            status_code=400,
            detail="Suppliers on this database cannot be retired.")

    # What is still owed, from the invoices themselves. Computed here rather
    # than trusting a stored balance, because a stored balance is the thing
    # that drifts and this is the one moment it must not.
    from ..models import SupplierInvoice

    # By status rather than by a paid-to-date column, because there is no such
    # column: payments are allocated to invoices in their own table, and an
    # invoice is "paid" when that allocation covers it. Summing the unsettled
    # ones is the same question asked the way the schema answers it.
    owed = float(
        db.query(func.coalesce(func.sum(SupplierInvoice.total), 0.0))
        .filter(SupplierInvoice.supplier_id == supplier.id,
                SupplierInvoice.status.notin_(
                    ("paid", "cancelled", "written_off")))
        .scalar() or 0.0)
    if owed and abs(owed) > 0.005:
        raise HTTPException(
            status_code=400,
            detail=f"{supplier.name} is still owed {owed:.2f}. Settle or write "
                   f"it off first. Retiring them takes the balance off the "
                   f"creditors ageing, and a debt nobody can see is one nobody "
                   f"pays.")
    supplier.active = False
    db.commit()
    return {"ok": True, "message": f"{supplier.name} retired."}



# ---------- purchase orders ----------
# GET /orders was here: the same list capped at 100, superseded by
# /orders/paged, which every screen uses. Two hundred and seventeen orders
# behind a cap of a hundred is the bug the paged one was written to fix,
# and leaving the capped twin in place leaves that bug where somebody can
# wire it again by accident.


@router.get("/orders/paged")
def list_orders_paged(
    status: str = "",
    page: int = 1, per_page: int = paging.DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
):
    """Purchase orders, paged. 217 orders behind a cap of 100."""
    # The supplier and every ordered line with its product, in one go rather
    # than four round trips an order.
    query = db.query(PurchaseOrder).options(
        joinedload(PurchaseOrder.supplier),
        selectinload(PurchaseOrder.items).joinedload(PurchaseOrderItem.product),
    )
    if status:
        query = query.filter(PurchaseOrder.status == status)
    result = paging.page(query.order_by(PurchaseOrder.created_at.desc()), page=page, per_page=per_page)
    return result.envelope(
        lambda x: schemas.POOut.model_validate(x, from_attributes=True).model_dump()
    )


@router.get("/orders/{order_id}", response_model=schemas.POOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return order


@router.post("/orders", response_model=schemas.POOut)
def create_order(body: schemas.POCreate, db: Session = Depends(get_db)):
    if not body.items:
        raise HTTPException(status_code=400, detail="Order needs at least one line")
    order = PurchaseOrder(
        order_number=helpers.next_number(db, PurchaseOrder, "PO", "order_number"),
        supplier_id=body.supplier_id,
        notes=body.notes,
    )
    db.add(order)
    db.flush()
    for line in body.items:
        product = db.get(Product, line.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {line.product_id} not found")
        db.add(PurchaseOrderItem(
            order_id=order.id,
            product_id=line.product_id,
            quantity_ordered=line.quantity_ordered,
            unit_cost=line.unit_cost or product.cost_price,
        ))
    db.commit()
    db.refresh(order)
    return order


@router.post("/orders/suggest", response_model=list[schemas.POOut])
def suggest_orders(db: Session = Depends(get_db)):
    """Auto-generate draft POs (one per supplier) for everything at/below reorder level."""
    low = (
        db.query(Product)
        .filter(Product.active, Product.quantity_on_hand <= Product.reorder_level, Product.category != "airtime")
        .all()
    )

    # Work out what to order per product first. A product with no reorder quantity
    # and no shortfall to make up yields nothing — ordering it would create a
    # zero-quantity line that can never be received.
    by_supplier: dict[int | None, list[tuple[Product, int]]] = {}
    for product in low:
        qty = max(product.reorder_quantity, product.reorder_level - product.quantity_on_hand)
        if qty <= 0:
            continue
        by_supplier.setdefault(product.supplier_id, []).append((product, qty))

    created = []
    default_supplier = db.query(Supplier).first()
    for supplier_id, lines in by_supplier.items():
        sid = supplier_id or (default_supplier.id if default_supplier else None)
        if sid is None:
            continue
        order = PurchaseOrder(
            order_number=helpers.next_number(db, PurchaseOrder, "PO", "order_number"),
            supplier_id=sid,
            notes="Auto-generated from reorder levels",
        )
        db.add(order)
        db.flush()
        for product, qty in lines:
            db.add(PurchaseOrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity_ordered=qty,
                unit_cost=product.cost_price,
            ))
        created.append(order)
    db.commit()
    for order in created:
        db.refresh(order)
    return created


@router.post("/orders/{order_id}/status", response_model=schemas.POOut)
def set_order_status(
    order_id: int,
    status: str,
    body: schemas.ReceiveOrderBody | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if status not in ("draft", "sent", "received", "cancelled"):
        raise HTTPException(status_code=400, detail="Invalid status")
    if status == "received" and order.status != "received":
        batch_info = {l.item_id: l for l in (body.lines if body else [])}
        for line in order.items:
            product = line.product
            line.quantity_received = line.quantity_ordered
            info = batch_info.get(line.id)
            if product.category == "airtime":
                helpers.move_stock(db, product, line.quantity_ordered, "receive", user.id,
                                   reference=order.order_number, in_packs=True)
            else:
                # An order line counts packs. Ten tubs of a thousand is ten
                # thousand capsules on the shelf.
                helpers.receive_stock_batch(
                    db, product, line.quantity_ordered, user.id, in_packs=True,
                    batch_number=(info.batch_number if info else "") or f"{order.order_number}-{line.id}",
                    expiry_date=info.expiry_date if info else None,
                    unit_cost=line.unit_cost or None,
                    reference=order.order_number,
                )
            helpers.record_register_entry(db, product, line.quantity_ordered, "receive", user.id, reference=order.order_number)
            if line.unit_cost:
                product.cost_price = line.unit_cost
        order.received_at = datetime.utcnow()
    order.status = status
    db.commit()
    if status == "received":
        # The liability exists the moment the goods are on the shelf, not when
        # the supplier is paid. Non-fatal, like every other posting: the stock
        # arrived whatever the ledger thinks.
        posting.post_stock_receipt(db, order, user.id)
    db.refresh(order)
    return order


# ---------- stock categories ----------


@router.get("/stock-categories")
def list_stock_categories(db: Session = Depends(get_db),
                          _: User = Depends(get_current_user)):
    """The pharmacy's own departments, with how much sits in each.

    Counted and valued in one grouped query rather than one per category. The
    value is what the shelf actually cost, because that is the figure a
    department is judged on — a thousand cosmetics lines worth two hundred
    dollars and forty dispensary lines worth nine thousand are not comparable
    on a count.
    """
    from ..models import StockCategory

    rows = dict(db.query(Product.category_id, func.count(Product.id))
                .filter(Product.active)
                .group_by(Product.category_id).all())
    value = dict(db.query(Product.category_id,
                          func.coalesce(func.sum(Product.quantity_on_hand
                                                 * Product.average_cost), 0.0))
                 .filter(Product.active)
                 .group_by(Product.category_id).all())
    stocked = dict(db.query(Product.category_id, func.count(Product.id))
                   .filter(Product.active, Product.quantity_on_hand > 0)
                   .group_by(Product.category_id).all())

    cats = db.query(StockCategory).order_by(StockCategory.name).all()
    out = [{
        "id": c.id, "code": c.code or "", "name": c.name,
        "target_margin": c.target_margin or 0.0,
        "active": bool(c.active),
        # Whether the dispensary offers what is filed here.
        "dispensable": bool(c.dispensable),
        "products": rows.get(c.id, 0),
        "in_stock": stocked.get(c.id, 0),
        "at_cost": round(value.get(c.id, 0.0) or 0.0, 2),
    } for c in cats]

    # Anything nobody has filed. Shown rather than left out, because an
    # untagged line is invisible on every department report and that is how a
    # product quietly stops being counted.
    untagged = rows.get(None, 0)
    return {"items": out, "untagged": untagged}


@router.post("/stock-categories")
def create_stock_category(body: dict, db: Session = Depends(get_db),
                          _: User = Depends(require_role("admin", "manager"))):
    """Add a department."""
    from ..models import StockCategory

    name = " ".join((body.get("name") or "").split())
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Give the department a name.")
    existing = (db.query(StockCategory)
                .filter(func.lower(StockCategory.name) == name.lower()).first())
    if existing:
        return {"id": existing.id, "name": existing.name, "code": existing.code or ""}
    cat = StockCategory(name=name, code=(body.get("code") or "").strip()[:20],
                        target_margin=float(body.get("target_margin") or 0),
                        # On unless the pharmacy says otherwise: a department
                        # somebody has just made is usually about to hold
                        # medicines, and a switch that hides them silently is
                        # worse than one that shows a jar of sweets.
                        dispensable=bool(body.get("dispensable", True)),
                        active=True)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name, "code": cat.code or "",
            "dispensable": bool(cat.dispensable)}


@router.put("/stock-categories/{category_id}")
def update_stock_category(category_id: int, body: dict, db: Session = Depends(get_db),
                          _: User = Depends(require_role("admin", "manager"))):
    """Change a department: its name, its code, or what it should earn.

    The target margin is the one that gets edited. It is a commercial decision
    that moves — a department carrying more consignment stock this quarter than
    last should not be measured against a figure somebody typed once, and it
    could be set when the department was created and never again.
    """
    from ..models import StockCategory

    cat = db.get(StockCategory, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="No such department.")

    if "name" in body:
        name = " ".join((body.get("name") or "").split())
        if len(name) < 2:
            raise HTTPException(status_code=400, detail="Give the department a name.")
        clash = (db.query(StockCategory)
                 .filter(func.lower(StockCategory.name) == name.lower(),
                         StockCategory.id != cat.id).first())
        if clash:
            raise HTTPException(
                status_code=400,
                detail=f"{clash.name} already uses that name.")
        cat.name = name
    if "code" in body:
        cat.code = (body.get("code") or "").strip()[:20]
    if "target_margin" in body:
        margin = float(body.get("target_margin") or 0)
        # A margin above a hundred per cent is a keying slip — 30 typed as 300 —
        # and it would quietly mark every line in the department as failing.
        if margin < 0 or margin > 100:
            raise HTTPException(
                status_code=400,
                detail="A target margin is a percentage between 0 and 100.")
        cat.target_margin = margin
    if "active" in body:
        cat.active = bool(body.get("active"))
    if "dispensable" in body:
        cat.dispensable = bool(body.get("dispensable"))

    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name, "code": cat.code or "",
            "target_margin": cat.target_margin, "active": cat.active,
            "dispensable": bool(cat.dispensable)}


@router.post("/stock-categories/tag")
def tag_everything(apply: bool = Body(default=False, embed=True),
                   retag: bool = Body(default=False, embed=True),
                   db: Session = Depends(get_db),
                   user: User = Depends(require_role("admin", "manager", "pharmacist"))):
    """Put every product that has no department into one.

    Preview first, always. A department is what every stock report groups on,
    so placing four thousand products wrongly is worse than leaving them
    unplaced: the totals would look right and be wrong.
    """
    from ..services import stock_tagging

    if user.pharmacy_id is None:
        raise HTTPException(400, "This account belongs to no pharmacy.")
    return stock_tagging.tag(db, pharmacy_id=user.pharmacy_id,
                             apply=apply, retag=retag)


@router.get("/stock-categories/unplaced")
def unplaced_products(limit: int = 200, db: Session = Depends(get_db)):
    """Products in no department, worth most first.

    The ones the rules cannot place are not a failure to be hidden — they are a
    short list somebody can work down, and the value on the shelf says which to
    do first.
    """
    rows = (db.query(Product)
            .filter(Product.active, Product.category_id.is_(None))
            .order_by((Product.quantity_on_hand * Product.cost_price).desc())
            .limit(limit).all())
    total = (db.query(func.count(Product.id))
             .filter(Product.active, Product.category_id.is_(None)).scalar())
    return {
        "total": int(total or 0),
        "showing": len(rows),
        "items": [{
            "id": p.id, "name": f"{p.name} {p.strength or ''}".strip(),
            "stock_code": p.stock_code or "", "schedule": p.schedule or 0,
            "on_hand": p.quantity_on_hand or 0,
            "value": round((p.quantity_on_hand or 0) * (p.cost_price or 0.0), 2),
        } for p in rows],
    }


@router.post("/products/{product_id}/category")
def tag_product(product_id: int, body: dict, db: Session = Depends(get_db),
                _: User = Depends(require_role("admin", "manager", "pharmacist"))):
    """File a product under a department."""
    from ..models import StockCategory

    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    raw = body.get("category_id")
    if raw in (None, "", 0):
        product.category_id = None
    else:
        cat = db.get(StockCategory, int(raw))
        if cat is None:
            raise HTTPException(status_code=404, detail="No such department.")
        product.category_id = cat.id
    db.commit()
    return {"id": product.id, "category_id": product.category_id}
