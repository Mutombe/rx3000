"""What was changed by hand, on which script, by whom, and why.

A pharmacy's figures are mostly computed. The interesting ones are the figures
somebody overrode: a price set by hand at the counter, a shelf count corrected
while a script was being dispensed, stock moved from one branch to another.
Each of those is already recorded somewhere. What did not exist was a way to
ask the question from the other end.

The question a manager actually asks is never "list every price override". It
is "this script, this patient, this morning: was anything about it changed by
hand, and by whom". Answering that from the tables directly means one query per
row on a list of two hundred, so it is answered here in two, for a whole page
at once.

WHAT COUNTS AS AN ADJUSTMENT, AND WHAT DOES NOT

A price override is a row somebody had to authorise with a code, so it counts
whether or not a sale ever followed: an override that was authorised and then
abandoned is the interesting one.

A stock correction counts when it names the script it was made from. It does
NOT count because it happened to be the same product a few minutes earlier.
That inference was the alternative and it is not good enough: on a busy counter
"same product, same user, close in time" is wrong in both directions, and a
guess printed next to a dispenser's name reads as an accusation.

Dispensing a medicine moves stock too, of course, and that is not an
adjustment. Only the movement types a person chooses deliberately are counted:
a correction, a write off, a receipt booked in by hand.
"""
from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from ..models import PriceOverride, StockMovement, User

#: Movement types that mean somebody decided something, as opposed to the
#: ordinary consequence of selling a box.
BY_HAND = ("adjustment", "write_off", "receive", "return")


def _who(user: User | None) -> str:
    return user.full_name if user and user.full_name else (user.username if user else "")


def price_by_prescription(db: Session, prescription_ids) -> dict[int, list[dict]]:
    """Hand set prices and claim amounts, keyed by the script they were on.

    Read off the override's own script link rather than through the item: the
    item does not exist yet when a price is authorised, which is why that
    column was null on every row ever written.
    """
    ids = [i for i in set(prescription_ids or []) if i]
    if not ids:
        return {}

    rows = (
        db.query(PriceOverride)
        .filter(PriceOverride.prescription_id.in_(ids))
        .options(joinedload(PriceOverride.product),
                 joinedload(PriceOverride.requested_by),
                 joinedload(PriceOverride.approved_by))
        .order_by(PriceOverride.created_at.desc())
        .all()
    )

    out: dict[int, list[dict]] = {}
    for override in rows:
        rx_id = override.prescription_id
        out.setdefault(rx_id, []).append({
            "id": override.id,
            "at": override.created_at,
            "kind": override.kind or "price",
            "product_id": override.product_id,
            "product": override.product.name if override.product else "",
            "was": round(override.was or 0.0, 2),
            "now": round(override.now or 0.0, 2),
            "difference": round((override.now or 0.0) - (override.was or 0.0), 2),
            "quantity": override.quantity or 1,
            "reason": override.reason or "",
            "set_by": _who(override.requested_by),
            "approved_by": _who(override.approved_by),
            # An override that was authorised and never used is the one worth
            # seeing, so it is said rather than left to be inferred from a null.
            "reached_a_sale": bool(override.used_at),
        })
    return out


def stock_by_prescription(db: Session, prescription_ids) -> dict[int, list[dict]]:
    """Shelf corrections made with one of these scripts on screen."""
    ids = [i for i in set(prescription_ids or []) if i]
    if not ids:
        return {}

    rows = (
        db.query(StockMovement)
        .filter(StockMovement.prescription_id.in_(ids))
        .filter(StockMovement.movement_type.in_(BY_HAND))
        .options(joinedload(StockMovement.product),
                 joinedload(StockMovement.user))
        .order_by(StockMovement.created_at.desc())
        .all()
    )

    out: dict[int, list[dict]] = {}
    for m in rows:
        out.setdefault(m.prescription_id, []).append({
            "id": m.id,
            "at": m.created_at,
            "product_id": m.product_id,
            "product": m.product.name if m.product else "",
            "movement_type": m.movement_type,
            "quantity_delta": m.quantity_delta,
            "balance_after": m.balance_after,
            "reference": m.reference or "",
            "reason": m.notes or "",
            "by": _who(m.user),
        })
    return out


def summarise(db: Session, prescription_ids) -> dict[int, dict]:
    """Both, per script, in the shape a list row wants.

    A row on a list needs to know THAT something was touched, and how much of
    it, so the screen can mark the row and let somebody open it. The detail is
    carried too, because it is already loaded and a second round trip to read
    four fields is worse than the bytes.
    """
    prices = price_by_prescription(db, prescription_ids)
    stock = stock_by_prescription(db, prescription_ids)

    out: dict[int, dict] = {}
    for rx_id in set(prices) | set(stock):
        p = prices.get(rx_id, [])
        s = stock.get(rx_id, [])
        out[rx_id] = {
            "price_adjusted": bool(p),
            "price_adjustments": len(p),
            "stock_adjusted": bool(s),
            "stock_adjustments": len(s),
            "prices": p,
            "stock": s,
            # One sentence a row can show without opening anything.
            "summary": _sentence(p, s),
        }
    return out


def _sentence(prices: list[dict], stock: list[dict]) -> str:
    """Said in words, because a badge with a number on it explains nothing."""
    parts = []
    if prices:
        who = {p["set_by"] for p in prices if p["set_by"]}
        parts.append(
            f"{len(prices)} price change{'s' if len(prices) != 1 else ''}"
            + (f" by {', '.join(sorted(who))}" if who else ""))
    if stock:
        who = {s["by"] for s in stock if s["by"]}
        parts.append(
            f"{len(stock)} shelf correction{'s' if len(stock) != 1 else ''}"
            + (f" by {', '.join(sorted(who))}" if who else ""))
    return " and ".join(parts)
