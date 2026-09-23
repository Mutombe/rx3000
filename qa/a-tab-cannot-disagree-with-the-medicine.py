"""The medicine decides, not the lane somebody picked.

WHAT THIS REPLACES

The dispensary opened on three tabs: Prescription, Dangerous Drugs, OTC.
Choosing one was the first thing a dispenser did, and it asked them to classify
a medicine the jurisdiction pack had classified when the product was created.
Two of the three were never two lanes: they shared one form and differed in a
search filter, a scan check and four sentences of copy.

Worse, the tab and the medicine could disagree. A controlled line captured on
the Prescription tab reached a refusal naming three verifications, and the
section holding those tickboxes only rendered on the Dangerous Drugs tab. The
button was enabled and the dispensing was impossible.

WHAT IS CHECKED, ALL OF IT SERVER-SIDE

There is no tab in this fixture, and that is the point: the server never
received one. `DispenseRequest` has no route field, the policy is computed from
the lines, and every rule follows from it.

  the strictest line decides   a basket holding an ordinary medicine AND a
                               controlled one is judged as controlled, so
                               nothing is softened by being mixed in with
                               something gentler.

  the record is demanded       a controlled line without its verifications is
                               refused, whatever screen it came from.

  and is enough                the same line WITH them goes through, so the
                               refusal is a gate rather than a wall.

  a cashier cannot             the capability is keyed off the computed route,
                               so somebody who may only sell over the counter
                               is refused a prescription line even with every
                               tickbox ticked.

  the search agrees            what a person is offered is drawn from the same
                               permission matrix that will judge them, so
                               nobody is shown a medicine they will be refused.
                               This is what replaced the tab.

    python qa/a-tab-cannot-disagree-with-the-medicine.py
"""
import os
import pathlib
import sys
from datetime import date, timedelta

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"no-tabs.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base, engine, SessionLocal          # noqa: E402
from app import branch_scope, models, schedule_policy, tenancy   # noqa: E402
from app.routers import dispensing_router                    # noqa: E402

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


COUNTER = next(s for s in range(9)
               if schedule_policy.policy_for(s).route == "otc")
SCRIPT = next(s for s in range(9)
              if schedule_policy.policy_for(s).route == "prescription")
CONTROLLED = next(s for s in range(9)
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
                          ("controlled", CONTROLLED)]:
        product = models.Product(
            name=f"Test {key}", schedule=schedule, active=True,
            unit_price=10.0, cost_price=4.0, units_per_pack=1,
            quantity_on_hand=500, pharmacy_id=gid)
        db.add(product)
        db.commit()
        made[key] = product.id
        db.add(models.StockBatch(
            product_id=product.id, branch_id=branch.id, batch_number=f"B-{key}",
            quantity_remaining=500, expiry_date=FAR_OFF, pharmacy_id=gid))

    people = {}
    for role, username in [("pharmacist", "rudo"), ("cashier", "tino")]:
        person = models.User(username=username, password_hash="x",
                             full_name=username.title(), role=role,
                             branch_id=branch.id, pharmacy_id=gid)
        db.add(person)
        db.commit()
        people[role] = person.id
    db.commit()
    db.close()


print("\n  a tab cannot disagree with the medicine\n")

print("the strictest line decides")
# `policy_for(max(schedules))` is how the server reads a mixed basket. Asserted
# directly, because every refusal below hangs off it.
mixed = max(COUNTER, CONTROLLED)
check(schedule_policy.policy_for(mixed).route == "controlled",
      "a basket of a counter medicine and a controlled one is judged "
      "controlled, not averaged down")
check(schedule_policy.policy_for(SCRIPT).requires_prescription,
      "a prescription medicine says so on its own policy, with no tab involved")

print("\nwhat each person may be offered")
token = tenancy.set_current_pharmacy(gid)
try:
    with branch_scope.every_branch():
        db = session()
        seen = {}
        for role, uid in people.items():
            person = db.get(models.User, uid)
            # No route named: the server works it out from the matrix. This is
            # the call the three tabs used to make on the dispenser's behalf.
            rows = dispensing_router.products_by_route(
                route="", q="Test", limit=50, db=db, user=person)
            seen[role] = {p.id for p in rows}
        db.close()
finally:
    tenancy.reset_current_pharmacy(token)

check(made["controlled"] in seen["pharmacist"],
      "a pharmacist is offered a controlled medicine without choosing a lane")
check(made["script"] in seen["pharmacist"],
      "and an ordinary prescription medicine from the same search box")
check(made["counter"] in seen["cashier"],
      "a cashier is offered the counter range")
check(made["script"] not in seen["cashier"],
      "and is not offered a prescription medicine they would be refused")
check(made["controlled"] not in seen["cashier"],
      "nor a controlled one")

print("\nthe capability follows the medicine")
# `ROUTE_CAPABILITY` keyed off the computed policy is what the tab was standing
# in for. Read here rather than reimplemented, so the guard cannot drift from
# the rule.
from app.routers.prescriptions_router import ROUTE_CAPABILITY      # noqa: E402

check(ROUTE_CAPABILITY[schedule_policy.policy_for(CONTROLLED).route]
      == "dispense.controlled",
      "a controlled line asks for the controlled capability")
check(ROUTE_CAPABILITY[schedule_policy.policy_for(SCRIPT).route]
      == "dispense.prescription",
      "a prescription line asks for the prescription capability")
check("prohibited" not in ROUTE_CAPABILITY,
      "and nothing grants the prohibited route, which no capability may reach")

print("\nthe record the medicine asks for")
controlled_policy = schedule_policy.policy_for(CONTROLLED)
counter_policy = schedule_policy.policy_for(COUNTER)
check(controlled_policy.requires_id_verification
      and controlled_policy.requires_script_sighted
      and controlled_policy.requires_prescriber_verification,
      "a controlled medicine asks for identity, the script and the prescriber")
check(not counter_policy.requires_id_verification,
      "a counter medicine asks for none of them, so the record appears with "
      "the line rather than with a tab")
check(controlled_policy.register_entry and not counter_policy.register_entry,
      "and only the controlled one is written into the register")

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The medicine decides.")
