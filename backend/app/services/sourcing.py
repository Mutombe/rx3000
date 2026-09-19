"""Where to buy one line, and how each supplier has actually behaved.

A buyer's question is answered from the supplier: open one and see everything
they supply. A pharmacist's question is the other way round and had no answer
at all: this line is short, who do we get it from, what did they charge, and
do they actually deliver.

WHY THERE IS NO STAR RATING

A number out of five is a judgement wearing the clothes of a measurement.
Nobody can act on "3.4 stars", and the moment somebody disagrees with it they
stop trusting every figure on the screen. What a buyer can act on is the four
facts underneath: what they last charged, whether they send what was ordered,
how long they take, and when they last supplied it. Those are shown, and the
recommendation says which of them it is based on, in words.

WHAT "RECOMMENDED" MEANS HERE, EXACTLY

Cheapest, among those that actually deliver. A supplier who is two percent
cheaper and sends eighty percent of what was ordered is not cheaper; the
shortfall is a second order, a second delivery and a patient waiting. So the
cheapest is taken from those with a fill rate at or above GOOD_FILL, and if
none of them qualifies the cheapest overall is offered with the reason stated.

WHY A SUPPLIER WITH ONE ORDER IS STILL SHOWN

Because a pharmacy that has bought a line once has bought it from somebody,
and hiding them until a sample size is reached leaves the screen empty exactly
when it is first useful. `orders` is on every row, so a fill rate of 100 per
cent from a single delivery can be read for what it is.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import PurchaseOrder, PurchaseOrderItem, Supplier

#: At or above this, a supplier is treated as one that delivers. Below it, a
#: cheaper price is not a saving, it is a second order and a waiting patient.
GOOD_FILL = 0.9

#: How many past orders before a fill rate is worth leaning on. Below this the
#: figure is still shown, and still said to be from few orders.
ENOUGH_ORDERS = 3


def for_product(db: Session, product_id: int) -> dict:
    """Every supplier this line has been bought from, and how they behaved."""
    rows = (
        db.query(PurchaseOrderItem, PurchaseOrder, Supplier)
        .join(PurchaseOrder, PurchaseOrderItem.order_id == PurchaseOrder.id)
        .join(Supplier, PurchaseOrder.supplier_id == Supplier.id)
        .filter(PurchaseOrderItem.product_id == product_id)
        .order_by(PurchaseOrder.created_at.desc())
        .all()
    )

    by_supplier: dict[int, dict] = {}
    for item, order, supplier in rows:
        s = by_supplier.setdefault(supplier.id, {
            "supplier_id": supplier.id,
            "supplier": supplier.name,
            "orders": 0,
            "ordered": 0,
            "received": 0,
            "last_cost": None,
            "best_cost": None,
            "last_ordered": None,
            "days": [],
        })
        s["orders"] += 1
        s["ordered"] += item.quantity_ordered or 0
        s["received"] += item.quantity_received or 0

        cost = round(item.unit_cost or 0.0, 2)
        if cost > 0:
            # Newest first, so the first one seen is the most recent.
            if s["last_cost"] is None:
                s["last_cost"] = cost
            s["best_cost"] = cost if s["best_cost"] is None else min(s["best_cost"], cost)

        if s["last_ordered"] is None:
            s["last_ordered"] = order.created_at
        if order.received_at and order.created_at:
            s["days"].append((order.received_at - order.created_at).days)

    out = []
    for s in by_supplier.values():
        ordered, received = s["ordered"], s["received"]
        fill = round(received / ordered, 4) if ordered else None
        days = s.pop("days")
        out.append({
            **s,
            "fill_rate": fill,
            "avg_days": round(sum(days) / len(days), 1) if days else None,
            "slowest_days": max(days) if days else None,
            "delivers": bool(fill is not None and fill >= GOOD_FILL),
            "few_orders": s["orders"] < ENOUGH_ORDERS,
            # Said in words, because a buyer reads a row rather than a metric.
            "record": _record(s["orders"], fill, days),
        })

    # Cheapest first among those that deliver, then the rest.
    out.sort(key=lambda r: (not r["delivers"],
                            r["last_cost"] if r["last_cost"] is not None else 1e12))

    return {"suppliers": out, "advice": _advice(out)}


def _record(orders: int, fill, days) -> str:
    if fill is None:
        return f"{orders} order(s), none received yet"
    part = f"{orders} order(s), {fill * 100:.0f}% of what was ordered arrived"
    if days:
        part += f", {sum(days) / len(days):.0f} days on average"
    return part


def _advice(rows: list[dict]) -> dict:
    """Who to buy it from, and why, in a sentence somebody can disagree with.

    Stating the reason is the point. A recommendation nobody can argue with is
    one nobody can correct when it is wrong about their trade.
    """
    if not rows:
        return {"supplier_id": None,
                "says": "This line has never been ordered through the system, "
                        "so there is nothing to compare."}

    priced = [r for r in rows if r["last_cost"] is not None]
    if not priced:
        return {"supplier_id": rows[0]["supplier_id"],
                "says": f"Only {rows[0]['supplier']} has supplied this, and no "
                        "cost was recorded against it."}

    reliable = [r for r in priced if r["delivers"]]
    pool = reliable or priced
    best = min(pool, key=lambda r: r["last_cost"])
    cheapest = min(priced, key=lambda r: r["last_cost"])

    if not reliable:
        return {"supplier_id": best["supplier_id"],
                "says": f"{best['supplier']} at {best['last_cost']:.2f}. Nobody "
                        "who has supplied this sends the full quantity "
                        "reliably, so this is on price alone."}

    if best["supplier_id"] != cheapest["supplier_id"]:
        return {
            "supplier_id": best["supplier_id"],
            "says": (f"{best['supplier']} at {best['last_cost']:.2f}. "
                     f"{cheapest['supplier']} is cheaper at "
                     f"{cheapest['last_cost']:.2f} but sends only "
                     f"{(cheapest['fill_rate'] or 0) * 100:.0f}% of what is "
                     "ordered, which is a second order and a waiting patient."),
        }

    note = " on few orders" if best["few_orders"] else ""
    return {"supplier_id": best["supplier_id"],
            "says": (f"{best['supplier']} at {best['last_cost']:.2f}, the "
                     f"cheapest of those that deliver{note}.")}
