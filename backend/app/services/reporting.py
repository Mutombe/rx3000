"""Financial reports derived from the ledger, never from the transactions.

The distinction matters more than it sounds. A revenue figure computed by summing
sales and a revenue figure taken from the ledger will agree only while every sale
has posted, and the moment they disagree, the one taken from the ledger is the
one that ties to the trial balance, the VAT return and the accountant's file.
Reporting off the transactions instead produces numbers that look right, reconcile
to nothing, and cannot be defended.

So every figure here comes from journal lines. Where that makes a report show
less than the till did, the answer is to post the missing transactions, which is
what the unposted queues are for — not to compute around the gap.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Account, JournalEntry, JournalLine, TradingPeriod
from . import ledger

# The buckets an accountant expects. 30/60/90 is convention, not arithmetic —
# a debtor is "60 days" when it has been outstanding into a third month.
AGE_BUCKETS = [(0, 30, "current"), (31, 60, "30 days"),
               (61, 90, "60 days"), (91, 120, "90 days")]


@dataclass
class Aged:
    party_type: str
    party_id: int | None
    name: str
    buckets: dict
    total: float


def _party_name(db: Session, party_type: str, party_id: int | None) -> str:
    if not party_id:
        return "(unattributed)"
    from ..models import MedicalAid, Patient, Supplier
    model = {"patient": Patient, "supplier": Supplier, "scheme": MedicalAid}.get(party_type)
    if not model:
        return f"{party_type} #{party_id}"
    row = db.get(model, party_id)
    if not row:
        return f"{party_type} #{party_id}"
    if party_type == "patient":
        return f"{row.first_name} {row.last_name}".strip()
    return row.name


def ageing(db: Session, subledger: str, *, asof: date | None = None) -> dict:
    """How old the money is, by who owes it or is owed.

    A total is nearly useless on its own: a pharmacy with 40,000 outstanding is
    healthy if it is all current and in trouble if half of it is past ninety
    days. The buckets are the report; the total is the footnote.
    """
    asof = asof or date.today()
    controls = db.query(Account).filter(Account.subledger == subledger).all()
    if not controls:
        raise ledger.LedgerError(f"No control account for the '{subledger}' subledger.")
    codes = [a.code for a in controls]
    debit_positive = controls[0].type in ledger.DEBIT_POSITIVE

    rows = (db.query(JournalLine.party_type, JournalLine.party_id,
                     JournalEntry.entry_date, JournalLine.debit, JournalLine.credit)
            .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
            .filter(JournalLine.account_code.in_(codes),
                    JournalEntry.entry_date <= asof)
            .all())

    parties: dict = {}
    for party_type, party_id, entry_date, debit, credit in rows:
        movement = (debit - credit) if debit_positive else (credit - debit)
        age = (asof - entry_date).days
        label = next((name for lo, hi, name in AGE_BUCKETS if lo <= age <= hi), "120+ days")
        key = (party_type or "", party_id)
        entry = parties.setdefault(key, {b[2]: 0.0 for b in AGE_BUCKETS} | {"120+ days": 0.0})
        entry[label] = round(entry[label] + movement, 2)

    aged = []
    for (party_type, party_id), buckets in parties.items():
        total = round(sum(buckets.values()), 2)
        if abs(total) < 0.005:
            continue          # settled in full; not a debtor any more
        aged.append(Aged(party_type=party_type or "(none)", party_id=party_id,
                         name=_party_name(db, party_type, party_id),
                         buckets=buckets, total=total).__dict__)

    aged.sort(key=lambda a: -abs(a["total"]))
    labels = [b[2] for b in AGE_BUCKETS] + ["120+ days"]
    totals = {label: round(sum(a["buckets"][label] for a in aged), 2) for label in labels}
    grand = round(sum(totals.values()), 2)
    overdue = round(sum(v for k, v in totals.items() if k != "current"), 2)
    return {
        "subledger": subledger,
        "as_at": asof,
        "buckets": labels,
        "parties": aged,
        "totals": totals,
        "total": grand,
        "overdue": overdue,
        "overdue_percent": round(100 * overdue / grand, 1) if grand else 0.0,
    }


def vat_return(db: Session, period_code: str) -> dict:
    """The figures a VAT return is filed from, for one trading period.

    Output tax less input tax is what is payable. Both come from the ledger
    rather than from sales and purchases, because a return has to agree with the
    accounts it was filed from — a revenue authority that queries it will be
    shown the trial balance, not a spreadsheet.
    """
    period = db.query(TradingPeriod).filter(TradingPeriod.code == period_code).first()
    if not period:
        raise ledger.LedgerError(f"No trading period {period_code}")

    def net(code: str) -> float:
        return abs(ledger.balance(db, code, period_code=period_code))

    output = net("2100")
    inp = net("1300")
    payable = round(output - inp, 2)

    # Sales excluding VAT, so the return's turnover line ties to the income
    # accounts rather than to the till total.
    revenue = round(sum(ledger.balance(db, a.code, period_code=period_code)
                        for a in db.query(Account).filter(Account.type == "income").all()), 2)

    return {
        "period_code": period.code,
        "period_name": period.name,
        "period_status": period.status,
        "from": period.start_date,
        "to": period.end_date,
        "vat_rate": settings.VAT_RATE,
        "turnover_excluding_vat": revenue,
        "output_tax": round(output, 2),
        "input_tax": round(inp, 2),
        "payable": payable,
        "direction": "payable to the revenue authority" if payable >= 0
                     else "refundable by the revenue authority",
        # A return filed from an open period can change after it is filed, which
        # is the situation nobody wants to be in when asked to explain it.
        "warning": ("" if period.status != "open" else
                    f"{period.name} is still open. A return filed from a period "
                    "that can still receive postings may not match the accounts "
                    "when somebody checks it. Close the period first."),
    }


def income_statement(db: Session, period_code: str = "") -> dict:
    """Profit and loss, straight off the income and expense accounts."""
    rows = []
    income = expense = 0.0
    for account in db.query(Account).filter(Account.type.in_(("income", "expense"))
                                            ).order_by(Account.code).all():
        balance = ledger.balance(db, account.code, period_code=period_code)
        if abs(balance) < 0.005:
            continue
        rows.append({"code": account.code, "name": account.name,
                     "type": account.type, "amount": balance})
        if account.type == "income":
            income += balance
        else:
            expense += balance
    income, expense = round(income, 2), round(expense, 2)
    profit = round(income - expense, 2)
    return {
        "period_code": period_code or "all time",
        "lines": rows,
        "income": income,
        "expenses": expense,
        "profit": profit,
        "margin_percent": round(100 * profit / income, 1) if income else 0.0,
    }


def balance_sheet(db: Session, *, asof: date | None = None) -> dict:
    """Assets, liabilities and equity, and whether they actually balance.

    Retained profit is folded in rather than left out, because assets will not
    equal liabilities plus equity without it and a balance sheet that does not
    balance is not a report, it is a fault.
    """
    asof = asof or date.today()
    sections: dict = {"asset": [], "liability": [], "equity": []}
    totals = {"asset": 0.0, "liability": 0.0, "equity": 0.0}
    for account in db.query(Account).order_by(Account.code).all():
        if account.type not in sections:
            continue
        balance = ledger.balance(db, account.code, upto=asof)
        if abs(balance) < 0.005:
            continue
        sections[account.type].append({"code": account.code, "name": account.name,
                                       "amount": balance})
        totals[account.type] = round(totals[account.type] + balance, 2)

    profit = income_statement(db)["profit"]
    totals["equity"] = round(totals["equity"] + profit, 2)
    sections["equity"].append({"code": "—", "name": "Profit for the period",
                               "amount": profit})

    difference = round(totals["asset"] - (totals["liability"] + totals["equity"]), 2)
    return {
        "as_at": asof,
        "sections": sections,
        "totals": totals,
        "difference": difference,
        "balanced": abs(difference) < 0.005,
        "message": ("" if abs(difference) < 0.005 else
                    f"Assets exceed liabilities and equity by {difference:.2f}. "
                    "Every journal entry balances at posting, so this points at "
                    "something posted to an account with no type, or a chart "
                    "entry with the wrong one."),
    }
