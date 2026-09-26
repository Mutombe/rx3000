"""No document number is worked out by counting rows.

WHY THIS GUARD EXISTS

`helpers.next_number` carries a long explanation of why counting rows is the
wrong way to issue a document number: a number can be issued without a row
being added, and a row can be added without a number being taken, and this
system does both. Its docstring ends by naming the consequence — a per-pharmacy
unique index refuses the insert and the request fails with "Something went
wrong at our end", at the till, in the middle of serving somebody.

Four services never moved over and went on counting rows: claims,
authorisations, to-follows and branch transfers. All four fields are in
`PER_TENANT_NUMBERS`, so all four could refuse.

They were missed for a reason worth recording. The note beside
`PER_TENANT_NUMBERS` in migrate.py said "helpers.next_number does count() + 1",
which was true when it was written and stopped being true when the helper was
fixed. Four services doing the same thing therefore looked consistent with the
shared one rather than left behind by it, to anybody reading the note. A
comment that has gone stale is worse than no comment, because it is evidence.

A to-follow shows the shape best: they are settled and cleared away all day, so
the count walks backwards constantly and the number it hands out next has
usually been used already.

WHAT IS CHECKED

Three things, and none of them is a matter of taste.

  * No service works out a document number from `.count()`. Read as source,
    because it has to hold for a table with no rows in it yet.
  * Every kind still produces the format it has always produced. A change
    there is a change that every printed document and every telephone call
    about one has to follow, so it should be a decision rather than a
    side effect of a fix.
  * The number the allocator offers is not one the table already holds. That
    is the property that fails at the till, asked of a real database.

Nothing is written. A guard that inserts into the database it is checking is
one nobody dares run against anything that matters, and the invariant can be
asked directly.

It also prints, for each kind, what counting rows WOULD have said. That is not
a check — on an empty table the two agree, and agreeing proves nothing — but it
is the whole argument in one line. On the development database the
authorisations row reads: issues AUTH260900001, counting rows would say
AUTH260900200. Both cannot be next.
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

passed = failed = 0


def check(said, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ok   {said}")
    else:
        failed += 1
        print(f"  X    {said}")
        if detail:
            print(f"       {detail}")


print("\n  a number is never handed out twice\n")

# ---------------------------------------------------------------------------
# Nobody counts rows to get a number
# ---------------------------------------------------------------------------
#
# The pattern is a count, and then that count formatted into something that
# looks like a document number. A bare `.count()` is ordinary and everywhere.
COUNTING = re.compile(
    r"\.count\(\)\s*\+\s*1[\s\S]{0,400}?f\"[A-Z][A-Z-]{1,6}\{")

offenders = []
for path in sorted((BACKEND / "app").rglob("*.py")):
    if path.name == "migrate.py":          # it describes the fault, in prose
        continue
    text = path.read_text(encoding="utf-8")
    if COUNTING.search(text):
        offenders.append(path.relative_to(ROOT).as_posix())

check(f"no service numbers a document by counting rows "
      f"({len(list((BACKEND / 'app').rglob('*.py')))} files read)",
      not offenders,
      "these hand out a number that has already been issued the moment a row "
      "is removed or a number is taken without one: " + ", ".join(offenders)
      + ". Use helpers.next_number, which reads the highest already issued.")

# ---------------------------------------------------------------------------
# And the allocator itself, against a real database
# ---------------------------------------------------------------------------
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app import tenancy                                        # noqa: E402
from app.database import SessionLocal                           # noqa: E402
from app.helpers import next_number                             # noqa: E402
from app.models import (Authorisation, BranchTransfer, Claim,   # noqa: E402
                        OwedItem, Pharmacy, Prescription, Sale)


#: Every numbered document this can exercise without building one first, with
#: the format each is expected to keep. A change of format here is a change
#: every printed document and every telephone call about one has to follow.
SHAPES = [
    (Claim, "CLM", "claim_number", {}, r"^CLM\d{4}\d{5}$"),
    (Authorisation, "AUTH", "reference", {}, r"^AUTH\d{4}\d{5}$"),
    (OwedItem, "TF", "reference", {}, r"^TF\d{4}\d{5}$"),
    (BranchTransfer, "TRF-", "reference",
     {"period": "%Y%m%d-", "width": 4}, r"^TRF-\d{8}-\d{4}$"),
    (Prescription, "RX", "rx_number", {}, r"^RX\d{4}\d{5}$"),
    (Sale, "INV", "sale_number", {}, r"^INV\d{4}\d{5}$"),
]

db = SessionLocal()
with tenancy.unscoped():
    shop = db.query(Pharmacy).first()
if shop:
    tenancy.set_current_pharmacy(shop.id)

wrong_shape, taken, evidence = [], [], []
try:
    for model, prefix, field, opts, shape in SHAPES:
        issued = next_number(db, model, prefix, field, **opts)
        if not re.match(shape, issued):
            wrong_shape.append(f"{model.__tablename__}.{field} gave {issued}")
            continue

        # THE INVARIANT, ASKED OF A REAL DATABASE AND WRITTEN NOWHERE.
        #
        # Nothing is inserted: a guard that writes to the database it is
        # checking is one nobody dares run against anything that matters. The
        # property that fails in production is simply that the number handed
        # out is one the table already holds, and that can be asked directly.
        column = getattr(model, field)
        if db.query(column).filter(column == issued).first():
            taken.append(f"{model.__tablename__}.{field} offered {issued}, "
                         f"which already exists")

        # What the old arithmetic would have said, for the record. Not a
        # check — on an empty table the two agree, and agreeing proves
        # nothing. It is here because the difference is the whole argument.
        rows = db.query(model).count() + 1
        stamp = issued[:len(issued) - (opts.get("width", 5))]
        by_counting = f"{stamp}{rows:0{opts.get('width', 5)}d}"
        collides = bool(db.query(column).filter(column == by_counting).first())
        evidence.append(f"{model.__tablename__:18} issues {issued}   "
                        f"counting rows would say {by_counting}"
                        + ("   <- already taken" if collides else ""))
finally:
    db.rollback()
    db.close()

check(f"every number keeps its own format ({len(SHAPES)} kinds)",
      not wrong_shape, "; ".join(wrong_shape))
check("no number offered is one the table already holds", not taken,
      "; ".join(taken))

print()
for line in evidence:
    print(f"       {line}")

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
