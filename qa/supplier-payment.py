"""Paying a wholesaler settles the invoice, and the ledger agrees.

The creditor side was complete except for this. Goods were received, the
invoice was matched line by line, approved, aged into a bucket and turned red —
and there was no screen that could pay it. Trade creditors could only ever
grow, so the ageing report was a list of debts the pharmacy had in many cases
already settled from its bank app.

What is asserted here is the part a screen cannot be trusted to get right on
its own: that the allocation actually reduces the invoice, that the double
entry lands (Dr creditors, Cr bank), that paying more than is owed is refused
rather than quietly booked, and that an unallocated payment is still recorded —
because a pharmacy paying a round figure on account is doing something ordinary
and refusing it is how payments end up existing only on the bank statement.
"""
import os
import pathlib
import sys
from datetime import date

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"supplier-payment.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base, engine, SessionLocal    # noqa: E402
from app import models                                 # noqa: E402
from app.services import payables, ledger              # noqa: E402

Base.metadata.create_all(engine)
db = SessionLocal()
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


user = models.User(username="owner", full_name="Owner", role="admin",
                   password_hash="x")
supplier = models.Supplier(name="Zimpharm Wholesalers")
db.add_all([user, supplier])
db.commit()

# Two invoices, the older one larger, so oldest-first has something to prove.
older = models.SupplierInvoice(
    supplier_id=supplier.id, invoice_number="ZP-1001",
    invoice_date=date(2026, 6, 1), due_date=date(2026, 7, 1),
    total=800.0, status="approved")
newer = models.SupplierInvoice(
    supplier_id=supplier.id, invoice_number="ZP-1042",
    invoice_date=date(2026, 7, 10), due_date=date(2026, 8, 10),
    total=300.0, status="approved")
db.add_all([older, newer])
db.commit()

print("paying 900 against an 800 and a 300, oldest first")
result = payables.record_payment(
    db, supplier_id=supplier.id, amount=900.0, method="bank",
    reference="CBZ 88213", user_id=user.id,
    allocations=[{"invoice_id": older.id, "amount": 800.0},
                 {"invoice_id": newer.id, "amount": 100.0}])
db.commit()

advice = payables.remittance(db, result["payment_id"])
check(advice["amount"] == 900.0, "the payment is 900.00")
check(advice["allocated"] == 900.0, "all 900 is allocated")
check(advice["on_account"] == 0.0, "nothing is left on account")
check({l["invoice_number"] for l in advice["lines"]} == {"ZP-1001", "ZP-1042"},
      "the advice names both invoices, so the supplier can find the money")

print("\nwhat the invoices now show")
aged = payables.ageing(db)
found = {i["invoice_number"]: i
         for s in aged["suppliers"] for i in s["invoices"]}
check("ZP-1001" not in found, "the settled 800 invoice has left the ageing")
check(round(found.get("ZP-1042", {}).get("outstanding", -1), 2) == 200.0,
      f"200.00 still owing on the part-paid one "
      f"({found.get('ZP-1042', {}).get('outstanding')})")

print("\nthe double entry")
entry = (db.query(models.JournalEntry)
         .filter(models.JournalEntry.source == "supplier_payment").first())
check(entry is not None, "a journal was posted")
if entry:
    debits = {l.account_code: l.debit for l in entry.lines if l.debit}
    credits = {l.account_code: l.credit for l in entry.lines if l.credit}
    check(debits.get(payables.CREDITORS) == 900.0,
          "creditors debited 900 — what is no longer owed")
    check(credits.get(payables.BANK) == 900.0,
          "bank credited 900 — what left the account")

print("\npaying on account, with no split worked out yet")
loose = payables.record_payment(db, supplier_id=supplier.id, amount=250.0,
                                method="bank", reference="round figure",
                                user_id=user.id)
db.commit()
loose_advice = payables.remittance(db, loose["payment_id"])
check(loose_advice["on_account"] == 250.0,
      "it is recorded in full and sits on account")

print("\nallocating more than is being paid")
try:
    payables.record_payment(db, supplier_id=supplier.id, amount=50.0,
                            user_id=user.id,
                            allocations=[{"invoice_id": newer.id, "amount": 500.0}])
    check(False, "refused")
except ValueError as exc:
    check("more than" in str(exc), f"refused, and says why: {exc}")

print("\nallocating to another supplier's invoice")
other = models.Supplier(name="Somebody Else")
db.add(other)
db.commit()
try:
    payables.record_payment(db, supplier_id=other.id, amount=100.0,
                            user_id=user.id,
                            allocations=[{"invoice_id": newer.id, "amount": 100.0}])
    check(False, "refused")
except ValueError as exc:
    check("another supplier" in str(exc), f"refused: {exc}")

print()
if failures:
    print(f"{len(failures)} failed")
    sys.exit(1)
print("supplier payments settle what they say they settle")
