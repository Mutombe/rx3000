"""Everything that has two records of one fact, and whether they agree.

A pharmacy reconciles five different things and had five different places to do
it. Card settlement was its own page. Bank statement was a tab inside the
ledger. Claims were reconciled from the remittances screen. Cash was in the
cash office. Stock drift was a tab inside the catalogue. Nothing anywhere
answered the question a manager actually has on a Monday morning, which is not
"how do I reconcile cards" but **"what does not tie up".**

That question has a shape. Every reconciliation in a pharmacy is the same
exercise: two independent records of one movement of value, and a difference
that is either explained or is money nobody can account for. So they are worth
one screen with one summary, even though the underlying work is different in
each case.

WHAT THIS DOES AND DOES NOT CLAIM

It reports differences. It does not correct them, and it does not decide which
of the two records is right — that is the entire skill of reconciling and the
software's opinion is worth nothing next to a person with the statement in
front of them.

Where a reconciliation cannot be summarised without work the user has not asked
for — card settlement needs an acquirer file that only exists once somebody
uploads it — it says so, rather than reporting nought differences and implying
everything agrees. **A reconciliation nobody has run is not a reconciliation
that passed**, and that distinction is the one this file exists to preserve.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Product, Shift, StockBatch

#: A till variance smaller than this is counting noise on a busy day, not a
#: control failure. Above it, somebody should have been asked at the time.
MATERIAL_VARIANCE = 5.0

#: How far back the summary looks. A month is the period a pharmacy actually
#: closes on, and a difference older than that is a write-off decision rather
#: than a reconciliation.
WINDOW_DAYS = 30


def _cash(db: Session, since: datetime) -> dict:
    """Till cash-ups: how many were counted, and how far out they were.

    Counted, not merely closed. A shift that was closed without a count has no
    variance, and reporting that as "no difference" would be the exact lie
    this file is meant to avoid.
    """
    shifts = (db.query(Shift)
              .filter(Shift.opened_at >= since)
              .filter(Shift.status == "closed").all())
    counted = [s for s in shifts if getattr(s, "counted_at", None)]
    uncounted = len(shifts) - len(counted)
    over = [s for s in counted if (s.variance or 0) > MATERIAL_VARIANCE]
    short = [s for s in counted if (s.variance or 0) < -MATERIAL_VARIANCE]
    worst = max(counted, key=lambda s: abs(s.variance or 0), default=None)

    return {
        "key": "cash",
        "label": "Cash — tills",
        "runs": len(shifts),
        "reconciled": len(counted),
        # Closed without anybody counting the drawer. Not a clean till; an
        # unchecked one, and the difference between those is the whole point.
        "not_reconciled": uncounted,
        "differences": len(over) + len(short),
        "value": round(sum(abs(s.variance or 0) for s in over + short), 2),
        "net": round(sum((s.variance or 0) for s in counted), 2),
        "worst": (round(worst.variance or 0, 2) if worst else 0.0),
        "worst_where": (f"till {worst.till_no or worst.id}"
                        if worst and (worst.variance or 0) else ""),
        "href": "/shifts",
        "says": (
            f"{uncounted} run(s) closed without the drawer being counted"
            if uncounted else
            f"{len(over) + len(short)} run(s) out by more than "
            f"{MATERIAL_VARIANCE:.0f}"
            if over or short else
            "every run counted and within tolerance"
            if counted else "no runs closed in this period"),
    }


def _stock(db: Session) -> dict:
    """A product's own count against the batches behind it.

    Dispensing draws against batches; almost every screen shows the product's
    own figure. Where they differ, the two describe the same shelf differently,
    and a dispenser is being shown one of them.
    """
    from . import stock_reconcile

    report = stock_reconcile.reconcile(db, limit=1)
    disagreeing = int(report.get("disagreeing", 0) or 0)
    products = int(report.get("products", 0) or 0)
    return {
        "key": "stock",
        "label": "Stock — count against batches",
        "runs": products,
        "reconciled": products - disagreeing,
        "not_reconciled": 0,
        "differences": disagreeing,
        "value": round(float(report.get("value_at_risk", 0.0) or 0.0), 2),
        "net": 0.0,
        "worst": 0.0, "worst_where": "",
        "href": "/stock?tab=reconcile",
        "says": report.get("message", ""),
    }


def _claims(db: Session) -> dict:
    """What was claimed against what a funder actually paid.

    The shortfall on a remittance is money the pharmacy has dispensed and not
    been paid for. Left unreconciled it is simply lost, which is why it is the
    one on this list most worth doing.
    """
    from . import era

    try:
        count, total = era.outstanding_totals(db, "")
    except Exception:  # noqa: BLE001 — an empty or partial claims set
        count, total = 0, 0.0
    return {
        "key": "claims",
        "label": "Claims — remittances",
        "runs": count, "reconciled": 0, "not_reconciled": 0,
        "differences": int(count or 0),
        "value": round(float(total or 0), 2),
        "net": -round(float(total or 0), 2),
        "worst": 0.0, "worst_where": "",
        "href": "/remittances",
        "says": (f"{count:,} line(s) short-paid and neither billed nor written "
                 f"off — dispensed and not paid for"
                 if count else "every remittance line accounted for"),
    }


def _card(db: Session) -> dict:
    """Card settlement, which cannot be summarised without the acquirer's file.

    Reported as not run rather than as nought differences. A reconciliation
    nobody has performed is not one that passed, and a dashboard that shows a
    green tick for an exercise nobody did is worse than one that shows nothing.
    """
    return {
        "key": "card",
        "label": "Card — acquirer settlement",
        "runs": 0, "reconciled": 0, "not_reconciled": 0,
        "differences": None,
        "value": 0.0, "net": 0.0, "worst": 0.0, "worst_where": "",
        "href": "/reconciliation/card",
        "says": "needs the acquirer's settlement file — nothing to compare "
                "against until one is loaded",
    }


def _bank(db: Session) -> dict:
    """The bank statement against the ledger. Same reason as card."""
    return {
        "key": "bank",
        "label": "Bank — statement against ledger",
        "runs": 0, "reconciled": 0, "not_reconciled": 0,
        "differences": None,
        "value": 0.0, "net": 0.0, "worst": 0.0, "worst_where": "",
        "href": "/reconciliation/bank",
        "says": "needs a bank statement — nothing to compare against until "
                "one is loaded",
    }


def _drivers(db: Session) -> dict:
    """Money collected at the door and not yet handed in.

    A driver holding the shop's cash is a reconciliation like any other: the
    waybills say what was collected, and the till says what arrived. Nothing
    tracked it at all before deliveries grew a money side.
    """
    from ..models import Waybill

    rows = (db.query(func.count(Waybill.id),
                     func.coalesce(func.sum(Waybill.cod_collected), 0.0))
            .filter(Waybill.cod_settled_at.is_(None),
                    Waybill.cod_collected > 0).first())
    count, total = (rows or (0, 0.0))
    return {
        "key": "drivers",
        "label": "Deliveries — cash with drivers",
        "runs": int(count or 0), "reconciled": 0, "not_reconciled": int(count or 0),
        "differences": int(count or 0),
        "value": round(float(total or 0), 2),
        "net": 0.0, "worst": 0.0, "worst_where": "",
        "href": "/drivers",
        "says": (f"{count} delivery(ies) collected for and not handed into a "
                 f"till" if count else "every round handed in"),
    }


def overview(db: Session, days: int = WINDOW_DAYS) -> dict:
    """One answer to 'what does not tie up'."""
    since = datetime.utcnow() - timedelta(days=max(1, days))

    areas = []
    for build in (_cash, ):
        areas.append(build(db, since))
    for build in (_claims, _drivers, _stock, _card, _bank):
        areas.append(build(db))

    # Money that two records of the same thing disagree about. Card and bank
    # contribute nothing because nobody has run them, and that is said out
    # loud rather than counted as zero.
    at_stake = round(sum(a["value"] for a in areas
                         if a["differences"] is not None), 2)
    not_run = [a["label"] for a in areas if a["differences"] is None]
    unchecked = sum(a["not_reconciled"] for a in areas)

    return {
        "days": days,
        "areas": areas,
        "at_stake": at_stake,
        "not_run": not_run,
        "unchecked": unchecked,
        "headline": _headline(at_stake, not_run, unchecked),
    }


def _headline(at_stake: float, not_run: list[str], unchecked: int) -> str:
    """What to say at the top, in the order somebody should act on it."""
    parts = []
    if at_stake:
        parts.append(f"{at_stake:,.2f} is in dispute between two records")
    if unchecked:
        parts.append(f"{unchecked} thing(s) closed without being checked")
    if not_run:
        parts.append(f"{len(not_run)} reconciliation(s) have not been run at "
                     f"all this period")
    if not parts:
        return "Everything with two records of it agrees."
    return "; ".join(parts) + "."
