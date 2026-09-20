"""Can a delivery be put against the invoice that bills for it?

An order is what was asked for, a delivery is what arrived, and an invoice is
what is charged. The three are separate records because they are separate
events, arriving days or weeks apart, and the whole value of keeping them
apart is being able to hold them up against each other afterwards.

The delivery and the invoice could not be held up against each other. The
column existed on the goods receipt, a service function existed to set it, and
nothing anywhere called that function — so "goods received with no invoice
number against them", the figure the Deliveries screen leads on, could only
ever go up.

WHAT IS CHECKED

That a delivery can be put on a bill and taken off again, because somebody
will match the wrong one and the way back has to exist; that a bill from a
different supplier is refused, since a delivery and its bill come from the
same wholesaler; that one bill cannot be claimed by two deliveries; and that
the gap between what arrived and what was charged is reported, because that
gap is the entire reason anybody looks.
"""
from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient          # noqa: E402

from app.main import app                           # noqa: E402
from app.database import SessionLocal              # noqa: E402
from app.tenancy import unscoped, set_current_pharmacy   # noqa: E402
from app import auth, branch_scope, models         # noqa: E402

passed = 0
failed = 0


def check(condition: bool, message: str, extra: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {message}")
    else:
        failed += 1
        print(f"  FAIL {message}{('   ' + extra) if extra else ''}")


client = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:5].upper()

with unscoped():
    me = (db.query(models.User)
          .filter(models.User.is_demo.is_(False), models.User.active,
                  models.User.pharmacy_id.isnot(None)).first())
    if me is None:
        print("  ..   no account on this database")
        sys.exit(0)
    headers = {"Authorization": f"Bearer {auth.create_token(me, db)}"}
    mine = me.pharmacy_id

set_current_pharmacy(mine)

with branch_scope.every_branch():
    suppliers = db.query(models.Supplier).limit(2).all()
    if len(suppliers) < 2:
        print("  ..   need two suppliers on this database")
        sys.exit(0)
    ours, other = suppliers[0], suppliers[1]

    receipt = models.GoodsReceipt(
        grv_number=f"QAG{tag}", supplier_id=ours.id, status="received",
        delivery_note=f"DN-{tag}", goods_total=480.0, pharmacy_id=mine)
    db.add(receipt)

    # A bill that agrees, one that does not, and one from the wrong supplier.
    agrees = models.SupplierInvoice(
        invoice_number=f"INV-{tag}-A", supplier_id=ours.id,
        invoice_date=date.today(), total=480.0, pharmacy_id=mine)
    differs = models.SupplierInvoice(
        invoice_number=f"INV-{tag}-B", supplier_id=ours.id,
        invoice_date=date.today(), total=531.0, pharmacy_id=mine)
    theirs = models.SupplierInvoice(
        invoice_number=f"INV-{tag}-C", supplier_id=other.id,
        invoice_date=date.today(), total=480.0, pharmacy_id=mine)
    db.add_all([agrees, differs, theirs])
    db.commit()
    rid, a_id, b_id, c_id = receipt.id, agrees.id, differs.id, theirs.id

print("\n  the bills this delivery could be on\n")

offered = client.get(f"/api/goods-receipts/{rid}/invoice-candidates",
                     headers=headers).json()
ids = [inv["id"] for inv in offered.get("invoices", [])]
check(a_id in ids and b_id in ids, "both of this supplier's bills are offered")
check(c_id not in ids, "and another supplier's is not",
      "a delivery and its bill come from the same wholesaler")
if ids:
    first = offered["invoices"][0]
    check(first["id"] == a_id,
          "the one that agrees with the goods is offered first",
          f"first was {first['invoice_number']}")
    check(abs(first["differs_by"]) < 0.01,
          "and is reported as agreeing")

print("\n  putting it on one\n")

put = client.post(f"/api/goods-receipts/{rid}/match", headers=headers,
                  json={"invoice_id": b_id})
check(put.status_code == 200, "a delivery can be put on a bill",
      f"status {put.status_code}")
check(abs((put.json().get("differs_by") or 0) - 51.0) < 0.01,
      "and the gap between goods and bill is reported",
      str(put.json().get("differs_by")))
check("worth querying" in (put.json().get("message") or ""),
      "in words that say what to do about it",
      (put.json().get("message") or "")[:70])

print("\n  what it refuses\n")

wrong = client.post(f"/api/goods-receipts/{rid}/match", headers=headers,
                    json={"invoice_id": c_id})
check(wrong.status_code == 400, "another supplier's bill is refused",
      f"status {wrong.status_code}")

with branch_scope.every_branch():
    second = models.GoodsReceipt(
        grv_number=f"QAH{tag}", supplier_id=ours.id, status="received",
        goods_total=100.0, pharmacy_id=mine)
    db.add(second)
    db.commit()
    sid = second.id

taken = client.post(f"/api/goods-receipts/{sid}/match", headers=headers,
                    json={"invoice_id": b_id})
check(taken.status_code == 409, "a bill already on one delivery is refused",
      f"status {taken.status_code}")
check("already against" in str(taken.json().get("detail", "")),
      "and says which delivery has it",
      str(taken.json().get("detail"))[:70])

print("\n  and taking it back off\n")

off = client.post(f"/api/goods-receipts/{rid}/match", headers=headers,
                  json={"invoice_id": None})
check(off.status_code == 200, "a delivery can be taken off a bill",
      "somebody will match the wrong one")
freed = client.post(f"/api/goods-receipts/{sid}/match", headers=headers,
                    json={"invoice_id": b_id})
check(freed.status_code == 200,
      "and the bill is then free for the delivery it really belongs to")

with branch_scope.every_branch(), unscoped():
    for row in db.query(models.GoodsReceipt).filter(
            models.GoodsReceipt.grv_number.in_([f"QAG{tag}", f"QAH{tag}"])).all():
        row.invoice_id = None
        db.delete(row)
    for row in db.query(models.SupplierInvoice).filter(
            models.SupplierInvoice.invoice_number.like(f"INV-{tag}-%")).all():
        db.delete(row)
    db.commit()

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\nkeeping the order, the delivery and the bill apart is only worth "
          "anything if they can be held up against each other.")
sys.exit(1 if failed else 0)
