"""Bank reconciliation — what the bank says against what the ledger says.

The two will never agree line for line, and the point of the exercise is the
difference rather than the match. A deposit banked on Friday clears on Monday; a
card settlement arrives net of fees; a bank charge appears that nobody entered.
Reconciliation is the routine that turns "the balance looks wrong" into a list
of specific things to do.

Three rules shape it:

* **Matching is layered, strongest evidence first.** A reference that ties a
  statement line to a journal entry is worth more than an amount that happens to
  agree, and far more than a date that happens to be close. A wrong match is
  worse than no match — it marks money as accounted for that is not — so the
  weak rules only run when the strong ones have failed, and every match records
  which rule made it.

* **Nothing is posted automatically.** A bank charge the ledger has never seen
  is a real transaction, but inventing a journal entry for it without somebody
  looking is how a ledger acquires figures nobody can explain. Unmatched lines
  are *reported*, with the entry that would fix them proposed but not posted.

* **The reconciliation is a statement of position, not a stored balance.** It is
  recomputed from the ledger and the statement every time, so it cannot drift
  away from either.
"""
import csv
import io
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Account, JournalEntry, JournalLine
from . import ledger

# A statement line and a journal entry within this many days may be the same
# money. Longer and a fortnight of deposits all look like candidates.
DATE_WINDOW = 5
TOLERANCE = 0.01


class ReconError(ValueError):
    """Raised when a statement cannot be read or reconciled."""


def parse_statement(text: str) -> list[dict]:
    """Read a bank statement export.

    Banks disagree about column names and about whether money in and out are two
    columns or one signed one. Both shapes are accepted, because the alternative
    is asking a pharmacy to reformat a file their bank generated.
    """
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ReconError("The file has no header row.")

    def pick(row, *names, default=""):
        for name in names:
            for key, value in row.items():
                if key and key.strip().lower().replace(" ", "_") == name:
                    return value
        return default

    def number(value):
        text = str(value or "").strip().replace(",", "").replace("(", "-").replace(")", "")
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0

    lines = []
    for index, row in enumerate(reader, start=1):
        if not any((v or "").strip() for v in row.values()):
            continue
        credit = number(pick(row, "credit", "money_in", "deposit"))
        debit = number(pick(row, "debit", "money_out", "withdrawal"))
        amount = number(pick(row, "amount"))
        # One signed column, or two unsigned ones. Never both.
        movement = round(amount if amount else credit - debit, 2)
        raw_date = str(pick(row, "date", "transaction_date", "posted")).strip()
        parsed = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y"):
            try:
                parsed = datetime.strptime(raw_date, fmt).date()
                break
            except ValueError:
                continue
        lines.append({
            "line_number": index,
            "date": parsed,
            "description": str(pick(row, "description", "narrative", "details",
                                    "reference")).strip(),
            "reference": str(pick(row, "reference", "ref", "cheque_no")).strip(),
            "amount": movement,
        })
    if not lines:
        raise ReconError("The file contained no statement lines.")
    return lines


def _candidates(db: Session, account_code: str, since: date, until: date):
    return (db.query(JournalLine, JournalEntry)
            .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
            .filter(JournalLine.account_code == account_code,
                    JournalEntry.entry_date >= since - timedelta(days=DATE_WINDOW),
                    JournalEntry.entry_date <= until + timedelta(days=DATE_WINDOW),
                    JournalEntry.status == "posted")
            .all())


def reconcile(db: Session, *, account_code: str, lines: list[dict]) -> dict:
    """Match a statement against an account, and report what did not match."""
    account = db.query(Account).filter(Account.code == account_code).first()
    if not account:
        raise ReconError(f"No account {account_code}")
    dated = [l for l in lines if l["date"]]
    if not dated:
        raise ReconError("No statement line carried a date that could be read.")

    since, until = min(l["date"] for l in dated), max(l["date"] for l in dated)
    pool = _candidates(db, account_code, since, until)
    used: set[int] = set()

    matched, unmatched = [], []
    for line in lines:
        movement = line["amount"]
        hit = rule = None

        # 1. The reference ties them together. Unambiguous.
        if line["reference"]:
            for jl, je in pool:
                if jl.id in used:
                    continue
                if line["reference"].lower() in (je.reference or "").lower() \
                        or line["reference"].lower() in (jl.description or "").lower():
                    hit, rule = (jl, je), "reference"
                    break

        # 2. Same money, same direction, close enough in time.
        if not hit and line["date"]:
            for jl, je in pool:
                if jl.id in used:
                    continue
                ledger_move = round(jl.debit - jl.credit, 2)
                if abs(ledger_move - movement) <= TOLERANCE \
                        and abs((je.entry_date - line["date"]).days) <= DATE_WINDOW:
                    hit, rule = (jl, je), "amount_and_date"
                    break

        if hit:
            jl, je = hit
            used.add(jl.id)
            matched.append({
                "line_number": line["line_number"], "date": line["date"],
                "description": line["description"], "amount": movement,
                "matched_by": rule,
                "entry_id": je.id, "entry_reference": je.reference,
                "entry_date": je.entry_date,
            })
        else:
            unmatched.append({
                **line,
                # Proposed, never posted. A bank charge is a real transaction,
                # but a ledger that invents entries acquires figures nobody can
                # explain.
                "suggestion": ("A receipt the ledger has not seen, a deposit, "
                               "or a settlement that arrived net of fees."
                               if movement > 0 else
                               "A payment the ledger has not seen, a bank "
                               "charge, a debit order, or a supplier paid "
                               "outside the system."),
            })

    # Ledger movements the statement does not carry: cheques not presented,
    # deposits banked after the statement was cut.
    in_ledger_only = []
    for jl, je in pool:
        if jl.id in used:
            continue
        movement = round(jl.debit - jl.credit, 2)
        if abs(movement) < TOLERANCE:
            continue
        in_ledger_only.append({
            "entry_id": je.id, "entry_reference": je.reference,
            "entry_date": je.entry_date,
            "description": jl.description or je.description,
            "amount": movement,
        })

    statement_total = round(sum(l["amount"] for l in lines), 2)
    matched_total = round(sum(m["amount"] for m in matched), 2)
    ledger_balance = ledger.balance(db, account_code)
    difference = round(sum(u["amount"] for u in unmatched)
                       - sum(i["amount"] for i in in_ledger_only), 2)

    return {
        "account_code": account.code,
        "account_name": account.name,
        "from": since,
        "to": until,
        "statement_lines": len(lines),
        "statement_total": statement_total,
        "matched": matched,
        "matched_count": len(matched),
        "matched_total": matched_total,
        "on_statement_only": unmatched,
        "in_ledger_only": in_ledger_only,
        "ledger_balance": ledger_balance,
        "unreconciled_difference": difference,
        "reconciled": not unmatched and not in_ledger_only,
        "message": (
            "Every statement line ties to the ledger and nothing is outstanding."
            if not unmatched and not in_ledger_only else
            f"{len(unmatched)} statement line(s) the ledger has not seen and "
            f"{len(in_ledger_only)} ledger movement(s) the statement does not "
            f"carry. Net difference {difference:.2f}."),
    }
