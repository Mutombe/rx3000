"""Handing the day's books to the pharmacy's accountant.

Almost every pharmacy in this market keeps its financials in Pastel, and the
person who does that is not the person at the counter. They want a file, once
a day, that goes into their own general ledger without being re-keyed.

WHAT IS EXPORTED, AND WHY IT IS THE JOURNAL

The journal, not the sales. A sale is a thing that happened in a shop; a
journal line is that thing stated in the language an accountant already uses,
and this system already writes one for every sale, dispensing, receipt,
supplier invoice, payment and write-off. Exporting the ledger rather than the
transactions means the export cannot disagree with the trial balance, because
it IS the trial balance in another shape.

THE PART THIS FILE WILL NOT PRETEND ABOUT

Pastel's import layout varies by version and by how the practice has set it
up, and the blueprint says so: the format and the GL mapping are to be
"configured through integration management" rather than fixed. So the column
order, the date format and the separator are settings, defaulted to the
common Pastel Partner general journal shape, and the first thing anybody
should do is send one file to the accountant and ask.

An export that quietly assumes the wrong layout is worse than no export: it
imports, it balances, and it puts everything in the wrong account.

THE MAPPING IS THE WHOLE JOB

An account here is 1200 STOCK ON HAND. In their books it might be 8400. Both
are right and neither is guessable, so `Account.external_code` holds theirs
and a line whose account has no mapping is reported rather than exported
under our code — which would import cleanly into whatever their 1200 happens
to be, and that is the failure worth refusing.
"""
from __future__ import annotations

import csv
import io
from datetime import date

from sqlalchemy.orm import Session

from ..models import Account, JournalEntry, JournalLine
from . import config

#: The columns, in the order Pastel Partner's general journal import expects
#: them by default. Held here rather than inline so the settings below can
#: reorder them without touching the writer.
COLUMNS = ("account", "date", "reference", "description", "debit", "credit",
           "tax_type", "currency")

#: How a date is written. Pastel installations differ and the wrong one
#: imports as a different day, which is the kind of error that balances.
DATE_FORMATS = {
    "ddmmyyyy": "%d%m%Y",
    "dd/mm/yyyy": "%d/%m/%Y",
    "yyyy-mm-dd": "%Y-%m-%d",
    "mm/dd/yyyy": "%m/%d/%Y",
}


def settings(db: Session) -> dict:
    """How this pharmacy's accountant wants the file."""
    return {
        "date_format": config.text(db, "pastel.date_format", "ddmmyyyy"),
        "separator": config.text(db, "pastel.separator", ","),
        "header": config.flag(db, "pastel.header", True),
        # Pastel wants one signed amount in some layouts and separate debit
        # and credit columns in others.
        "single_amount": config.flag(db, "pastel.single_amount", False),
        "tax_type": config.text(db, "pastel.tax_type", "0"),
    }


def _mapped(db: Session) -> dict[str, str]:
    """Our account code to theirs, for the accounts somebody has mapped."""
    return {a.code: (a.external_code or "").strip()
            for a in db.query(Account).all()}


def unmapped(db: Session, since: date, until: date) -> list[dict]:
    """Accounts the day's journal touches that nobody has mapped yet.

    Reported before anything is written. A line exported under OUR code
    imports cleanly into whatever their account of that number happens to be,
    which is a wrong set of books that balances — the hardest kind of error to
    find and the easiest to prevent.
    """
    mapping = _mapped(db)
    names = {a.code: a.name for a in db.query(Account).all()}
    used = (db.query(JournalLine.account_code)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .filter(JournalEntry.entry_date >= since,
                    JournalEntry.entry_date <= until,
                    JournalEntry.status == "posted")
            .distinct().all())
    return [{"code": code, "name": names.get(code, "")}
            for (code,) in sorted(used)
            if not mapping.get(code)]


def rows(db: Session, since: date, until: date) -> list[dict]:
    """The journal for these days, in their account codes."""
    mapping = _mapped(db)
    out: list[dict] = []
    entries = (db.query(JournalEntry)
               .filter(JournalEntry.entry_date >= since,
                       JournalEntry.entry_date <= until,
                       JournalEntry.status == "posted")
               .order_by(JournalEntry.entry_date.asc(),
                         JournalEntry.id.asc()).all())
    for entry in entries:
        for line in entry.lines:
            out.append({
                "account": mapping.get(line.account_code) or line.account_code,
                "our_account": line.account_code,
                "date": entry.entry_date,
                "reference": entry.reference or "",
                # The line's own note where it has one, else the entry's. A
                # bookkeeper reading this months later has only this sentence.
                "description": (line.description or entry.description or "")[:100],
                "debit": round(line.debit or 0.0, 2),
                "credit": round(line.credit or 0.0, 2),
                "currency": entry.currency_code or "USD",
            })
    return out


def to_csv(db: Session, since: date, until: date) -> str:
    """The file itself."""
    how = settings(db)
    fmt = DATE_FORMATS.get(how["date_format"], DATE_FORMATS["ddmmyyyy"])
    buffer = io.StringIO()
    # QUOTE_MINIMAL and \r\n: Pastel is a Windows application and a bare \n
    # has been known to swallow the last line of an import.
    writer = csv.writer(buffer, delimiter=(how["separator"] or ",")[0],
                        quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")

    if how["single_amount"]:
        head = ["Account", "Date", "Reference", "Description", "Amount",
                "TaxType", "Currency"]
    else:
        head = ["Account", "Date", "Reference", "Description", "Debit",
                "Credit", "TaxType", "Currency"]
    if how["header"]:
        writer.writerow(head)

    for row in rows(db, since, until):
        when = row["date"].strftime(fmt) if row["date"] else ""
        if how["single_amount"]:
            # A debit is positive and a credit negative, which is the
            # convention every single-amount layout this has met uses.
            amount = round(row["debit"] - row["credit"], 2)
            writer.writerow([row["account"], when, row["reference"],
                             row["description"], f"{amount:.2f}",
                             how["tax_type"], row["currency"]])
        else:
            writer.writerow([row["account"], when, row["reference"],
                             row["description"], f"{row['debit']:.2f}",
                             f"{row['credit']:.2f}", how["tax_type"],
                             row["currency"]])
    return buffer.getvalue()


def summary(db: Session, since: date, until: date) -> dict:
    """What the file will contain, before anybody downloads it.

    Including whether it balances. An export that does not balance will be
    rejected by Pastel, and finding that out in the accountant's office a day
    later is a wasted day for both of them.
    """
    lines = rows(db, since, until)
    debit = round(sum(r["debit"] for r in lines), 2)
    credit = round(sum(r["credit"] for r in lines), 2)
    missing = unmapped(db, since, until)
    return {
        "from": since.isoformat(),
        "to": until.isoformat(),
        "lines": len(lines),
        "debit": debit,
        "credit": credit,
        "balanced": abs(debit - credit) < 0.01,
        "unmapped": missing,
        "settings": settings(db),
        "says": (
            "Nothing was posted in those days."
            if not lines else
            f"{len(lines)} line(s), {debit:,.2f} against {credit:,.2f}."
            + ("" if abs(debit - credit) < 0.01 else
               " These do not balance, and Pastel will refuse the file.")
            + ("" if not missing else
               f" {len(missing)} account(s) have no Pastel code, so those "
               "lines would arrive under our numbering.")
        ),
    }
