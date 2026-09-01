"""Prove every medical aid can actually be claimed against.

The bug this exists to catch cost three hundred and eighteen claims. Each one
was raised correctly, each looked right on its own screen, and none could ever
be batched — because the batching work list reaches a claim by joining scheme
to pay office, and no scheme had a pay office. Nothing errored. The screen just
said there was no work to do.

So the check is not "does the seeder run". It is the invariant the seeder
exists to establish: after a boot, every scheme is reachable from the work list.
The order below is the one that broke it — offices created before any scheme
exists, schemes arriving afterwards, which is exactly what a pharmacy does when
it signs up a new medical aid in year two.
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"claimable-schemes.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base, engine, SessionLocal      # noqa: E402
from app import models, seed                             # noqa: E402

Base.metadata.create_all(engine)
db = SessionLocal()
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


# 1. The boot that broke it: offices are created while no scheme exists yet.
print("a first boot with no medical aids on file")
seed.seed_claiming_if_empty(db)
offices = db.query(models.PayOffice).count()
check(offices > 0, f"pay offices were created ({offices})")

# 2. The pharmacy signs up its schemes afterwards: the ordinary case.
print("\nschemes signed up afterwards")
for name, code in [("CIMAS Medical Aid", "CIMAS"),
                   ("PSMAS", "PSMAS"),
                   ("First Mutual Health", "FMH"),
                   ("First Mutual Health ZWG", "FMHZWA"),
                   ("Alliance Health", "ALLIANCE"),
                   ("Nyaradzo Medical Aid", "NYAR")]:
    db.add(models.MedicalAid(name=name, scheme_code=code))
db.commit()

# 3. A later boot. This is the call that used to do nothing at all.
seed.seed_claiming_if_empty(db)

aids = db.query(models.MedicalAid).all()
orphans = [a.name for a in aids if not a.pay_office_id]
check(not orphans, f"every scheme has a pay office (orphaned: {orphans or 'none'})")

# 4. Not merely attached — attached to the right payer. Filing a real funder
#    under private patients sends its claims where no money comes back from.
private = db.query(models.PayOffice).filter(models.PayOffice.code == "PRIVATE").first()
misfiled = [a.name for a in aids if private and a.pay_office_id == private.id]
check(not misfiled, f"no funder filed under private patients (misfiled: {misfiled or 'none'})")

# 5. One scheme running two currency books is one payer, not two.
fmh = {a.scheme_code: a for a in aids}
# Both being unset would satisfy a bare equality, which is the very state this
# file exists to catch, so the office has to exist before it can be shared.
check(fmh["FMH"].pay_office_id is not None
      and fmh["FMH"].pay_office_id == fmh["FMHZWA"].pay_office_id,
      "First Mutual's USD and ZiG books share one pay office")

# 6. The invariant that actually matters: the work list can see the claims.
print("\nthe batching work list")
reachable = (db.query(models.MedicalAid)
             .join(models.PayOffice, models.MedicalAid.pay_office_id == models.PayOffice.id)
             .count())
check(reachable == len(aids),
      f"all {len(aids)} schemes are reachable by the join the work list uses "
      f"(reachable: {reachable})")

# 7. Running it again changes nothing: a boot is not an event.
before = db.query(models.PayOffice).count()
seed.seed_claiming_if_empty(db)
check(db.query(models.PayOffice).count() == before,
      "a repeat boot creates no duplicate offices")

db.close()
print(f"\n{len(failures)} failing" if failures else "\nall checks passed")
sys.exit(1 if failures else 0)
