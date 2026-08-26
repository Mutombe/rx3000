"""Prove the new seeder stages produce a ledger that balances, and resume.

Two questions, both of which have been answered wrongly here before:

  Does it produce anything?  Purchase orders were made only for products at or
  below their reorder level, which after a seed is none of them, so the whole
  supply chain came out empty and nothing said so.

  Does running it twice double it?  The dispensary once wiped and rebuilt
  itself on every retry. A seeder that is not safe to re-run cannot finish
  against a database that occasionally drops the connection.
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"seed-stages.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text                       # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, realseed                  # noqa: E402
from app.services import ledger, payables         # noqa: E402

Base.metadata.create_all(engine)

failures = []
DAYS = 14


def counts(db):
    out = {}
    for table in ("sales", "prescriptions", "purchase_orders",
                  "purchase_order_items", "supplier_invoices",
                  "supplier_invoice_items", "supplier_payments",
                  "journal_entries", "journal_lines", "claims"):
        try:
            out[table] = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        except Exception:
            db.rollback()
            out[table] = None
    return out


print(f"seeding {DAYS} days…\n")
realseed.run(wipe_all=True, days=DAYS)

db = SessionLocal()
first = counts(db)
print("\n-- what it produced --")
for table, n in first.items():
    print(f"   {table:26} {n}")

for table in ("purchase_orders", "supplier_invoices", "journal_entries"):
    if not first.get(table):
        failures.append(f"{table} is empty")
        print(f"FAIL {table} is empty")

print("\n-- the ledger balances --")
tb = ledger.trial_balance(db)
diff = round(tb.get("difference", 0.0), 2)
print(f"{'ok  ' if abs(diff) < 0.005 else 'FAIL'} trial balance difference: {diff:.2f}")
if abs(diff) >= 0.005:
    failures.append("trial balance does not balance")

print("\n-- the books say something a pharmacy would recognise --")
for code, name, want in (("1110", "medical scheme debtors", "positive"),
                         ("1010", "bank", "not overdrawn"),
                         ("1000", "cash on hand", "positive"),
                         ("2000", "trade creditors", "positive")):
    got = ledger.balance(db, code)
    ok = got > 0.005 if want == "positive" else got >= -0.005
    print(f"{'ok  ' if ok else 'FAIL'} {name:24} {got:>12.2f}  ({want})")
    if not ok:
        failures.append(f"{name} is {got:.2f}, expected {want}")

print("\n-- creditors agree with the invoices behind them --")
aged = payables.ageing(db)
print(f"     owed on the invoices : {aged['total']:.2f}")
print(f"     the control account  : {aged['control_balance']:.2f}")
print(f"     difference           : {aged['difference']:.2f}")
# They are expected to differ here: the receipt raises the creditor and only an
# *approved* invoice moves it to what was billed, and the seeder deliberately
# leaves some unapproved. What must hold is that the control is not negative
# and not wildly adrift.
if aged["control_balance"] < -0.005:
    failures.append("the creditors control account is negative")
    print("FAIL the creditors control account is negative")

print("\n-- the match finds the invoices that do not agree --")
bad = 0
for invoice in db.query(models.SupplierInvoice).all():
    if not payables.match(db, invoice)["matched"]:
        bad += 1
print(f"     {bad} of {first['supplier_invoices']} invoices do not match cleanly")
if bad == 0:
    failures.append("no invoice disagreed, so the match proves nothing")
    print("FAIL every invoice agreed; the match has nothing to demonstrate")
if bad == first["supplier_invoices"]:
    failures.append("every invoice disagreed, which is not a pharmacy")
    print("FAIL every single invoice disagreed")

db.close()

print("\n-- running it again must not double anything --")
realseed.run(wipe_all=False, days=DAYS)
db = SessionLocal()
second = counts(db)
for table, n in second.items():
    was = first.get(table)
    same = was == n
    print(f"{'ok  ' if same else 'FAIL'} {table:26} {was} -> {n}")
    if not same:
        failures.append(f"{table} changed on a second run ({was} -> {n})")

tb = ledger.trial_balance(db)
diff = round(tb.get("difference", 0.0), 2)
print(f"\n{'ok  ' if abs(diff) < 0.005 else 'FAIL'} still balances: {diff:.2f}")
if abs(diff) >= 0.005:
    failures.append("trial balance broke on the second run")

print()
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(f"  · {f}")
    sys.exit(1)
print("the new stages produce data, balance, and resume")
