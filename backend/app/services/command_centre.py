"""The one screen an owner opens first, answering what to do about today.

A dashboard of counts is a dashboard nobody reads twice. "Fourteen low stock
lines" is a fact; it becomes a decision only when it says what those lines are
worth and what happens if nothing is done. So every figure here is either money
or leads to money, and every one of them is attached to the screen that can act
on it.

Four questions, in the order an owner actually asks them:

  **Is today better or worse?**  Takings against the same day last week, not
  against nothing. A number with no comparison cannot be good or bad.

  **Which shop is working?**  Sales by branch, side by side, with the margin —
  because the branch taking the most money is not always the one earning it.

  **What am I losing without seeing it?**  The repeat book: what fell due, what
  was captured, and what the gap is worth. A repeat that was not filled leaves
  no record anywhere, so this is the only place it appears.

  **What is my money doing?**  Owed to us and by us, and how much of what is
  owed is late enough to be at risk.

Assembled from the services that already answer each of these, rather than
recomputing them here. Two screens giving different answers to the same
question is worse than one screen that is a little slower.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..models import Product, Sale, StockBatch
from . import branch_scorecard, repeat_performance


def _money(v) -> float:
    return round(float(v or 0.0), 2)


def _trend(now: float, before: float) -> dict:
    """This period against the last, said as a direction and a share.

    `None` where there is nothing to compare against: a first week in business
    has no trend, and rendering one as "+100%" is a number somebody could act
    on wrongly.
    """
    if before <= 0.005:
        return {"change": None, "direction": "flat", "was": _money(before)}
    change = round((now - before) / before, 4)
    return {
        "change": change,
        "direction": "up" if change > 0.02 else "down" if change < -0.02 else "flat",
        "was": _money(before),
    }


def overview(db: Session, *, days: int = 14) -> dict:
    today = date.today()
    since = today - timedelta(days=days - 1)
    prior = since - timedelta(days=days)

    # ---- takings, day by day, over twice the window ------------------------
    #
    # Twice, so the same length of time before it can be compared without a
    # second query. One grouped query for both halves.
    rows = (
        db.query(func.date(Sale.created_at).label("day"),
                 func.count(Sale.id),
                 func.coalesce(func.sum(Sale.total), 0.0))
        .filter(Sale.status == "paid",
                Sale.created_at >= datetime.combine(prior, datetime.min.time()))
        .group_by(func.date(Sale.created_at))
        .all())

    def as_date(v):
        return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])

    by_day = {as_date(d): (int(n), _money(v)) for d, n, v in rows if d}

    series, this_half, last_half = [], 0.0, 0.0
    for offset in range(days):
        when = since + timedelta(days=offset)
        count, value = by_day.get(when, (0, 0.0))
        this_half += value
        was = by_day.get(when - timedelta(days=days), (0, 0.0))[1]
        last_half += was
        series.append({
            "date": when,
            "sales": count,
            "value": value,
            # The same weekday a fortnight ago, so a Monday is compared with a
            # Monday. Comparing a Saturday with the Friday before it is how a
            # pharmacy convinces itself trade has collapsed every weekend.
            "before": was,
            "today": when == today,
        })

    todays = by_day.get(today, (0, 0.0))
    same_day_before = by_day.get(today - timedelta(days=7), (0, 0.0))

    # ---- which shop is working ---------------------------------------------
    board = branch_scorecard.scorecard(db, days=days)
    branches = [{
        "branch_id": b["branch_id"],
        "branch": b["branch"],
        "value": b["sales"]["value"],
        "count": b["sales"]["count"],
        "average": b["sales"]["average"],
        # Cash-up accuracy is the one branch measure that is about people
        # rather than about trade, and the one an owner can do something about
        # this week.
        "cashup_accuracy": b["cashup"]["accuracy"],
        "variance": b["cashup"]["total_variance"],
        "scripts": b["dispensing"]["items"],
        "claims_recovered": b["claims"]["recovery"],
    } for b in board.get("branches", [])]
    branches.sort(key=lambda r: -r["value"])
    board_total = sum(b["value"] for b in branches)
    for b in branches:
        b["share"] = round(b["value"] / board_total, 4) if board_total > 0.005 else 0.0

    # ---- the repeat book ----------------------------------------------------
    repeats = repeat_performance.performance(db, days=days)

    # ---- money -------------------------------------------------------------
    owed_to_us = (
        db.query(func.coalesce(func.sum(Sale.total), 0.0))
        .filter(Sale.status.in_(("pending", "part_paid"))).scalar() or 0.0)
    owed_count = (db.query(func.count(Sale.id))
                  .filter(Sale.status.in_(("pending", "part_paid"))).scalar() or 0)

    # ---- the shelf ----------------------------------------------------------
    short = (
        db.query(func.count(Product.id),
                 func.coalesce(
                     func.sum(Product.cost_price * Product.reorder_quantity), 0.0))
        .filter(Product.active,
                Product.quantity_on_hand <= Product.reorder_level).first())
    expiring = (
        db.query(func.count(StockBatch.id),
                 func.coalesce(func.sum(StockBatch.quantity_remaining
                                        * StockBatch.unit_cost), 0.0))
        .filter(StockBatch.quantity_remaining > 0,
                StockBatch.expiry_date <= today + timedelta(days=90),
                StockBatch.expiry_date >= today).first())

    return {
        "as_at": today,
        "days": days,
        "today": {
            "value": todays[1],
            "sales": todays[0],
            **_trend(todays[1], same_day_before[1]),
            "compared_with": "the same day last week",
        },
        "period": {
            "value": _money(this_half),
            **_trend(this_half, last_half),
            "compared_with": f"the {days} days before",
        },
        "series": series,
        "branches": branches,
        "repeats": {
            "due": repeats["due"],
            "due_value": repeats["due_value"],
            "captured": repeats["captured"],
            "captured_value": repeats["captured_value"],
            "lost": repeats["lost"],
            "lost_value": repeats["lost_value"],
            "value_loss_rate": repeats["value_loss_rate"],
            "on_time": repeats.get("on_time"),
            "on_time_rate": repeats.get("on_time_rate"),
            "due_today": repeats["due_today"],
            "due_today_value": repeats["due_today_value"],
            "split": repeats.get("loss_split", []),
            "average_value": repeats["average_value"],
        },
        "money": {
            "owed_to_us": _money(owed_to_us),
            "owed_to_us_count": int(owed_count),
            "claims_recovered": board.get("claims_recovery"),
        },
        "shelf": {
            "short_lines": int(short[0] or 0),
            "reorder_cost": _money(short[1]),
            "expiring_batches": int(expiring[0] or 0),
            "expiring_value": _money(expiring[1]),
        },
    }


def actions(overview_data: dict) -> list[dict]:
    """What to do about it, worth first.

    A dashboard's job is finished when somebody knows what to do next, so this
    ranks by money rather than by category. Everything here is derived from
    figures already on the page — nothing is computed twice, and nothing
    appears that the reader cannot see the basis for.
    """
    out: list[dict] = []
    r = overview_data["repeats"]
    shelf = overview_data["shelf"]
    money = overview_data["money"]

    # The repeat split names its own fix; carry those through rather than
    # inventing new wording for the same thing.
    for part in r.get("split", []):
        if part["value"] < 0.005 or part["reason"] == "still in hand":
            continue
        out.append({
            "what": f"{part['count']} repeat{'' if part['count'] == 1 else 's'} "
                    f"{part['reason']}",
            "worth": part["value"],
            "do": part["fix"],
            "to": "/repeats?tab=value",
            "tone": "bad" if part["reason"] == "cannot supply" else "warn",
        })

    if money["owed_to_us"] > 0.005:
        out.append({
            "what": f"{money['owed_to_us_count']} sale"
                    f"{'' if money['owed_to_us_count'] == 1 else 's'} dispensed "
                    f"and never settled",
            "worth": money["owed_to_us"],
            "do": "Chase them, or put them on account so they age where "
                  "somebody looks.",
            "to": "/money-owed",
            "tone": "warn",
        })

    if shelf["short_lines"]:
        out.append({
            "what": f"{shelf['short_lines']} line"
                    f"{'' if shelf['short_lines'] == 1 else 's'} at or below "
                    f"reorder level",
            "worth": shelf["reorder_cost"],
            "do": "Raise an order. What is not on the shelf cannot be "
                  "dispensed, and a repeat that cannot be supplied is the one "
                  "loss the pharmacy causes itself.",
            "to": "/orders",
            "tone": "warn",
        })

    if shelf["expiring_batches"]:
        out.append({
            "what": f"{shelf['expiring_batches']} batch"
                    f"{'' if shelf['expiring_batches'] == 1 else 'es'} expiring "
                    f"within 90 days",
            "worth": shelf["expiring_value"],
            "do": "Move it, return it, or write it off — the value falls to "
                  "nothing on a date that is already known.",
            "to": "/stock?tab=batches",
            "tone": "warn",
        })

    # A branch counting badly is money leaving the till, and it is the one item
    # here that is about people rather than about trade.
    for b in overview_data["branches"]:
        if b["variance"] and abs(b["variance"]) > 0.005:
            out.append({
                "what": f"{b['branch']} is out by {abs(b['variance']):,.2f} "
                        f"across its cash-ups",
                "worth": abs(b["variance"]),
                "do": "Read the shifts. A drawer that is never exactly right "
                      "is either a process nobody follows or a person worth "
                      "watching.",
                "to": "/shifts",
                "tone": "bad" if abs(b["variance"]) > 50 else "warn",
            })

    out.sort(key=lambda a: -a["worth"])
    return out
