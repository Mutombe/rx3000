"""Cashing up a till.

The incumbent's screen is keyed on **till / run / draw** and reconciles a grid
of *counted* against *system* per tender, with a physical count of the drawer
entered denomination by denomination. That structure is right and is kept.

Three things about it are not, and this is where the work is:

**The count must be blind.** Their screen shows the expected figure next to the
box you type the counted figure into. Nobody sets out to copy it, and almost
everybody eventually does, and a cash-up that always balances is telling you
nothing at all. Here the expected figure does not exist in any response until a
count has been committed, so it cannot be copied even by accident. This costs
nothing to build and is the single largest control improvement available.

**Denominations come from the jurisdiction.** Theirs shows pounds, which is a
locale default nobody ever changed. A Zimbabwean till holds USD and ZWG at the
same time, and a single blended total is useless — you cannot bank it, and you
cannot tell which drawer is short.

**A variance is a record, not a number on a screen.** Over and short are
attributed to the person who counted and kept, so "which till is repeatedly
short on a Friday" becomes answerable. Their system can produce the number and
then forgets it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Sale, SaleTender, Shift

# The tenders a drawer is reconciled across. Cash is the only one physically
# counted; the rest are counted off slips and the terminal's own totals.
TENDERS = [
    ("cash", "Cash"),
    ("card", "Card"),
    ("mobile_money", "Mobile money"),
    ("medical_aid", "Medical aid"),
    ("voucher", "Vouchers"),
    ("cheque", "Cheques"),
    ("direct", "Direct deposit"),
]

# What a note or coin is worth, per currency. Used to turn a denomination count
# into a figure, and to lay the counting screen out in the order a person
# actually works through a drawer: biggest first.
DENOMINATIONS: dict[str, list[float]] = {
    "USD": [100, 50, 20, 10, 5, 2, 1, 0.5, 0.25, 0.10, 0.05, 0.01],
    "ZWG": [200, 100, 50, 20, 10, 5, 2, 1, 0.5, 0.25, 0.10],
}


@dataclass
class Line:
    method: str
    label: str
    counted: float
    system: float

    @property
    def difference(self) -> float:
        return round(self.counted - self.system, 2)


def denominations(currency: str) -> list[float]:
    return DENOMINATIONS.get(currency.upper(), DENOMINATIONS["USD"])


def count_from_coinage(coinage: dict) -> float:
    """Turn `{"100": 3, "20": 5, "0.5": 2}` into a figure.

    The operator counts objects, not money, and asking them to do the
    multiplication is asking for the arithmetic error that the count exists to
    catch.
    """
    total = 0.0
    for face, quantity in (coinage or {}).items():
        try:
            total += float(face) * int(quantity or 0)
        except (TypeError, ValueError):
            # A denomination we do not recognise is skipped rather than
            # aborting the count — but it is not silently treated as zero
            # value either, because it never contributed to the total.
            continue
    return round(total, 2)


def system_totals(db: Session, shift: Shift) -> dict[str, float]:
    """What the system believes passed through this till during the shift.

    Read from tenders where a sale has them, because a split payment is the
    whole reason per-tender reconciliation exists: a sale settled half in cash
    and half on a card is one row on `Sale` and two facts about the drawer.
    Sales with no tender rows fall back to their single payment method.
    """
    start = shift.opened_at
    end = shift.closed_at or datetime.utcnow()

    totals = {method: 0.0 for method, _ in TENDERS}

    tendered = (
        db.query(SaleTender.method, func.sum(SaleTender.amount_in_base))
        .join(Sale, Sale.id == SaleTender.sale_id)
        .filter(Sale.created_at >= start, Sale.created_at <= end)
        .filter(Sale.status != "void")
        # Change given is a negative movement on the drawer, and it is already
        # signed, so it is included rather than filtered out.
        .group_by(SaleTender.method)
        .all()
    )
    seen_sale_ids = {
        row[0] for row in
        db.query(SaleTender.sale_id)
        .join(Sale, Sale.id == SaleTender.sale_id)
        .filter(Sale.created_at >= start, Sale.created_at <= end)
        .distinct()
        .all()
    }
    for method, amount in tendered:
        totals[method] = round(totals.get(method, 0.0) + float(amount or 0), 2)

    # Sales that recorded only a payment method, with no tender breakdown.
    simple = (
        db.query(Sale.payment_method, func.sum(Sale.total))
        .filter(Sale.created_at >= start, Sale.created_at <= end)
        .filter(Sale.status != "void")
        .filter(~Sale.id.in_(seen_sale_ids) if seen_sale_ids else True)
        .group_by(Sale.payment_method)
        .all()
    )
    for method, amount in simple:
        if method == "split":
            # A split with no tender rows cannot be attributed, and guessing
            # would put money in the wrong column. Left out and surfaced.
            totals["_unattributed"] = round(
                totals.get("_unattributed", 0.0) + float(amount or 0), 2)
            continue
        totals[method] = round(totals.get(method, 0.0) + float(amount or 0), 2)

    return totals


def petty_cash_total(db: Session, shift: Shift) -> float:
    """Net petty cash for this shift. Negative means money left the drawer.

    Counted separately from sales because it is not a sale, and included in what
    the drawer should hold because it is real money that moved. Leave it out and
    the till is short at every cash-up by exactly the amount that was paid out,
    and a cashier is asked to explain a variance that is not theirs.
    """
    from ..models import PettyCash

    start = shift.opened_at
    end = shift.closed_at or datetime.utcnow()
    total = (
        db.query(func.coalesce(func.sum(PettyCash.amount), 0.0))
        .filter(PettyCash.created_at >= start, PettyCash.created_at <= end)
        .scalar()
    )
    return round(float(total or 0), 2)


def reconcile(db: Session, shift: Shift, counted: dict[str, float]) -> dict:
    """Compare a committed count to the system, once and for the record."""
    system = system_totals(db, shift)
    lines = [
        Line(method, label, round(float(counted.get(method) or 0), 2),
             round(system.get(method, 0.0), 2))
        for method, label in TENDERS
    ]

    # The float is not takings. It was in the drawer before trading started and
    # will be there after, so it is added to what the drawer should hold but
    # never to what the till sold.
    opening_float = round(shift.opening_float or 0, 2)
    petty = petty_cash_total(db, shift)
    expected_cash = round(system.get("cash", 0.0) + opening_float + petty, 2)
    counted_cash = round(float(counted.get("cash") or 0), 2)

    total_counted = round(sum(l.counted for l in lines), 2)
    total_system = round(sum(l.system for l in lines) + opening_float + petty, 2)

    return {
        "shift_id": shift.id,
        "till_no": getattr(shift, "till_no", None),
        "run_number": getattr(shift, "run_number", None),
        "opening_float": opening_float,
        "petty_cash": petty,
        "lines": [
            {
                "method": l.method, "label": l.label,
                "counted": l.counted,
                # The float belongs to the cash line and nowhere else.
                # The float and any petty cash belong to the cash line and
                # nowhere else.
                "system": round(
                    l.system + (opening_float + petty if l.method == "cash" else 0), 2),
                "difference": round(
                    l.counted - l.system
                    - (opening_float + petty if l.method == "cash" else 0), 2),
            }
            for l in lines
        ],
        "unattributed": round(system.get("_unattributed", 0.0), 2),
        "expected_cash": expected_cash,
        "counted_cash": counted_cash,
        "cash_variance": round(counted_cash - expected_cash, 2),
        "total_counted": total_counted,
        "total_system": total_system,
        "variance": round(total_counted - total_system, 2),
        # What was cancelled during the run. Not part of the reconciliation —
        # a void takes no money — but it is the figure a supervisor reads next
        # to a variance, because voiding a sale after taking the cash produces a
        # drawer that is over by exactly the voided amount.
        **_cancellations(db, shift),
    }


def _cancellations(db: Session, shift: Shift) -> dict:
    """Voids and credits raised during the run, with counts.

    Returned only as part of a reconciliation, which exists only after a count
    has been committed. These are sale totals, and sale totals published before
    the count are the expected figure waiting to be added up.
    """
    start = shift.opened_at
    end = shift.closed_at or datetime.utcnow()
    rows = (
        db.query(Sale.status, func.count(Sale.id), func.coalesce(func.sum(Sale.total), 0.0))
        .filter(Sale.created_at >= start, Sale.created_at <= end)
        .filter(Sale.status.in_(("void", "credited")))
        .group_by(Sale.status)
        .all()
    )
    found = {status: (int(n), round(float(total or 0), 2)) for status, n, total in rows}
    voids, void_total = found.get("void", (0, 0.0))
    credits, credit_total = found.get("credited", (0, 0.0))
    return {
        "void_count": voids, "void_total": void_total,
        "credit_count": credits, "credit_total": credit_total,
    }


def store(shift: Shift, result: dict, coinage: dict | None, notes: str) -> None:
    """Write the count onto the shift, so it survives the screen it was typed on."""
    shift.counted_cash = result["counted_cash"]
    shift.expected_cash = result["expected_cash"]
    shift.variance = result["cash_variance"]
    shift.card_total = next(
        (l["counted"] for l in result["lines"] if l["method"] == "card"), 0.0)
    shift.medical_aid_total = next(
        (l["counted"] for l in result["lines"] if l["method"] == "medical_aid"), 0.0)
    if hasattr(shift, "cashup_json"):
        # The whole reconciliation, including the denomination count, because
        # "the drawer was 12 short" is not a useful record without knowing
        # whether it was one missing twenty and eight extra singles.
        shift.cashup_json = json.dumps({
            "result": result, "coinage": coinage or {}, "notes": notes,
            "counted_at": datetime.utcnow().isoformat(),
        })
    if notes:
        shift.notes = ((shift.notes or "") + "\n" + notes).strip()
