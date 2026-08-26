"""Prove the payables cycle arrives at the right creditor balance.

The question this answers is not "does it run" but "does trade creditors end up
saying what the pharmacy actually owes". Every defect this module was written to
fix is a balance that was wrong while every individual entry looked correct, so
the check is on the balance, not on the calls.
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"payables-check.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from datetime import date, timedelta            # noqa: E402
from app.database import Base, engine, SessionLocal   # noqa: E402
from app import models                          # noqa: E402
from app.services import ledger, payables, posting   # noqa: E402

Base.metadata.create_all(engine)
db = SessionLocal()
ledger.ensure_chart(db)

failures = []


def check(label, got, want, tol=0.005):
    ok = abs(got - want) <= tol
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got:.2f} (expected {want:.2f})")
    if not ok:
        failures.append(label)


def creditors():
    # `balance` reports each account in the direction its type runs, so a
    # liability is already positive here. No negation.
    return round(ledger.balance(db, "2000"), 2)


supplier = models.Supplier(name="Zimpharm Wholesalers", phone="+263 242 771 900")
product = models.Product(name="Amoxicillin", strength="500mg", unit_price=3.50, cost_price=4.20)
db.add_all([supplier, product])
db.commit()

# An order for 100 at 4.20, of which 100 arrive. 420.00 gross.
order = models.PurchaseOrder(order_number="PO-9001", supplier_id=supplier.id,
                             status="received")
db.add(order)
db.commit()
db.add(models.PurchaseOrderItem(order_id=order.id, product_id=product.id,
                                quantity_ordered=100, quantity_received=100,
                                unit_cost=4.20))
db.commit()
db.refresh(order)

print("\n-- goods received --")
posting.post_stock_receipt(db, order)
check("creditors after receipt", creditors(), 420.00)

# The wholesaler bills 4.85, not the 4.20 on the order. 485.00.
print("\n-- invoice arrives at a higher price --")
invoice = models.SupplierInvoice(
    invoice_number="ZW-44821", supplier_id=supplier.id, order_id=order.id,
    invoice_date=date.today(), due_date=date.today() + timedelta(days=30),
    total=485.00)
db.add(invoice)
db.commit()
db.add(models.SupplierInvoiceItem(invoice_id=invoice.id, product_id=product.id,
                                  quantity=100, unit_cost=4.85, line_total=485.00))
db.commit()
db.refresh(invoice)

result = payables.match(db, invoice)
print(f"     depth={result['depth']} matched={result['matched']}")
for problem in result["problems"]:
    print(f"     · {problem}")
check("variance reported", result["variance"], 65.00)
if result["matched"]:
    failures.append("a 15% price rise passed the match")
    print("FAIL a 15% price rise passed the match")
else:
    print("ok   the price rise was flagged")

print("\n-- approve: the difference posts, not a second liability --")
posted = payables.post_invoice(db, invoice)
print(f"     {posted}")
check("creditors after approval", creditors(), 485.00)
if posted.get("kind") != "variance":
    failures.append("posted the whole invoice instead of the difference")

# Approving twice must not move anything. This is the trap the provision hit.
payables.post_invoice(db, invoice)
check("creditors after approving twice", creditors(), 485.00)

print("\n-- ageing --")
aged = payables.ageing(db)
check("owed on the ageing", aged["total"], 485.00)
check("ageing agrees with the control account", aged["difference"], 0.00)
print(f"     band: {aged['suppliers'][0]['invoices'][0]['band']}")

print("\n-- payment --")
paid = payables.record_payment(
    db, supplier_id=supplier.id, amount=485.00, method="bank",
    reference="FCB-TT-7781",
    allocations=[{"invoice_id": invoice.id, "amount": 485.00}])
print(f"     {paid['reference']} allocated {paid['allocated']:.2f}")
check("creditors after payment", creditors(), 0.00)

db.refresh(invoice)
print(f"{'ok  ' if invoice.status == 'paid' else 'FAIL'} invoice status: {invoice.status}")
if invoice.status != "paid":
    failures.append("invoice not marked paid")

aged = payables.ageing(db)
check("nothing left owing", aged["total"], 0.00)

print("\n-- an invoice with no order behind it posts in full --")
loose = models.SupplierInvoice(invoice_number="ZW-44999", supplier_id=supplier.id,
                               invoice_date=date.today(), total=120.00)
db.add(loose)
db.commit()
db.refresh(loose)
loose_match = payables.match(db, loose)
print(f"     depth={loose_match['depth']} · {loose_match['problems'][0][:60]}…")
payables.post_invoice(db, loose)
check("creditors after an unmatched invoice", creditors(), 120.00)

print("\n-- short delivery: billed 100, only 80 arrived --")
order2 = models.PurchaseOrder(order_number="PO-9002", supplier_id=supplier.id,
                              status="received")
db.add(order2)
db.commit()
db.add(models.PurchaseOrderItem(order_id=order2.id, product_id=product.id,
                                quantity_ordered=100, quantity_received=80,
                                unit_cost=4.20))
db.commit()
db.refresh(order2)
short = models.SupplierInvoice(invoice_number="ZW-45010", supplier_id=supplier.id,
                               order_id=order2.id, invoice_date=date.today(),
                               total=420.00)
db.add(short)
db.commit()
db.add(models.SupplierInvoiceItem(invoice_id=short.id, product_id=product.id,
                                  quantity=100, unit_cost=4.20, line_total=420.00))
db.commit()
db.refresh(short)
short_match = payables.match(db, short)
caught = any("received" in p and "billed for" in p.lower()
             for p in short_match["problems"])
print(f"{'ok  ' if caught else 'FAIL'} short delivery flagged")
for problem in short_match["problems"]:
    print(f"     · {problem}")
if not caught:
    failures.append("short delivery not flagged")

print("\n-- the ledger still balances --")
tb = ledger.trial_balance(db)
diff = round(tb.get("difference", 0.0), 2)
check("trial balance difference", diff, 0.00)

print()
if failures:
    print(f"{len(failures)} FAILURE(S): " + "; ".join(failures))
    sys.exit(1)
print("payables cycle is sound")
