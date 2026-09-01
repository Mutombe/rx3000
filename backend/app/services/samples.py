"""The sample register: medicine in the building that is not stock.

A representative leaves a box of something on the counter. It is medicine, it is
in the pharmacy, and it is not stock — it was not bought, it cannot be sold, and
it appears on no invoice. That is precisely why it goes missing from the records:
every other medicine in the building arrives through a purchase order and leaves
through a till, and a sample does neither.

MCAZ expects a pharmacy to account for what it holds. A box of samples with no
paper trail is the easiest thing in the shop to be wrong about, and "a rep left
them, I think in March" is not an answer to an inspector.

The shape is the controlled register's, because it is the same question: what
came in, what went out, to whom, and what is left. The balance is carried on each
movement rather than recomputed, so a register whose balance does not descend is
visibly wrong rather than quietly recalculated into looking right.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import Product, SampleMovement, SampleReceipt

#: What a movement can be, and whether it takes stock off the shelf.
MOVEMENTS = {
    "issued": ("Given to a patient", True),
    "returned": ("Returned to the representative", True),
    "destroyed": ("Destroyed", True),
    "expired": ("Written off, out of date", True),
    "counted": ("Counted, balance corrected", False),
}


class SampleError(ValueError):
    """Raised when a sample movement cannot be recorded as asked."""


def _next_reference(db: Session) -> str:
    n = db.query(func.count(SampleReceipt.id)).scalar() or 0
    return f"SMP{4000 + n + 1}"


def receive(db: Session, *, product_id: int, quantity: int, supplier_name: str,
            representative: str = "", batch_number: str = "",
            expiry_date: date | None = None, user_id: int | None = None,
            notes: str = "") -> SampleReceipt:
    """Book in what a representative left.

    The expiry is asked for and not required. A sample often arrives in a plain
    box with the date on the blister inside, and refusing to record it at all
    until somebody finds the date means it does not get recorded, which is the
    situation this exists to end.
    """
    product = db.get(Product, product_id)
    if not product:
        raise SampleError("That product is not in the catalogue.")
    if quantity <= 0:
        raise SampleError("A receipt has to be for at least one unit.")
    if not supplier_name.strip():
        raise SampleError(
            "Say who left them. A sample with no source cannot be returned, "
            "queried or explained.")

    receipt = SampleReceipt(
        reference=_next_reference(db),
        product_id=product_id,
        supplier_name=supplier_name.strip()[:160],
        representative=representative.strip()[:120],
        batch_number=batch_number.strip()[:60],
        expiry_date=expiry_date,
        quantity_received=quantity,
        quantity_remaining=quantity,
        received_by_id=user_id,
        notes=notes.strip(),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def move(db: Session, receipt_id: int, *, movement: str, quantity: int,
         patient_id: int | None = None, given_to: str = "",
         witness_id: int | None = None, reason: str = "",
         user_id: int | None = None) -> SampleMovement:
    """Record something leaving, and carry the balance.

    Destruction needs a witness, the same as writing off a controlled item. One
    person deciding on their own that medicine was destroyed is the gap every
    stock loss goes through, and a field nobody is made to fill in is a field
    that stays empty.
    """
    receipt = db.get(SampleReceipt, receipt_id)
    if not receipt:
        raise SampleError("That receipt is not on file.")
    if movement not in MOVEMENTS:
        raise SampleError(f"'{movement}' is not a kind of movement this register keeps.")
    if quantity <= 0:
        raise SampleError("A movement has to be for at least one unit.")

    label, reduces = MOVEMENTS[movement]
    if reduces and quantity > (receipt.quantity_remaining or 0):
        raise SampleError(
            f"Only {receipt.quantity_remaining} left on {receipt.reference}. "
            f"Recording {quantity} would put the register below zero, which "
            "means either the count or an earlier movement is wrong.")
    if movement == "destroyed" and not witness_id:
        raise SampleError(
            "Destroying medicine needs a second person to witness it. "
            "One person deciding alone is the gap every stock loss goes through.")
    if movement == "issued" and not (patient_id or given_to.strip()):
        raise SampleError(
            "Say who it was given to. A sample handed over with no name is the "
            "one an inspector asks about.")

    if movement == "counted":
        # A count sets the balance rather than reducing it, and the difference is
        # what gets explained.
        balance = quantity
    else:
        balance = (receipt.quantity_remaining or 0) - quantity

    entry = SampleMovement(
        receipt_id=receipt.id,
        movement=movement,
        quantity=quantity,
        balance_after=max(0, balance),
        patient_id=patient_id,
        given_to=given_to.strip()[:120],
        witness_id=witness_id,
        reason=reason.strip(),
        user_id=user_id,
    )
    receipt.quantity_remaining = max(0, balance)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def register(db: Session, *, only_open: bool = False, limit: int = 200) -> dict:
    """The register, newest receipt first, with what is left on each."""
    query = db.query(SampleReceipt).options(joinedload(SampleReceipt.product))
    if only_open:
        query = query.filter(SampleReceipt.quantity_remaining > 0)
    rows = (query.order_by(SampleReceipt.received_at.desc())
                 .limit(limit + 1).all())
    more = len(rows) > limit
    rows = rows[:limit]

    today = date.today()
    items = []
    for r in rows:
        expired = bool(r.expiry_date and r.expiry_date < today)
        items.append({
            "id": r.id,
            "reference": r.reference,
            "product_id": r.product_id,
            "product": f"{r.product.name} {r.product.strength or ''}".strip() if r.product else "",
            "schedule": r.product.schedule if r.product else None,
            "supplier_name": r.supplier_name,
            "representative": r.representative,
            "batch_number": r.batch_number,
            "expiry_date": r.expiry_date,
            "quantity_received": r.quantity_received,
            "quantity_remaining": r.quantity_remaining,
            "received_at": r.received_at,
            "received_by": r.received_by.full_name if r.received_by else "",
            "expired": expired,
            # Expired samples still on the shelf are the finding an inspector
            # writes down, so they are named rather than left to be noticed.
            "attention": ("Out of date and still on the register"
                          if expired and (r.quantity_remaining or 0) > 0 else ""),
            "notes": r.notes,
        })

    # Counted over the whole register rather than the page.
    open_q = db.query(SampleReceipt).filter(SampleReceipt.quantity_remaining > 0)
    return {
        "items": items,
        "more": more,
        "total": db.query(func.count(SampleReceipt.id)).scalar() or 0,
        "open": open_q.count(),
        "units_held": db.query(func.coalesce(func.sum(SampleReceipt.quantity_remaining), 0)).scalar() or 0,
        "expired_open": open_q.filter(SampleReceipt.expiry_date.isnot(None),
                                      SampleReceipt.expiry_date < today).count(),
    }


def history(db: Session, receipt_id: int) -> list[dict]:
    """Every movement against one receipt, oldest first, as a register reads."""
    rows = (db.query(SampleMovement)
              .filter(SampleMovement.receipt_id == receipt_id)
              .order_by(SampleMovement.created_at.asc())
              .all())
    return [{
        "id": m.id,
        "movement": m.movement,
        "label": MOVEMENTS.get(m.movement, (m.movement, True))[0],
        "quantity": m.quantity,
        "balance_after": m.balance_after,
        "given_to": m.given_to or (
            f"{m.patient.first_name} {m.patient.last_name}" if m.patient else ""),
        "witness": m.witness.full_name if m.witness else "",
        "reason": m.reason,
        "by": m.user.full_name if m.user else "",
        "created_at": m.created_at,
    } for m in rows]
