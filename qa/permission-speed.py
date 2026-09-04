"""Does the fast answer match the slow one, and is it actually fast?

`/api/auth/me` took four and a half seconds. It asked `can()` once per
capability, and each `can()` re-read the person's grants and the pharmacy's
role matrix — thirty-four sequential round trips to a database in another
country, all of it the same two tables. The session provider calls that
endpoint on every page load, so it was the floor under every screen.

`everything()` reads the two tables once and answers all seventeen. The risk
in any such change is the obvious one: a faster second implementation of "may
they" that disagrees with the first. That is worse than the delay, because the
screen and the endpoint would then say different things and the screen is the
one people believe.

So this asserts both halves.

  1. Every answer from `everything()` equals the answer from `can()`, for
     several kinds of person: a role that has it, a role that does not, a
     grant by name, and a denial that beats the role.
  2. It really is two queries, counted rather than assumed, because the
     saving is the whole point and a stray lazy load inside the loop would
     put the round trips back without changing any answer.

    python qa/permission-speed.py
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"permission-speed.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import event                                  # noqa: E402
from app.database import Base, engine, SessionLocal           # noqa: E402
from app import branch_scope, models, tenancy                 # noqa: E402
from app.services import permissions                          # noqa: E402

Base.metadata.create_all(engine)
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


with tenancy.unscoped(), branch_scope.every_branch():
    db = SessionLocal()
    group = models.Pharmacy(name="Speed Test")
    db.add(group)
    db.commit()

    plain = models.User(username="a", password_hash="x", full_name="Assistant A",
                        role="assistant", pharmacy_id=group.id)
    boss = models.User(username="m", password_hash="x", full_name="Manager M",
                       role="manager", pharmacy_id=group.id)
    granted = models.User(username="g", password_hash="x", full_name="Granted G",
                          role="assistant", pharmacy_id=group.id)
    denied = models.User(username="d", password_hash="x", full_name="Denied D",
                         role="manager", pharmacy_id=group.id)
    db.add_all([plain, boss, granted, denied])
    db.commit()

    # One granted by name, one denied by name, and one role default moved.
    db.add_all([
        models.UserPermission(user_id=granted.id, capability="sale.void",
                              allow=True, reason="trusted on lates",
                              pharmacy_id=group.id),
        models.UserPermission(user_id=denied.id, capability="sale.void",
                              allow=False, reason="under investigation",
                              pharmacy_id=group.id),
    ])
    db.commit()
    permissions.set_role_capability(db, "assistant", "sale.return", True,
                                    actor=boss)
    permissions.set_role_capability(db, "cashier", "sale.return", False,
                                    actor=boss)

    print("\n  the fast answer is the same answer\n")

    for who in (plain, boss, granted, denied):
        fast = permissions.everything(db, who)
        slow = {key: permissions.can(db, who, key)
                for key, _n, _r in permissions.CAPABILITIES}
        check(fast == slow,
              f"{who.full_name} ({who.role}): all "
              f"{len(permissions.CAPABILITIES)} answers agree")
        if fast != slow:
            for key in fast:
                if fast[key] != slow[key]:
                    print(f"         {key}: fast={fast[key]} slow={slow[key]}")

    # The interesting ones individually, so a failure says which rule broke.
    check(permissions.everything(db, granted)["sale.void"],
          "a grant by name reaches the bulk answer")
    check(not permissions.everything(db, denied)["sale.void"],
          "and a denial by name still beats the role there")
    check(permissions.everything(db, plain)["sale.return"],
          "as does a role default the pharmacy moved")

    print("\n  and it is actually fewer queries\n")

    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cursor, statement, params, context, many):
        statements.append(statement)

    statements.clear()
    permissions.everything(db, boss)
    bulk = len(statements)

    statements.clear()
    for key, _n, _r in permissions.CAPABILITIES:
        permissions.can(db, boss, key)
    one_at_a_time = len(statements)

    event.remove(engine, "before_cursor_execute", _count)

    print(f"        {bulk} quer(ies) for all {len(permissions.CAPABILITIES)}, "
          f"against {one_at_a_time} asking one at a time")
    check(bulk <= 4,
          f"the bulk resolver reads the two tables once ({bulk} queries)")
    check(bulk * 4 <= one_at_a_time,
          f"which is several times fewer than {one_at_a_time} — the saving is "
          f"the reason the change exists, so it is counted rather than assumed")
    db.close()

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  {f}")
    raise SystemExit(1)
print("one rule, two entry points, and the fast one is not a second opinion")
