"""Does every per-branch view actually run?

A CORS error was reported from production:

    Access to fetch at '/api/insight/movement/branches?days=90' has been
    blocked by CORS policy: No 'Access-Control-Allow-Origin' header

Nothing was wrong with CORS. The handler raised `AttributeError: type object
'Prescription' has no attribute 'branch_id'`, and an unhandled exception
returns a response the CORS middleware never decorated — so the browser, which
can only see that the header is absent, reports the one thing it can see. The
error named the wrong cause, on a different layer, in a different subsystem.

WHY IT SURVIVED

`Prescription.branch_id` reads perfectly. A prescription belongs to a pharmacy,
a pharmacy has branches, so of course a script has a branch — except that it
does not: a prescription is written by a doctor and captured by a shop, and the
column was never added. Python does not check an attribute until the line runs,
SQLAlchemy does not check a column until the query is built, and the line only
runs when somebody asks for one branch. Both places that had it — stock
movement and seasonality — were dead from the moment they were written, and
the group view beside them worked perfectly, which is what made it look like a
deployment problem rather than a code one.

WHAT THIS DOES

Calls every per-branch analysis with a real branch and a real window, because
the only way to catch an attribute that does not exist is to execute the line.
A type checker would not have found it; neither would a smoke test that only
asked for the group.

    python qa/branch-filters.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal              # noqa: E402
from app import tenancy                            # noqa: E402
from app.models import Branch                      # noqa: E402
from app.services import basket, movement, seasonality   # noqa: E402


def main() -> int:
    tenancy.set_current_pharmacy(1)
    db = SessionLocal()
    tenancy.stamp(db)
    failures: list[str] = []

    branch = db.query(Branch).filter(Branch.active.is_(True)).first()
    if branch is None:
        print("FAIL: no active branch on this database")
        return 2
    print(f"  against {branch.name}\n")

    # Every analysis that narrows to one shop. Group calls are included beside
    # them: a group view that works while its branch view raises is exactly the
    # shape that made this look like a deployment fault.
    cases = [
        ("movement, group", lambda: movement.analyse(db, days=90, limit=3)),
        ("movement, one branch",
         lambda: movement.analyse(db, days=90, branch_id=branch.id, limit=3)),
        ("movement, every branch", lambda: movement.by_branch(db, days=90)),
        ("seasonality, group", lambda: seasonality.products(db)),
        ("seasonality, one branch",
         lambda: seasonality.products(db, branch_id=branch.id)),
        ("seasonality by month, group", lambda: seasonality.by_month(db)),
        ("seasonality by month, one branch",
         lambda: seasonality.by_month(db, branch_id=branch.id)),
        ("seasonality, consolidated", lambda: seasonality.group(db)),
        ("basket, group", lambda: basket.repeat_baskets(db, days=90)),
        ("basket, one branch",
         lambda: basket.repeat_baskets(db, days=90, branch_id=branch.id)),
    ]

    for name, run in cases:
        started = time.time()
        try:
            run()
            print(f"  ok   {name:<34} {time.time() - started:.1f}s")
        except Exception as exc:                        # noqa: BLE001
            print(f"  FAIL {name:<34} {type(exc).__name__}: {exc}")
            failures.append(
                f"{name} raises {type(exc).__name__}: {exc}\n"
                f"       In the browser this arrives as a CORS error, because "
                f"an unhandled\n"
                f"       exception returns a response the CORS middleware never "
                f"decorated.")

    db.close()
    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("every per-branch analysis runs; none of them is a 500 wearing a "
          "CORS error")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
