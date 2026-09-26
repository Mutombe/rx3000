"""Every dataset a button offers actually produces a file.

WHY THIS GUARD EXISTS

The export endpoint is one function with twenty-seven branches, and each branch
names columns off a model by hand. A typecheck cannot see any of it: the button
compiles, the route resolves, and the fault is an `AttributeError` raised inside
a list comprehension at the moment somebody at a counter presses Export at the
end of a long month.

Two of the branches written in one sitting said `doctor.full_name`. Users have
`full_name`, drivers have `full_name`, and prescribers have `name` — so Scripts
and the controlled Register both produced a 500 and everything else worked.
Found by running it, not by reading it, which is the whole argument for this
file.

It also ties the two halves together. `ExportButton` carries a union of dataset
names so a typo is a build error, and that union is only as good as its
agreement with the server: a name in the union that the server does not know is
a button that 404s, and a dataset the server can produce that no name reaches is
work nobody can get at.

WHAT IT CANNOT CHECK

Whether the columns are the RIGHT columns. A sheet with the wrong figure in it
is a judgement, and it is made where the branch is written.
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
ROUTER = BACKEND / "app" / "routers" / "dispensing_extras_router.py"
BUTTON = ROOT / "frontend" / "src" / "components" / "ExportButton.tsx"

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


print("\n  every grid leaves as a sheet\n")

# ---------------------------------------------------------------------------
# The two lists agree
# ---------------------------------------------------------------------------
source = ROUTER.read_text(encoding="utf-8")
body = source[source.index("@router.get(\"/export/{dataset}\")"):]
body = body[:body.index("\n@router.")]
served = set(re.findall(r'dataset == "([a-z-]+)"', body))

tsx = BUTTON.read_text(encoding="utf-8")
union = tsx[tsx.index("export type Dataset ="):]
union = union[:union.index(";")]
offered = set(re.findall(r'"([a-z-]+)"', union))

check(f"there are datasets to check ({len(served)} on the server, "
      f"{len(offered)} named in the button)", len(served) > 20)

missing = sorted(offered - served)
check("every name a button can pass is one the server knows", not missing,
      "these would 404 at the end of a long month: " + ", ".join(missing))

unreached = sorted(served - offered)
check("every dataset the server produces has a name that reaches it",
      not unreached,
      "work nobody can get at, because the union refuses the name: "
      + ", ".join(unreached))

# ---------------------------------------------------------------------------
# And each one actually produces a file
# ---------------------------------------------------------------------------
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app import tenancy                                    # noqa: E402
from app.database import SessionLocal                       # noqa: E402
from app.models import Pharmacy                             # noqa: E402
from app.routers.dispensing_extras_router import export     # noqa: E402

db = SessionLocal()
with tenancy.unscoped():
    shop = db.query(Pharmacy).first()
if shop:
    tenancy.set_current_pharmacy(shop.id)

broke = []
for name in sorted(served):
    # Both formats, because the workbook writer coerces every cell and the CSV
    # writer does not: a value openpyxl refuses is invisible in the CSV.
    for fmt in ("xlsx", "csv"):
        try:
            if not len(export(name, format=fmt, db=db).body):
                broke.append(f"{name} ({fmt}) produced nothing")
        except Exception as e:                              # noqa: BLE001
            broke.append(f"{name} ({fmt}) {type(e).__name__}: {e}")
db.close()

check(f"every dataset produces a file, in both formats ({len(served) * 2} files)",
      not broke, "; ".join(broke[:4]))

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
