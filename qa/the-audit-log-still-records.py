"""The audit row is no longer waited for. Is it still written?

Every state-changing call used to block on its own audit write: a connection,
an INSERT and a COMMIT before the caller saw a byte. Against the hosted
database that is three round trips, about three hundred milliseconds added to
every sale, every dispensing and every stock movement — and all of it after
the response was already built, so none of it could change the answer.

It is now written from a task the response does not wait for. That is a
straight win only if the row still lands every time, so this is the check that
earns it. A log that quietly loses rows is worse than a slow one: the slowness
is visible and the gap is not.

WHAT IT CHECKS

That a state-changing request still leaves a row naming the method, the path,
the person and the status; that a read does not (it never did — GETs are
skipped, and logging them would bury the log in noise); and that the rows
survive being produced faster than they can be written, which is the case the
change actually introduces.
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient          # noqa: E402

from app.main import app                           # noqa: E402
from app.database import SessionLocal              # noqa: E402
from app.tenancy import unscoped                   # noqa: E402
from app import auth, models                       # noqa: E402

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


db = SessionLocal()
with unscoped():
    me = (db.query(models.User)
          .filter(models.User.is_demo.is_(False), models.User.active,
                  models.User.pharmacy_id.isnot(None)).first())
    if me is None:
        print("  ..   no account on this database")
        sys.exit(0)
    headers = {"Authorization": f"Bearer {auth.create_token(me, db)}"}


def rows_for(path: str) -> list[models.AuditLog]:
    with unscoped():
        db.expire_all()
        return (db.query(models.AuditLog)
                .filter(models.AuditLog.path == path).all())


def settle(path: str, want: int, seconds: float = 6.0) -> list[models.AuditLog]:
    """Wait for the writes to land. They are no longer synchronous."""
    until = time.time() + seconds
    while time.time() < until:
        found = rows_for(path)
        if len(found) >= want:
            return found
        time.sleep(0.15)
    return rows_for(path)


# The TestClient runs the app's lifespan, so shutdown drains what is in flight.
with TestClient(app) as client:
    print("\n  one state-changing call\n")
    tag = uuid.uuid4().hex[:8]
    one = f"/api/scan"
    before = len(rows_for(one))
    client.post(one, headers=headers, json={"code": f"QA{tag}", "context": "pos"})
    found = settle(one, before + 1)
    check(len(found) > before, "a POST leaves an audit row",
          f"{before} -> {len(found)}")
    if found:
        newest = max(found, key=lambda r: r.id)
        check(newest.action == "POST", "naming the method")
        check(newest.username == me.username, "and the person",
              f"{newest.username!r}")
        check(newest.status_code > 0, "and what the call answered",
              str(newest.status_code))

    print("\n  a read, which was never logged\n")
    reads = len(rows_for("/api/auth/me"))
    client.get("/api/auth/me", headers=headers)
    time.sleep(1.0)
    check(len(rows_for("/api/auth/me")) == reads,
          "a GET still leaves nothing, so the log stays readable")

    print("\n  faster than they can be written\n")
    # The case the change introduces: calls arriving while earlier writes are
    # still in flight. Every one of them has to land.
    burst = 12
    start = len(rows_for(one))
    for i in range(burst):
        client.post(one, headers=headers,
                    json={"code": f"QB{tag}{i}", "context": "pos"})
    landed = settle(one, start + burst, seconds=12.0)
    check(len(landed) >= start + burst,
          f"all {burst} of a burst are recorded",
          f"{start} -> {len(landed)}, wanted {start + burst}")

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\na log that quietly loses rows is worse than a slow one: the "
          "slowness is visible and the gap is not.")
sys.exit(1 if failed else 0)
