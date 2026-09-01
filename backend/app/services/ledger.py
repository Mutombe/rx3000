"""Double-entry bookkeeping.

Double entry is not tradition. It is the only bookkeeping that can tell you it
is wrong: a list of transactions always adds up to whatever it adds up to, but a
journal with an unbalanced entry is detectably broken. Every rule below exists
to keep that property, because the moment one unbalanced entry is allowed
through, the ledger stops being evidence of anything.

Three rules are enforced rather than encouraged:

* **An entry must balance to the cent, or it does not post.** Not "is flagged" —
  does not post. A ledger that accepts a broken entry and warns about it will
  accumulate broken entries, because warnings are read once and then not.

* **Nothing posts into a closed period.** The period module owns that rule; this
  module asks it. A backdated journal is exactly how a signed-off figure changes
  underneath the person who signed it.

* **A posted entry is never edited or deleted — it is reversed.** The reversal is
  its own entry with its own date, so the correction is visible as a correction.
  Editing history is how a ledger becomes something nobody can rely on.

The subledger design is worth explaining. A control account in the general
ledger is a summary of a subledger — debtors, creditors, stock, VAT. They are
kept separately *so that they can disagree*: if the debtors control account and
the sum of what patients owe drift apart, something was posted around the
subledger rather than through it, and `reconcile_control()` finds it. A system
that computed the control from the subledger could never detect that, which is
the entire point of having both.
"""
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Account, JournalEntry, JournalLine
from . import periods

# Debits increase these; credits increase the rest.
DEBIT_POSITIVE = ("asset", "expense")

#: The chart a pharmacy starts with.
#:
#: Six columns rather than four. `section` and `is_cash` have been on the model
#: from the beginning and were seeded by nothing, so every account fell into the
#: default and the balance sheet grouped by `type` alone, which puts the stock
#: on the shelf and a delivery van in one undifferentiated pile of "assets", and
#: gives a reader no way to see working capital at all.
CHART = [
    # code, name, type, subledger, section, is_cash
    ("1000", "Cash on hand", "asset", "", "current_asset", True),
    ("1010", "Bank", "asset", "", "current_asset", True),
    ("1020", "Mobile money float", "asset", "", "current_asset", True),
    ("1100", "Trade debtors", "asset", "debtors", "current_asset", False),
    ("1110", "Medical scheme debtors", "asset", "debtors", "current_asset", False),
    ("1200", "Stock on hand", "asset", "stock", "current_asset", False),
    ("1300", "VAT input", "asset", "vat", "current_asset", False),
    # The things a pharmacy owns for longer than a year. Absent until now, so a
    # shopfitting or a delivery vehicle had nowhere to go but an expense — which
    # understates both the profit of the year it was bought and the worth of the
    # business ever after.
    ("1500", "Fixtures and fittings", "asset", "", "non_current_asset", False),
    ("1510", "Dispensary equipment", "asset", "", "non_current_asset", False),
    ("1520", "Motor vehicles", "asset", "", "non_current_asset", False),
    ("1590", "Accumulated depreciation", "asset", "", "non_current_asset", False),
    ("2000", "Trade creditors", "liability", "creditors", "current_liability", False),
    ("2100", "VAT output", "liability", "vat", "current_liability", False),
    ("2200", "VAT control", "liability", "vat", "current_liability", False),
    ("2300", "PAYE and NSSA payable", "liability", "", "current_liability", False),
    ("2400", "Accruals", "liability", "", "current_liability", False),
    ("2600", "Bank overdraft", "liability", "", "current_liability", False),
    ("2800", "Long-term loans", "liability", "", "non_current_liability", False),
    ("3000", "Owner's equity", "equity", "", "equity", False),
    ("3100", "Retained earnings", "equity", "", "equity", False),
    ("3200", "Drawings", "equity", "", "equity", False),
    ("4000", "Dispensary revenue", "income", "", "revenue", False),
    ("4010", "Front shop revenue", "income", "", "revenue", False),
    ("4900", "Discounts allowed", "income", "", "revenue", False),
    ("5000", "Cost of goods sold", "expense", "", "cogs", False),
    ("5100", "Stock write-offs", "expense", "", "cogs", False),
    ("6000", "Professional fees earned", "income", "", "revenue", False),
    ("6100", "Salaries and wages", "expense", "", "operating_expense", False),
    ("6200", "Rent", "expense", "", "operating_expense", False),
    ("6300", "Electricity and water", "expense", "", "operating_expense", False),
    ("6400", "Telephone and internet", "expense", "", "operating_expense", False),
    ("6500", "Licences and subscriptions", "expense", "", "operating_expense", False),
    ("6600", "Repairs and maintenance", "expense", "", "operating_expense", False),
    ("6700", "Depreciation", "expense", "", "operating_expense", False),
    ("6800", "Bank charges", "expense", "", "operating_expense", False),
    ("8000", "Bad debts written off", "expense", "", "other_expense", False),
]

#: What a section is called on a statement, and the order a reader expects.
SECTIONS = [
    ("current_asset", "Current assets", "asset"),
    ("non_current_asset", "Non-current assets", "asset"),
    ("current_liability", "Current liabilities", "liability"),
    ("non_current_liability", "Non-current liabilities", "liability"),
    ("equity", "Equity", "equity"),
    ("revenue", "Revenue", "income"),
    ("cogs", "Cost of sales", "expense"),
    ("operating_expense", "Operating expenses", "expense"),
    ("other_income", "Other income", "income"),
    ("other_expense", "Other expenses", "expense"),
]

#: Where an account goes when whoever created it did not say. Not a guess made
#: silently: the chart screen shows the section it landed in, so a wrong one is
#: visible rather than only discovered when a balance sheet reads oddly.
DEFAULT_SECTION = {
    "asset": "current_asset",
    "liability": "current_liability",
    "equity": "equity",
    "income": "revenue",
    "expense": "operating_expense",
}


class LedgerError(ValueError):
    """Raised when an entry cannot be posted."""


@dataclass
class Line:
    account_code: str
    debit: float = 0.0
    credit: float = 0.0
    description: str = ""
    party_type: str = ""
    party_id: int | None = None


def ensure_chart(db: Session) -> int:
    """Seed the chart, and give the accounts already there their section.

    The backfill matters as much as the seed. Every pharmacy already running
    this software has the original twenty accounts with an empty `section`, and
    a chart that groups half its rows under "unclassified" is one nobody reads.
    Only ever fills a blank: an account somebody has since moved stays moved.
    """
    created = 0
    have = {a.code: a for a in db.query(Account).all()}
    touched = False
    for code, name, kind, subledger, section, is_cash in CHART:
        account = have.get(code)
        if account is None:
            db.add(Account(code=code, name=name, type=kind, subledger=subledger,
                           section=section, is_cash=is_cash))
            created += 1
            continue
        if not account.section:
            account.section = section
            touched = True
        if is_cash and not account.is_cash:
            account.is_cash = True
            touched = True

    # Anything hand-created before sections existed, or since. Placed by type
    # rather than left out of the statements entirely.
    for account in have.values():
        if not account.section:
            account.section = DEFAULT_SECTION.get(account.type, "")
            touched = touched or bool(account.section)

    if created or touched:
        db.commit()
    return created


def next_reference(db: Session) -> str:
    """The next journal reference, taken from the highest one in use.

    It used to be `COUNT(*) + 1`, which is unique only while nothing is ever
    deleted. Remove sixty entries to repost them and the count falls back over
    numbers that are still on the books, so the next entry collides with one
    from an hour ago, and because the reference is indexed unique, the whole
    posting run fails on a constraint rather than on anything to do with
    accounting.

    Counting rows is not the same as counting how many have existed. The
    highest number actually issued is.
    """
    prefix = f"JE{datetime.utcnow():%y%m}"
    highest = 0
    for (reference,) in db.query(JournalEntry.reference).filter(
            JournalEntry.reference.like(f"{prefix}%")).all():
        tail = (reference or "")[len(prefix):]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}{highest + 1:06d}"


def post(db: Session, *, entry_date: date, description: str, lines: list[Line],
         source: str = "", source_id: int | None = None,
         currency_code: str = "USD", user_id: int | None = None) -> JournalEntry:
    """Post a balanced entry into an open period, or refuse."""
    if len(lines) < 2:
        raise LedgerError("An entry needs at least two lines, that is what makes "
                          "it double entry.")

    debits = round(sum(l.debit for l in lines), 2)
    credits = round(sum(l.credit for l in lines), 2)
    if abs(debits - credits) > 0.005:
        raise LedgerError(
            f"Entry does not balance: debits {debits:.2f}, credits {credits:.2f}, "
            f"out by {abs(debits - credits):.2f}. It has not been posted.")
    if debits == 0:
        raise LedgerError("An entry of zero has nothing to record.")

    for line in lines:
        if line.debit and line.credit:
            raise LedgerError(
                f"{line.account_code} is both debited and credited on one line. "
                "Split it into two lines so the intent is readable.")
        if line.debit < 0 or line.credit < 0:
            raise LedgerError("A negative amount is a posting on the other side — "
                              "put it there instead.")

    known = {a.code for a in db.query(Account).filter(Account.active).all()}
    unknown = sorted({l.account_code for l in lines} - known)
    if unknown:
        raise LedgerError(f"No such account: {', '.join(unknown)}.")

    # The period module owns this rule; asking it keeps one answer in one place.
    try:
        period = periods.guard(db, entry_date)
    except periods.PeriodError as exc:
        raise LedgerError(str(exc)) from exc

    entry = JournalEntry(
        reference=next_reference(db), period_code=period.code, entry_date=entry_date,
        description=description[:240], source=source, source_id=source_id,
        currency_code=currency_code, created_by_id=user_id,
    )
    db.add(entry)
    db.flush()
    for line in lines:
        db.add(JournalLine(
            entry_id=entry.id, account_code=line.account_code,
            debit=round(line.debit, 2), credit=round(line.credit, 2),
            description=line.description[:240],
            party_type=line.party_type, party_id=line.party_id,
        ))
    db.commit()
    db.refresh(entry)
    return entry


def reverse(db: Session, entry: JournalEntry, on: date | None = None,
            reason: str = "", user_id: int | None = None) -> JournalEntry:
    """Undo an entry by posting its mirror. History is never edited."""
    if entry.status == "reversed":
        raise LedgerError(f"{entry.reference} has already been reversed.")
    mirrored = [
        Line(account_code=l.account_code, debit=l.credit, credit=l.debit,
             description=f"Reversal: {l.description}".strip(),
             party_type=l.party_type, party_id=l.party_id)
        for l in entry.lines
    ]
    reversal = post(
        db, entry_date=on or date.today(),
        description=f"Reversal of {entry.reference}"
                    + (f": {reason}" if reason else ""),
        lines=mirrored, source=entry.source, source_id=entry.source_id,
        currency_code=entry.currency_code, user_id=user_id)
    entry.status = "reversed"
    reversal.reverses_id = entry.id
    db.commit()
    return reversal


def balance(db: Session, account_code: str, *, upto: date | None = None,
            period_code: str = "") -> float:
    """The signed balance of one account, in the direction its type runs."""
    account = db.query(Account).filter(Account.code == account_code).first()
    if not account:
        raise LedgerError(f"No such account: {account_code}")
    query = (db.query(func.coalesce(func.sum(JournalLine.debit), 0.0),
                      func.coalesce(func.sum(JournalLine.credit), 0.0))
             .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
             .filter(JournalLine.account_code == account_code))
    if upto:
        query = query.filter(JournalEntry.entry_date <= upto)
    if period_code:
        query = query.filter(JournalEntry.period_code == period_code)
    debits, credits = query.one()
    net = debits - credits
    return round(net if account.type in DEBIT_POSITIVE else -net, 2)


def balances(db: Session, codes: list[str], *, upto: date | None = None,
             period_code: str = "") -> dict[str, float]:
    """Every balance in one query, in the direction each account's type runs.

    `balance` answers for one code, and a chart of accounts screen calling it in
    a loop is a query per account — twenty-one accounts, forty-five queries and
    five seconds against a hosted database to produce under two kilobytes. The
    arithmetic is identical; only the number of round trips differs.
    """
    if not codes:
        return {}
    kinds = {a.code: a.type for a in
             db.query(Account).filter(Account.code.in_(codes)).all()}
    query = (db.query(JournalLine.account_code,
                      func.coalesce(func.sum(JournalLine.debit), 0.0),
                      func.coalesce(func.sum(JournalLine.credit), 0.0))
             .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
             .filter(JournalLine.account_code.in_(codes)))
    if upto:
        query = query.filter(JournalEntry.entry_date <= upto)
    if period_code:
        query = query.filter(JournalEntry.period_code == period_code)

    out = {code: 0.0 for code in codes}
    for code, debits, credits in query.group_by(JournalLine.account_code).all():
        net = (debits or 0.0) - (credits or 0.0)
        out[code] = round(net if kinds.get(code) in DEBIT_POSITIVE else -net, 2)
    return out


def trial_balance(db: Session, *, period_code: str = "",
                  upto: date | None = None) -> dict:
    """Every account with a movement, and the proof that the whole thing balances."""
    query = (db.query(JournalLine.account_code,
                      func.coalesce(func.sum(JournalLine.debit), 0.0),
                      func.coalesce(func.sum(JournalLine.credit), 0.0))
             .join(JournalEntry, JournalLine.entry_id == JournalEntry.id))
    if period_code:
        query = query.filter(JournalEntry.period_code == period_code)
    if upto:
        query = query.filter(JournalEntry.entry_date <= upto)
    rows = query.group_by(JournalLine.account_code).all()

    accounts = {a.code: a for a in db.query(Account).all()}
    lines, total_debit, total_credit = [], 0.0, 0.0
    for code, debits, credits in sorted(rows):
        account = accounts.get(code)
        net = round(debits - credits, 2)
        lines.append({
            "code": code,
            "name": account.name if account else "(unknown account)",
            "type": account.type if account else "",
            "subledger": account.subledger if account else "",
            "debit": round(debits, 2),
            "credit": round(credits, 2),
            "balance": round(net if (account and account.type in DEBIT_POSITIVE)
                             else -net, 2),
        })
        total_debit += debits
        total_credit += credits

    difference = round(total_debit - total_credit, 2)
    return {
        "period_code": period_code,
        "lines": lines,
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "difference": difference,
        "balanced": abs(difference) < 0.005,
        # If this is ever false it is not a rounding question. Every entry is
        # checked at posting, so an unbalanced trial balance means something
        # reached the tables without going through post().
        "message": ("" if abs(difference) < 0.005 else
                    f"The ledger is out by {difference:.2f}. Every entry balances "
                    "at posting, so something has been written to the journal "
                    "without going through it."),
    }


def subledger(db: Session, name: str, *, period_code: str = "") -> dict:
    """What a subledger holds, by party. The detail behind a control account."""
    controls = [a for a in db.query(Account).filter(Account.subledger == name).all()]
    if not controls:
        raise LedgerError(f"No control account is marked as the '{name}' subledger.")
    codes = [a.code for a in controls]

    query = (db.query(JournalLine.party_type, JournalLine.party_id,
                      func.coalesce(func.sum(JournalLine.debit), 0.0),
                      func.coalesce(func.sum(JournalLine.credit), 0.0))
             .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
             .filter(JournalLine.account_code.in_(codes)))
    if period_code:
        query = query.filter(JournalEntry.period_code == period_code)
    rows = query.group_by(JournalLine.party_type, JournalLine.party_id).all()

    debit_positive = controls[0].type in DEBIT_POSITIVE
    parties, total = [], 0.0
    for party_type, party_id, debits, credits in rows:
        net = round(debits - credits, 2)
        amount = net if debit_positive else -net
        total += amount
        parties.append({"party_type": party_type or "(unattributed)",
                        "party_id": party_id, "balance": round(amount, 2)})
    return {
        "subledger": name,
        "control_accounts": codes,
        "parties": sorted(parties, key=lambda p: -abs(p["balance"])),
        "total": round(total, 2),
    }


def reconcile_control(db: Session, name: str, *, period_code: str = "") -> dict:
    """Does the control account agree with the subledger behind it?

    The two are kept separately precisely so they can disagree. A difference
    means something was posted around the subledger rather than through it —
    usually a journal written straight to the control account by hand, and it
    is the single most useful check in a ledger, because it is the one that
    catches the errors nothing else can see.
    """
    detail = subledger(db, name, period_code=period_code)
    control_total = round(sum(balance(db, code, period_code=period_code)
                              for code in detail["control_accounts"]), 2)
    difference = round(control_total - detail["total"], 2)
    unattributed = [p for p in detail["parties"] if not p["party_id"]]
    return {
        "subledger": name,
        "control_balance": control_total,
        "subledger_total": detail["total"],
        "difference": difference,
        "reconciled": abs(difference) < 0.005,
        "unattributed_lines": round(sum(p["balance"] for p in unattributed), 2),
        "message": ("Control agrees with the subledger."
                    if abs(difference) < 0.005 else
                    f"The {name} control account says {control_total:.2f} but the "
                    f"subledger adds to {detail['total']:.2f}, a difference of "
                    f"{difference:.2f}. Something was posted to the control "
                    "account without a party, or around the subledger entirely."),
        "parties": detail["parties"][:50],
    }
