"""A till sells what a till may sell, and refuses the rest.

WHAT WAS WRONG

`pos_router.py` did not import `schedule_policy` at all. The only guards in
`create_sale` were: the basket is empty, the product does not exist, the product
is retired. Nothing anywhere in the sale path read the schedule.

The till searched `/api/products`, the whole catalogue, rather than the counter
range. So a cashier could type "pethidine", find it, basket it and sell it, with
no prescription, no prescriber, no pharmacist and no refusal at any layer. Then
`record_register_entry` wrote it into the controlled register with none of that
attached, so the register an inspector reads carried a supply nobody could
account for, filed by the system itself.

`requires_prescription` existed on every policy the whole time. It was read in
three places and not one of them refused anything: a quote payload, an advisory
scan warning, and a printed wall chart.

WHAT IS CHECKED

  the counter range sells      an ordinary counter medicine still goes through,
                               because a guard that stops the shop trading is a
                               guard somebody removes.

  a script does not            a prescription-route medicine is refused, and the
                               refusal names the code this country uses and says
                               where to dispense it instead.

  a controlled one does not    the same, for the schedules that carry a register
                               entry. This is the one that was writing false
                               register rows.

  the search does not offer    `counter_only` narrows the picker to the counter
                               range, so nobody is shown a medicine they will
                               then be refused. Refusing at the sale is the
                               rule; this is the courtesy.

  the dispensary still pays    THE REGRESSION THAT WOULD ACTUALLY HURT. A
                               script dispensed and sent to the front till is
                               settled through `pay_sale`, a different endpoint
                               that takes money against a sale the dispensary
                               already made. If the new refusal reached that,
                               a pharmacy could dispense a controlled medicine
                               and then be unable to take payment for it, which
                               is worse than the hole being closed.

    python qa/a-till-cannot-sell-a-script.py
"""
import os
import pathlib
import sys
from datetime import date, timedelta

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"till-scripts.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from fastapi import HTTPException                            # noqa: E402
from app.database import Base, engine, SessionLocal          # noqa: E402
from app import branch_scope, models, schedule_policy, tenancy   # noqa: E402
from app.routers import pos_router, stock_router             # noqa: E402

Base.metadata.create_all(engine)
FAR_OFF = date.today() + timedelta(days=720)
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


def session():
    db = SessionLocal()
    tenancy.stamp(db)
    branch_scope.stamp(db)
    return db


# One of each kind of medicine, named by what the jurisdiction pack says about
# it rather than by a schedule number this guard has decided for itself.
COUNTER = next(s for s in range(0, 9)
               if schedule_policy.policy_for(s).route == "otc")
SCRIPT = next(s for s in range(0, 9)
              if schedule_policy.policy_for(s).route == "prescription")
CONTROLLED = next(s for s in range(0, 9)
                  if schedule_policy.policy_for(s).route == "controlled")

with tenancy.unscoped(), branch_scope.every_branch():
    db = session()
    group = models.Pharmacy(name="Zvandiri Pharmacies")
    db.add(group)
    db.commit()
    gid = group.id

    branch = models.Branch(name="Avondale", code="AVN", pharmacy_id=gid)
    db.add(branch)
    db.commit()

    made = {}
    for key, schedule in [("counter", COUNTER), ("script", SCRIPT),
                          ("controlled", CONTROLLED), ("unclassified", None)]:
        product = models.Product(
            name=f"Test {key}", schedule=schedule, active=True,
            unit_price=10.0, cost_price=4.0, units_per_pack=1,
            quantity_on_hand=100, pharmacy_id=gid)
        db.add(product)
        db.commit()
        made[key] = product.id
        db.add(models.StockBatch(
            product_id=product.id, branch_id=branch.id, batch_number=f"B-{key}",
            quantity_remaining=100, expiry_date=FAR_OFF, pharmacy_id=gid))
    cashier = models.User(username="tino", password_hash="x", full_name="Tino M",
                          role="cashier", branch_id=branch.id, pharmacy_id=gid)
    db.add(cashier)
    db.commit()
    cashier_id = cashier.id
    db.close()


def sell(product_id):
    """Post a one-line basket, and say how the till answered."""
    token = tenancy.set_current_pharmacy(gid)
    try:
        with branch_scope.every_branch():
            db = session()
            user = db.get(models.User, cashier_id)
            body = pos_router.schemas.SaleCreate(
                items=[{"product_id": product_id, "quantity": 1}],
                payment_method="cash", amount_tendered=100.0)
            try:
                pos_router.create_sale(body=body, db=db, user=user)
                return ""
            except HTTPException as exc:
                return str(exc.detail)
            finally:
                db.close()
    finally:
        tenancy.reset_current_pharmacy(token)


print("\n  a till cannot sell a script\n")

print("the counter range sells")
refusal = sell(made["counter"])
check(refusal == "", f"an ordinary counter medicine still goes through "
                     f"({refusal or 'sold'})")

print("\na script does not")
refusal = sell(made["script"])
check(refusal != "", "a prescription medicine is refused at the till")
check(schedule_policy.code_for(SCRIPT) in refusal,
      f"the refusal names it the way this country does "
      f"({schedule_policy.code_for(SCRIPT)}): {refusal[:70]}")
check("dispensary" in refusal.lower(),
      "and says where it should be dispensed instead")

print("\na controlled one does not")
refusal = sell(made["controlled"])
check(refusal != "",
      "a controlled medicine is refused, so the register stops recording "
      "supplies nobody can account for")
check(schedule_policy.code_for(CONTROLLED) in refusal,
      f"named as {schedule_policy.code_for(CONTROLLED)}: {refusal[:70]}")

print("\nthe search does not offer what the sale will refuse")
token = tenancy.set_current_pharmacy(gid)
try:
    with branch_scope.every_branch():
        db = session()
        user = db.get(models.User, cashier_id)
        offered = {p.id for p in stock_router.list_products(
            q="Test", counter_only=True, db=db, user=user)}
        everything = {p.id for p in stock_router.list_products(
            q="Test", db=db, user=user)}
        db.close()
finally:
    tenancy.reset_current_pharmacy(token)

check(made["counter"] in offered, "the counter medicine is offered")
check(made["script"] not in offered, "the prescription medicine is not")
check(made["controlled"] not in offered, "nor the controlled one")
check(made["script"] in everything,
      "and the stock catalogue still shows every line the pharmacy owns")

print("\nthe dispensary still pays")
# A controlled script dispensed at the back and sent to the front till. The
# sale already exists; the till is only taking the money. If the new refusal
# reached this path a pharmacy could dispense a medicine and then be unable to
# be paid for it, which is a worse fault than the one being fixed.
token = tenancy.set_current_pharmacy(gid)
try:
    with branch_scope.every_branch():
        db = session()
        user = db.get(models.User, cashier_id)
        pending = models.Sale(
            sale_number="S-DISP-1", status="pending", total=10.0,
            subtotal=10.0, vat_amount=0.0, pharmacy_id=gid, branch_id=None)
        db.add(pending)
        db.commit()
        db.add(models.SaleItem(
            sale_id=pending.id, product_id=made["controlled"], quantity=1,
            unit_price=10.0, line_total=10.0, pharmacy_id=gid))
        db.commit()
        settled = ""
        try:
            pos_router.pay_sale(
                sale_id=pending.id,
                body=pos_router.schemas.PayRequest(
                    payment_method="cash", amount_tendered=10.0),
                db=db, user=user, step_up="")
        except HTTPException as exc:
            settled = str(exc.detail)
        db.close()
finally:
    tenancy.reset_current_pharmacy(token)

check(settled == "",
      f"a dispensed controlled script can still be paid for at the front till "
      f"({settled or 'settled'})")

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("A till sells what a till may sell.")
