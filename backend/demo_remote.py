"""Refresh the demonstration pharmacy on the hosted database.

The demonstration tenant is shared: every visitor who clicks "try it" is placed
in one pharmacy, because seeding sixty days of trade takes two minutes and
nobody waits two minutes at a sign-up button. The honest cost of that is
written down in `services/demo_tenant`, and this script is the other half of
it: once the demonstration has filled up with other people's experiments, it
is replaced.

    python demo_remote.py --status   # say what is there, change nothing
    python demo_remote.py --fresh    # set the old one aside and seed a new one

Same contract as `seed_remote.py`, and for the same reason. The URL comes from
`SEED_TARGET_URL` in backend/.env, which is gitignored, and it is read and set
into the environment BEFORE anything imports `app.config` — that module reads
`DATABASE_URL` once at import and never looks again, so a later assignment
would point the script at the local SQLite file while appearing to work.

WHAT --fresh ACTUALLY DOES, AND WHY IT IS NOT A DELETE

It renames. A delete across eighty tables in foreign-key order, against a
production database, to remove rows nobody is looking at, is a far larger risk
than the storage it reclaims. The old pharmacy is renamed and deactivated, no
account is attached to it, and the next demo creates a clean one. The rows stay
where they are, unreachable.

WHO ELSE IT AFFECTS

Anybody mid-demonstration at that moment. Their account keeps working and keeps
its four hours; it simply points at a pharmacy that is no longer the
demonstration one, so their screens go quiet. That is a real cost and the
reason this is run deliberately rather than on a schedule.
"""
from __future__ import annotations

import argparse
import logging
import os
import pathlib
import sys
import time


def _target() -> str:
    env = pathlib.Path(__file__).with_name(".env")
    if not env.exists():
        sys.exit("backend/.env not found; nothing to read the target from.")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SEED_TARGET_URL="):
            url = line.split("=", 1)[1].strip()
            if url:
                return url
    sys.exit("SEED_TARGET_URL is not set in backend/.env.")


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--fresh", action="store_true",
                    help="set the current demonstration aside and seed a new one")
parser.add_argument("--status", action="store_true",
                    help="say what is there and change nothing")
parser.add_argument("--resume", action="store_true",
                    help="finish a seed that was interrupted, without "
                         "replacing the pharmacy")
parser.add_argument("--days", type=int, default=0,
                    help="days of trade to generate (default: the module's own)")
args = parser.parse_args()

os.environ["DATABASE_URL"] = _target()

logging.basicConfig(level=logging.INFO, format="%(message)s")

from app.database import SessionLocal                        # noqa: E402
from app.services import demo, demo_tenant                   # noqa: E402
from app.tenancy import unscoped                             # noqa: E402
from app import models as m                                  # noqa: E402

where = os.environ["DATABASE_URL"].split("@")[-1].split("/")[0]
print(f"target: {where}\n")

db = SessionLocal()


def describe() -> int:
    """What is in the demonstration pharmacy now."""
    with unscoped():
        pharmacy = demo_tenant.get(db)
        print(f"  demonstration pharmacy: {pharmacy.name} (id={pharmacy.id})")
        print(f"  state: {demo_tenant.state(db) or 'never seeded'}")
        for label, model in (("products", m.Product), ("patients", m.Patient),
                             ("sales", m.Sale), ("prescriptions", m.Prescription)):
            count = (db.query(model)
                     .filter(model.pharmacy_id == pharmacy.id).count())
            print(f"    {label:<15} {count:>7,}")
        visitors = (db.query(m.User)
                    .filter(m.User.pharmacy_id == pharmacy.id,
                            m.User.is_demo.is_(True)).count())
        print(f"    {'demo visitors':<15} {visitors:>7,}")
        her = (db.query(m.User)
               .filter(m.User.username == demo.APPROVER_USERNAME).first())
        print(f"    standing pharmacist: "
              + (f"in pharmacy {her.pharmacy_id}" if her else "not made yet"))
        return pharmacy.id


before = describe()

if args.resume:
    # FINISHING AN INTERRUPTED SEED, WHICH IS NOT THE SAME AS RETRYING ONE.
    #
    # `seed` refuses to run while the pharmacy is marked SEEDING, and it is
    # right to: that mark means either another process is doing it or one died
    # trying, and writing a second copy on top of a half-written one is how a
    # demonstration ends up with two of every sale. Clearing the mark is the
    # deliberate act the refusal is asking for, done here rather than by
    # editing a column by hand.
    #
    # What makes it safe to run again is the seeder itself: trading skips any
    # day that already has sales and every other stage checks whether its own
    # rows exist, so this fills the gap rather than doubling what survived.
    with unscoped():
        mark = demo_tenant.state(db)
    if mark == demo_tenant.MARK_DONE:
        print("\n  Already finished. Nothing to resume.")
        sys.exit(0)
    print(f"\n  Marked {mark or 'nothing'}; clearing it so the seeder will "
          f"pick up where it stopped.")
    with unscoped():
        demo_tenant._mark(db, "")

    days = args.days or demo_tenant.DEMO_DAYS
    started = time.perf_counter()
    made = demo_tenant.seed(db, days=days)
    print(f"\n  Finished in {time.perf_counter() - started:,.0f}s: "
          + (", ".join(f"{v:,} {k}" for k, v in sorted(made.items()))
             or "nothing left to write"))
    with unscoped():
        her = demo.approver(db, demo_tenant.get(db).id)
    print(f"  standing pharmacist: {her.full_name} in pharmacy {her.pharmacy_id}")
    print("\n  after:\n")
    describe()
    sys.exit(0)

if args.status or not args.fresh:
    if not args.fresh:
        print("\n  Nothing asked for. Pass --fresh to replace it.")
    sys.exit(0)

print("\n  Setting the current demonstration aside.")
with unscoped():
    moved = demo_tenant.set_aside(db)
print(f"  set aside: {moved or '(there was nothing to move)'}")

with unscoped():
    pharmacy = demo_tenant.get(db)
print(f"  new demonstration pharmacy: id={pharmacy.id}")

days = args.days or demo_tenant.DEMO_DAYS
print(f"\n  Seeding {days} days. This takes a couple of minutes against a "
      f"remote database.\n")
started = time.perf_counter()
made = demo_tenant.seed(db, days=days)
took = time.perf_counter() - started

print(f"\n  Seeded in {took:,.0f}s: "
      + ", ".join(f"{v:,} {k}" for k, v in sorted(made.items())))

# The colleague a visitor calls over for the three actions nobody may approve
# alone. Made here rather than waiting for the first visitor, so the
# demonstration is complete the moment this finishes.
with unscoped():
    her = demo.approver(db, pharmacy.id)
print(f"  standing pharmacist: {her.full_name} in pharmacy {her.pharmacy_id}")

print("\n  after:\n")
describe()
