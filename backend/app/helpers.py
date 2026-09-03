"""Shared domain helpers: numbering, stock movements, batches/FEFO, schedule register."""
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import BatchAllocation, Product, RegisterEntry, StockBatch, StockMovement

REGISTER_SCHEDULE_MIN = 5  # S5 and S6 substances go into the electronic register
DEFAULT_SHELF_LIFE_DAYS = 730  # assumed expiry when none is supplied at receipt


def next_number(db: Session, model, prefix: str, field: str) -> str:
    """The next document number for this pharmacy, this month.

    Read from the numbers already issued, not from a count of rows.

    Counting rows is wrong whenever a number is issued without adding a row, or
    a row is added without taking a number, and this system does both:

      finalising a draft takes a number and creates nothing, so the count does
        not move and the next caller is handed the SAME number;
      saving a draft creates a row and takes no number, so the count runs ahead
        of what has been issued and numbers are skipped.

    Every numbered document then carries a per-pharmacy UNIQUE index (see
    `PER_TENANT_NUMBERS` in migrate.py), so the duplicate is not a cosmetic
    oddity: Postgres refuses the insert and the request fails with a 500. In
    production that read as "Something went wrong at our end" on an ordinary
    prescription capture, immediately after a draft had been finished, and it
    would have done the same to a sale, a claim, a waybill or a lay-by, all
    nineteen of which are numbered here.

    So the highest number already issued this period is read back, and the
    candidate is then checked to be genuinely free. The check costs one indexed
    lookup and covers the two cases the arithmetic alone cannot: a width change
    once five digits are exhausted, and a number issued by a request that
    landed between this one's read and its write.

    Scoped to the pharmacy automatically: the model carries `TenantMixin`, so
    the query is filtered before it reaches the database, which is the same
    boundary the unique index is drawn on.
    """
    stamp = f"{prefix}{datetime.utcnow():%y%m}"
    column = getattr(model, field)

    highest = (db.query(func.max(column))
               .filter(column.like(f"{stamp}%")).scalar())
    n = 1
    if highest:
        tail = str(highest)[len(stamp):]
        if tail.isdigit():
            n = int(tail) + 1

    # Walk forward off any number already taken. Bounded, because an unbounded
    # loop against a database is how a slow page becomes a hung one.
    for _ in range(1000):
        candidate = f"{stamp}{n:05d}"
        if not db.query(column).filter(column == candidate).first():
            return candidate
        n += 1
    raise RuntimeError(
        f"Could not find a free {field} for {stamp} after 1000 tries. "
        f"Something is issuing numbers faster than they can be recorded.")


def move_stock(
    db: Session,
    product: Product,
    delta: int,
    movement_type: str,
    user_id: int | None,
    reference: str = "",
    notes: str = "",
) -> StockMovement:
    """Apply a stock movement and record it. Negative delta = stock out."""
    product.quantity_on_hand = (product.quantity_on_hand or 0) + delta
    movement = StockMovement(
        product_id=product.id,
        movement_type=movement_type,
        quantity_delta=delta,
        balance_after=product.quantity_on_hand,
        reference=reference,
        notes=notes,
        user_id=user_id,
    )
    db.add(movement)
    return movement


def receive_stock_batch(
    db: Session,
    product: Product,
    quantity: int,
    user_id: int | None,
    batch_number: str = "",
    expiry_date: date | None = None,
    unit_cost: float | None = None,
    reference: str = "",
    movement_type: str = "receive",
    notes: str = "",
    branch_id: int | None = None,
) -> StockBatch:
    """Receive stock as a tracked batch (airtime is exempt from batch tracking).

    Goods arrive *somewhere*. A batch with no branch is stock that exists in the
    database and on a shelf but appears at neither, so incoming stock is stamped
    with the receiving branch, defaulting to the default one.
    """
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Receive quantity must be positive")
    if branch_id is None:
        from .services import branches as _branches
        branch_id = _branches.default_branch(db).id
    batch = StockBatch(
        product_id=product.id,
        batch_number=batch_number or f"AUTO-{datetime.utcnow():%y%m%d%H%M%S}",
        expiry_date=expiry_date or (date.today() + timedelta(days=DEFAULT_SHELF_LIFE_DAYS)),
        quantity_received=quantity,
        quantity_remaining=quantity,
        unit_cost=unit_cost if unit_cost is not None else product.cost_price,
        reference=reference,
        branch_id=branch_id,
    )
    db.add(batch)
    product.quantity_on_hand = (product.quantity_on_hand or 0) + quantity
    db.add(StockMovement(
        product_id=product.id,
        movement_type=movement_type,
        quantity_delta=quantity,
        balance_after=product.quantity_on_hand,
        reference=reference,
        notes=(notes + f" | batch {batch.batch_number} exp {batch.expiry_date}").strip(" |"),
        user_id=user_id,
        branch_id=branch_id,
    ))
    return batch


def consume_stock_fefo(
    db: Session,
    product: Product,
    quantity: int,
    movement_type: str,
    user_id: int | None,
    reference: str = "",
    notes: str = "",
    sale_item_id: int | None = None,
    allow_expired: bool = False,
    branch_id: int | None = None,
) -> list[BatchAllocation]:
    """Draw stock First-Expiry-First-Out, from one branch.

    Expired batches are skipped for dispensing and sales (allow_expired=False)
    but remain usable for write-offs.

    `branch_id` is the till's branch. It defaults to the default branch, which
    is what a single-shop pharmacy has and never thinks about. It matters the
    moment there are two shops: without it a dispenser in Bulawayo would draw
    against a batch sitting in Harare, decrementing stock that is four hundred
    kilometres away and handing the patient something the shelf does not hold.
    Every path that consumes stock comes through here, so scoping it here scopes
    all of them.
    """
    if branch_id is None:
        from .services import branches as _branches
        branch_id = _branches.default_branch(db).id
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")

    query = (
        db.query(StockBatch)
        .filter(StockBatch.product_id == product.id,
                StockBatch.quantity_remaining > 0,
                StockBatch.branch_id == branch_id)
    )
    if not allow_expired:
        query = query.filter(StockBatch.expiry_date >= date.today())
    batches = query.order_by(StockBatch.expiry_date.asc(), StockBatch.id.asc()).all()

    available = sum(b.quantity_remaining for b in batches)
    if available < quantity:
        total_any = (
            db.query(StockBatch)
            .filter(StockBatch.product_id == product.id,
                    StockBatch.quantity_remaining > 0,
                    StockBatch.branch_id == branch_id)
            .count()
        )
        # If another branch holds it, say so. "Insufficient stock" sends someone
        # to reorder; "Bulawayo has 40" sends them to raise a transfer, which is
        # the same afternoon rather than the next delivery.
        elsewhere = (
            db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
            .filter(StockBatch.product_id == product.id,
                    StockBatch.quantity_remaining > 0,
                    StockBatch.branch_id != branch_id)
            .scalar() or 0
        )
        hint = (f" Another branch holds {int(elsewhere)}, raise a transfer."
                if elsewhere else "")
        if not allow_expired and total_any and available < quantity:
            raise HTTPException(
                status_code=400,
                detail=f"{product.name}: only {available} unexpired unit(s) at this "
                       f"branch. Check batches for expired stock.{hint}",
            )
        raise HTTPException(
            status_code=400,
            detail=f"{product.name}: not enough stock at this branch "
                   f"({available} available).{hint}",
        )

    allocations: list[BatchAllocation] = []
    remaining = quantity
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.quantity_remaining, remaining)
        batch.quantity_remaining -= take
        remaining -= take
        product.quantity_on_hand = (product.quantity_on_hand or 0) - take
        db.add(StockMovement(
            product_id=product.id,
            movement_type=movement_type,
            quantity_delta=-take,
            balance_after=product.quantity_on_hand,
            reference=reference,
            notes=(notes + f" | batch {batch.batch_number} exp {batch.expiry_date}").strip(" |"),
            user_id=user_id,
            branch_id=branch_id,
        ))
        allocation = BatchAllocation(
            batch_id=batch.id, sale_item_id=sale_item_id, quantity=take, reference=reference,
        )
        db.add(allocation)
        allocations.append(allocation)
    return allocations


def restore_allocations(
    db: Session,
    product: Product,
    sale_item_id: int,
    user_id: int | None,
    reference: str = "",
) -> int:
    """Return voided stock to the exact batches it was drawn from."""
    allocations = (
        db.query(BatchAllocation).filter(BatchAllocation.sale_item_id == sale_item_id).all()
    )
    restored = 0
    for allocation in allocations:
        batch = allocation.batch
        batch.quantity_remaining += allocation.quantity
        product.quantity_on_hand = (product.quantity_on_hand or 0) + allocation.quantity
        restored += allocation.quantity
        db.add(StockMovement(
            product_id=product.id,
            movement_type="return",
            quantity_delta=allocation.quantity,
            balance_after=product.quantity_on_hand,
            reference=reference,
            notes=f"void, restored to batch {batch.batch_number}",
            user_id=user_id,
        ))
        db.delete(allocation)
    return restored


def return_sale_stock(db: Session, sale, user_id: int | None, reference: str) -> None:
    """Put a reversed sale's stock back where it came from.

    Shared by the two ways a sale is undone, because they must leave inventory
    in the same state. A void withdraws the sale outright; a credit note leaves
    the original receipt standing and files a reversing one, which is the only
    lawful route once a receipt has been filed with the revenue authority. The
    fiscal treatment differs: the stock does not. The goods came back over the
    counter either way, and they belong in the batches they were drawn from so
    they keep their expiry dates.
    """
    for item in sale.items:
        product = item.product
        if not product or product.category == "airtime":
            continue
        restored = restore_allocations(db, product, item.id, user_id, reference=reference)
        if restored < item.quantity:  # sales that predate batch tracking
            move_stock(db, product, item.quantity - restored, "return", user_id,
                       reference=sale.sale_number, notes="reversal (untracked)")
        record_register_entry(db, product, item.quantity, "adjustment", user_id,
                              reference=reference)

    # Give back any pre-authorisation the sale had drawn. Without this the
    # patient silently loses cover for medicine they handed back.
    from .services import authorisation as _authorisation
    _authorisation.release(db, reference=sale.sale_number,
                           claim_id=sale.claim.id if sale.claim else None)

    # The ledger follows the goods. A sale that came back must not still be
    # sitting in revenue.
    from .services import posting as _posting
    _posting.post_reversal(db, sale, user_id)


def ensure_opening_batches(db: Session) -> int:
    """Create OPENING batches for stock that predates batch tracking."""
    created = 0
    products = db.query(Product).filter(Product.category != "airtime").all()
    for product in products:
        tracked = (
            db.query(StockBatch)
            .filter(StockBatch.product_id == product.id)
            .with_entities(StockBatch.quantity_remaining)
            .all()
        )
        tracked_qty = sum(q for (q,) in tracked)
        untracked = (product.quantity_on_hand or 0) - tracked_qty
        if untracked > 0:
            db.add(StockBatch(
                product_id=product.id,
                batch_number="OPENING",
                expiry_date=date.today() + timedelta(days=540),
                quantity_received=untracked,
                quantity_remaining=untracked,
                unit_cost=product.cost_price,
                reference="opening stock",
            ))
            created += 1
    return created


def record_register_entry(
    db: Session,
    product: Product,
    delta: int,
    entry_type: str,
    user_id: int | None,
    patient_id: int | None = None,
    doctor_id: int | None = None,
    prescription_item_id: int | None = None,
    reference: str = "",
) -> RegisterEntry | None:
    """Record an S5/S6 register entry. No-op for lower schedules."""
    if (product.schedule or 0) < REGISTER_SCHEDULE_MIN:
        return None
    entry = RegisterEntry(
        product_id=product.id,
        schedule=product.schedule,
        entry_type=entry_type,
        quantity_delta=delta,
        balance_after=product.quantity_on_hand,
        patient_id=patient_id,
        doctor_id=doctor_id,
        prescription_item_id=prescription_item_id,
        user_id=user_id,
        reference=reference,
    )
    db.add(entry)
    return entry
