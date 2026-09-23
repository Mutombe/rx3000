"""To follows — medicine the pharmacy owes a patient.

The situation is ordinary and happens most days: the script says sixty tablets,
there are twenty on the shelf, and the patient is standing at the counter. No
pharmacy sends them away with nothing. They hand over the twenty, take payment
for the sixty, and owe forty.

That debt exists whether or not the software records it. When the software does
not, it lives on a note stuck to the till, and gets forgotten, or honoured
twice, or argued about when the patient returns and a different assistant is on.
Propharm has this as "To Follows" on Ctrl+T, and a pharmacy that has relied on it
for a decade will not move to a system that makes them go back to paper. It is
probably the single most switch-blocking gap in the product.

Two things here go further than tracking the debt:

* **`ready()` turns the queue around.** The incumbent can tell you what is owed.
  This can tell you what is owed *and now in stock*, which is the difference
  between a list somebody has to remember to check and a list that tells the
  pharmacy who to telephone this morning. Stock arriving is the event that
  matters, and nothing else in the shop notices it.

* **Settling draws through the ordinary FEFO path**, so an owed item handed over
  three weeks later still moves real batches with real expiry dates. A shortcut
  here would put unbatched stock into a patient's hands.
"""
from datetime import date, datetime

from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload

from .. import helpers
from ..models import OwedItem, Product


class OwedError(ValueError):
    """Raised when an owed item cannot be created or settled."""


def next_reference(db: Session) -> str:
    count = db.query(OwedItem).count() + 1
    return f"TF{datetime.utcnow():%y%m}{count:05d}"


def record(db: Session, *, product: Product, quantity_owed: int,
           patient_id: int | None = None, prescription_item_id: int | None = None,
           sale_id: int | None = None, user_id: int | None = None,
           promised_for: date | None = None, notes: str = "") -> OwedItem:
    """Record what could not be handed over.

    Flushes; never commits. The caller owns the unit of work.

    It used to commit, and it is called from inside the dispensing loop, which
    builds a sale, deducts stock and records owed balances line by line and
    commits once at the end — so that a refusal on any line undoes the lot. A
    commit here closed that transaction halfway: a script whose first line was
    partly supplied and whose second was refused for stock left the first
    line's deduction, this balance and a half-built sale saved, while the
    dispenser was told the dispensing had failed. A pharmacy would then owe a
    patient medicine for a supply that never happened.

    Flushing still gives the row its id and makes it visible to the rest of the
    transaction. Committing is left to whoever decided what one transaction is.
    """
    if quantity_owed <= 0:
        raise OwedError("An owed quantity must be positive.")
    owed = OwedItem(
        reference=next_reference(db),
        prescription_item_id=prescription_item_id,
        patient_id=patient_id,
        product_id=product.id,
        sale_id=sale_id,
        quantity_owed=quantity_owed,
        promised_for=promised_for,
        notes=notes,
        created_by_id=user_id,
    )
    db.add(owed)
    db.flush()
    return owed


def outstanding_quantity(owed: OwedItem) -> int:
    return max(0, (owed.quantity_owed or 0) - (owed.quantity_settled or 0))


def settle(db: Session, owed: OwedItem, quantity: int, user_id: int,
           reference: str = "") -> dict:
    """Hand over some or all of what is owed, drawing stock the ordinary way."""
    if owed.status == "cancelled":
        raise OwedError(f"{owed.reference} was cancelled and cannot be settled.")
    if owed.status == "settled":
        raise OwedError(f"{owed.reference} has already been settled in full.")
    remaining = outstanding_quantity(owed)
    if quantity <= 0:
        raise OwedError("A settlement quantity must be positive.")
    if quantity > remaining:
        raise OwedError(
            f"{owed.reference} has {remaining} outstanding; {quantity} was offered.")

    product = owed.product
    # THIS SHELF, not the group's.
    #
    # The gate read the group total and the FEFO walk below draws from one
    # branch, so a pharmacy with stock at the other shop passed this check and
    # was refused three lines later by a different message about batches. Both
    # were true and neither said the useful thing, which is that the medicine
    # is in the other shop and wants a transfer.
    from . import branches as _branches
    branch_id = _branches.branch_of(db, user_id)
    available = (_branches.on_hand_many(
        db, [product.id], branch_id, sellable_only=True).get(product.id, 0)
        if branch_id is not None else (product.quantity_on_hand or 0))
    if available < quantity:
        elsewhere = (product.quantity_on_hand or 0) - available
        raise OwedError(
            f"Only {available} of {product.name} on this branch's shelf: "
            f"{quantity} is needed to settle this."
            + (f" Another branch holds {elsewhere}, raise a transfer."
               if elsewhere > 0 else " Receive stock first."))

    # Through the ordinary FEFO path: an item handed over three weeks late still
    # moves real batches with real expiry dates.
    helpers.consume_stock_fefo(
        db, product, quantity, "sale", user_id,
        reference=reference or f"TO FOLLOW {owed.reference}")
    helpers.record_register_entry(
        db, product, -quantity, "dispense", user_id,
        patient_id=owed.patient_id,
        prescription_item_id=owed.prescription_item_id,
        reference=reference or f"TO FOLLOW {owed.reference}")

    owed.quantity_settled = (owed.quantity_settled or 0) + quantity
    if outstanding_quantity(owed) == 0:
        owed.status = "settled"
        owed.settled_at = datetime.utcnow()
    db.commit()
    db.refresh(owed)
    return summarise(owed)


def cancel(db: Session, owed: OwedItem, reason: str) -> OwedItem:
    """Write the debt off. The patient got it elsewhere, or no longer needs it."""
    if owed.status == "settled":
        raise OwedError(f"{owed.reference} has already been settled.")
    if not (reason or "").strip():
        raise OwedError("Cancelling a to-follow needs a reason.")
    owed.status = "cancelled"
    owed.cancelled_reason = reason.strip()
    db.commit()
    db.refresh(owed)
    return owed


def summarise(owed: OwedItem, on_hand: int | None = None) -> dict:
    """One owed item as a screen reads it.

    `on_hand` is what the branch asking holds, passed in because this is a
    plain function over a loaded row and a per-row stock query down a list of
    two hundred is the thing `on_hand_many` exists to avoid. Left out, it falls
    back to the group total, which is right for a single-shop pharmacy and is
    what every caller got before branches were considered here at all.
    """
    product = owed.product
    remaining = outstanding_quantity(owed)
    if on_hand is None:
        on_hand = (product.quantity_on_hand or 0) if product else 0
    return {
        "id": owed.id,
        "reference": owed.reference,
        "status": owed.status,
        "patient_id": owed.patient_id,
        "patient_name": (f"{owed.patient.first_name} {owed.patient.last_name}".strip()
                         if owed.patient else ""),
        "patient_phone": owed.patient.phone if owed.patient else "",
        "product_id": owed.product_id,
        "product_name": (f"{product.name} {product.strength}".strip()
                         if product else ""),
        "prescription_item_id": owed.prescription_item_id,
        "sale_id": owed.sale_id,
        "quantity_owed": owed.quantity_owed,
        "quantity_settled": owed.quantity_settled,
        "quantity_outstanding": remaining,
        "quantity_on_hand": on_hand,
        # The whole point: not just what is owed, but whether it can be handed
        # over right now.
        "can_settle_now": owed.status == "outstanding" and remaining > 0
                          and on_hand >= remaining,
        "can_settle_partially": owed.status == "outstanding" and 0 < on_hand < remaining,
        "promised_for": owed.promised_for,
        "overdue": bool(owed.promised_for and owed.status == "outstanding"
                        and owed.promised_for < date.today()),
        "notes": owed.notes,
        "cancelled_reason": owed.cancelled_reason,
        "created_at": owed.created_at,
        "created_by": owed.created_by.full_name if owed.created_by else "",
        "settled_at": owed.settled_at,
    }


def _loaded(query):
    """Fetch what `summarise` reads, rather than three round trips a row.

    Every row names a medicine, a patient and whoever recorded the debt, and all
    three were lazy. A hundred and seventy-nine owed items came to a hundred and
    seventy-six queries — eighteen seconds against a hosted database, for the
    list a dispensary works through first thing.
    """
    return query.options(
        joinedload(OwedItem.product),
        joinedload(OwedItem.patient),
        joinedload(OwedItem.created_by),
    )


def _held(db: Session, rows, branch_id: int | None) -> dict[int, int]:
    """What the asking branch holds, for every product in one page of rows."""
    if branch_id is None:
        return {}
    from . import branches as _branches
    return _branches.on_hand_many(
        db, {o.product_id for o in rows if o.product_id},
        branch_id, sellable_only=True)


def queue(db: Session, *, status: str = "outstanding", patient_id: int = 0,
          product_id: int = 0, limit: int = 200,
          branch_id: int | None = None) -> list[dict]:
    query = _loaded(db.query(OwedItem))
    if status:
        query = query.filter(OwedItem.status == status)
    if patient_id:
        query = query.filter(OwedItem.patient_id == patient_id)
    if product_id:
        query = query.filter(OwedItem.product_id == product_id)
    rows = query.order_by(OwedItem.created_at).limit(limit).all()
    here = _held(db, rows, branch_id)
    return [summarise(o, here.get(o.product_id)) for o in rows]


def ready(db: Session, limit: int = 200,
          branch_id: int | None = None) -> list[dict]:
    """What is owed *and* now in stock: the call list.

    Tracking a debt is bookkeeping. Knowing the moment it can be honoured is the
    part the pharmacy actually wants, because stock arriving is an event nothing
    else in the shop connects to a waiting patient.

    WHICH SHELF DECIDES WHO GETS TELEPHONED

    This is the list somebody works down with a phone, so a wrong name on it
    costs a patient a trip. Judged on the group total, a delivery into
    Borrowdale told Avondale to ring five patients and ask them to come in for
    medicine that was four hundred kilometres away, and the mistake only
    surfaced with the patient at the counter.

    The branch filter is applied AFTER the group one rather than instead of it:
    the query narrows to products the pharmacy holds at all, which is a cheap
    index scan, and the branch figures are then summed for that much smaller
    set in one query.
    """
    rows = (_loaded(db.query(OwedItem))
            .join(Product, OwedItem.product_id == Product.id)
            .filter(OwedItem.status == "outstanding",
                    Product.quantity_on_hand > 0)
            .order_by(OwedItem.created_at)
            .limit(limit).all())
    here = _held(db, rows, branch_id)
    out = [summarise(o, here.get(o.product_id)) for o in rows]
    # Oldest promise first, and anything overdue above anything not.
    return sorted([o for o in out if o["quantity_on_hand"] > 0],
                  key=lambda o: (not o["overdue"], not o["can_settle_now"],
                                 o["created_at"]))


def totals(db: Session, branch_id: int | None = None) -> dict:
    outstanding = (db.query(func.count(OwedItem.id),
                            func.coalesce(func.sum(OwedItem.quantity_owed
                                                   - OwedItem.quantity_settled), 0))
                   .filter(OwedItem.status == "outstanding").one())
    # Counted on the same shelf the list itself is counted on, or the tile
    # says four are ready to hand over and the list under it shows one.
    ready_now = [o for o in ready(db, branch_id=branch_id) if o["can_settle_now"]]
    overdue = [o for o in queue(db, branch_id=branch_id) if o["overdue"]]
    return {
        "outstanding_items": outstanding[0],
        "outstanding_units": int(outstanding[1] or 0),
        "ready_to_hand_over": len(ready_now),
        "overdue": len(overdue),
    }
