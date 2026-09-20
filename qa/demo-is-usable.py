"""Can somebody evaluating this product actually finish a demonstration?

WHAT WENT WRONG

Sixteen actions in this product are protected by step-up: voiding a sale,
adjusting stock, setting a price by hand, closing a stock take, taking a lot
out of turn. Each stops and asks for a credential before it proceeds. That is
the control working.

A demo account is created with a random password nobody is told, deliberately:
a visitor gets a session rather than credentials, so there is nothing to write
down and nothing to try against a live install. That is also right.

Nobody had put the two together. Every one of those sixteen answered

    403  That password was not accepted.

about a password that had never existed. The prompt told the visitor to
re-enter a password they were never given, and there was no way past it. So a
demonstration dead-ended at exactly the features worth demonstrating, and it
did so silently — the demo looked complete right up until somebody tried to
do the interesting half of it.

WHAT IS CHECKED HERE

That a demo visitor can pass every protected action with the demo PIN, that
the product tells them what that PIN is rather than expecting them to guess,
and — the half that matters more — that none of this reaches a real account:
a live user is told no code, and the demo code opens nothing of theirs.
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
from app import auth, models                       # noqa: E402
from app.services import demo                      # noqa: E402

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

print("\n  a visitor evaluating the product\n")

started = client.post("/api/auth/demo", json={})
check(started.status_code == 200, "a demo session can be started")
visitor = {"Authorization": f"Bearer {started.json()['access_token']}"}

state = client.get("/api/auth/demo/state", headers=visitor).json()
check(state.get("is_demo") is True, "and it knows itself to be a demo")
check(bool(state.get("pin")),
      "the product tells the visitor the code it is about to ask them for")
check(state.get("pin") == demo.DEMO_PIN,
      "and it is the code the server actually checks against")

actions = client.get("/api/step-up/actions", headers=visitor).json()
check(len(actions) > 0, f"the protected actions are listed ({len(actions)})")

check(bool(state.get("approver")),
      "and who to call over for the ones nobody may approve alone")

refused = []
needed_a_colleague = []
for action in actions:
    # Alone first, which is how most of them are done.
    granted = client.post("/api/step-up", headers=visitor,
                          json={"action": action["key"], "pin": state["pin"]})
    if granted.status_code == 200:
        continue
    # Then the way a dispensary does it: the pharmacist comes over and puts
    # her own code in on your till. Three of these refuse to be self-approved
    # and that is the control, not a fault, so it is checked rather than
    # relaxed.
    with_colleague = client.post("/api/step-up", headers=visitor,
                                 json={"action": action["key"],
                                       "pin": state["pin"],
                                       "approver": state["approver"]})
    if with_colleague.status_code == 200:
        needed_a_colleague.append(action["key"])
    else:
        refused.append(f"{action['key']} ({with_colleague.status_code})")

check(not refused,
      "a visitor can get past every protected action: "
      + (", ".join(refused) if refused else f"all {len(actions)}"))
check(len(needed_a_colleague) > 0,
      "and the ones that need a second person still do: "
      + (", ".join(needed_a_colleague) or "none, which means the rule is gone"))

# And the grant it hands back is the real thing, spent once and gone: the demo
# must not be a route to a weaker version of the control.
one = client.post("/api/step-up", headers=visitor,
                  json={"action": "stock.adjust", "pin": state["pin"]}).json()
spent = client.post("/api/step-up", headers=visitor,
                    json={"action": "stock.adjust", "pin": state["pin"]}).json()
check(one.get("token") and spent.get("token") and one["token"] != spent["token"],
      "each grant is its own, rather than one code standing in for all of them")

print("\n  and a real account, which none of this may touch\n")

with unscoped():
    from app.services import demo_tenant
    # A live account belonging to somebody who is NOT the demonstration
    # pharmacy. Its own standing pharmacist holds the demo code on purpose and
    # would make this check pass for the wrong reason.
    demo_pharmacy = demo_tenant.get(db).id
    live = (db.query(models.User)
            .filter(models.User.is_demo.is_(False), models.User.active,
                    models.User.pharmacy_id.isnot(None),
                    models.User.pharmacy_id != demo_pharmacy)
            .first())
if live is None:
    print("  ..   no live account on this database to check against")
else:
    real = {"Authorization": f"Bearer {auth.create_token(live, db)}"}
    theirs = client.get("/api/auth/demo/state", headers=real).json()
    check(theirs.get("is_demo") is not True,
          "a real session is not a demo")
    check(theirs.get("pin") == "",
          "and is told no code at all, so no live till can quote one")

    # The important one. The demo code must open nothing that is not a demo.
    got = client.post("/api/step-up", headers=real,
                      json={"action": "stock.adjust", "pin": demo.DEMO_PIN})
    check(got.status_code != 200,
          "the demo code opens nothing on a real account "
          f"(answered {got.status_code})")

print(f"\n{pass_count} passed, {fail_count} failed")
if fail_count:
    print("\na demonstration that stops at the interesting half is a "
          "demonstration of the wrong thing.")
sys.exit(1 if fail_count else 0)
