"""Does a scan make somebody stand still?

A scan used to wait on the server before the line appeared. Locally that is
fifty milliseconds and invisible. Against the hosted API it is over two
seconds, measured, so a cashier scanning a basket of six stood there for
thirteen — waiting for an answer the browser already had, because the
catalogue is synced onto the till for exactly this.

WHAT THIS FILE IS FOR

The optimistic half of that bargain is easy and the correction is the hard
half, and the correction is the one that matters: a line put into a basket
before the server has spoken has to be able to come back out. A till that can
add but not take back is worse than a slow till, because the mistake leaves
with the customer.

So this checks the taking back, not the speed. Speed is a number anybody can
measure; a basket that quietly keeps the wrong medicine is not.

WHAT IT CHECKS

That the server still answers a scan correctly, since the local answer is only
ever provisional and the server is what settles it — an alternate barcode
carrying a pack size, a code the browser has never seen, and a code that is
nothing at all. The browser side is exercised in the till itself.
"""
from __future__ import annotations

import sys
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


def scan(code: str) -> dict:
    return client.post("/api/scan", headers=headers,
                       json={"code": code, "context": "pos"}).json()


print("\n  what the server settles a provisional line with\n")

with branch_scope.every_branch():
    product = (db.query(models.Product)
               .filter(models.Product.active).first())
    # An outer carton: one code, meaning a case. This is the fact the browser
    # cannot know, because alternate barcodes are not in the catalogue it
    # syncs — so a case reads as one locally and has to be settled to twelve.
    case_code = f"QA-CASE-{product.id}"
    existing = (db.query(models.ProductBarcode)
                .filter(models.ProductBarcode.code == case_code).first())
    if existing is None:
        db.add(models.ProductBarcode(product_id=product.id, code=case_code,
                                     pack_size=12, label="outer carton",
                                     source="manual", pharmacy_id=mine))
        db.commit()

carton = scan(case_code)
check(carton.get("found") is True, "an alternate barcode resolves",
      str(carton.get("message"))[:60])
check(carton.get("quantity_multiplier") == 12,
      "and carries the pack size the browser could not know",
      f"multiplier={carton.get('quantity_multiplier')}")
check(carton.get("product", {}).get("id") == product.id,
      "against the right product")

nothing = scan("QA-NO-SUCH-CODE-AT-ALL")
check(nothing.get("found") is False,
      "a code that is nothing at all is still a miss")
check(bool(nothing.get("message")),
      "and says so, so a provisional line can be taken back out",
      str(nothing.get("message"))[:60])

# The branch stock figure is the other thing only the server knows.
if carton.get("found"):
    check("quantity_on_hand" in (carton.get("product") or {}),
          "and the stock at this branch comes back to settle the line with")

with branch_scope.every_branch(), unscoped():
    row = (db.query(models.ProductBarcode)
           .filter(models.ProductBarcode.code == case_code).first())
    if row is not None:
        db.delete(row)
        db.commit()

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\na till that can add a line but not take it back is worse than a "
          "slow till: the mistake leaves with the customer.")
sys.exit(1 if failed else 0)
