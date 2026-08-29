"""The bank statement against the ledger, and the list of things to chase.

The service was written carefully and had no screen. Its own rules say the
point is the difference rather than the match, that nothing is posted
automatically, and that a wrong match is worse than no match — it marks money
as accounted for that is not. None of that reached anybody, because the only
way to run a reconciliation was to POST a CSV by hand.

What is asserted here is what the screen now shows and therefore has to be
true: that a line tied by reference is reported as tied by reference and not by
a coincidence of amount, that money the bank knows about and the ledger does
not is surfaced rather than silently absorbed, that a cheque not yet presented
shows on the other side, and that nothing is written to the ledger by running
it. That last one matters most: a reconciliation that quietly posts is a
reconciliation nobody can safely run twice.
"""
import os
import pathlib
import sys
from datetime import date

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"bank-recon.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base, engine, SessionLocal    # noqa: E402
from app import models                                 # noqa: E402
from app.services import bank_recon, ledger            # noqa: E402

Base.metadata.create_all(engine)
db = SessionLocal()
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


BANK = "1010"
ledger.ensure_chart(db)
db.commit()

user = models.User(username="book", full_name="Bookkeeper", role="admin",
                   password_hash="x")
db.add(user)
db.commit()


def post(day: int, description: str, reference: str, into_bank: float):
    """One movement through the bank account.

    The reference rides on the line description, which is where the matcher
    looks for it and where a real posting puts it — a deposit slip number, a
    cheque number.
    """
    description = f"{description} {reference}"
    other = "4000" if into_bank > 0 else "5000"
    lines = [
        ledger.Line(account_code=BANK,
                    debit=into_bank if into_bank > 0 else 0.0,
                    credit=-into_bank if into_bank < 0 else 0.0,
                    description=description),
        ledger.Line(account_code=other,
                    credit=into_bank if into_bank > 0 else 0.0,
                    debit=-into_bank if into_bank < 0 else 0.0,
                    description=description),
    ]
    return ledger.post(db, entry_date=date(2026, 7, day), description=description,
                       lines=lines, source="test", source_id=day,
                       user_id=user.id)


takings = post(3, "Friday takings banked", "DEP-4471", 1200.00)
cheque = post(4, "Cheque to Zimpharm", "CHQ-0912", -640.00)
db.commit()

# What the bank sent back. The deposit carries the reference; the bank charge
# is something the ledger has never seen; the cheque has not been presented.
STATEMENT = """date,description,reference,amount
2026-07-03,CASH DEPOSIT BRANCH 12,DEP-4471,1200.00
2026-07-06,MONTHLY SERVICE CHARGE,,-14.50
2026-07-08,POS SETTLEMENT NET OF FEES,,487.35
"""

print("reading the statement")
lines = bank_recon.parse_statement(STATEMENT)
check(len(lines) == 3, f"three lines read ({len(lines)})")

print("\nreconciling")
r = bank_recon.reconcile(db, account_code=BANK, lines=lines)
check(r["statement_lines"] == 3, "three statement lines")
check(r["matched_count"] == 1, f"one of them ties up ({r['matched_count']})")
check(r["matched"][0]["matched_by"] == "reference",
      f"and it tied by reference, not by a coincidence of amount "
      f"({r['matched'][0]['matched_by']})")
# The matched row carries the *statement* line's wording and the ledger
# entry's id, which is what the screen needs: the bank calls it "CASH DEPOSIT
# BRANCH 12" and the ledger calls it the Friday takings, and a person reading
# the reconciliation has to see both names to believe the match.
check(r["matched"][0]["entry_id"] == takings.id,
      "against the deposit entry")
check(r["matched"][0]["description"] == "CASH DEPOSIT BRANCH 12",
      "shown under the name the bank gave it")

print("\nwhat the bank knows and the ledger does not")
only_bank = {l["description"] for l in r["on_statement_only"]}
check("MONTHLY SERVICE CHARGE" in only_bank,
      "the bank charge is surfaced — nobody entered it, and it is real money")
check("POS SETTLEMENT NET OF FEES" in only_bank,
      "so is the card settlement")
check(all(l["suggestion"] for l in r["on_statement_only"]),
      "each carries a suggestion of what it probably is")
check(any(l["amount"] < 0 for l in r["on_statement_only"]),
      "and the direction is kept — a charge is not a receipt")

print("\nwhat the ledger knows and the bank does not")
only_ledger = " ".join(l["description"] for l in r["in_ledger_only"])
check("CHQ-0912" in only_ledger,
      "the cheque has not been presented, and says so")
check("DEP-4471" not in only_ledger,
      "the deposit does not appear on both sides")

print("\nthe figure somebody acts on")
check(not r["reconciled"], "it does not claim to be reconciled")
check(abs(r["unreconciled_difference"]) > 0.005,
      f"and reports a difference of {r['unreconciled_difference']}")

print("\nnothing was posted")
count_before = db.query(models.JournalEntry).count()
bank_recon.reconcile(db, account_code=BANK, lines=lines)
check(db.query(models.JournalEntry).count() == count_before,
      "running it again writes nothing — a reconciliation that posts is one "
      "nobody can safely run twice")

print("\na statement it cannot read")
try:
    bank_recon.parse_statement("this is not a csv")
    check(False, "refused")
except bank_recon.ReconError as exc:
    check(True, f"refused, and says why: {exc}")

print()
if failures:
    print(f"{len(failures)} failed")
    sys.exit(1)
print("the reconciliation says what it knows and no more")
