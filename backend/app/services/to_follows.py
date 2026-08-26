"""To follows — medicine the pharmacy owes a patient.

The situation is ordinary and happens most days: the script says sixty tablets,
there are twenty on the shelf, and the patient is standing at the counter. No
pharmacy sends them away with nothing. They hand over the twenty, take payment
for the sixty, and owe forty.

That debt exists whether or not the software records it. When the software does
not, it lives on a note stuck to the till — and gets forgotten, or honoured
twice, or argued about when the patient returns and a different assistant is on.
Propharm has this as "To Follows" on Ctrl+T, and a pharmacy that has relied on it
for a decade will not move to a system that makes them go back to paper. It is
probably the single most switch-blocking gap in the product.

Two things here go further than tracking the debt:

* **`ready()` turns the queue around.** The incumbent can tell you what is owed.
  This can tell you what is owed *and now in stock* — which is the difference
  between a list somebody has to remember to check and a list that tells the
  pharmacy who to telephone this morning. Stock arriving is the event that
  matters, and nothing else in the shop notices it.

* **Settling draws through the ordinary FEFO path**, so an owed item handed over
  three weeks later still moves real batches with real expiry dates. A shortcut
  here would put unbatched stock into a patient's hands.
"""
from datetime import date, datetime

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

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
    """Record what could not be handed over."""
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
    db.commit()
    db.refresh(owed)
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
    available = product.quantity_on_hand or 0
    if available < quantity:
        raise OwedError(
            f"Only {available} of {product.name} in stock — {quantity} is needed to "
            "settle this. Receive stock first.")

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


def summarise(owed: OwedItem) -> dict:
    product = owed.product
    remaining = outstanding_quantity(owed)
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


def queue(db: Session, *, status: str = "outstanding", patient_id: int = 0,
          product_id: int = 0, limit: int = 200) -> list[dict]:
    query = db.query(OwedItem)
    if status:
        query = query.filter(OwedItem.status == status)
    if patient_id:
        query = query.filter(OwedItem.patient_id == patient_id)
    if product_id:
        query = query.filter(OwedItem.product_id == product_id)
    rows = query.order_by(OwedItem.created_at).limit(limit).all()
    return [summarise(o) for o in rows]


def ready(db: Session, limit: int = 200) -> list[dict]:
    """What is owed *and* now in stock — the call list.

    Tracking a debt is bookkeeping. Knowing the moment it can be honoured is the
    part the pharmacy actually wants, because stock arriving is an event nothing
    else in the shop connects to a waiting patient.
    """
    rows = (db.query(OwedItem)
            .join(Product, OwedItem.product_id == Product.id)
            .filter(OwedItem.status == "outstanding",
                    Product.quantity_on_hand > 0)
            .order_by(OwedItem.created_at)
            .limit(limit).all())
    out = [summarise(o) for o in rows]
    # Oldest promise first, and anything overdue above anything not.
    return sorted([o for o in out if o["quantity_on_hand"] > 0],
                  key=lambda o: (not o["overdue"], not o["can_settle_now"],
                                 o["created_at"]))


def totals(db: Session) -> dict:
    outstanding = (db.query(func.count(OwedItem.id),
                            func.coalesce(func.sum(OwedItem.quantity_owed
                                                   - OwedItem.quantity_settled), 0))
                   .filter(OwedItem.status == "outstanding").one())
    ready_now = [o for o in ready(db) if o["can_settle_now"]]
    overdue = [o for o in queue(db) if o["overdue"]]
    return {
        "outstanding_items": outstanding[0],
        "outstanding_units": int(outstanding[1] or 0),
        "ready_to_hand_over": len(ready_now),
        "overdue": len(overdue),
    }
