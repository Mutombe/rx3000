"""Does what a handler works out actually reach the browser?

FastAPI's `response_model` silently DROPS any key the schema does not name.
Not an error, not a warning: the handler computes something, puts it in the
dict it returns, and it is quietly removed on the way out. The endpoint looks
correct, the test of the endpoint passes if it checks the fields it declared,
and the feature simply is not there.

This has now cost this codebase four features.

  `POOut.sep_breaches` — a delivery invoiced above the published maximum was
  detected at goods receipt and the warning never arrived.

  `POOut.grv_number` — the same, for the delivery document raised alongside.

  `MeOut.may_switch` — every branch a person could switch to was worked out on
  every page load and dropped, so `Layout` read `me.may_switch ?? []` and the
  branch switcher in the top bar was permanently empty. A multi-branch
  pharmacy could not change which shop it was looking at, and nothing anywhere
  said so.

  `DispenseRequest` fields, caught before release by the same kind of check.

WHY A GUARD RATHER THAN CARE

Because care has been applied four times and the fault is silent by
construction. Nothing fails, nothing logs, and the only symptom is a screen
that does not do something — which looks like a feature nobody built rather
than one that is being thrown away eight lines before it arrives.

WHAT THIS CHECKS

The keys the browser actually relies on, asked for over HTTP and asserted to
be present. Adding a key to a handler without declaring it on the schema fails
here rather than in a pharmacy.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient          # noqa: E402

from app.main import app                           # noqa: E402
from app.database import SessionLocal              # noqa: E402
from app.tenancy import unscoped                   # noqa: E402
from app import auth, models, schemas              # noqa: E402

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


#: Schema, and the keys a screen reads off it that are NOT obvious columns.
#: Each of these was computed by a handler and could be dropped by a schema
#: that forgot to name it.
CONTRACTS: list[tuple[str, type, tuple[str, ...]]] = [
    ("the signed-in user", schemas.MeOut,
     ("can", "branches", "branch", "all_branches", "may_switch")),
    ("a purchase order", schemas.POOut,
     ("sep_breaches", "grv_number", "items")),
]

print("\n  what each response promises to carry\n")

for what, model, keys in CONTRACTS:
    declared = set(model.model_fields)
    missing = [k for k in keys if k not in declared]
    check(not missing, f"{what} declares everything its screen reads",
          "dropped: " + ", ".join(missing))

print("\n  and what it actually sends\n")

db = SessionLocal()
with unscoped():
    me = (db.query(models.User)
          .filter(models.User.is_demo.is_(False), models.User.active,
                  models.User.pharmacy_id.isnot(None)).first())
    if me is None:
        print("  ..   no account on this database")
        sys.exit(1 if failed else 0)
    headers = {"Authorization": f"Bearer {auth.create_token(me, db)}"}

client = TestClient(app)
said = client.get("/api/auth/me", headers=headers)
check(said.status_code == 200, "the signed-in user can be read",
      str(said.status_code))
body = said.json() if said.status_code == 200 else {}
for key in ("can", "branches", "all_branches", "may_switch"):
    check(key in body, f"it arrives carrying {key!r}",
          "keys: " + ", ".join(sorted(body))[:80])

# The one that was actually broken, stated as the thing it means.
check(isinstance(body.get("may_switch"), list),
      "and the branch switcher has a list to draw from")

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\na response_model drops what it does not name, silently. The "
          "symptom is a screen that does nothing, which looks like a feature "
          "nobody built.")
sys.exit(1 if failed else 0)
