from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import helpers, schemas
from ..auth import get_current_user
from ..database import get_db
from ..services import paging
from ..services import posting
from ..models import (
    Dispensing, PrescriptionItem, Product, PurchaseOrder, PurchaseOrderItem,
    Sale, SaleItem, StockBatch, StockMovement, Supplier, User,
)

router = APIRouter(prefix="/api", tags=["stock"], dependencies=[Depends(get_current_user)])


# ---------- products ----------
def _product_search(db: Session, q: str, category: str, low_stock: bool):
    query = db.query(Product).filter(Product.active)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Product.name.ilike(like),
            Product.barcode.ilike(like),
            Product.nappi_code.ilike(like),
        ))
    if category:
        query = query.filter(Product.category == category)
    if low_stock:
        query = query.filter(Product.quantity_on_hand <= Product.reorder_level)
    return query.order_by(Product.name)


@router.get("/products", response_model=list[schemas.ProductOut])
def list_products(q: str = "", category: str = "", low_stock: bool = False, limit: int = 300, db: Session = Depends(get_db)):
    """Capped list, for pickers and typeaheads that want a shortlist."""
    return _product_search(db, q, category, low_stock).limit(limit).all()


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


@router.get("/products/barcode/{code}", response_model=schemas.ProductOut)
def product_by_barcode(code: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(or_(Product.barcode == code, Product.nappi_code == code)).first()
    if not product:
        raise HTTPException(status_code=404, detail="No product with that barcode")
    return product


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
@router.get("/stock/batches", response_model=list[schemas.BatchOut])
def list_batches(
    product_id: int | None = None,
    expiring_within_days: int | None = None,
    include_empty: bool = False,
    db: Session = Depends(get_db),
):
    query = db.query(StockBatch)
    if product_id:
        query = query.filter(StockBatch.product_id == product_id)
    if not include_empty:
        query = query.filter(StockBatch.quantity_remaining > 0)
    if expiring_within_days is not None:
        query = query.filter(StockBatch.expiry_date <= date.today() + timedelta(days=expiring_within_days))
    return query.order_by(StockBatch.expiry_date.asc()).limit(500).all()


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
    query = db.query(StockBatch)
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
    product.quantity_on_hand = (product.quantity_on_hand or 0) - qty
    db.add(StockMovement(
        product_id=product.id, movement_type="adjustment", quantity_delta=-qty,
        balance_after=product.quantity_on_hand,
        reference=f"WRITE-OFF {batch.batch_number}",
        notes=f"batch write-off (exp {batch.expiry_date})", user_id=user.id,
    ))
    helpers.record_register_entry(db, product, -qty, "adjustment", user.id, reference=f"WRITE-OFF {batch.batch_number}")
    db.commit()
    return {"ok": True, "written_off": qty, "quantity_on_hand": product.quantity_on_hand}


@router.get("/stock/movements", response_model=list[schemas.StockMovementOut])
def list_movements(product_id: int | None = None, limit: int = 200, db: Session = Depends(get_db)):
    query = db.query(StockMovement)
    if product_id:
        query = query.filter(StockMovement.product_id == product_id)
    return query.order_by(StockMovement.created_at.desc()).limit(limit).all()


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
@router.get("/orders", response_model=list[schemas.POOut])
def list_orders(status: str = "", db: Session = Depends(get_db)):
    query = db.query(PurchaseOrder)
    if status:
        query = query.filter(PurchaseOrder.status == status)
    return query.order_by(PurchaseOrder.created_at.desc()).limit(100).all()


@router.get("/orders/paged")
def list_orders_paged(
    status: str = "",
    page: int = 1, per_page: int = paging.DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
):
    """Purchase orders, paged. 217 orders behind a cap of 100."""
    query = db.query(PurchaseOrder)
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
