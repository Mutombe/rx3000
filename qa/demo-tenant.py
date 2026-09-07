"""Does somebody who asks to try the product actually see anything?

They did not. A demo account was created with no pharmacy, tenancy narrows a
request with no pharmacy in force to rows that have none, and after the tenancy
backfill there are none. Every visitor who clicked "Try it for 4 hours" got a
complete, working, entirely empty pharmacy — no patients, no stock, no trade,
nothing on any screen. Verified against production before this was written: the
patients list, the product list and every sidebar count came back empty.

So this asserts the three things that have to be true, in the order they
matter:

  1. A demo visitor sees the demonstration data.
  2. A demo visitor CANNOT see a real customer's data, and a real customer
     cannot see theirs. The demonstration pharmacy is a tenant like any other,
     so this is the same rule as tenant-isolation rather than a second one —
     asserted here because the whole point of the change is that demo accounts
     now have a tenant, and a tenant is exactly what could be the wrong one.
  3. The seed can run into a second pharmacy at all. `users.username` is
     globally unique while staff belong to a pharmacy, so seeding a second
     tenant used to hit the unique index on the first staff member.

    python qa/demo-tenant.py
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"demo-tenant.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base, engine, SessionLocal              # noqa: E402
from app import branch_scope, models, tenancy                    # noqa: E402
from app.services import demo, demo_tenant                       # noqa: E402

Base.metadata.create_all(engine)
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


# A real customer, with a patient of their own.
with tenancy.unscoped(), branch_scope.every_branch():
    db = SessionLocal()
    real = models.Pharmacy(name="A Real Customer")
    db.add(real)
    db.commit()
    db.add(models.Patient(first_name="Confidential", last_name="Patient",
                          pharmacy_id=real.id))
    # The staff names the seed will also want, taken first by the customer.
    db.add(models.User(username="admin", password_hash="x", full_name="Their Admin",
                       role="admin", pharmacy_id=real.id))
    db.commit()
    real_id = real.id
    db.close()

print("\n  seeding the demonstration pharmacy\n")

with tenancy.unscoped(), branch_scope.every_branch():
    db = SessionLocal()
    # Ten days rather than sixty: this is proving the mechanism, not the volume.
    made = demo_tenant.seed(db, days=10)
    demo_id = demo_tenant.get(db).id
    db.close()

check(bool(made), f"the seed ran into a second pharmacy: {made}")
check(demo_id != real_id, "and it is its own tenant, not the customer's")

with tenancy.unscoped():
    db = SessionLocal()
    clash = (db.query(models.User)
             .filter(models.User.username == "admin").count())
    check(clash == 1,
          f"the customer keeps the plain username and the demo's copy is "
          f"suffixed ({clash} row called 'admin')")
    demo_staff = (db.query(models.User)
                  .filter(models.User.pharmacy_id == demo_id).count())
    check(demo_staff > 0, f"the demonstration pharmacy has its own staff "
                          f"({demo_staff})")
    db.close()

print("\n  what a visitor sees when they ask to try it\n")

with tenancy.unscoped(), branch_scope.every_branch():
    db = SessionLocal()
    visitor, _expires = demo.start(db, "A Prospect")
    visitor_id = visitor.id
    db.close()


def as_visitor(query):
    """Exactly what their token puts in force: their pharmacy, every branch."""
    with tenancy.unscoped():
        db = SessionLocal()
        user = db.get(models.User, visitor_id)
        pid = user.pharmacy_id
        db.close()
    token = tenancy.set_current_pharmacy(pid)
    btoken = branch_scope.set_visible_branches(None)
    try:
        db = SessionLocal()
        out = query(db)
        db.close()
        return out
    finally:
        branch_scope.reset_visible_branches(btoken)
        tenancy.reset_current_pharmacy(token)


patients = as_visitor(lambda db: db.query(models.Patient).count())
products = as_visitor(lambda db: db.query(models.Product).count())
sales = as_visitor(lambda db: db.query(models.Sale).count())

check(patients > 50, f"patients: {patients}")
check(products > 50, f"products: {products}")
check(sales > 100, f"sales: {sales}")
check(min(patients, products, sales) > 0,
      "the demonstration pharmacy is not empty, which is what every visitor "
      "found before this")

print("\n  and cannot reach the customer\n")

leaked = as_visitor(lambda db: db.query(models.Patient)
                    .filter(models.Patient.last_name == "Patient").count())
check(leaked == 0,
      "a demo visitor does not see the customer's patient")

token = tenancy.set_current_pharmacy(real_id)
try:
    db = SessionLocal()
    theirs = db.query(models.Patient).count()
    db.close()
finally:
    tenancy.reset_current_pharmacy(token)
check(theirs == 1,
      f"and the customer sees only their own ({theirs}), not the "
      f"demonstration data")

print("\n  seeding twice does not make a second set\n")

with tenancy.unscoped(), branch_scope.every_branch():
    db = SessionLocal()
    again = demo_tenant.seed(db, days=10)
    db.close()
check(again == {}, "a second run is a no-op, so a restart cannot double it")

after = as_visitor(lambda db: db.query(models.Sale).count())
check(after == sales, f"and the trade is unchanged ({after})")

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  {f}")
    raise SystemExit(1)
print("a visitor sees a working pharmacy, and it is not anybody's real one")
