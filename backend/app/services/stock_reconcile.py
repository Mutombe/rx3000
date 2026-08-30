"""Does the shelf count agree with the batches behind it?

A product carries `quantity_on_hand`. Its batches each carry
`quantity_remaining`. These are two records of the same fact, and the ledger has
had a control-versus-subledger check since it was written for exactly this
reason — a figure kept in two places will disagree, and the day it does is the
day something was posted around one of them.

Stock had no such check, and the two had drifted on more than half the
catalogue.

**Why it matters more than it sounds.** The two numbers are not decoration for
each other; different parts of the software trust different ones:

  * Dispensing draws against BATCHES, first-expiry-first-out, at one branch,
    skipping anything expired. That is what actually decides whether medicine
    can go out today.
  * Almost every screen shows `quantity_on_hand` — the reorder report, the
    product record, the counter's "can we supply this" prompt.

So a pharmacy can be told it has none of something it has three hundred of, or
be sent to reorder a line the shelf is full of. Worse, `quantity_on_hand` has
no floor: a batch write-off subtracts the batch's remainder from it whether or
not the product ever had that much, which is how a product ends up at minus
seven and a dispenser reads "only -7 on hand".

**What this does not do is guess.** It reports the difference and where it
falls; it does not silently correct one from the other, because which of them
is right is a question only a person holding the box can answer. The fix is a
stock take, and that is a screen this software already has.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Product, StockBatch


def _rows(db: Session) -> list[dict]:
    """Every product, its own count, and what its batches say.

    Two grouped queries and a join in Python rather than a correlated subquery
    per product: this walks the whole catalogue, and a query per product is the
    shape that makes an audit too slow to run.
    """
    products = (db.query(Product)
                .filter(Product.active.is_(True))
                .order_by(Product.name).all())

    held = dict(
        db.query(StockBatch.product_id,
                 func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
        .group_by(StockBatch.product_id).all())

    # What could actually be dispensed today: unexpired only. A pharmacy with
    # four hundred units of something that expired last month has stock on the
    # shelf and nothing it may hand over, and those are different problems.
    usable = dict(
        db.query(StockBatch.product_id,
                 func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
        .filter(StockBatch.expiry_date >= date.today())
        .group_by(StockBatch.product_id).all())

    out = []
    for p in products:
        in_batches = int(held.get(p.id, 0) or 0)
        can_use = int(usable.get(p.id, 0) or 0)
        on_hand = int(p.quantity_on_hand or 0)
        out.append({
            "product_id": p.id,
            "product": f"{p.name} {p.strength or ''}".strip(),
            "on_hand": on_hand,
            "in_batches": in_batches,
            "usable": can_use,
            "expired": in_batches - can_use,
            "difference": on_hand - in_batches,
            "negative": on_hand < 0,
            # Priced at cost: a difference of four hundred units of something
            # cheap is a different conversation from four of something dear,
            # and a list sorted by unit count puts the wrong one first.
            "value_at_risk": round(abs(on_hand - in_batches) * (p.cost_price or 0.0), 2),
        })
    return out


def reconcile(db: Session, *, limit: int = 200) -> dict:
    """The stock control account against its subledger."""
    rows = _rows(db)
    off = [r for r in rows if r["difference"] != 0]
    negative = [r for r in rows if r["negative"]]

    # Which way the drift runs is the diagnosis. Counted low against the
    # batches means stock was taken out without its batch being drawn down —
    # an adjustment, a write-off applied twice, an import. Counted high means
    # batches were consumed without the product's own figure following.
    counted_low = [r for r in off if r["difference"] < 0]
    counted_high = [r for r in off if r["difference"] > 0]

    off.sort(key=lambda r: -r["value_at_risk"])

    return {
        "as_at": date.today(),
        "products": len(rows),
        "disagreeing": len(off),
        "agree_rate": round(1 - len(off) / len(rows), 4) if rows else 1.0,
        "counted_low": len(counted_low),
        "counted_high": len(counted_high),
        "negative": len(negative),
        "value_at_risk": round(sum(r["value_at_risk"] for r in off), 2),
        "reconciled": not off,
        "message": (
            "Every product's own count agrees with its batches."
            if not off else
            f"{len(off)} of {len(rows)} products disagree with the batches "
            f"behind them, {round(sum(r['value_at_risk'] for r in off), 2):,.2f} "
            f"at cost. Dispensing draws against the batches; almost every screen "
            f"shows the product's own count. Until they agree the two will tell "
            f"a pharmacy different things about the same shelf."),
        "lines": off[:limit],
        "truncated": len(off) > limit,
    }
