from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import helpers, schemas
from ..auth import get_current_user, require_role
from ..database import get_db
from ..services import paging
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
    prices, and they must stay that way — but the person at the counter is
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


@router.get("/products/{product_id}", response_model=schemas.ProductDetail)
def get_product(product_id: int, db: Session = Depends(get_db)):
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
@router.post("/stock/adjust")
def adjust_stock(body: schemas.StockAdjust, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    product = db.get(Product, body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.quantity_on_hand + body.quantity_delta < 0:
        raise HTTPException(status_code=400, detail="Adjustment would make stock negative")

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
def write_off_batch(batch_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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
    # allowed to drift — so writing off a batch could leave a product at minus
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
    query = db.query(StockMovement)
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
                helpers.move_stock(db, product, line.quantity_ordered, "receive", user.id, reference=order.order_number)
            else:
                helpers.receive_stock_batch(
                    db, product, line.quantity_ordered, user.id,
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
                        active=True)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name, "code": cat.code or ""}


@router.put("/stock-categories/{category_id}")
def update_stock_category(category_id: int, body: dict, db: Session = Depends(get_db),
                          _: User = Depends(require_role("admin", "manager"))):
    """Change a department: its name, its code, or what it should earn.

    The target margin is the one that gets edited. It is a commercial decision
    that moves — a department carrying more consignment stock this quarter than
    last should not be measured against a figure somebody typed once — and it
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

    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name, "code": cat.code or "",
            "target_margin": cat.target_margin, "active": cat.active}


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
