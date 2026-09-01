"""Which lines earn their shelf space, and which are quietly eating the float.

A pharmacy's money is on its shelves. Four thousand lines, and the difference
between a good year and a bad one is almost entirely which of them the buyer
puts money into, yet the only numbers most systems produce are "units sold"
and "what is in stock", neither of which answers a buying question.

The questions a buyer actually has, and the number that answers each:

    what moves            units sold, and how often it goes out
    how fast              monthly average usage — the reorder driver
    how long will it last days of cover: what is on hand, divided by a day's
                          usage. The one figure that says *when*
    what does it earn     gross profit at the cost frozen on the sale, not at
                          today's cost price
    is it worth the space GMROI — gross profit per dollar of stock held. The
                          single best retail figure, and the one that exposes a
                          line with a beautiful margin that sells twice a year
    where                 all of it per branch, because a line that flies in
                          one shop is dead in another and a group average
                          hides both

WHY THE COST COMES FROM THE SALE

`SaleItem.unit_cost` is frozen at the moment of sale. Computing last quarter's
margin from this quarter's cost price gives an answer that is confidently wrong
in a market where a wholesaler reprices monthly, and wrong in the flattering
direction while prices are rising, which is the worst way to be wrong about
whether a line makes money.

WHAT "DEAD" MEANS, AND WHY IT IS SAID CAREFULLY

A line with no sales in the period and stock on the shelf is capital the
pharmacy has already spent and cannot get back by waiting. But a slow line is
not automatically a bad one: a pharmacy stocks some things because a patient
needs them, not because they turn. So this reports the money and lets somebody
who knows the shop decide. It does not recommend delisting.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Branch, Dispensing, Prescription, PrescriptionItem,
                      Product, Sale, SaleItem, StockCategory)

#: Days in a month, for turning a period into a monthly rate.
MONTH = 30.44

#: How the movement classes are cut, in times out per month.
#: Deliberately by OCCASIONS rather than units: one bottle of a thousand
#: tablets is a big number and one event, and a line's speed is how often
#: somebody wants it.
FAST = 8.0      # roughly twice a week or better
STEADY = 2.0    # a couple of times a month
SLOW = 0.34     # about four times a year


def _class(per_month: float, on_hand: int) -> str:
    if per_month >= FAST:
        return "fast"
    if per_month >= STEADY:
        return "steady"
    if per_month >= SLOW:
        return "slow"
    if on_hand > 0:
        # Nothing moving and money on the shelf. The only class that is a
        # finding rather than a description.
        return "dead"
    return "none"


def analyse(db: Session, *, days: int = 90, branch_id: int | None = None,
            limit: int = 200, category_id: int | None = None) -> dict:
    """Every line that moved, with what it earned and how fast it turns."""
    end = datetime.utcnow()
    start = end - timedelta(days=max(1, days))
    months = max(days / MONTH, 0.1)

    # ---- what sold, at the cost frozen on the sale ------------------------
    sold = (
        db.query(SaleItem.product_id,
                 func.sum(SaleItem.quantity),
                 func.sum(SaleItem.line_total),
                 func.sum(SaleItem.unit_cost * SaleItem.quantity),
                 func.count(SaleItem.id))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.created_at >= start, Sale.created_at <= end,
                Sale.status.in_(("paid", "part_paid"))))
    if branch_id:
        sold = sold.filter(Sale.branch_id == branch_id)
    sold = sold.group_by(SaleItem.product_id).all()

    # ---- and what was dispensed, which never reaches a sale on a scheme ---
    dispensed = (
        db.query(PrescriptionItem.product_id,
                 func.sum(Dispensing.quantity),
                 func.count(Dispensing.id))
        .join(PrescriptionItem,
              PrescriptionItem.id == Dispensing.prescription_item_id)
        .filter(Dispensing.dispensed_at >= start,
                Dispensing.dispensed_at <= end))
    # A dispensing belongs to a branch through its SALE, not through its
    # script.
    #
    # This filtered on `Prescription.branch_id`, which does not exist — a
    # prescription is written by a doctor and captured by a pharmacy; it is not
    # held at a shop. The attribute error raised a 500, and an unhandled 500
    # carries no CORS headers, so the browser reported the whole thing as a
    # cross-origin failure. Every per-branch call to this service had been
    # dead since it was written, and the error named the wrong cause.
    #
    # Dispensings with no sale behind them cannot be attributed to a branch at
    # all. They are excluded here and COUNTED below, because silently dropping
    # them would understate every branch's units by however many scheme scripts
    # never reached a till, and a figure quietly missing a slice is worse than
    # one that says what it is missing.
    #
    # Counted whether or not a branch was asked for, because the number means
    # something either way and it is not the same thing:
    #
    #   in a GROUP view these dispensings are included — they moved, and the
    #     group is every shop, so nothing is lost;
    #   in a BRANCH view they are excluded, because no branch can claim them.
    #
    # Which is why branch figures need not sum to the group figure, and why
    # that has to be stated rather than left for somebody to notice.
    unattributed = (
        db.query(func.count(Dispensing.id))
        .filter(Dispensing.dispensed_at >= start,
                Dispensing.dispensed_at <= end,
                Dispensing.sale_id.is_(None))
        .scalar() or 0)
    if branch_id:
        dispensed = (dispensed
                     .join(Sale, Sale.id == Dispensing.sale_id)
                     .filter(Sale.branch_id == branch_id))
    dispensed = dispensed.group_by(PrescriptionItem.product_id).all()

    # Sold and dispensed are counted apart, and the money only ever comes from
    # the sold half.
    #
    # A dispensing that never reached a sale — a scheme script settled by the
    # funder, or an import that never linked the two — has a known quantity and
    # an UNKNOWN price. The first version costed those units at the product's
    # average cost and left revenue at nothing, which produced a gross profit
    # of minus the cost: this pharmacy's 180 days read as a 1.9 million loss.
    #
    # That is arithmetic performed correctly on numbers that do not belong
    # together, and it is the second time this exact shape has appeared. Money
    # questions are answered from lines that carry money. Units that moved
    # without one are counted as units, said as units, and never priced.
    stats: dict[int, dict] = defaultdict(
        lambda: {"sold_units": 0.0, "revenue": 0.0, "cost": 0.0,
                 "out_units": 0.0, "occasions": 0, "unpriced": 0.0})
    for product_id, units, revenue, cost, lines in sold:
        s = stats[product_id]
        s["sold_units"] += float(units or 0)
        s["revenue"] += float(revenue or 0)
        s["cost"] += float(cost or 0)
        s["occasions"] += int(lines or 0)
    for product_id, units, events in dispensed:
        s = stats[product_id]
        s["unpriced"] += float(units or 0)
        s["occasions"] += int(events or 0)
    for s in stats.values():
        # Everything that left the shelf, whatever paid for it. This is the
        # right basis for usage, cover and reordering — a scheme script empties
        # a shelf exactly as a cash sale does.
        s["out_units"] = s["sold_units"] + s["unpriced"]

    products = (db.query(Product).filter(Product.active))
    if category_id:
        products = products.filter(Product.category_id == category_id)
    products = products.all()
    departments = {c.id: c.name for c in db.query(StockCategory).all()}

    rows = []
    for product in products:
        s = stats.get(product.id)
        units = s["out_units"] if s else 0.0
        sold_units = s["sold_units"] if s else 0.0
        unpriced = s["unpriced"] if s else 0.0
        occasions = s["occasions"] if s else 0
        revenue = round(s["revenue"], 2) if s else 0.0
        cost = round(s["cost"], 2) if s else 0.0

        on_hand = product.quantity_on_hand or 0
        held_at_cost = round(on_hand * float(product.average_cost
                                             or product.cost_price or 0), 2)

        # Profit only from the half that carries money. A line that moved 300
        # units on scheme scripts and sold none over the counter has a real
        # usage figure and no margin figure, and saying so is the honest
        # answer — not a margin of minus everything.
        profit = round(revenue - cost, 2) if revenue else 0.0
        per_month = round(occasions / months, 2)
        units_month = round(units / months, 2)
        cover = (round(on_hand / (units / max(days, 1)), 1)
                 if units > 0 else None)

        rows.append({
            "product_id": product.id,
            "product": f"{product.name} {product.strength or ''}".strip(),
            "department": departments.get(product.category_id, ""),
            "schedule": product.schedule or 0,
            "units": round(units, 1),
            "sold_units": round(sold_units, 1),
            # Units that left the shelf with no sale line behind them. Reported
            # rather than priced, because their price is not known.
            "unpriced_units": round(unpriced, 1),
            "occasions": occasions,
            "revenue": revenue,
            "cost": cost,
            "profit": profit,
            "margin": (round(100.0 * profit / revenue, 1) if revenue else None),
            # The reorder driver. Stated per month because that is the unit a
            # buyer orders in.
            "monthly_usage": units_month,
            "times_out_a_month": per_month,
            "on_hand": on_hand,
            "held_at_cost": held_at_cost,
            # When it runs out, at the rate it has actually been leaving.
            "days_cover": cover,
            # Gross profit per dollar of stock held. The figure that exposes a
            # line with a lovely margin that sells twice a year.
            "gmroi": (round(profit / held_at_cost, 2)
                      if held_at_cost > 0 and profit > 0 else None),
            # Whether the money on this row can be believed at all.
            "priced": revenue > 0,
            "movement": _class(per_month, on_hand),
        })

    moved = [r for r in rows if r["units"] > 0]
    moved.sort(key=lambda r: (-r["profit"], -r["units"]))

    # ---- the Pareto, which is the buying conversation --------------------
    #
    # Built from priced lines alone. A contribution ranking that includes rows
    # earning a known nothing puts them at the top of the list of what makes
    # the money, which is how "1,026 of 1,029 lines make 80% of the profit"
    # came out of the first version — a sentence that is arithmetically true
    # and says nothing.
    priced = [r for r in moved if r["priced"]]
    total_profit = round(sum(r["profit"] for r in priced), 2)
    running = 0.0
    for rank, row in enumerate(priced, start=1):
        running += row["profit"]
        row["rank"] = rank
        row["share_of_profit"] = (round(100.0 * running / total_profit, 1)
                                  if total_profit else None)
        # A, B and C on contribution, not on units: the lines to protect are
        # the ones the profit comes from.
        row["abc"] = ("A" if (row["share_of_profit"] or 0) <= 80
                      else "B" if (row["share_of_profit"] or 0) <= 95 else "C")

    dead = [r for r in rows if r["movement"] == "dead"]
    dead.sort(key=lambda r: -r["held_at_cost"])

    return {
        "days": days, "branch_id": branch_id,
        "products": moved[:limit],
        "dead": dead[:limit],
        # Dispensings in this window that no branch can claim, because nothing
        # ties them to a till. Reported rather than swallowed: it is the size of
        # the gap between "what this branch moved" and "what moved".
        "unattributed_dispensings": unattributed,
        **_summary(rows, moved, priced, dead, total_profit, days),
    }


def _summary(rows, moved, priced, dead, total_profit, days) -> dict:
    revenue = round(sum(r["revenue"] for r in priced), 2)
    unpriced_lines = len(moved) - len(priced)
    held = round(sum(r["held_at_cost"] for r in rows), 2)
    dead_money = round(sum(r["held_at_cost"] for r in dead), 2)
    classes: dict[str, int] = defaultdict(int)
    for r in rows:
        classes[r["movement"]] += 1

    # How many lines make 80% of the profit. The one number a buyer should be
    # told before any other.
    a_lines = sum(1 for r in priced if r.get("abc") == "A")
    return {
        "lines_stocked": len(rows),
        "lines_moved": len(moved),
        "revenue": revenue,
        "profit": total_profit,
        "margin": (round(100.0 * total_profit / revenue, 1) if revenue else None),
        "held_at_cost": held,
        "dead_money": dead_money,
        "classes": dict(classes),
        "a_lines": a_lines,
        "gmroi": (round(total_profit / held, 2) if held else None),
        "lines_priced": len(priced),
        "lines_unpriced": unpriced_lines,
        # Said out loud rather than left for somebody to infer from a small
        # revenue figure. A shop whose dispensings never reached a sale cannot
        # be told anything about margin, and pretending otherwise is worse than
        # saying so.
        "unpriced_note": (
            f"{unpriced_lines:,} line(s) moved with no sale behind them — a "
            f"scheme script settled by the funder, or stock that left before "
            f"the till saw it. Their usage is counted; their margin is not "
            f"known and is not guessed at."
            if unpriced_lines else ""),
        "headline": (
            f"{a_lines} of {len(priced):,} priced lines make 80% of the "
            f"profit. {dead_money:,.2f} sits in {len(dead):,} line(s) that "
            f"have not moved in {days} days."
            if priced else
            f"{len(moved):,} line(s) moved in {days} days and none carried a "
            f"sale, so nothing can be said about what they earn — only about "
            f"how fast they go."
            if moved else
            f"Nothing moved in the last {days} days."),
    }


def by_branch(db: Session, *, days: int = 90, limit: int = 12) -> dict:
    """The same question per shop, because a group average hides both answers.

    A line that flies in one branch and is dead in another averages to
    "steady", which is a description of nothing and a buying decision that is
    wrong in both shops.
    """
    branches = (db.query(Branch).filter(Branch.active.is_(True))
                .order_by(Branch.name).limit(limit).all())
    rows = []
    for branch in branches:
        result = analyse(db, days=days, branch_id=branch.id, limit=5)
        rows.append({
            "branch_id": branch.id, "branch": branch.name,
            "revenue": result["revenue"], "profit": result["profit"],
            "margin": result["margin"], "gmroi": result["gmroi"],
            "held_at_cost": result["held_at_cost"],
            "dead_money": result["dead_money"],
            "lines_moved": result["lines_moved"],
            "top": [{"product": p["product"], "profit": p["profit"],
                     "units": p["units"]} for p in result["products"][:5]],
        })
    rows.sort(key=lambda r: -(r["profit"] or 0))

    group = analyse(db, days=days, limit=0)
    best = rows[0] if rows else None
    worst = min(rows, key=lambda r: r["gmroi"] if r["gmroi"] is not None else 1e9,
                default=None) if rows else None
    # How much of the estate's movement no branch can claim. Said once, at the
    # top, because it governs how the whole table should be read.
    unattributed = group.get("unattributed_dispensings", 0)
    total_dispensings = (
        db.query(func.count(Dispensing.id))
        .filter(Dispensing.dispensed_at >= datetime.utcnow() - timedelta(days=days))
        .scalar() or 0)
    share = round(unattributed * 100.0 / total_dispensings, 1) if total_dispensings else 0.0

    return {
        "days": days,
        "branches": rows,
        "unattributed_dispensings": unattributed,
        "unattributed_share": share,
        # Stated as a sentence rather than left as two numbers, because the
        # reader's question is "can I trust this table", not "what is 2510".
        "caveat": (
            f"{unattributed:,} of {total_dispensings:,} dispensings "
            f"({share:.0f}%) in this window have no sale behind them, so no "
            f"branch can claim them. They are in the group figures and in "
            f"none of the branch figures, which is why the branches do not sum "
            f"to the group."
            if share >= 5 else ""),
        "group": {k: group[k] for k in
                  ("revenue", "profit", "margin", "gmroi", "held_at_cost",
                   "dead_money", "lines_moved", "lines_stocked", "a_lines")},
        "headline": (
            f"{best['branch']} makes the most profit; "
            f"{worst['branch']} earns least per dollar on its shelves"
            + (f" ({worst['gmroi']} against {best['gmroi']})."
               if worst and worst["gmroi"] is not None
               and best and best["gmroi"] is not None else ".")
            if best and worst and best is not worst else
            "Not enough branch trade to compare."),
    }
