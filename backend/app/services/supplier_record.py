"""How one wholesaler has actually behaved, across everything they supply.

`sourcing` answers the pharmacist's question: this line is short, who do we
get it from. This answers the owner's: we have spent eleven thousand dollars
with these people this year, are they any good.

Nothing here is new information. It is the same purchase orders, receipts and
quotations the pharmacy already has, read down the supplier instead of across
the product, which is the direction nobody could read them in before. A buyer
renewing terms, or deciding which of two wholesalers to drop, had no screen to
open and went on what they remembered.

WHY THERE IS STILL NO STAR RATING

For the reason `sourcing` gives and one more. A number out of five is a
judgement wearing the clothes of a measurement, and the moment somebody
disagrees with it they stop trusting every figure on the screen. But also: the
weights would be ours, not the pharmacy's. A shop in Bulawayo that cannot hold
stock cares far more about lead time than about two percent on price, and a
single blended score quietly decides that trade-off on their behalf and hides
it. So the facts are separated, each said in the unit it was measured in, and
the person who knows their own trade weighs them.

WHAT "SHORT" MEANS, AND WHY IT IS COUNTED IN ORDERS NOT UNITS

A supplier who sends 99 per cent of a very large order and one who sends
nothing on two small ones can show the same unit fill rate, and they are not
the same supplier. The second one has left a shelf empty twice. So both are
kept: the proportion of units that arrived, and the number of orders that came
up short.

SILENCE IS A FACT ABOUT A SUPPLIER

A wholesaler who never answers a request for quotation costs the pharmacy the
time it took to ask and the days it waited. That is worth as much as their
price, and until now it was recorded nowhere anybody looked.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import PurchaseOrder, RfqQuote, RfqSupplier, Supplier
from .sourcing import ENOUGH_ORDERS, GOOD_FILL

#: Spend inside this many days is "recent", for the question a buyer actually
#: asks: are we still using these people.
RECENT_DAYS = 90


def _days_between(order: PurchaseOrder) -> int | None:
    """How long they took, counted from when the order actually went.

    From `sent_at` where there is one, because the days an order sat in draft
    on somebody's screen are the pharmacy's fault and not the wholesaler's,
    and counting them makes every supplier look slower than they are.
    """
    start = order.sent_at or order.created_at
    if not (start and order.received_at):
        return None
    return max((order.received_at - start).days, 0)


def _orders_for(db: Session, supplier_ids: list[int]) -> dict[int, list]:
    """Every order for these suppliers, in one query, grouped by supplier.

    The league asked per supplier, which was three queries each and a page
    that gets slower every time the pharmacy takes on a wholesaler. The lines
    come with them, because reading `order.items` afterwards is the same N+1
    one level down.
    """
    rows = (
        db.query(PurchaseOrder)
        .options(joinedload(PurchaseOrder.items))
        .filter(PurchaseOrder.supplier_id.in_(supplier_ids))
        .filter(PurchaseOrder.status != "cancelled")
        .order_by(PurchaseOrder.created_at.desc())
        .all()
    )
    grouped: dict[int, list] = {sid: [] for sid in supplier_ids}
    for order in rows:
        grouped.setdefault(order.supplier_id, []).append(order)
    return grouped


def _invites_for(db: Session, supplier_ids: list[int]) -> dict[int, list]:
    """Every quotation these suppliers were invited to, in one query."""
    rows = (
        db.query(RfqSupplier)
        .options(joinedload(RfqSupplier.quotes))
        .filter(RfqSupplier.supplier_id.in_(supplier_ids))
        .all()
    )
    grouped: dict[int, list] = {sid: [] for sid in supplier_ids}
    for invited in rows:
        grouped.setdefault(invited.supplier_id, []).append(invited)
    return grouped


def _buying(db: Session, supplier: Supplier, rows: list | None = None) -> dict:
    """What they have been ordered, and what actually arrived."""
    if rows is None:
        rows = _orders_for(db, [supplier.id])[supplier.id]

    since = datetime.utcnow() - timedelta(days=RECENT_DAYS)
    ordered = received = 0
    spend = recent_spend = 0.0
    short_orders = 0
    days: list[int] = []
    products: set[int] = set()
    received_orders = 0
    last_order = last_delivery = None

    outstanding = 0
    for order in rows:
        if last_order is None:
            last_order = order.created_at
        # AN ORDER STILL IN TRANSIT HAS NOT FAILED TO DELIVER.
        #
        # The first version divided everything received by everything ever
        # ordered, so an order sent yesterday and not yet in dragged the
        # supplier to "0% arrives" in red. On the demonstration data that
        # branded seven of nine wholesalers as total failures, and it would
        # have done the same in production the day anybody had an order
        # outstanding, which is every day.
        #
        # Silence is not nought. Same rule the quotation comparison already
        # follows: an answer nobody has given yet is not an answer of none.
        # So the fill rate is computed over DELIVERED orders only, and what
        # is still on its way is carried separately.
        delivered = bool(order.received_at) or any(
            (i.quantity_received or 0) > 0 for i in order.items)
        came_up_short = False
        for item in order.items:
            products.add(item.product_id)
            want = item.quantity_ordered or 0
            got = item.quantity_received or 0
            if delivered:
                ordered += want
                received += got
                if got < want:
                    came_up_short = True
            else:
                outstanding += want
            value = (item.unit_cost or 0.0) * got
            spend += value
            when = order.received_at or order.created_at
            if when and when >= since:
                recent_spend += value
        # `delivered` is read off the lines as well as the header, because an
        # order can be receipted line by line without anything stamping
        # `received_at`. Reading the header alone said a supplier had
        # received nought orders while the same card showed 580 units arrived
        # from them, and two figures from the same rows contradicting each
        # other on one screen is how a person stops believing both.
        if delivered:
            received_orders += 1
            if last_delivery is None:
                last_delivery = order.received_at or order.created_at
            # Only a delivered order can be short. One still in transit has
            # not failed at anything yet.
            if came_up_short:
                short_orders += 1
        took = _days_between(order)
        if took is not None:
            days.append(took)

    fill = round(received / ordered, 4) if ordered else None
    return {
        "orders": len(rows),
        "orders_received": received_orders,
        "units_ordered": ordered,
        "units_received": received,
        # What is still on its way, kept apart from what failed to arrive.
        "units_outstanding": outstanding,
        "fill_rate": fill,
        "short_orders": short_orders,
        "lines_supplied": len(products),
        "spend": round(spend, 2),
        "recent_spend": round(recent_spend, 2),
        "avg_days": round(sum(days) / len(days), 1) if days else None,
        "slowest_days": max(days) if days else None,
        "quickest_days": min(days) if days else None,
        "last_ordered": last_order,
        "last_delivered": last_delivery,
        "delivers": bool(fill is not None and fill >= GOOD_FILL),
        "few_orders": len(rows) < ENOUGH_ORDERS,
    }


def _quoting(db: Session, supplier: Supplier, invited: list | None = None,
             best_on: dict[int, float] | None = None) -> dict:
    """Whether they answer when asked, and how they price when they do."""
    if invited is None:
        invited = _invites_for(db, [supplier.id])[supplier.id]
    asked = [i for i in invited if i.sent_at]
    answered = [i for i in asked if i.responded_at]
    declined = [i for i in answered if i.declined]

    replies: list[int] = []
    for i in answered:
        if i.sent_at and i.responded_at:
            replies.append(max((i.responded_at - i.sent_at).days, 0))

    # How often their price was the best one on the table. Counted per line,
    # because a wholesaler who is keenest on two lines out of twenty is not a
    # cheap supplier, and a single "cheapest quote" badge would say they were.
    mine = [q for i in answered for q in i.quotes
            if q.available and q.unit_price]
    # Every rival price on those lines, in ONE query. Asking per line was a
    # query per quoted line, which on a supplier with a year of quotations
    # behind them is a page that takes seconds to answer a question nobody
    # thinks is expensive. The league hands this in already worked out for
    # everybody, so the whole table costs one query rather than one each.
    if best_on is None:
        best_on = cheapest_by_line(db, [q.rfq_line_id for q in mine])

    lines_quoted = len(mine)
    keenest = sum(1 for q in mine
                  if q.unit_price <= best_on.get(q.rfq_line_id, q.unit_price))

    return {
        "asked": len(asked),
        "answered": len(answered),
        "declined": len(declined),
        "never_answered": len(asked) - len(answered),
        "avg_reply_days": round(sum(replies) / len(replies), 1) if replies else None,
        "lines_quoted": lines_quoted,
        "keenest_on": keenest,
    }


def _verdict(buying: dict, quoting: dict, supplier: Supplier) -> list[dict]:
    """The findings, in sentences, each one arguable.

    A list rather than a paragraph because a buyer reads down it, and because
    a finding that does not apply is simply absent rather than rendered as a
    hedge. `tone` is what the pharmacy should feel about it, not a score.
    """
    out: list[dict] = []
    name = supplier.name

    if not buying["orders"]:
        out.append({"tone": "muted",
                    "says": f"Nothing has ever been ordered from {name} "
                            "through the system, so there is nothing to judge."})
        return out

    fill = buying["fill_rate"]
    if fill is None:
        waiting = (f", {buying['units_outstanding']} unit(s) still to come"
                   if buying["units_outstanding"] else "")
        out.append({"tone": "muted",
                    "says": f"{buying['orders']} order(s) placed and none "
                            f"delivered yet{waiting}, so how they deliver is "
                            "not known."})
    elif fill >= GOOD_FILL:
        note = " on few orders" if buying["few_orders"] else ""
        out.append({"tone": "ok",
                    "says": f"{fill * 100:.0f}% of what was ordered arrived"
                            f"{note}."})
    else:
        out.append({"tone": "bad",
                    "says": f"Only {fill * 100:.0f}% of what was ordered "
                            "arrived. A cheaper price from them is not a "
                            "saving, it is a second order and a waiting "
                            "patient."})

    if buying["short_orders"]:
        out.append({
            "tone": "warn" if buying["short_orders"] < 3 else "bad",
            "says": f"{buying['short_orders']} of {buying['orders_received']} "
                    "delivered order(s) came up short of what was asked for.",
        })

    if buying["avg_days"] is not None:
        spread = ""
        if buying["slowest_days"] is not None and buying["quickest_days"] is not None \
                and buying["slowest_days"] > buying["quickest_days"]:
            spread = (f", between {buying['quickest_days']} and "
                      f"{buying['slowest_days']}")
        out.append({"tone": "muted",
                    "says": f"{buying['avg_days']:g} days from sending the "
                            f"order to receiving it on average{spread}."})

    if quoting["asked"]:
        if quoting["never_answered"]:
            out.append({
                "tone": "warn",
                "says": f"Asked for a price {quoting['asked']} time(s) and did "
                        f"not answer {quoting['never_answered']} of them.",
            })
        if quoting["avg_reply_days"] is not None:
            out.append({"tone": "muted",
                        "says": f"Replies to a request in "
                                f"{quoting['avg_reply_days']:g} day(s) on average."})
        if quoting["lines_quoted"]:
            share = quoting["keenest_on"] / quoting["lines_quoted"]
            out.append({
                "tone": "ok" if share >= 0.5 else "muted",
                "says": f"Cheapest on {quoting['keenest_on']} of "
                        f"{quoting['lines_quoted']} line(s) they have quoted.",
            })

    if buying["last_ordered"]:
        idle = (datetime.utcnow() - buying["last_ordered"]).days
        if idle > 180:
            out.append({"tone": "warn",
                        "says": f"Nothing has been ordered from them for "
                                f"{idle} days."})
    return out


def cheapest_by_line(db: Session, line_ids: list[int]) -> dict[int, float]:
    """The best available price quoted on each of these lines."""
    best: dict[int, float] = {}
    if not line_ids:
        return best
    for quote in (db.query(RfqQuote)
                  .filter(RfqQuote.rfq_line_id.in_(set(line_ids))).all()):
        if not (quote.available and quote.unit_price):
            continue
        at = best.get(quote.rfq_line_id)
        if at is None or quote.unit_price < at:
            best[quote.rfq_line_id] = quote.unit_price
    return best


def card(db: Session, supplier: Supplier, *, orders: list | None = None,
         invited: list | None = None,
         best_on: dict[int, float] | None = None) -> dict:
    """Everything known about how this wholesaler behaves."""
    buying = _buying(db, supplier, orders)
    quoting = _quoting(db, supplier, invited, best_on)
    return {
        "supplier_id": supplier.id,
        "supplier": supplier.name,
        **buying,
        "quoting": quoting,
        "findings": _verdict(buying, quoting, supplier),
    }


def league(db: Session, limit: int = 50) -> list[dict]:
    """Every supplier side by side, dearest relationship first.

    Ordered by spend rather than by any measure of quality, deliberately: the
    supplier worth ten minutes of an owner's attention is the one taking the
    most money, whether they are the best or the worst on the list.
    """
    suppliers = db.query(Supplier).limit(limit).all()
    ids = [s.id for s in suppliers]
    if not ids:
        return []

    # Four queries for the whole table rather than three per supplier. At
    # nine wholesalers that was 29; a pharmacy with fifty would have paid 150
    # for one page, and nothing about the page tells anybody it is expensive.
    orders = _orders_for(db, ids)
    invites = _invites_for(db, ids)
    best_on = cheapest_by_line(db, [
        q.rfq_line_id
        for rows in invites.values() for i in rows for q in i.quotes])

    out = [card(db, s, orders=orders.get(s.id, []),
                invited=invites.get(s.id, []), best_on=best_on)
           for s in suppliers]
    out.sort(key=lambda r: -r["spend"])
    return out
