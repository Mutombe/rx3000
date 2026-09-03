"""Does the permission service actually stop anybody?

`services/permissions.py` is three hundred lines that resolve role defaults,
per-person grants, denials that beat grants, ceilings, daily allowances, hours,
days and expiry, and produce a sentence explaining the answer. It was complete
and it was called from one file: the head-office screen that *describes*
permissions. Of four hundred and sixty-one endpoints, none consulted it.

That is the failure mode this codebase keeps producing, and it is worse than a
missing feature. A missing feature is visible. A permission model that is
present, administrable, and enforced nowhere lets somebody spend an afternoon
setting limits for their staff, believe the shop is controlled, and be wrong.

So this asks two questions, and the second is the real one:

  1. Is every capability in the catalogue attached to at least one endpoint?
     A capability nobody checks is a promise on a settings screen.

  2. Does the gate refuse? Built by calling the real dependency with a real
     user who lacks the capability, and requiring both a 403 and a sentence
     that names who may do it instead.

WHY THE REFUSAL TEXT IS ASSERTED

Because "Requires role: admin" is what this codebase said before, and that
sentence is why pharmacies share passwords. The question asked at a counter is
never "am I allowed" — the person already knows they are not — it is "who do I
ask". A refusal that does not answer that gets answered by a manager reading
out their password, and from then on the audit trail is fiction.

    python qa/capability-gates.py
"""
import os
import pathlib
import re
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"capability-gates.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT/"backend"
sys.path.insert(0, str(BACKEND))

from fastapi import HTTPException                            # noqa: E402
from app.database import Base, engine, SessionLocal          # noqa: E402
from app import auth, branch_scope, models, tenancy          # noqa: E402
from app.services import permissions                         # noqa: E402

Base.metadata.create_all(engine)
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


# ---- 1. is each capability attached to anything? -------------------------

ROUTERS = sorted((BACKEND/"app"/"routers").glob("*.py"))
source = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                   for p in ROUTERS)
gated = set(re.findall(r'auth\.requires\("([^"]+)"\)', source))
# The head-office screens check the same capabilities through the service
# directly, which is the same enforcement by a different route.
# Whatever the actor variable is called. The first version of this line
# assumed `user` and reported `hq.impersonate` as unenforced because the
# impersonation route calls its actor `actor` — a false alarm about the one
# capability that gates signing in as somebody else, which is exactly the kind
# of wrong that stops people reading a check.
gated |= set(re.findall(r'_guard\(\s*db,\s*\w+,\s*"([^"]+)"', source))

print(f"\n  {len(gated)} of {len(permissions.CAPABILITIES)} capabilities are "
      f"checked somewhere\n")

#: Capabilities that describe a shape of access rather than one act, so there
#: is no single endpoint to hang them on. Each is a decision, with its reason.
NOT_AN_ENDPOINT = {
    "reports.money": "margin and cost appear on many screens; it gates the "
                     "figures inside responses rather than a route",
    "sale.discount": "a price override is part of the sale body, checked with "
                     "the amount in hand rather than by a dependency",
    "stock.price": "the same: a price change carries a number, and the ceiling "
                   "is the point",
    "stock.deactivate": "retiring a product code is an admin route already "
                        "behind require_role('admin')",
    "claims.write_off": "a shortfall write-off carries an amount",
    "dispense.controlled": "enforced in the dispensing rules with the schedule "
                           "in hand, which knows S5 from S2",
}

for key, name, _roles in permissions.CAPABILITIES:
    if key in gated or key in NOT_AN_ENDPOINT:
        continue
    check(False, f"nothing checks {key} ({name}) — it is administrable and "
                 f"unenforced, which is worse than absent")

check(bool(gated), "the permission service is consulted by the application at "
                   "all, not only by the screen that describes it")

# ---- 2. does the gate refuse, and say something useful? -------------------

print("\n  what happens to somebody who may not\n")

with tenancy.unscoped(), branch_scope.every_branch():
    db = SessionLocal()
    group = models.Pharmacy(name="Test Group")
    db.add(group)
    db.commit()
    assistant = models.User(username="anesu", password_hash="x",
                            full_name="Anesu C", role="assistant",
                            pharmacy_id=group.id)
    manager = models.User(username="boss", password_hash="x",
                          full_name="The Manager", role="manager",
                          pharmacy_id=group.id)
    db.add_all([assistant, manager])
    db.commit()

    gate = auth.requires("sale.void")
    refused = None
    try:
        gate(user=assistant, db=db)
    except HTTPException as exc:
        refused = exc

    check(refused is not None,
          "an assistant is refused a sale void")
    check(refused is not None and refused.status_code == 403,
          "with 403, not 500 and not a silent pass")
    text = str(refused.detail) if refused else ""
    check("manager" in text.lower() or "admin" in text.lower(),
          f"and the refusal says who may do it instead: {text!r}")
    check("requires role" not in text.lower(),
          "not 'Requires role: admin', which is the sentence that gets "
          "answered by sharing a password")

    allowed = None
    try:
        gate(user=manager, db=db)
        allowed = True
    except HTTPException:
        allowed = False
    check(allowed, "a manager is allowed through the same gate")

    # A denial by name beats the role. This is the property the whole design
    # rests on, so it is asserted rather than assumed.
    db.add(models.UserPermission(user_id=manager.id, capability="sale.void",
                                 allow=False, reason="under investigation",
                                 pharmacy_id=group.id))
    db.commit()
    denied = None
    try:
        gate(user=manager, db=db)
        denied = False
    except HTTPException as exc:
        denied = True
        text = str(exc.detail)
    check(denied, "a denial by name beats the role that would allow it")
    check(denied and "investigation" in text,
          "and the reason somebody typed is what the screen shows")

    # ---- 3. can a pharmacy change what a role may do? -------------------
    #
    # The floor, as against the per-person ceiling above. A shop that cannot
    # move it grants the same thing to eleven people one at a time, and then
    # makes the eleven people managers instead.
    print("\n  a pharmacy setting its own role defaults\n")

    returns = auth.requires("sale.return")
    cashier = models.User(username="rutendo", password_hash="x",
                          full_name="Rutendo P", role="cashier",
                          pharmacy_id=group.id)
    db.add(cashier)
    db.commit()

    ok_by_default = None
    try:
        returns(user=cashier, db=db)
        ok_by_default = True
    except HTTPException:
        ok_by_default = False
    check(ok_by_default,
          "a cashier may take a return, which is the built-in default")

    permissions.set_role_capability(db, "cashier", "sale.return", False,
                                    actor=manager)
    now = None
    try:
        returns(user=cashier, db=db)
        now = True
    except HTTPException:
        now = False
    check(not now,
          "a pharmacy that switches it off for cashiers is obeyed by the gate, "
          "not merely recorded on a settings screen")

    permissions.set_role_capability(db, "cashier", "sale.return", True,
                                    actor=manager)
    back = None
    try:
        returns(user=cashier, db=db)
        back = True
    except HTTPException:
        back = False
    check(back, "and switching it back on restores it")

    # An administrator must not be reducible here, or a pharmacy is one click
    # from needing somebody else's engineer to get back in.
    locked = None
    try:
        permissions.set_role_capability(db, "admin", "staff.manage", False,
                                        actor=manager)
        locked = False
    except ValueError:
        locked = True
    check(locked,
          "an administrator's own authority cannot be switched off, so a "
          "pharmacy cannot lock itself out of its own user management")

    rows = permissions.role_matrix(db)
    check(len(rows) == len(permissions.CAPABILITIES),
          f"the matrix covers every capability ({len(rows)})")
    check(all("default" in cell and "allowed" in cell
              for row in rows for cell in row["roles"].values()),
          "and each cell says both the effective answer and the built-in "
          "default, so the screen can mark what somebody changed")
    db.close()

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  {f}")
    raise SystemExit(1)
print("the permission model refuses people, and tells them who to ask")
