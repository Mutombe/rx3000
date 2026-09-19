"""What a line has been priced at, and who moved it.

One entry point, called from every place a price is written, because a trail
with three of the four doors covered is worse than none: it reads as complete
and is not.

There are exactly four such doors in this application and they are all here in
the docstring so the next one is added deliberately rather than discovered
missing:

    form      the product screen, somebody editing the line by hand
    import    a supplier price file, or the price backfill from sales history
    counter   "from now on" on a price authorised at the dispensary
    margin    a price set by choosing a margin rather than a figure

WHAT IS NOT RECORDED, AND WHY

A change that changes nothing. Saving the product form rewrites every field
whether or not it moved, so recording unconditionally would write a row every
time somebody corrected a spelling, and the trail would be mostly noise with
the real decisions buried in it. Only a figure that actually moved is written.

A price that was already null and is still null. A line nobody has priced is
not a price decision.

Rounding is to four places rather than two, deliberately: these are per pack
figures divided by pack size at the counter, and a half cent lost here is a
margin that does not reconcile there.
"""
from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from ..models import PriceChange, Product, User

#: How much of a move is worth a row. Below this it is a rounding artefact
#: rather than a decision, and a trail full of them cannot be read.
EPSILON = 0.0001


def record(db: Session, product: Product, *, field: str, was, now,
           user: User | None = None, source: str = "form",
           reason: str = "") -> PriceChange | None:
    """Write one price movement. Returns None when nothing moved.

    Does NOT commit. The caller is already in a transaction that is changing
    the product, and the trail must land or fail with it: a history that
    survives a rolled back price change is a lie about what happened.
    """
    old = round(float(was or 0.0), 4)
    new = round(float(now or 0.0), 4)
    if abs(new - old) < EPSILON:
        return None

    row = PriceChange(
        product_id=product.id,
        field=field,
        was=old,
        now=new,
        source=source,
        reason=(reason or "").strip()[:200],
        changed_by_id=user.id if user else None,
    )
    db.add(row)
    return row


def for_product(db: Session, product_id: int, limit: int = 50) -> list[dict]:
    """The trail for one line, newest first, in the shape a screen wants."""
    rows = (
        db.query(PriceChange)
        .filter(PriceChange.product_id == product_id)
        .options(joinedload(PriceChange.changed_by))
        .order_by(PriceChange.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [{
        "id": r.id,
        "at": r.created_at,
        "field": r.field,
        "was": round(r.was or 0.0, 2),
        "now": round(r.now or 0.0, 2),
        "difference": r.difference,
        "percent": r.percent,
        "source": r.source,
        "reason": r.reason or "",
        "by": (r.changed_by.full_name or r.changed_by.username) if r.changed_by else "",
        # Said rather than left to the reader, because "form" and "import" are
        # our words, not a pharmacist's.
        "how": HOW.get(r.source, r.source),
    } for r in rows]


#: Our internal word, and what it means to somebody reading the screen.
HOW = {
    "form": "Changed on the product screen",
    "import": "Loaded from a supplier price file",
    "counter": "Set at the counter, and kept from then on",
    "margin": "Set by choosing a margin",
}
