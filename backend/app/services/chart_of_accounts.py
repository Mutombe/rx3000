"""The chart of accounts: the shape of the business, before any figures.

A trial balance answers "do the books balance". This answers the question that
comes first and is asked far more often — "where does this go". A bookkeeper
posting an electricity bill, an owner asking what the shop is worth, an
accountant at year end all read this same list, and each of them needs it
grouped the way a statement is grouped rather than sorted by code.

Two things this deliberately does that a bare account list does not:

  **It groups by section, not by type.** Stock and a delivery van are both
  assets. Putting them in one heap is how a pharmacy comes to believe it has
  forty thousand dollars of working capital when half of that is a vehicle.

  **It shows what an account is used by.** An account nobody may delete because
  the posting rules name it is a different thing from one somebody added last
  month and got wrong, and the screen has no way to tell them apart unless this
  says so.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import Account, JournalLine
from . import ledger

#: Accounts the posting rules name directly. Renaming one is fine; removing or
#: retyping one silently breaks every sale, receipt and write-off that posts
#: through it, and the breakage shows up as a trial balance that stops
#: balancing weeks later.
PROTECTED = {code for code, *_ in ledger.CHART}

VALID_TYPES = ("asset", "liability", "equity", "income", "expense")
SECTION_OF = {key: kind for key, _label, kind in ledger.SECTIONS}
SECTION_LABEL = {key: label for key, label, _kind in ledger.SECTIONS}


class ChartError(ValueError):
    """Raised when an account cannot be created or changed."""


def chart(db: Session, *, include_inactive: bool = False) -> dict:
    """Every account, grouped as a statement groups them, with its balance."""
    ledger.ensure_chart(db)

    query = db.query(Account)
    if not include_inactive:
        query = query.filter(Account.active)
    accounts = query.order_by(Account.code).all()

    # One grouped query for every balance rather than one per account: the
    # chart is forty rows now and would otherwise be forty round trips, which
    # on a hosted database is four seconds to draw a list.
    sums = ledger.balances(db, [a.code for a in accounts])

    # Which accounts have ever been posted to. An account with movement cannot
    # be deleted, and saying so on the row is better than refusing at the point
    # of the click.
    used = {code for (code,) in db.query(JournalLine.account_code).distinct().all()}

    groups: dict[str, dict] = {}
    for key, label, kind in ledger.SECTIONS:
        groups[key] = {"section": key, "label": label, "type": kind,
                       "accounts": [], "total": 0.0}
    # Anything whose section is unrecognised still has to appear. An account
    # missing from the chart is an account whose balance is missing from the
    # statements, and silence is the worst possible way to report that.
    groups["unclassified"] = {"section": "unclassified", "label": "Unclassified",
                              "type": "", "accounts": [], "total": 0.0}

    for a in accounts:
        section = a.section if a.section in groups else "unclassified"
        balance = sums.get(a.code, 0.0)
        groups[section]["accounts"].append({
            "code": a.code, "name": a.name, "type": a.type,
            "section": a.section or "", "subledger": a.subledger or "",
            "parent_code": a.parent_code or "", "is_cash": bool(a.is_cash),
            "active": bool(a.active), "notes": a.notes or "",
            "balance": balance,
            "protected": a.code in PROTECTED,
            "posted_to": a.code in used,
        })
        groups[section]["total"] = round(groups[section]["total"] + balance, 2)

    ordered = [g for g in groups.values() if g["accounts"]]

    def total_of(*sections: str) -> float:
        return round(sum(groups[s]["total"] for s in sections
                         if s in groups), 2)

    assets = total_of("current_asset", "non_current_asset")
    liabilities = total_of("current_liability", "non_current_liability")
    equity = total_of("equity")
    revenue = total_of("revenue", "other_income")
    expenses = total_of("cogs", "operating_expense", "other_expense")
    profit = round(revenue - expenses, 2)

    return {
        "groups": ordered,
        "count": len(accounts),
        "totals": {
            "assets": assets,
            "current_assets": total_of("current_asset"),
            "non_current_assets": total_of("non_current_asset"),
            "liabilities": liabilities,
            "current_liabilities": total_of("current_liability"),
            "non_current_liabilities": total_of("non_current_liability"),
            "equity": equity,
            "revenue": revenue,
            "expenses": expenses,
            "profit": profit,
            # Working capital: what could be turned into cash inside a year
            # against what has to be paid inside a year. The single number a
            # pharmacy owner most needs and least often has.
            "working_capital": round(total_of("current_asset")
                                     - total_of("current_liability"), 2),
        },
        # Assets = liabilities + equity + profit for the period. Shown rather
        # than asserted: a chart that quietly hides a difference is a chart
        # that lets one accumulate.
        "difference": round(assets - (liabilities + equity + profit), 2),
        "sections": [{"key": k, "label": l, "type": t}
                     for k, l, t in ledger.SECTIONS],
    }


def _clean_code(code: str) -> str:
    code = (code or "").strip()
    if not re.fullmatch(r"[0-9A-Za-z]{3,10}", code):
        raise ChartError(
            "An account code is 3 to 10 letters or digits. Codes are what "
            "every posting rule and every export refers to, so they cannot "
            "carry spaces or punctuation.")
    return code.upper() if code.isalpha() else code


def create(db: Session, *, code: str, name: str, type: str,
           section: str = "", subledger: str = "", parent_code: str = "",
           is_cash: bool = False, notes: str = "") -> Account:
    """Add an account to the chart."""
    code = _clean_code(code)
    name = (name or "").strip()
    if not name:
        raise ChartError("An account needs a name.")
    if type not in VALID_TYPES:
        raise ChartError(
            f"'{type}' is not an account type. It has to be one of: "
            + ", ".join(VALID_TYPES) + ".")

    if db.query(Account).filter(Account.code == code).first():
        raise ChartError(
            f"Account {code} already exists. Two accounts with one code would "
            f"make every figure posted to it ambiguous.")

    section = section or ledger.DEFAULT_SECTION.get(type, "")
    if section and SECTION_OF.get(section) not in (None, type):
        raise ChartError(
            f"A {type} account cannot sit under {SECTION_LABEL.get(section, section)} "
            f"— that part of the statement is for "
            f"{SECTION_OF[section]} accounts.")

    if parent_code:
        parent = db.query(Account).filter(Account.code == parent_code).first()
        if parent is None:
            raise ChartError(f"There is no account {parent_code} to sit under.")
        if parent.type != type:
            raise ChartError(
                f"{parent_code} is a {parent.type} account, so a {type} account "
                f"cannot roll up into it.")

    account = Account(code=code, name=name, type=type, section=section,
                      subledger=(subledger or "").strip(),
                      parent_code=(parent_code or "").strip(),
                      is_cash=bool(is_cash), notes=(notes or "").strip(),
                      active=True)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def update(db: Session, code: str, **changes) -> Account:
    """Rename, reclassify or retire an account.

    A code is never changed. Every journal line ever posted refers to it, and
    changing it would either orphan those lines or require rewriting history —
    both worse than living with a code that reads oddly.
    """
    account = db.query(Account).filter(Account.code == code).first()
    if account is None:
        raise ChartError(f"There is no account {code}.")

    posted = db.query(JournalLine).filter(
        JournalLine.account_code == code).first() is not None

    if "name" in changes and changes["name"]:
        account.name = str(changes["name"]).strip()
    if "notes" in changes:
        account.notes = str(changes["notes"] or "").strip()

    if "type" in changes and changes["type"] and changes["type"] != account.type:
        if code in PROTECTED:
            raise ChartError(
                f"{code} is used by the posting rules, so its type cannot "
                f"change. Its name can.")
        if posted:
            raise ChartError(
                f"{code} has already been posted to. Changing an account from "
                f"{account.type} to {changes['type']} would flip the sign of "
                f"every figure already in it. Create a new account and journal "
                f"the balance across.")
        if changes["type"] not in VALID_TYPES:
            raise ChartError(f"'{changes['type']}' is not an account type.")
        account.type = changes["type"]
        account.section = ledger.DEFAULT_SECTION.get(account.type, "")

    if "section" in changes and changes["section"]:
        section = changes["section"]
        if SECTION_OF.get(section) not in (None, account.type):
            raise ChartError(
                f"A {account.type} account cannot sit under "
                f"{SECTION_LABEL.get(section, section)}.")
        account.section = section

    if "is_cash" in changes:
        account.is_cash = bool(changes["is_cash"])

    if "active" in changes and not changes["active"]:
        if code in PROTECTED:
            raise ChartError(
                f"{code} is used by the posting rules. Retiring it would stop "
                f"sales, receipts or write-offs from posting at all.")
        if abs(ledger.balance(db, code)) > 0.005:
            raise ChartError(
                f"{code} still has a balance. Clear it to nil with a journal "
                f"first — retiring an account with money in it hides that money "
                f"rather than moving it.")
        account.active = False
    elif changes.get("active"):
        account.active = True

    db.commit()
    db.refresh(account)
    return account
