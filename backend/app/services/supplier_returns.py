"""Goods going back to the wholesaler, and the credit owed for them.

The one part of the stock lifecycle this system had no record of. Returns
happen constantly: a short dated delivery, a cracked bottle, a line ordered in
error, a manufacturer recall. Every one was done by telephone and a note on a
spike, and the stock was adjusted out as a write-off if it was adjusted at
all. The shelf ended up right and the story was gone.

Which matters most for the part nobody sees: a pharmacy that cannot list what
it is owed does not chase it.

THE ORDER OF EVENTS, AND WHY IT IS THAT ORDER

Raise, approve, credit.

Raising quarantines the batches. The goods have to stop moving the moment
somebody decides they are going back, or they sit on the shelf looking
available, get handed to a patient, and the return is approved against stock
that has left the building. Quarantine already exists for exactly this: owned,
counted, and not allowed out.

Approving is what removes them. Until a supervisor has agreed, nothing has
been written off and a return can be cancelled with the batches released back
onto the shelf as if it had never happened.

Crediting is separate again, because it happens on the supplier's timetable
rather than ours, and often weeks later. A return with no credit note against
it is the list a pharmacy should be working down.

WHAT IS VALIDATED, AND WHY EACH ONE

Quantity against what is left in the batch, because a claim for more than was
received is one a supplier will reject and an argument the pharmacy will lose.

The batch against the product, because a line naming somebody else's lot is a
typing mistake that becomes a false claim.

A consumed batch is refused outright: those goods went to a patient, they
cannot also go back to the wholesaler, and the blueprint names this as a
control for the obvious reason.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import (Product, StockBatch, StockMovement, Supplier,
                      SupplierReturn, SupplierReturnLine, User)
from . import quarantine, stock_reasons

#: What a return may be for. A return is always goods leaving because
#: something is wrong with them or with the order, never a count correction.
RETURNABLE = ("damaged", "expired", "recalled", "received")


def raise_return(db: Session, *, supplier_id: int, lines: list[dict],
                 reason: str, user: User, notes: str = "",
                 branch_id: int | None = None) -> SupplierReturn:
    """Start a return and hold the goods. Nothing leaves the shelf yet."""
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(404, "That supplier is not on file.")
    if stock_reasons.get(reason) is None or reason not in RETURNABLE:
        raise HTTPException(
            400, "Say why these are going back. One of: "
                 + ", ".join(RETURNABLE) + ".")
    if not lines:
        raise HTTPException(400, "A return needs at least one line.")

    from .. import helpers
    out = SupplierReturn(
        reference=helpers.next_number(db, SupplierReturn, "RTN", "reference"),
        supplier_id=supplier.id, branch_id=branch_id, status="raised",
        reason_code=reason, notes=(notes or "")[:2000],
        raised_by_id=user.id,
    )
    db.add(out)
    db.flush()

    total = 0.0
    for raw in lines:
        batch = db.get(StockBatch, int(raw.get("batch_id") or 0))
        if batch is None:
            raise HTTPException(400, "A line names a batch that is not on file.")
        product = db.get(Product, batch.product_id)
        quantity = int(raw.get("quantity") or 0)
        if quantity <= 0:
            raise HTTPException(400, f"{product.name}: a return needs a quantity.")
        if quantity > (batch.quantity_remaining or 0):
            raise HTTPException(
                400,
                f"{product.name}: batch {batch.batch_number} has "
                f"{batch.quantity_remaining or 0} unit(s) left and the return "
                f"asks for {quantity}. Goods already dispensed cannot go back "
                "to the supplier as well.")

        line = SupplierReturnLine(
            return_id=out.id, product_id=product.id, batch_id=batch.id,
            quantity=quantity,
            # What it cost, per unit, frozen now.
            unit_cost=round(batch.unit_cost or product.unit_cost(), 4),
        )
        db.add(line)
        total += line.line_total

        # Hold the goods. Already held is fine and common: a recall or an
        # expiry sweep will have got there first, which is usually WHY
        # somebody is raising the return.
        quarantine.hold(db, batch, reason=reason, user=user,
                        note=f"On supplier return {out.reference}.")

    out.total = round(total, 2)
    return out


def approve(db: Session, out: SupplierReturn, *, user: User) -> SupplierReturn:
    """Agree it, and take the goods off the books."""
    if out.status != "raised":
        raise HTTPException(400, f"That return is already {out.status}.")

    from .. import helpers
    for line in out.lines:
        product = db.get(Product, line.product_id)
        batch = db.get(StockBatch, line.batch_id) if line.batch_id else None
        if batch is None:
            continue
        if (batch.quantity_remaining or 0) < line.quantity:
            raise HTTPException(
                400,
                f"{product.name}: batch {batch.batch_number} now holds "
                f"{batch.quantity_remaining or 0} unit(s), fewer than the "
                f"{line.quantity} this return claims. Something has moved "
                "since it was raised.")
        batch.quantity_remaining -= line.quantity
        product.quantity_on_hand = (product.quantity_on_hand or 0) - line.quantity
        db.add(StockMovement(
            product_id=product.id,
            movement_type="supplier_return",
            quantity_delta=-line.quantity,
            balance_after=product.quantity_on_hand,
            reference=out.reference,
            notes=(f"Returned to {out.supplier.name}, batch "
                   f"{batch.batch_number}"),
            reason_code=out.reason_code or "",
            user_id=user.id,
            branch_id=out.branch_id or batch.branch_id,
            pharmacy_id=out.pharmacy_id,
        ))
        # The batch is gone from the shelf, so there is nothing left to hold.
        if (batch.quantity_remaining or 0) <= 0:
            quarantine.release(db, batch, user=user,
                               note=f"Returned in full on {out.reference}.")

    out.status = "approved"
    out.approved_by_id = user.id
    out.approved_at = datetime.utcnow()
    return out


def cancel(db: Session, out: SupplierReturn, *, user: User) -> SupplierReturn:
    """Call it off. Only before approval, and the goods go back on the shelf."""
    if out.status != "raised":
        raise HTTPException(
            400,
            f"That return is {out.status}. Goods that have already left cannot "
            "be un-returned: raise a fresh receipt if the supplier sends them "
            "back.")
    for line in out.lines:
        batch = db.get(StockBatch, line.batch_id) if line.batch_id else None
        if batch is not None:
            quarantine.release(db, batch, user=user,
                               note=f"Return {out.reference} cancelled.")
    out.status = "cancelled"
    return out


def record_credit(db: Session, out: SupplierReturn, *, credit_note: str,
                  user: User) -> SupplierReturn:
    """The supplier has credited it. This is the end of the story."""
    if out.status not in ("approved", "credited"):
        raise HTTPException(
            400, "A return has to be approved before a credit can be recorded "
                 "against it.")
    if not (credit_note or "").strip():
        raise HTTPException(400, "Enter the supplier's credit note number.")
    out.credit_note = credit_note.strip()[:40]
    out.credited_at = datetime.utcnow()
    out.status = "credited"
    return out


def outstanding(db: Session) -> dict:
    """Approved returns with no credit against them. The money to chase."""
    rows = (db.query(SupplierReturn)
            .filter(SupplierReturn.status == "approved")
            .order_by(SupplierReturn.approved_at.asc()).all())
    return {
        "returns": [shape(r) for r in rows],
        "total": round(sum(r.total or 0 for r in rows), 2),
        "count": len(rows),
    }


def shape(out: SupplierReturn) -> dict:
    """One return, as a screen needs it."""
    return {
        "id": out.id,
        "reference": out.reference,
        "supplier_id": out.supplier_id,
        "supplier": out.supplier.name if out.supplier else "",
        "status": out.status,
        "why": stock_reasons.label(out.reason_code),
        "reason_code": out.reason_code or "",
        "notes": out.notes or "",
        "total": round(out.total or 0.0, 2),
        "credit_note": out.credit_note or "",
        "credited_at": out.credited_at.isoformat() if out.credited_at else "",
        "raised_by": out.raised_by.username if out.raised_by else "",
        "approved_by": out.approved_by.username if out.approved_by else "",
        "approved_at": out.approved_at.isoformat() if out.approved_at else "",
        "created_at": out.created_at.isoformat() if out.created_at else "",
        "lines": [{
            "product_id": l.product_id,
            "product": l.product.name if l.product else "",
            "batch": l.batch.batch_number if l.batch else "",
            "expiry": (l.batch.expiry_date.isoformat()
                       if l.batch and l.batch.expiry_date else ""),
            "quantity": l.quantity,
            "unit_cost": round(l.unit_cost or 0.0, 4),
            "line_total": l.line_total,
        } for l in out.lines],
    }
