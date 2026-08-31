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

**The register and the cash-up have to be the same list.** They were not. The
till knew the customer paid on EcoCash and wrote the wallet into the front of a
free-text reference; the takings screen read it back out by splitting on a
space; this file did not read it at all and reconciled seven hard-coded
families instead. Two screens, one shift, different shapes — and money taken on
any method outside the seven was counted into the totals and then never
printed, because the lines were built from the constant rather than from what
actually moved. A till taking 30 on EcoCash, 20 on InnBucks and 45 cash on
delivery reconciled to 50 and said nothing at all about the other 45. Both
screens now read `services.instruments`, so they cannot disagree about what the
columns are.

**A variance is a record, not a number on a screen.** Over and short are
attributed to the person who counted and kept, so "which till is repeatedly
short on a Friday" becomes answerable. Their system can produce the number and
then forgets it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..models import PaymentInstrument, Sale, SaleTender, Shift
from . import instruments

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


def instrument_totals(db: Session, shift: Shift) -> list[dict]:
    """What passed through this till, split the way the bank statements are.

    One row per (instrument, currency), because that is the unit somebody ticks
    off against a statement: EcoCash USD settles separately from EcoCash ZiG,
    and both settle separately from a Stanbic swipe.

    Rows are built from **what actually moved**, then the pharmacy's standard
    instruments are added at zero. Building them from the list alone is how
    money goes missing; building them from movement alone is how a column
    nobody used that day quietly disappears from the sheet, which is its own
    kind of lie when the sheet is a control document.
    """
    start = shift.opened_at
    end = shift.closed_at or datetime.utcnow()
    known = {i.code: i for i in db.query(PaymentInstrument).all()}

    rows: dict[tuple, dict] = {}

    def row(code: str, method: str, currency: str) -> dict:
        inst = known.get(code)
        key = (code or f"~{method}", currency)
        return rows.setdefault(key, {
            "instrument": code,
            "label": (inst.name if inst else
                      instruments.METHOD_LABELS.get(method, method.title())),
            "method": method,
            "currency": currency,
            "counted_in_drawer": bool(inst.is_cash_drawer) if inst else method == "cash",
            "is_delivery": bool(inst.is_delivery) if inst else False,
            "amount": 0.0, "in_base": 0.0, "count": 0,
            # An instrument the till could not name. Shown as its family so the
            # money is visible and reconcilable, and flagged so somebody can
            # fix the till rather than quietly living with an "Other" column.
            "unnamed": not code,
        })

    tenders = (
        db.query(SaleTender)
        .join(Sale, Sale.id == SaleTender.sale_id)
        .filter(Sale.created_at >= start, Sale.created_at <= end)
        .filter(Sale.status != "void")
        .all()
    )
    for tender in tenders:
        code = tender.instrument or ""
        if code and code not in known:
            code = ""
        r = row(code, tender.method or "cash", (tender.currency_code or "").upper())
        r["amount"] = round(r["amount"] + float(tender.amount or 0), 2)
        r["in_base"] = round(r["in_base"] + float(tender.amount_in_base or 0), 2)
        if not tender.is_change:
            r["count"] += 1

    # Sales settled without a tender breakdown — an older till, or an import.
    seen = {t.sale_id for t in tenders}
    base = _base_code()
    simple = (
        db.query(Sale.payment_method,
                 func.sum(case((Sale.status == "part_paid",
                                func.coalesce(Sale.amount_tendered, 0.0)),
                               else_=Sale.total)))
        .filter(Sale.created_at >= start, Sale.created_at <= end)
        .filter(Sale.status.in_(("paid", "part_paid")))
        .filter(~Sale.id.in_(seen) if seen else True)
        .group_by(Sale.payment_method).all()
    )
    for method, amount in simple:
        method = method or "cash"
        code = "" if method == "split" else instruments.resolve(
            db, method=method, currency_code=base)
        r = row(code, method, base)
        r["amount"] = round(r["amount"] + float(amount or 0), 2)
        r["in_base"] = round(r["in_base"] + float(amount or 0), 2)

    # Every standard instrument, so a column that took nothing today is still
    # on the sheet with a zero against it rather than absent.
    for inst in db.query(PaymentInstrument).filter(
            PaymentInstrument.active.is_(True)).all():
        for code in (inst.currency_list or [base]):
            row(inst.code, inst.method, code)

    return sorted(rows.values(),
                  key=lambda r: (not r["counted_in_drawer"], -r["in_base"],
                                 r["label"], r["currency"]))


def _base_code() -> str:
    from . import currency as _currency
    return _currency.base_code()


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
    #
    # What was TAKEN, not what was owed. This summed `Sale.total` for anything
    # not void, which counts money that never reached the drawer:
    #
    #   a `pending` sale is a dispensing waiting to be paid for at the till —
    #   nothing was taken, and on a busy morning there are dozens of them;
    #
    #   a `part_paid` sale took what the patient could find and left the rest
    #   owing, so its total is the wrong figure by exactly the balance.
    #
    # A shift with one pending sale of 80 and one part payment of 20 against 60
    # expected 190 in a drawer holding 70, and told the cashier they were 120
    # short. A cash-up that accuses people of what the software got wrong is
    # worse than no cash-up: the real shortfalls get lost in the noise, and
    # staff learn to sign off a variance without reading it.
    simple = (
        db.query(
            Sale.payment_method,
            func.sum(case((Sale.status == "part_paid",
                           func.coalesce(Sale.amount_tendered, 0.0)),
                          else_=Sale.total)))
        .filter(Sale.created_at >= start, Sale.created_at <= end)
        # Settled or part settled. A pending sale has taken nothing yet, and a
        # credit note is money going the other way against a different shift.
        .filter(Sale.status.in_(("paid", "part_paid")))
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
    """Compare a committed count to the system, once and for the record.

    Lines come from `instrument_totals` — from what actually moved through the
    till, plus every standard instrument at zero. They used to come from the
    `TENDERS` constant, which meant money taken on anything not in that list
    was added to the totals and then never printed. A till that took 30 on
    EcoCash, 20 on InnBucks and 45 cash on delivery reconciled to 50 and never
    mentioned the missing 45. Nothing can go missing from a list built from the
    movements themselves.

    `counted` may be keyed by instrument code or by method. The screen sends
    instruments; older clients and the QA harness send methods, and a cash-up
    that rejects a count because of a key name is a cash-up nobody completes.
    """
    rows = instrument_totals(db, shift)
    system = system_totals(db, shift)

    # A method-level count is spread over that method's instruments in
    # proportion to what the system saw. Splitting it evenly, or putting it all
    # on the first, would manufacture a variance on both.
    by_method: dict[str, float] = {}
    for row in rows:
        by_method[row["method"]] = round(
            by_method.get(row["method"], 0.0) + row["in_base"], 2)

    def counted_for(row: dict) -> float:
        code = row["instrument"]
        if code and code in counted:
            return round(float(counted.get(code) or 0), 2)
        if code and f"{code}:{row['currency']}" in counted:
            return round(float(counted.get(f"{code}:{row['currency']}") or 0), 2)
        # Fall back to the method, apportioned.
        whole = counted.get(row["method"])
        if whole is None:
            return 0.0
        total = by_method.get(row["method"], 0.0)
        if not total:
            # Nothing was seen on this method, so there is nothing to apportion
            # against. The whole count lands on the first row for the method,
            # where it shows as an over rather than dissolving.
            first = next((r for r in rows if r["method"] == row["method"]), None)
            return round(float(whole or 0), 2) if first is row else 0.0
        return round(float(whole or 0) * row["in_base"] / total, 2)

    lines = [
        Line(row["instrument"] or row["method"], row["label"],
             counted_for(row), round(row["in_base"], 2))
        for row in rows
    ]
    instrument_rows = [
        {**row, "counted": counted_for(row),
         "difference": round(counted_for(row) - row["in_base"], 2)}
        for row in rows
    ]

    # The float is not takings. It was in the drawer before trading started and
    # will be there after, so it is added to what the drawer should hold but
    # never to what the till sold.
    opening_float = round(shift.opening_float or 0, 2)
    petty = petty_cash_total(db, shift)

    # What is physically in the drawer, which is not the same as everything
    # with `method == "cash"`. Cash on delivery is cash, and it is in a
    # driver's pocket somewhere on Samora Machel Avenue — counting it against
    # this drawer tells a cashier they are short by the size of the round.
    drawer = [r for r in instrument_rows if r["counted_in_drawer"]]
    on_the_road = [r for r in instrument_rows
                   if r["is_delivery"] and round(r["in_base"], 2)]
    system_cash = round(sum(r["in_base"] for r in drawer), 2) if drawer         else round(system.get("cash", 0.0), 2)
    expected_cash = round(system_cash + opening_float + petty, 2)
    counted_cash = round(
        float(counted.get("cash") or 0) if "cash" in counted
        else sum(r["counted"] for r in drawer), 2)

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
                "method": row["method"], "instrument": row["instrument"],
                "label": row["label"], "currency": row["currency"],
                "counted": row["counted"],
                "counted_in_drawer": row["counted_in_drawer"],
                "is_delivery": row["is_delivery"], "unnamed": row["unnamed"],
                # The float and any petty cash sit in the drawer, so they
                # belong to the drawer instruments and nowhere else. On the
                # first of them, once, or two cash columns each claim the float
                # and the till reads as over by twice the opening balance.
                "system": round(row["in_base"] + (
                    opening_float + petty
                    if drawer and row is drawer[0] else 0), 2),
                "difference": round(
                    row["counted"] - row["in_base"] - (
                        opening_float + petty
                        if drawer and row is drawer[0] else 0), 2),
            }
            for row in instrument_rows
        ],
        # Money the shop has taken that is not in this drawer and should not be
        # counted against it. Shown beside the variance because a supervisor
        # reading "short by 140" needs to know a driver is out with 140.
        "on_the_road": [
            {"label": r["label"], "currency": r["currency"],
             "amount": round(r["in_base"], 2), "count": r["count"]}
            for r in on_the_road
        ],
        "on_the_road_total": round(sum(r["in_base"] for r in on_the_road), 2),
        # Payments the till could not name an instrument for. Not an error and
        # not hidden: the money is in the totals, it just cannot be ticked off
        # against a statement until somebody fixes what sent it.
        "unnamed_total": round(
            sum(r["in_base"] for r in instrument_rows if r["unnamed"]), 2),
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
