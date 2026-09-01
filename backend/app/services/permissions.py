"""What a person may do, beyond what their role says.

A role is a good default and a bad rule. Every pharmacy has the assistant who
is trusted to void a sale, the locum pharmacist who must not touch pricing, the
manager who covers two branches on alternate weeks, and the owner's daughter
who does the banking on Fridays. None of them fits a five-word role.

What happens without a way to say so is not that those people are refused. It
is that somebody gives them an administrator's login, because that is the only
thing that works, and from that moment the audit trail says "admin" for
everything, the controlled register cannot say who checked what, and the entire
control structure is decoration. **A permission system that is too coarse does
not make a pharmacy stricter; it makes the records false.**

So: a grant is one capability, on one person, optionally at one branch, given
by somebody named, with a reason, and with an end date where it should have
one. A locum's authority should die with the locum.

DENIES BEAT GRANTS, ALWAYS

`allow=False` takes something away that the role would otherwise give. It wins
over every grant, including the role's own. That order is not a preference: a
denial is somebody deciding this specific person must not do this specific
thing, and a system where a later grant could quietly undo it is one where
nobody can rely on a denial meaning anything.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import User, UserPermission

#: (capability, what it lets somebody do, which roles already have it)
#:
#: Named after the act rather than the screen — "void a sale" survives the
#: screen being redesigned, "POS page button 3" does not.
CAPABILITIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("sale.void", "Void or credit-note a sale after it has been rung up",
     ("admin", "manager")),
    ("sale.return", "Take part of a sale back over the counter",
     ("admin", "manager", "pharmacist", "cashier")),
    ("sale.discount", "Change a price at the till",
     ("admin", "manager")),
    ("stock.write_off", "Write off stock — expired, damaged, recalled",
     ("admin", "manager")),
    ("stock.adjust", "Adjust a stock figure outside a stock take",
     ("admin", "manager")),
    ("stock.price", "Change what the shop charges for something",
     ("admin", "manager")),
    ("stock.deactivate", "Take a product code out of use across the group",
     ("admin",)),
    ("cash.reconcile", "Commit a cash-up and sign off a variance",
     ("admin", "manager")),
    ("cash.petty", "Pay money out of the till", ("admin", "manager")),
    ("dispense.controlled", "Dispense a schedule 5 or 6 medicine",
     ("admin", "pharmacist")),
    ("claims.submit", "Send a claim batch to a funder",
     ("admin", "manager", "pharmacist")),
    ("claims.write_off", "Write off a claim shortfall",
     ("admin", "manager")),
    ("supplier.pay", "Record a payment to a supplier", ("admin", "manager")),
    ("staff.manage", "Add staff, change roles, stop a login", ("admin",)),
    ("branch.freeze", "Stop or restart a branch's trading", ("admin",)),
    ("hq.impersonate", "Sign in as another user to see what they see",
     ("admin",)),
    ("reports.money", "See margin, cost and profit figures",
     ("admin", "manager")),
]

BY_KEY = {c[0]: c for c in CAPABILITIES}


def role_has(role: str, capability: str) -> bool:
    entry = BY_KEY.get(capability)
    if entry is None:
        # An unknown capability is refused rather than allowed. A typo in a
        # guard must fail closed: `require("stock.writeoff")` letting everybody
        # through because nothing matched is the worst possible way for a
        # permission check to be wrong.
        return False
    return role in entry[2]


def grants_for(db: Session, user_id: int) -> list[UserPermission]:
    today = date.today()
    rows = (db.query(UserPermission)
            .filter(UserPermission.user_id == user_id,
                    UserPermission.active.is_(True)).all())
    # An expired grant is not a grant. Filtered here rather than in SQL so a
    # row with no end date is kept — most are standing.
    return [g for g in rows if not g.expires_on or g.expires_on >= today]


DAY_INITIALS = "MTWTFSS"


def _within_hours(grant: UserPermission, at: datetime) -> bool:
    """Is this grant awake right now?

    A locum who covers Saturdays should not carry Saturday's authority into
    Tuesday, and an authority that only exists during somebody's shift is one
    that cannot be used with their card after they have gone home.
    """
    if grant.days:
        # "M  T F  " — a blank in a slot means not that day.
        index = at.weekday()
        if index < len(grant.days) and grant.days[index] in (" ", "-", "_"):
            return False
    if grant.hours:
        try:
            start, _, end = grant.hours.partition("-")
            sh, sm = (int(x) for x in start.strip().split(":"))
            eh, em = (int(x) for x in end.strip().split(":"))
        except (ValueError, AttributeError):
            # An unreadable window is not a licence. Fail closed: a permission
            # whose hours nobody can parse must not become a permission with no
            # hours at all.
            return False
        minutes = at.hour * 60 + at.minute
        return sh * 60 + sm <= minutes <= eh * 60 + em
    return True


def check(db: Session, user: User, capability: str, *,
          branch_id: int | None = None, amount: float = 0.0,
          at: datetime | None = None) -> dict:
    """May this person do this, here, now, for this much.

    Returns a decision rather than a boolean, because "no" is rarely the whole
    answer. A ceiling that is exceeded is not a refusal — it is a request for
    somebody senior, and a system that says only "denied" there is one where
    the assistant rings the manager and the manager reads out their password.

        allowed        may proceed on their own
        needs_approval may proceed with a second named person
        why            the sentence to put on the screen
        limit          the ceiling that was hit, where one was
    """
    at = at or datetime.utcnow()
    grants = grants_for(db, user.id)
    mine = [g for g in grants if g.capability == capability
            and (g.branch_id is None or g.branch_id == branch_id)]

    # Denies first and always. A denial that a later grant could undo is a
    # denial nobody can rely on.
    for grant in mine:
        if not grant.allow:
            return _no(capability,
                       f"{user.full_name} is specifically prevented from this"
                       + (f" — {grant.reason}" if grant.reason else "")
                       + ". A denial is not overridden by a role or by a grant.")

    awake = [g for g in mine if g.allow and _within_hours(g, at)]
    asleep = [g for g in mine if g.allow and not _within_hours(g, at)]

    from_role = role_has(user.role, capability)
    if not from_role and not awake:
        if asleep:
            g = asleep[0]
            return _no(capability,
                       f"{user.full_name} may do this"
                       + (f" on {g.days}" if g.days else "")
                       + (f" between {g.hours}" if g.hours else "")
                       + ", and it is outside those hours now.")
        entry = BY_KEY.get(capability)
        who = ", ".join(entry[2]) if entry else "an administrator"
        return _no(capability,
                   f"A {user.role} may not do this. It belongs to: {who}.")

    # The bounds only come from a grant. A role grants a capability outright —
    # if it should be bounded for somebody, that is a grant with a ceiling
    # rather than a role with a footnote.
    bounded = [g for g in awake if g.limit_value or g.daily_limit
               or g.dual_approval]
    if not bounded:
        return _yes(capability, "Allowed."
                    if from_role else "Granted to them by name.")

    grant = bounded[0]

    if grant.dual_approval:
        return {
            "capability": capability, "allowed": False,
            "needs_approval": True, "limit": None,
            "why": (f"{user.full_name} may do this with a second person's "
                    f"approval, never alone"
                    + (f" — {grant.reason}" if grant.reason else "") + "."),
        }

    if grant.limit_value and amount > grant.limit_value:
        return {
            "capability": capability, "allowed": False,
            "needs_approval": bool(grant.escalates),
            "limit": round(grant.limit_value, 2),
            "why": (f"{amount:,.2f} is over {user.full_name}'s limit of "
                    f"{grant.limit_value:,.2f} for this."
                    + (" Somebody senior can approve it."
                       if grant.escalates else
                       " It cannot be approved up; it needs somebody who "
                       "holds the authority themselves.")),
        }

    if grant.daily_limit:
        # Four small voids in an afternoon is a pattern a per-transaction
        # ceiling cannot see, and it is the pattern that matters.
        used = _used_today(db, user, capability, at)
        if used + amount > grant.daily_limit:
            return {
                "capability": capability, "allowed": False,
                "needs_approval": bool(grant.escalates),
                "limit": round(grant.daily_limit, 2),
                "why": (f"{user.full_name} has used {used:,.2f} of a "
                        f"{grant.daily_limit:,.2f} daily allowance for this. "
                        f"{amount:,.2f} more would go over it."),
            }

    return _yes(capability,
                f"Within {user.full_name}'s limit of "
                f"{grant.limit_value:,.2f}." if grant.limit_value
                else "Granted to them by name.")


def _used_today(db: Session, user: User, capability: str,
                at: datetime) -> float:
    """What this person has already spent of a daily allowance.

    Read from the audit trail, which is the only record that spans every screen
    the capability is exercised from. Returns nought rather than raising where
    the trail cannot answer — a daily limit that cannot be measured must not
    block the work, and the per-transaction ceiling still applies.
    """
    from ..models import AuditLog

    try:
        start = at.replace(hour=0, minute=0, second=0, microsecond=0)
        return float(
            db.query(func.coalesce(func.sum(AuditLog.amount), 0.0))
            .filter(AuditLog.user_id == user.id,
                    AuditLog.capability == capability,
                    AuditLog.created_at >= start).scalar() or 0.0)
    except Exception:  # noqa: BLE001 - the trail does not carry amounts yet
        return 0.0


def _yes(capability: str, why: str) -> dict:
    return {"capability": capability, "allowed": True,
            "needs_approval": False, "limit": None, "why": why}


def _no(capability: str, why: str) -> dict:
    return {"capability": capability, "allowed": False,
            "needs_approval": False, "limit": None, "why": why}


def can(db: Session, user: User, capability: str,
        branch_id: int | None = None, amount: float = 0.0) -> bool:
    """The plain yes/no, for a caller that only needs one."""
    return check(db, user, capability,
                 branch_id=branch_id, amount=amount)["allowed"]


def explain(db: Session, user: User, capability: str,
            branch_id: int | None = None) -> dict:
    """Why the answer is what it is.

    A permission check that can only say no is one nobody can administer. The
    question asked at a counter is never "am I allowed" — the person already
    knows they are not — it is "who do I ask, and why not".
    """
    allowed = can(db, user, capability, branch_id)
    entry = BY_KEY.get(capability)
    grants = [g for g in grants_for(db, user.id) if g.capability == capability]
    denied = [g for g in grants if not g.allow]
    granted = [g for g in grants if g.allow]

    if denied:
        why = (f"{user.full_name} has been specifically prevented from this"
               + (f" — {denied[0].reason}" if denied[0].reason else "")
               + ". A denial is not overridden by a role or by a later grant.")
    elif role_has(user.role, capability):
        why = f"Every {user.role} may do this."
    elif granted:
        g = granted[0]
        why = ("Granted to them by name"
               + (f" by {g.granted_by.full_name}" if g.granted_by else "")
               + (f" — {g.reason}" if g.reason else "")
               + (f", until {g.expires_on:%d %b %Y}" if g.expires_on else "."))
    else:
        who = ", ".join(entry[2]) if entry else "an administrator"
        why = (f"A {user.role} may not do this. It belongs to: {who}. "
               f"Somebody with staff.manage can grant it to them by name.")

    return {
        "capability": capability,
        "name": entry[1] if entry else capability,
        "allowed": allowed,
        "why": why,
        "role_grants_it": role_has(user.role, capability),
        "granted_by_name": bool(granted),
        "denied_by_name": bool(denied),
    }


def for_user(db: Session, user: User) -> list[dict]:
    """Everything this person may and may not do, and why. For the HQ screen."""
    return [explain(db, user, key) for key, _name, _roles in CAPABILITIES]
