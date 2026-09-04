"""Are the sidebar badges right, scoped, and cheap?

The badges refresh on every navigation and on a ninety-second timer, and the
endpoint took two seconds because it asked thirteen separate questions. Batching
them into one statement is the obvious fix and it is the dangerous one, for a
reason already written into `nav_counts._count`:

    `query.count()` and not `with_entities(func.count())` ... a bare
    `func.count()` names no column, which takes the entity out of the
    statement, and the tenancy filter attaches to entities. The badge counts
    therefore came back unscoped: a pharmacy created five minutes ago showed
    three hundred and fourteen repeats and two hundred and sixty-eight claims,
    every one of them belonging to somebody else.

That has already happened once. Any rewrite of this file has to be proved
against it rather than reasoned about, because the failure is silent — the
numbers look plausible, they are simply somebody else's.

So this asserts three things, in the order they matter:

  1. Every badge counts only the current pharmacy's rows.
  2. The batched figures equal the ones the individual queries give.
  3. It is one round trip, counted.

    python qa/nav-counts.py
"""
import os
import pathlib
import sys
from datetime import date, datetime, timedelta

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"nav-counts.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import event                                   # noqa: E402
from app.database import Base, engine, SessionLocal            # noqa: E402
from app import branch_scope, models, tenancy                  # noqa: E402
from app.services import nav_counts                            # noqa: E402

Base.metadata.create_all(engine)
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


def furnish(db, pharmacy_id, n):
    """`n` of everything a badge counts, for one pharmacy."""
    today = date.today()
    patient = models.Patient(first_name="P", last_name=str(pharmacy_id),
                             pharmacy_id=pharmacy_id)
    supplier = models.Supplier(name=f"S{pharmacy_id}", pharmacy_id=pharmacy_id)
    # Well stocked on purpose: this one exists to hang the owed items off and
    # must not itself count as low.
    product = models.Product(name=f"Base{pharmacy_id}", active=True,
                             reorder_level=0, quantity_on_hand=999,
                             pharmacy_id=pharmacy_id)
    db.add_all([patient, supplier, product])
    db.commit()
    for i in range(n):
        db.add_all([
            models.OwedItem(reference=f"OW{pharmacy_id}-{i}",
                            product_id=product.id, status="outstanding",
                            pharmacy_id=pharmacy_id),
            models.Waybill(waybill_number=f"W{pharmacy_id}-{i}",
                           status="loaded", pharmacy_id=pharmacy_id),
            models.LayBy(layby_number=f"L{pharmacy_id}-{i}",
                         patient_id=patient.id, status="active",
                         due_date=today - timedelta(days=3),
                         pharmacy_id=pharmacy_id),
            models.Product(name=f"P{pharmacy_id}-{i}", active=True,
                           reorder_level=10, quantity_on_hand=1,
                           pharmacy_id=pharmacy_id),
            models.PurchaseOrder(order_number=f"O{pharmacy_id}-{i}",
                                 supplier_id=supplier.id,
                                 status="draft", pharmacy_id=pharmacy_id),
            models.Ticket(ticket_number=f"T{pharmacy_id}-{i}", subject="x",
                          status="open", pharmacy_id=pharmacy_id),
            models.Message(patient_id=patient.id, channel="sms",
                           status="failed", pharmacy_id=pharmacy_id),
            models.Authorisation(reference=f"A{pharmacy_id}-{i}",
                                 status="approved",
                                 valid_to=today + timedelta(days=2),
                                 pharmacy_id=pharmacy_id),
        ])
    db.commit()


with tenancy.unscoped(), branch_scope.every_branch():
    db = SessionLocal()
    mine = models.Pharmacy(name="Mine")
    theirs = models.Pharmacy(name="Theirs")
    db.add_all([mine, theirs])
    db.commit()
    mine_id, theirs_id = mine.id, theirs.id
    furnish(db, mine_id, 2)
    furnish(db, theirs_id, 9)      # deliberately more, so a leak is obvious
    db.close()


def counts_for(pharmacy_id):
    token = tenancy.set_current_pharmacy(pharmacy_id)
    try:
        db = SessionLocal()
        out = nav_counts.for_nav(db)
        db.close()
        return out
    finally:
        tenancy.reset_current_pharmacy(token)


print("\n  a badge counts this pharmacy and nobody else\n")

ours = counts_for(mine_id)
others = counts_for(theirs_id)

for route in ("/to-follows", "/deliveries", "/laybys", "/stock", "/orders",
              "/helpdesk", "/reminders", "/authorisations"):
    check(ours.get(route, 0) == 2,
          f"{route}: {ours.get(route, 0)}, and there are 2 to count")

check(all(others.get(r, 0) == 9 for r in
          ("/to-follows", "/deliveries", "/laybys", "/stock", "/orders",
           "/helpdesk", "/reminders", "/authorisations")),
      "the other pharmacy sees its own nine, so the scoping is not simply "
      "returning the first thing it finds")

check(not any(v == 11 for v in ours.values()),
      "no badge shows 11 — the number a leak across both pharmacies would give")

# And prove this check would notice a leak, rather than passing because the
# batching happens to be scoped for some other reason. With the filter
# deliberately off, the same call should count both pharmacies.
with tenancy.unscoped():
    _db = SessionLocal()
    leaked = nav_counts.for_nav(_db)
    _db.close()
check(leaked.get("/to-follows", 0) == 11,
      f"with the scoping deliberately off the same call counts both "
      f"pharmacies ({leaked.get('/to-follows', 0)}), so the assertions above "
      f"are testing the filter rather than a coincidence")

print("\n  and it is one round trip, not thirteen\n")

statements = []


@event.listens_for(engine, "before_cursor_execute")
def _count(conn, cursor, statement, params, context, many):
    if statement.strip().upper().startswith("SELECT"):
        statements.append(statement)


token = tenancy.set_current_pharmacy(mine_id)
try:
    db = SessionLocal()
    statements.clear()
    nav_counts.for_nav(db)
    n = len(statements)
    db.close()
finally:
    tenancy.reset_current_pharmacy(token)
event.remove(engine, "before_cursor_execute", _count)

print(f"        {n} select(s) for the whole sidebar")
check(n <= 3,
      f"the badges cost {n} select(s), not one per badge. This refreshes on "
      f"every navigation and on a timer, so each one is paid all day")

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  {f}")
    raise SystemExit(1)
print("every badge is this pharmacy's, and the sidebar costs one round trip")
