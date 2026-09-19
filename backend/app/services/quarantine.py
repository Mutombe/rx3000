"""Stock the pharmacy owns and may not hand over.

Expired stock was already unsellable, because the FEFO walk filters on the
date. That achieves the safety outcome and nothing else. The stock is
invisible rather than held: nobody can list it, nobody is asked to do anything
about it, and it sits on a real shelf where a person can reach it.

And it only ever covered expiry. A batch pulled because a bottle arrived
cracked, or because the manufacturer withdrew it that morning, had no way to
be marked at all. The recall module says in its own docstring that it reports
"how much is still on the shelf to quarantine" — a verb the software did not
have.

WHAT QUARANTINE IS NOT

It is not a write-off. The pharmacy paid for these goods, they are on a shelf,
and whether the money comes back depends on a supplier credit that has not
happened yet. Taking them out of the valuation would be deciding that in
advance, which is the same mistake the recall module refuses to make when it
says the financial side is "deliberately not automatic".

So quarantined stock stays owned, stays counted, and stays out of every path
that hands goods to a person: dispensing, the till, and transfers between
branches. Held apart from what can be sold is a different thing from gone.

WHY RELEASING IS A SEPARATE ACT WITH A NAME ON IT

Because the reason it was held may have been wrong. A batch quarantined in a
recall that turns out to name different lot numbers should go back on the
shelf, and that decision wants the same trail as the one that held it. Both
write a movement of zero units, which is this system's existing way of saying
"nothing moved and something happened".
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from ..models import StockBatch, StockMovement, User
from . import stock_reasons

HELD = "quarantined"
FREE = "available"


def hold(db: Session, batch: StockBatch, *, reason: str, user: User | None = None,
         note: str = "") -> bool:
    """Take one batch out of circulation. False if it was already held."""
    if (batch.status or FREE) == HELD:
        return False
    batch.status = HELD
    batch.quarantined_at = datetime.utcnow()
    batch.quarantined_by_id = getattr(user, "id", None)
    batch.quarantine_reason = (reason or "")[:20]
    batch.quarantine_note = (note or "")[:200]
    _note(db, batch, user,
          f"Quarantined: {stock_reasons.label(reason) or 'held'}"
          + (f". {note}" if note else ""))
    return True


def release(db: Session, batch: StockBatch, *, user: User | None = None,
            note: str = "") -> bool:
    """Put one batch back on the shelf. False if it was not being held."""
    if (batch.status or FREE) != HELD:
        return False
    was = batch.quarantine_reason
    batch.status = FREE
    batch.quarantined_at = None
    batch.quarantined_by_id = None
    batch.quarantine_reason = ""
    batch.quarantine_note = ""
    _note(db, batch, user,
          f"Released from quarantine (was {stock_reasons.label(was) or 'held'})"
          + (f". {note}" if note else ""))
    return True


def _note(db: Session, batch: StockBatch, user: User | None, said: str) -> None:
    """Write it down, as a movement of nothing.

    A quantity of zero is how this system already records something that
    happened to stock without any stock moving: a reprice does it, and so does
    a bin change. It keeps the whole story of a batch on one timeline rather
    than in a second table nobody thinks to look in.
    """
    db.add(StockMovement(
        product_id=batch.product_id,
        movement_type="quarantine",
        quantity_delta=0,
        balance_after=batch.quantity_remaining or 0,
        reference=batch.batch_number or "",
        notes=said,
        reason_code=batch.quarantine_reason or "",
        user_id=getattr(user, "id", None),
        branch_id=batch.branch_id,
        # TAKEN FROM THE BATCH, NOT LEFT TO THE STAMP.
        #
        # The nightly sweep runs with no tenant in force, so `tenancy.stamp`
        # has nothing to write and the row lands with a null pharmacy — which
        # is not merely untidy, it is INVISIBLE to every tenant, because the
        # scoping filter matches on the column. The batch knows whose it is,
        # so the row is stamped from it and the answer is right whether this
        # was called from a request or from a job at ten past seven.
        #
        # Third time this has bitten: StockAlert wrote 1,081 invisible
        # findings the same way, and the stock sweep before it.
        pharmacy_id=batch.pharmacy_id,
    ))


def sweep_expired(db: Session, *, today: date | None = None) -> int:
    """Hold every batch that has gone past its date, and say how many.

    The blueprint asks for expired stock to be quarantined automatically, and
    the nightly sweep is already walking these rows to raise the alert, so it
    costs nothing to also enforce what the alert is about.

    Only batches with something left. A batch that has been fully dispensed
    expires like any other and holding it would put thousands of rows on a
    screen whose whole purpose is the handful somebody must go and deal with.
    """
    today = today or date.today()
    rows = (
        db.query(StockBatch)
        .filter(StockBatch.quantity_remaining > 0,
                StockBatch.expiry_date.isnot(None),
                StockBatch.expiry_date < today,
                StockBatch.status != HELD)
        .all()
    )
    for batch in rows:
        hold(db, batch, reason="expired",
             note=f"Expired {batch.expiry_date.isoformat()}, held by the nightly sweep.")
    return len(rows)


def held_stock(db: Session, limit: int = 300) -> list[dict]:
    """What is being held, dearest first, with why and since when."""
    from ..models import Product
    from . import valuation

    rows = (
        db.query(StockBatch, Product)
        .join(Product, Product.id == StockBatch.product_id)
        .filter(StockBatch.status == HELD, StockBatch.quantity_remaining > 0)
        .all()
    )
    out = [{
        "batch_id": batch.id,
        "product_id": product.id,
        "product": f"{product.name} {product.strength or ''}".strip(),
        "batch": batch.batch_number or "",
        "expiry": batch.expiry_date.isoformat() if batch.expiry_date else "",
        "quantity": int(batch.quantity_remaining or 0),
        "value": valuation.at_cost(product, batch.quantity_remaining or 0),
        "why": stock_reasons.label(batch.quarantine_reason) or "Held",
        "reason_code": batch.quarantine_reason or "",
        "note": batch.quarantine_note or "",
        "since": batch.quarantined_at.isoformat() if batch.quarantined_at else "",
        "by": batch.quarantined_by.username if batch.quarantined_by else "",
        # Who it came from, so a return can be raised from this screen without
        # the person having to know. Null where the line has no supplier on
        # file, which is the honest answer and disables the button rather than
        # guessing at a wholesaler.
        "supplier_id": product.supplier_id,
        "supplier": product.supplier.name if product.supplier else "",
        # Whether a return has already been raised for this batch, so the
        # button does not offer to do it twice.
        "on_return": bool(batch.quarantine_note
                          and "supplier return" in batch.quarantine_note.lower()),
    } for batch, product in rows]
    out.sort(key=lambda r: -r["value"])
    return out[:limit]
