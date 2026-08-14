"""Financial statements, built from the journal and nothing else.

Three rules hold this together, and every accounting bug I have seen in a small
system is one of them being broken:

1. **Nothing is stored.** A balance sheet is a query over journal lines, never a
   table that is updated alongside them. The moment a figure is kept in two
   places they disagree, and the one on the report is the one nobody checks.

2. **The current period's profit belongs in equity.** This is the classic reason
   a balance sheet does not balance: income and expense accounts are left out of
   the equity side, and the statement is out by exactly the profit. Retained
   earnings carries prior years; the current result is computed and shown as its
   own line, so a reader can see where the number came from.

3. **A section is shown even when it is empty.** A zero under Inventory means
   the pharmacy holds no stock, which is information. A missing Inventory line
   means nobody knows whether it is zero or forgotten. Zero-balance sections can
   be hidden on request, but never by default.

Every figure that is a total of several accounts is accompanied by its
breakdown, in `notes`. A total nobody can decompose is a number a pharmacist
cannot check, and an unauditable statement is worth very little to the person
who has to sign it.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Account, JournalEntry, JournalLine

# Which way round a positive balance runs. Assets and expenses are naturally
# debits; everything else is naturally a credit. Getting this wrong flips signs
# on half the statement, so it is stated once here and never re-derived.
DEBIT_TYPES = {"asset", "expense"}

# The shape of each statement: section key, heading, and the order it reads in.
# Sections appear in this order whether or not they hold anything.
BALANCE_SHEET_LAYOUT = [
    ("non_current_asset", "Non-current assets", "asset"),
    ("current_asset", "Current assets", "asset"),
    ("non_current_liability", "Non-current liabilities", "liability"),
    ("current_liability", "Current liabilities", "liability"),
    ("equity", "Equity", "equity"),
]

INCOME_LAYOUT = [
    ("revenue", "Revenue", "income"),
    ("cogs", "Cost of sales", "expense"),
    ("operating_expense", "Operating expenses", "expense"),
    ("other_income", "Other income", "income"),
    ("other_expense", "Other expenses", "expense"),
]


def infer_section(account: Account) -> str:
    """Where an account belongs when nobody has said.

    Existing charts predate the section column, and a statement that silently
    drops an unclassified account is worse than one that guesses and shows its
    working: a dropped account makes the balance sheet fail to balance with no
    indication of which figure is missing. So everything lands somewhere, and
    the guess is conservative — current rather than non-current, operating
    rather than exceptional — because that is where a pharmacy's accounts
    actually are.
    """
    if account.section:
        return account.section
    kind = (account.type or "").lower()
    code = (account.code or "").strip()
    if kind == "asset":
        # A fixed-asset range is the one distinction worth making by code.
        return "non_current_asset" if code.startswith(("15", "16", "17")) else "current_asset"
    if kind == "liability":
        return "non_current_liability" if code.startswith(("25", "26")) else "current_liability"
    if kind == "equity":
        return "equity"
    if kind == "income":
        # Trading revenue against incidental income. Both are income; only one
        # belongs in the gross-profit calculation.
        return "revenue" if code.startswith("4") else "other_income"
    if kind == "expense":
        return "cogs" if code.startswith("5") and not code.startswith("51") else "operating_expense"
    return "operating_expense"


def _movements(db: Session, *, start: date | None, upto: date) -> dict[str, float]:
    """Net debit-minus-credit per account code over a window.

    Reversed entries are excluded rather than netted. A reversal posts its own
    contra lines, so counting both the original and the reversal would double
    the correction.
    """
    query = (
        db.query(
            JournalLine.account_code,
            func.coalesce(func.sum(JournalLine.debit), 0.0),
            func.coalesce(func.sum(JournalLine.credit), 0.0),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .filter(JournalEntry.status == "posted")
        .filter(JournalEntry.entry_date <= upto)
    )
    if start is not None:
        query = query.filter(JournalEntry.entry_date >= start)
    return {
        code: round(float(debit) - float(credit), 2)
        for code, debit, credit in query.group_by(JournalLine.account_code).all()
    }


def _signed(account: Account, raw: float) -> float:
    """A balance as a reader expects to see it: positive means 'has this much'.

    Raw balances are debit-positive. A creditor with 4,000 owing carries a
    credit balance of -4,000, and printing that on a balance sheet as a negative
    liability is how a statement stops being readable.
    """
    return round(raw if (account.type or "").lower() in DEBIT_TYPES else -raw, 2)


def _collect(db: Session, balances: dict[str, float], layout, accounts):
    """Group accounts into the layout's sections, with each section's breakdown."""
    sections = {key: {"key": key, "heading": heading, "total": 0.0, "accounts": []}
                for key, heading, _ in layout}
    for account in accounts:
        section = infer_section(account)
        if section not in sections:
            continue
        raw = balances.get(account.code, 0.0)
        value = _signed(account, raw)
        sections[section]["accounts"].append({
            "code": account.code, "name": account.name,
            "amount": value, "subledger": account.subledger or "",
        })
        sections[section]["total"] = round(sections[section]["total"] + value, 2)
    for section in sections.values():
        # Largest first: a reader scanning a statement is looking for what is
        # big, not for what is alphabetically early.
        section["accounts"].sort(key=lambda a: (-abs(a["amount"]), a["code"]))
    return sections


def income_statement(db: Session, *, start: date, upto: date, hide_zero: bool = False) -> dict:
    """Revenue through to profit for a window."""
    accounts = db.query(Account).filter(Account.active).order_by(Account.code).all()
    balances = _movements(db, start=start, upto=upto)
    sections = _collect(db, balances, INCOME_LAYOUT, accounts)

    revenue = sections["revenue"]["total"]
    cogs = sections["cogs"]["total"]
    gross = round(revenue - cogs, 2)
    operating = sections["operating_expense"]["total"]
    other_income = sections["other_income"]["total"]
    other_expense = sections["other_expense"]["total"]
    net = round(gross - operating + other_income - other_expense, 2)

    rows = []
    for key, heading, _ in INCOME_LAYOUT:
        section = sections[key]
        if hide_zero and not section["total"] and not section["accounts"]:
            continue
        rows.append(section)
        if key == "cogs":
            rows.append({"key": "gross_profit", "heading": "Gross profit",
                         "total": gross, "accounts": [], "subtotal": True})

    return {
        "from": start.isoformat(), "to": upto.isoformat(),
        "sections": rows,
        "revenue": revenue, "cost_of_sales": cogs, "gross_profit": gross,
        "gross_margin": round(gross / revenue * 100, 1) if revenue else 0.0,
        "operating_expenses": operating,
        "other_income": other_income, "other_expenses": other_expense,
        "net_profit": net,
    }


def balance_sheet(db: Session, *, upto: date, year_start: date, hide_zero: bool = False) -> dict:
    """Position at a date, including the profit earned so far this year."""
    accounts = db.query(Account).filter(Account.active).order_by(Account.code).all()
    balances = _movements(db, start=None, upto=upto)
    sections = _collect(db, balances, BALANCE_SHEET_LAYOUT, accounts)

    # Rule 2. Without this the statement is out by exactly the year's profit.
    result = income_statement(db, start=year_start, upto=upto)
    profit = result["net_profit"]
    sections["equity"]["accounts"].append({
        "code": "—", "name": f"Profit for the period to {upto.isoformat()}",
        "amount": profit, "subledger": "", "computed": True,
    })
    sections["equity"]["total"] = round(sections["equity"]["total"] + profit, 2)

    assets = round(sections["non_current_asset"]["total"] + sections["current_asset"]["total"], 2)
    liabilities = round(
        sections["non_current_liability"]["total"] + sections["current_liability"]["total"], 2)
    equity = sections["equity"]["total"]
    difference = round(assets - liabilities - equity, 2)

    rows = []
    for key, heading, _ in BALANCE_SHEET_LAYOUT:
        section = sections[key]
        if hide_zero and not section["total"] and not section["accounts"]:
            continue
        rows.append(section)

    return {
        "as_at": upto.isoformat(),
        "year_start": year_start.isoformat(),
        "sections": rows,
        "total_assets": assets,
        "total_liabilities": liabilities,
        "total_equity": equity,
        "profit_for_period": profit,
        "balances": difference == 0,
        # Named, not hidden. A statement that is out by a cent has something
        # wrong with it, and rounding it away removes the only evidence.
        "difference": difference,
        "note": (
            "Assets equal liabilities plus equity."
            if difference == 0
            else f"Out of balance by {difference:.2f}. A journal is one-sided, or an "
                 "account is missing from the chart."
        ),
    }
