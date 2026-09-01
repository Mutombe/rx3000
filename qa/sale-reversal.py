"""A sale can be taken back: the right way for how it was filed.

Until now nothing could reverse a sale at all. Both halves existed on the
server and neither had a screen, so a cashier who rang up the wrong item had
no move: the stock stayed sold, the claim stayed raised, and the loyalty points
stayed earned. The one message anybody could have reached said

    "This sale has been fiscalised and cannot be voided.
     Issue a credit note instead (POST /api/fiscal/credit-note/{sale_id})"

which is a sentence written for somebody holding curl, not for somebody holding
a customer's receipt.

Which of the two is legal is not the cashier's judgement. A receipt filed with
ZIMRA can never be withdrawn — it stands, is still reported, and a credit note
is filed against it. One never filed is simply voided. This asserts that the
server keeps that distinction, that both put the stock back, and that neither
can be run twice.
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"sale-reversal.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient              # noqa: E402
from app.database import Base, engine, SessionLocal, get_db   # noqa: E402
from app import models                                 # noqa: E402
from app.main import app                               # noqa: E402
from app.auth import get_current_user                  # noqa: E402
from app.services import fiscal, stepup                # noqa: E402
from app import helpers                                # noqa: E402
from app.auth import hash_password                     # noqa: E402

Base.metadata.create_all(engine)
db = SessionLocal()
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


# A real password, because reversing a sale is behind step-up and a test that
# stops at the 428 is testing the guard rather than the thing it guards.
user = models.User(username="till", full_name="Till", role="cashier",
                   password_hash=hash_password("correct horse"))
# Reversing a sale forbids self-approval, which is the right rule: the person
# who rang it up is the person with a reason to make it disappear. So the
# manager walks over and types their own password on the cashier's till.
manager = models.User(username="manager", full_name="Rutendo", role="admin",
                      password_hash=hash_password("supervisor pass"))
product = models.Product(name="Paracetamol 500mg", unit_price=2.0,
                         quantity_on_hand=100)
db.add_all([user, manager, product])
db.commit()

batch = models.StockBatch(product_id=product.id, batch_number="B1",
                          quantity_received=100, quantity_remaining=100,
                          unit_cost=1.0)
db.add(batch)
db.commit()


def make_sale(number: str):
    sale = models.Sale(sale_number=number, total=20.0, vat_amount=2.6,
                       subtotal=17.4, payment_method="cash", status="paid",
                       amount_tendered=20.0, cashier_id=user.id)
    db.add(sale)
    db.flush()
    db.add(models.SaleItem(sale_id=sale.id, product_id=product.id,
                           description=product.name, quantity=10,
                           unit_price=2.0, line_total=20.0, vat_rate=0.15))
    db.commit()
    return sale


app.dependency_overrides[get_current_user] = lambda: user
app.dependency_overrides[get_db] = lambda: db
client = TestClient(app)


def authority(context: str) -> dict:
    """A single-use grant, minted the way the dialog mints one."""
    grant = stepup.request(db, action_key="sale.void", actor=user,
                           approver_username="manager",
                           password="supervisor pass", context=context)
    return {"X-Step-Up": grant.token}

print("a sale that was never filed with ZIMRA")
plain = make_sale("S-0001")
before = product.quantity_on_hand
print("  (the cashier cannot approve their own reversal)")
try:
    stepup.request(db, action_key="sale.void", actor=user,
                   password="correct horse", context="self")
    check(False, "self-approval refused")
except stepup.StepUpError as exc:
    check(True, f"refused: {exc}")
check(client.post(f"/api/pos/sales/{plain.id}/void").status_code == 428,
      "without authority it is refused with 428, not 401 — a cashier who tries "
      "to void a sale must not be logged out for it")
r = client.post(f"/api/pos/sales/{plain.id}/void", headers=authority("void S-0001"))
check(r.status_code == 200, f"with authority it goes through ({r.status_code})")
db.refresh(plain)
db.refresh(product)
check(plain.status == "void", "it is voided")
check(product.quantity_on_hand == before + 10,
      f"the ten went back on the shelf ({before} -> {product.quantity_on_hand})")

print("\na sale that was filed")
filed = make_sale("S-0002")
receipt = fiscal.fiscalise(db, filed)
db.commit()
check(receipt is not None, "it has a fiscal receipt")
check(fiscal.is_locked(db, filed),
      f"and the server locks it (status {receipt.status})")

# A receipt still queued has not reached ZIMRA, so the server does not lock the
# sale. The screen is deliberately stricter and offers the credit note as soon
# as a receipt exists at all: a queued receipt is one that *will* be filed, and
# voiding the sale under it would file a receipt for a sale that no longer
# exists.
receipt.status = "queued"
db.commit()
check(not fiscal.is_locked(db, filed), "a queued receipt does not lock it")
receipt.status = "accepted"
db.commit()

r = client.post(f"/api/pos/sales/{filed.id}/void", headers=authority("void S-0002"))
check(r.status_code == 400,
      f"voiding it is refused ({r.status_code}) — a filed receipt cannot be "
      f"withdrawn")
check("credit note" in r.json().get("detail", "").lower(),
      "and the refusal names the lawful alternative")

print("\nthe receipt lookup the sale screen now uses")
rows = client.get(f"/api/fiscal/receipts?sale_id={filed.id}").json()
check(len(rows) == 1, f"one receipt comes back for that sale ({len(rows)})")
check(client.get(f"/api/fiscal/receipts?sale_id={plain.id}").json() == [],
      "and none for the sale that was never filed, which is exactly how the "
      "screen decides which button to offer")

print("\ncrediting the filed sale")
before = product.quantity_on_hand
r = client.post(f"/api/fiscal/credit-note/{filed.id}",
                headers=authority("credit S-0002"))
check(r.status_code == 200, f"the credit note is filed ({r.status_code})")
db.refresh(filed)
db.refresh(product)
check(filed.status == "credited",
      "the sale reads 'credited', not 'void' — reports have to tell them apart")
check(product.quantity_on_hand == before + 10, "the stock came back")

both = client.get(f"/api/fiscal/receipts?sale_id={filed.id}").json()
check(len(both) == 2, "both documents stay on the record")
check(any(x["receipt_type"] == "credit_note" for x in both),
      "one of them is the credit note")
check(any(x["reverses_receipt_id"] == receipt.id for x in both),
      "and it points at what it reverses")

print("\ncrediting it a second time")
r = client.post(f"/api/fiscal/credit-note/{filed.id}",
                headers=authority("credit S-0002 again"))
check(r.status_code == 400,
      f"refused ({r.status_code}) — a sale credited twice is a refund given twice")

print("\nfiltering the register to credit notes")
paged = client.get("/api/fiscal/receipts/paged?receipt_type=credit_note").json()
check(paged["total"] == 1, f"one credit note in the register ({paged['total']})")

print()
if failures:
    print(f"{len(failures)} failed")
    sys.exit(1)
print("a sale can be taken back, the right way round")
