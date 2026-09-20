"""Does a refreshed demonstration still work?

`demoseed --fresh` sets the old demonstration pharmacy aside and a new one
takes its name. That is how the demonstration is refreshed when it has been
filled with somebody's experiments, and it is meant to be routine.

WHAT IT QUIETLY BROKE

The demonstration pharmacy has a standing pharmacist, so a visitor has
somebody to call over for the three actions that refuse to be self-approved.
She is found by username, which is unique across the estate, so after a
refresh the lookup still found her — attached to the pharmacy that had just
been set aside.

The approver lookup at the prompt is tenant scoped, as it must be: one
pharmacy's staff cannot approve another's. So a visitor in the new
demonstration pharmacy named a colleague the server could not see, and
voiding a sale, overriding a price and closing a stock take went back to
being unreachable. Nothing would have said so until somebody tried.

This runs the refresh and then does what a visitor does.
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
from app import models                             # noqa: E402
from app.services import demo, demo_tenant         # noqa: E402

pass_count = 0
fail_count = 0


def check(condition: bool, message: str) -> None:
    global pass_count, fail_count
    if condition:
        pass_count += 1
        print(f"  ok   {message}")
    else:
        fail_count += 1
        print(f"  FAIL {message}")


client = TestClient(app)
db = SessionLocal()

# A visitor before the refresh, so the pharmacist exists and belongs somewhere.
first = client.post("/api/auth/demo", json={})
check(first.status_code == 200, "a demo works before the refresh")
with unscoped():
    was = demo_tenant.get(db).id
    her = (db.query(models.User)
           .filter(models.User.username == demo.APPROVER_USERNAME).first())
    check(her is not None and her.pharmacy_id == was,
          f"the standing pharmacist is in the demonstration pharmacy ({was})")

# The refresh itself. Renamed rather than deleted, which is what `set_aside`
# does and why this is safe to run here.
with unscoped():
    moved = demo_tenant.set_aside(db)
check(bool(moved), f"the old demonstration pharmacy is set aside ({moved[:44]})")

with unscoped():
    now = demo_tenant.get(db).id
check(now != was, f"and a new one takes its name ({was} -> {now})")

# And now a visitor, which is the whole question.
after = client.post("/api/auth/demo", json={})
check(after.status_code == 200, "a demo still starts after the refresh")
visitor = {"Authorization": f"Bearer {after.json()['access_token']}"}
state = client.get("/api/auth/demo/state", headers=visitor).json()

with unscoped():
    her = (db.query(models.User)
           .filter(models.User.username == demo.APPROVER_USERNAME).first())
    check(her is not None and her.pharmacy_id == now,
          "the pharmacist has followed the demonstration to the new pharmacy")

# The three that need a second person. This is what silently broke.
second_person = []
for key in ("sale.void", "sale.price_override", "stocktake.close"):
    granted = client.post("/api/step-up", headers=visitor,
                          json={"action": key, "pin": state["pin"],
                                "approver": state["approver"]})
    if granted.status_code != 200:
        second_person.append(f"{key} ({granted.status_code})")
check(not second_person,
      "a visitor can still call her over: "
      + (", ".join(second_person) if second_person else "all three"))

# And the ordinary ones, which never needed her.
alone = client.post("/api/step-up", headers=visitor,
                    json={"action": "stock.adjust", "pin": state["pin"]})
check(alone.status_code == 200, "and still get past the rest alone")

print(f"\n{pass_count} passed, {fail_count} failed")
if fail_count:
    print("\na demonstration that has been refreshed is the one a prospect "
          "sees; it has to work at least as well as the one before it.")
sys.exit(1 if fail_count else 0)
