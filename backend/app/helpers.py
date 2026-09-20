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
    # Two requests reading the same highest number issued the same next one, and
    # the second insert broke the unique index. Held until this transaction ends,
    # so the number is written before anybody else reads.
    from . import concurrency
    concurrency.serialise(db, f"number:{model.__tablename__}:{field}:{prefix}")

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


def in_units(product: Product, quantity: int, in_packs: bool) -> int:
    """Turn a caller's number into the units stock is counted in.

    Stock is held in dispensable units — a tub of a thousand capsules is 1000.
    Callers do not all speak that language: a purchase order is in packs, a
    dispensing is in units, and both arrive as an integer called `quantity`.

    So the caller says which, every time, and this is the only place the
    multiplication happens. There is no default that is right for both, which is
    why `in_packs` has no sensible default and every door states it.
    """
    if not in_packs:
        return int(quantity)
    return int(quantity) * product.per_pack


def move_stock(
    db: Session,
    product: Product,
    delta: int,
    movement_type: str,
    user_id: int | None,
    reference: str = "",
    notes: str = "",
    *,
    in_packs: bool = False,
    prescription_id: int | None = None,
    reason_code: str = "",
) -> StockMovement:
    """Apply a stock movement and record it. Negative delta = stock out.

    `in_packs` says whether `delta` counts packs or dispensable units. Stock is
    held in units; see `in_units` above.
    """
    from . import concurrency
    concurrency.lock_product(db, product)
    delta = in_units(product, delta, in_packs) if delta >= 0 else -in_units(
        product, -delta, in_packs)
    product.quantity_on_hand = (product.quantity_on_hand or 0) + delta
    movement = StockMovement(
        product_id=product.id,
        movement_type=movement_type,
        quantity_delta=delta,
        balance_after=product.quantity_on_hand,
        reference=reference,
        notes=notes,
        user_id=user_id,
        # What the person was doing when they moved it, where that was a
        # script. Null everywhere else, which is most of the time.
        prescription_id=prescription_id,
        # Why, from the list. See services/stock_reasons.
        reason_code=reason_code,
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
    in_packs: bool = False,
    movement_type: str = "receive",
    notes: str = "",
    branch_id: int | None = None,
    prescription_id: int | None = None,
    reason_code: str = "",
) -> StockBatch:
    """Receive stock as a tracked batch (airtime is exempt from batch tracking).

    Goods arrive *somewhere*. A batch with no branch is stock that exists in the
    database and on a shelf but appears at neither, so incoming stock is stamped
    with the receiving branch, defaulting to the default one.
    """
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Receive quantity must be positive")
    # A delivery is counted in packs and the shelf is counted in units. Ten tubs
    # of a thousand is ten thousand capsules, and the batch has to be written in
    # the same currency the dispensing will draw from it in.
    quantity = in_units(product, quantity, in_packs)
    if branch_id is None:
        from .services import branches as _branches
        branch_id = _branches.branch_of(db, user_id) or _branches.default_branch(db).id
    from . import concurrency
    concurrency.lock_product(db, product)

    # ONE LOT, ONE BATCH ROW.
    #
    # A batch number names a manufacturing lot. The same product and the same
    # lot at the same branch is the SAME goods, so a second delivery from it
    # belongs on the row that is already there rather than beside it. Two rows
    # for one lot means a recall traces one of them, FEFO treats them as
    # separate queues, and a delivery note posted twice silently doubles the
    # shelf — which is the ordinary Monday mistake, not an exotic one.
    #
    # The importer has guarded this since it was written, with a comment
    # saying so. Neither receive path did.
    #
    # An expiry that disagrees is refused rather than merged. One lot cannot
    # have two expiry dates: either the number was mistyped or the date was,
    # and both are worth somebody's attention before the stock is on a shelf
    # and a patient is holding it.
    existing = None
    if batch_number:
        existing = (
            db.query(StockBatch)
            .filter(StockBatch.product_id == product.id,
                    StockBatch.branch_id == branch_id,
                    func.upper(StockBatch.batch_number) == batch_number.strip().upper())
            .first()
        )
    if existing is not None:
        wanted = expiry_date or existing.expiry_date
        if (existing.expiry_date and wanted and existing.expiry_date != wanted):
            raise HTTPException(
                status_code=400,
                detail=(f"{product.name}: batch {batch_number} is already on "
                        f"this shelf expiring {existing.expiry_date.isoformat()}, "
                        f"and this delivery says {wanted.isoformat()}. One lot "
                        "cannot have two expiry dates, so one of them is a "
                        "typing mistake. Check the box."))
        existing.quantity_received = (existing.quantity_received or 0) + quantity
        existing.quantity_remaining = (existing.quantity_remaining or 0) + quantity
        if unit_cost is not None:
            existing.unit_cost = unit_cost / product.per_pack
        product.quantity_on_hand = (product.quantity_on_hand or 0) + quantity
        db.add(StockMovement(
            product_id=product.id,
            movement_type=movement_type,
            quantity_delta=quantity,
            balance_after=product.quantity_on_hand,
            reference=reference,
            notes=(notes + f" | added to existing batch {existing.batch_number}").strip(" |"),
            user_id=user_id,
            branch_id=branch_id,
            prescription_id=prescription_id,
            reason_code=reason_code,
        ))
        return existing

    batch = StockBatch(
        product_id=product.id,
        batch_number=batch_number or f"AUTO-{datetime.utcnow():%y%m%d%H%M%S}",
        expiry_date=expiry_date or (date.today() + timedelta(days=DEFAULT_SHELF_LIFE_DAYS)),
        quantity_received=quantity,
        quantity_remaining=quantity,
        # PER UNIT, the same as the two quantities above it.
        #
        # This stored `product.cost_price`, which is what a PACK cost, against
        # a quantity that was converted to units three lines earlier. Every
        # reader that multiplies `quantity_remaining * unit_cost` was then
        # over by the pack size. A caller that passes a cost passes a per pack
        # one too, because that is what a purchase order line and a supplier
        # invoice carry, so it is converted here rather than at each call.
        unit_cost=(unit_cost / product.per_pack if unit_cost is not None
                   else product.unit_cost()),
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
        prescription_id=prescription_id,
        reason_code=reason_code,
    ))
    return batch


def stock_without_a_good_date(db: Session, product: Product, branch_id: int) -> tuple[int, int]:
    """Units at this branch that dispensing cannot count: (undated, expired)."""
    undated = (db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
               .filter(StockBatch.product_id == product.id,
                       StockBatch.quantity_remaining > 0,
                       StockBatch.branch_id == branch_id,
                       StockBatch.expiry_date.is_(None))
               .scalar() or 0)
    expired = (db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
               .filter(StockBatch.product_id == product.id,
                       StockBatch.quantity_remaining > 0,
                       StockBatch.branch_id == branch_id,
                       StockBatch.expiry_date < date.today())
               .scalar() or 0)
    return int(undated), int(expired)


def dated_stock(db: Session, product: Product, branch_id: int) -> int:
    """Units at this branch that dispensing can draw: in date, with a date."""
    return int(db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
               .filter(StockBatch.product_id == product.id,
                       StockBatch.quantity_remaining > 0,
                       StockBatch.branch_id == branch_id,
                       StockBatch.expiry_date >= date.today())
               .scalar() or 0)


def date_undated_stock(db: Session, product: Product, expiry: date, user_id: int | None,
                       branch_id: int | None = None) -> list[StockBatch]:
    """Record the expiry read off the pack on this branch's undated stock.

    The CareXpress opening stock arrived as one batch per product with no expiry,
    which dispensing cannot draw from: its whole point is refusing stock that
    might be out of date. Rather than let undated stock through, the dispenser
    holding the pack is asked for the date printed on it, and the batch is dated
    with it — so the shelf is dated one dispensing at a time, and the label that
    goes on the box carries a real expiry.

    Each dating is recorded as a zero-quantity stock movement: who read the date,
    when, and onto which batch. A batch has nowhere else to say it.
    """
    if branch_id is None:
        from .services import branches as _branches
        branch_id = _branches.branch_of(db, user_id) or _branches.default_branch(db).id
    undated = (db.query(StockBatch)
               .filter(StockBatch.product_id == product.id,
                       StockBatch.quantity_remaining > 0,
                       StockBatch.branch_id == branch_id,
                       StockBatch.expiry_date.is_(None))
               .all())
    for batch in undated:
        batch.expiry_date = expiry
        db.add(StockMovement(
            product_id=product.id, movement_type="adjustment", quantity_delta=0,
            balance_after=product.quantity_on_hand or 0,
            reference=f"EXPIRY {batch.batch_number}"[:60],
            notes=f"Expiry {expiry:%d %b %Y} recorded from the pack at dispensing.",
            user_id=user_id, branch_id=branch_id,
        ))
    db.flush()
    return undated


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
    in_packs: bool = False,
    prescription_id: int | None = None,
    reason_code: str = "",
    prefer_batch_id: int | None = None,
    override_note: str = "",
) -> list[BatchAllocation]:
    """Draw stock First-Expiry-First-Out, from one branch.

    Expired batches are skipped for dispensing and sales (allow_expired=False)
    but remain usable for write-offs.

    `prefer_batch_id` names a lot to take ahead of the rotation. It moves that
    batch to the front of the walk and changes NOTHING else: the lot is still
    checked for branch, expiry, quarantine and stock, and anything the walk
    cannot fill from it carries on FEFO down the rest of the shelf. An
    override is permission to break the rotation rule, never a safety one.
    Authorisation is the caller's business, because only the caller knows
    whether a supervisor stood there; see services/fefo.py.

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
        branch_id = _branches.branch_of(db, user_id) or _branches.default_branch(db).id
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    # A till sells boxes and a dispensary sells tablets; the batches are in
    # tablets. Converted here so the FEFO walk below draws the right amount
    # whichever door the sale came through.
    quantity = in_units(product, quantity, in_packs)
    # The shelf as it is now, not as it was when this request first looked:
    # two counters reading ten units each drew one and both wrote nine.
    from . import concurrency
    concurrency.lock_product(db, product)

    query = (
        db.query(StockBatch)
        .filter(StockBatch.product_id == product.id,
                StockBatch.quantity_remaining > 0,
                StockBatch.branch_id == branch_id)
    )
    if not allow_expired:
        query = query.filter(StockBatch.expiry_date >= date.today())
        # Quarantined stock does not go out. Held on the same flag as
        # `allow_expired` because the two callers that pass it are a write-off
        # and a stock take, and both of those are exactly the acts that have
        # to be able to reach quarantined goods: a batch pulled for damage is
        # written off FROM quarantine, and a count counts what is on the shelf
        # whether it may be sold or not.
        query = query.filter(StockBatch.status != "quarantined")
    batches = query.order_by(StockBatch.expiry_date.asc(), StockBatch.id.asc()).all()

    # A NAMED LOT GOES FIRST, AND ONLY FIRST.
    #
    # Moved to the head of the same list rather than replacing it, so a lot
    # holding three units of a ten unit supply gives its three and the other
    # seven come off the shelf in rotation, which is what happens in the room.
    # It is taken from `batches` rather than fetched separately, so every
    # filter above still applies to it: naming a quarantined or out of branch
    # lot cannot smuggle it past the checks by way of the override.
    if prefer_batch_id:
        chosen = [b for b in batches if b.id == int(prefer_batch_id)]
        if chosen:
            batches = chosen + [b for b in batches if b.id != int(prefer_batch_id)]

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
        # Named only when some of the shelf really is undated or expired. A plain
        # shortage used to come through here too and read "only 4 in-date units
        # — . Take the expired stock off the shelf." on a shelf with none.
        parts: list[str] = []
        action = ""
        if not allow_expired and total_any and available < quantity:
            # Say which it is. This said "check batches for expired stock" for
            # every shortfall of dated stock, and on the CareXpress import most
            # of it is not expired at all: the opening stock came in as one
            # batch per product with no expiry recorded, which a dated check
            # cannot count. A dispenser was sent looking for expired packs on a
            # shelf of good ones.
            undated, expired = stock_without_a_good_date(db, product, branch_id)
            if undated:
                parts.append(f"{undated} unit(s) have no expiry date recorded")
            if expired:
                parts.append(f"{expired} unit(s) are past their expiry")
            action = (" Enter the expiry printed on the pack to dispense them."
                      if undated else " Take the expired stock off the shelf.")
        if parts:
            raise HTTPException(
                status_code=400,
                detail=(f"{product.name}: only {available} in-date unit(s) at this branch. "
                        + " and ".join(parts) + "." + action + hint),
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
        # Said on the movement for the lot that was actually jumped to, not on
        # the ones the walk carried on to afterwards. A report counting
        # overrides counts packs taken out of turn, and the remainder that
        # came off the shelf in rotation was not taken out of turn.
        jumped = (override_note and prefer_batch_id
                  and batch.id == int(prefer_batch_id))
        db.add(StockMovement(
            product_id=product.id,
            movement_type=movement_type,
            quantity_delta=-take,
            balance_after=product.quantity_on_hand,
            reference=reference,
            notes=(notes + f" | batch {batch.batch_number} exp {batch.expiry_date}"
                   + (f" | taken ahead of rotation: {override_note}" if jumped else "")
                   ).strip(" |"),
            user_id=user_id,
            branch_id=branch_id,
            prescription_id=prescription_id,
            reason_code=reason_code,
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
    from . import concurrency
    concurrency.lock_product(db, product)
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
                # `untracked` comes off quantity_on_hand, so it is units, and
                # the cost beside it has to be per unit too.
                unit_cost=product.unit_cost(),
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


def refuse_if_retired(product: Product, doing: str) -> None:
    """A line taken out of use cannot be used for anything NEW.

    Deactivating a product hid it from the pickers and stopped there. The
    catalogue search would not offer it, the dispensary would not suggest it,
    and every endpoint that took a `product_id` would still accept one: a
    stale browser tab, a barcode on an old box, a saved basket, an import
    naming the code. So a line retired precisely BECAUSE it should not go out
    any more could still be dispensed, sold, received and transferred, and
    nothing on any screen looked wrong.

    WHAT IS STILL ALLOWED, AND WHY IT HAS TO BE

    Correcting and writing off. A product is usually retired while there is
    still stock on the shelf, and that stock has to be counted, written off
    and reconciled afterwards. Refusing those would leave the units stranded
    on the books with no lawful way to remove them, which is a worse problem
    than the one this fixes.

    So: nothing new goes OUT to a patient or IN from a supplier, and the
    housekeeping that empties the shelf is untouched.
    """
    if product is not None and product.active is False:
        raise HTTPException(
            status_code=400,
            detail=(f"{product.name} has been taken out of use, so it cannot "
                    f"be {doing}. Stock already on the shelf can still be "
                    "counted or written off. If this line is wanted again, "
                    "put it back into use first."))
