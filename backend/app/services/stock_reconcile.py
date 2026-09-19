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

**The cost is the same story.** A product carries `cost_price`, what a PACK
cost, and each batch carries `unit_cost`, what ONE UNIT of that delivery cost.
Two records of the same fact again, and they drifted the same way: three
writers put the pack figure in the unit column, so a batch could be valued at
the pack price against a count of units. The writers are fixed and the rows
that were plainly a copied pack price have been divided.

What is left over is reported here rather than repaired, for the reason above.
A batch costing many times the catalogue's unit cost is either a delivery that
really was dear, which is worth knowing, or a figure in the wrong unit, which
is worth knowing. Neither is worth guessing at: a heuristic that rewrites a
real price to tidy a column has destroyed the only record of what was paid.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Product, StockBatch
from . import valuation


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
            # Both sides of the difference are UNITS, so the price has to be
            # per unit too.
            "value_at_risk": valuation.at_cost(p, abs(on_hand - in_batches)),
        })
    return out


#: How far a batch's cost may sit above the catalogue's unit cost before it is
#: worth a person's attention. Three times is generous for a price that moved
#: between deliveries and far below the pack size of any product where the two
#: units could be confused, the smallest of which is four.
COST_DRIFT = 3.0


def _cost_disagreements(db: Session) -> list[dict]:
    """Live batches whose cost is a long way from the catalogue's.

    Only batches with stock left: a cost on an empty batch prices nothing and
    putting it on the list buries the ones that still matter.
    """
    rows = (
        db.query(StockBatch, Product)
        .join(Product, Product.id == StockBatch.product_id)
        .filter(StockBatch.quantity_remaining > 0,
                StockBatch.unit_cost > 0,
                Product.cost_price > 0,
                Product.units_per_pack > 1)
        .all()
    )
    out = []
    for batch, product in rows:
        catalogue = product.unit_cost()
        if not catalogue or batch.unit_cost <= catalogue * COST_DRIFT:
            continue
        out.append({
            "product_id": product.id,
            "product": f"{product.name} {product.strength or ''}".strip(),
            "batch": batch.batch_number or "",
            "quantity": int(batch.quantity_remaining or 0),
            "batch_cost": round(batch.unit_cost, 4),
            "catalogue_cost": round(catalogue, 4),
            "times": round(batch.unit_cost / catalogue, 1),
            "per_pack": product.per_pack,
            # Said plainly, because the two readings lead to different actions.
            "says": (
                f"This batch is priced at {batch.unit_cost:,.4f} a unit while "
                f"the catalogue says {catalogue:,.4f}. Either the delivery was "
                f"dearer than the catalogue knows, or the figure is a pack "
                f"price in a unit column: one pack is {product.per_pack}."),
            "value": round((batch.quantity_remaining or 0) * batch.unit_cost, 2),
        })
    out.sort(key=lambda r: -r["value"])
    return out


def reconcile(db: Session, *, limit: int = 200) -> dict:
    """The stock control account against its subledger."""
    rows = _rows(db)
    costs = _cost_disagreements(db)
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
        # The other half of the same question: not how many, but at what.
        "cost_drift": costs[:limit],
        "cost_drift_total": len(costs),
        "cost_drift_value": round(sum(r["value"] for r in costs), 2),
    }
