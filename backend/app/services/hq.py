"""Head office: stopping a branch, signing in as somebody, and the map.

Three capabilities a group needs and a single shop never thinks about.

**Freezing a branch.** Under investigation, mid stock-take, or a manager has
walked out with the keys — head office needs the shop to stop moving money
without waiting for anybody there to agree. Distinct from deactivating it,
which says the shop no longer exists.

Reading is deliberately still allowed while frozen. A branch that cannot look
up a patient's allergies is a branch that will find a way around the freeze,
and the object is to stop the money moving rather than to stop the pharmacists
thinking.

**Impersonation.** "It does not work on my screen" is unanswerable from head
office, and the alternative, asking a branch for their password, is how a
pharmacy ends up with four people sharing one login. So head office may sign in
as somebody, and every action carries both names for as long as they do.

The trail is the whole safeguard, so it is built into the token rather than
into a screen: an impersonated session cannot forget to declare itself, and it
is short, because a session that lasts all day stops being an investigation and
becomes a second identity.

**The map.** Twelve branches in a list is a list. On a map it is a business —
where the takings are, which shop has gone quiet this week, which two are close
enough to share stock rather than each order it.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import Branch, Sale, User

#: An impersonated session is deliberately short. Long enough to see what the
#: branch sees; not long enough to become a way of working.
IMPERSONATION_MINUTES = 30


class HQError(RuntimeError):
    """Raised when a head-office action would break its own rules."""


# --------------------------------------------------------------- freezing --

def freeze(db: Session, branch: Branch, *, by: User, reason: str) -> dict:
    reason = (reason or "").strip()
    if not reason:
        # Never optional. A branch stopped without a stated reason is an
        # argument nobody can settle afterwards, and the person who has to
        # settle it is rarely the person who pressed the button.
        raise HQError(
            "Say why. A branch stopped without a recorded reason is an "
            "argument nobody can settle later.")
    if branch.frozen:
        raise HQError(f"{branch.name} is already frozen.")

    branch.frozen = True
    branch.frozen_at = datetime.utcnow()
    branch.frozen_by_id = by.id
    branch.frozen_reason = reason[:300]
    return {
        "ok": True,
        "message": (
            f"{branch.name} is frozen. Nobody there can take a sale, dispense, "
            f"move stock or cash up until it is released. They can still read "
            f"everything — a branch that cannot check an allergy will work "
            f"around the freeze."),
    }


def unfreeze(db: Session, branch: Branch, *, by: User) -> dict:
    if not branch.frozen:
        raise HQError(f"{branch.name} is not frozen.")
    was = branch.frozen_reason
    stopped_for = (datetime.utcnow() - branch.frozen_at
                   if branch.frozen_at else None)
    branch.frozen = False
    branch.frozen_at = None
    branch.frozen_by_id = None
    branch.frozen_reason = ""
    return {
        "ok": True,
        "message": (
            f"{branch.name} is trading again"
            + (f", after {stopped_for.days} day(s) stopped" if stopped_for
               and stopped_for.days else "")
            + (f" — {was}" if was else "") + "."),
    }


#: Methods that change something. A freeze stops these and lets everything else
#: through, which is the difference between stopping the money and stopping the
#: shop.
WRITING = {"POST", "PUT", "PATCH", "DELETE"}

#: What head office must still be able to do to a frozen branch, or the freeze
#: could never be lifted and the shop would be stopped forever by its own
#: control.
ALWAYS_ALLOWED = (
    "/api/auth", "/api/hq/", "/api/compliance/", "/api/profile",
)


def blocked(path: str, method: str, branch: Branch | None) -> str:
    """Why this request is refused, or "" when it is not.

    Returns the sentence rather than a boolean, because the sentence is the
    whole value: somebody at a frozen branch pressing Dispense needs to be told
    the shop is stopped and by whom, not given a 403.
    """
    if branch is None or not branch.frozen:
        return ""
    if method.upper() not in WRITING:
        return ""
    if any(path.startswith(prefix) for prefix in ALWAYS_ALLOWED):
        return ""
    return (
        f"{branch.name} is frozen by head office and nothing can be recorded "
        f"here until it is released"
        + (f" — {branch.frozen_reason}" if branch.frozen_reason else "")
        + ". Reading still works; ring head office to have it lifted.")


# ---------------------------------------------------------- impersonation --

def may_impersonate(actor: User, target: User) -> None:
    """Refuse the cases that would make the trail useless or dangerous."""
    if actor.id == target.id:
        raise HQError("You are already signed in as yourself.")
    if not target.active:
        raise HQError(
            f"{target.full_name}'s login is stopped. Signing in as somebody "
            f"who cannot sign in themselves would be a way around that.")
    if target.role == "admin" and actor.role != "admin":
        raise HQError("Only an administrator can act as another administrator.")
    if getattr(target, "is_demo", False):
        raise HQError("Demo accounts cannot be impersonated.")


# ------------------------------------------------------------------ map ----

def map_view(db: Session, *, days: int = 1) -> dict:
    """Every branch, where it is, and what it has taken.

    Twelve branches in a list is a list. On a map it is a business: where the
    takings are, which shop has gone quiet, and which two sit close enough to
    share stock rather than each order it.
    """
    start = datetime.utcnow() - timedelta(days=max(1, days))
    taken = dict(
        db.query(Sale.branch_id, func.coalesce(func.sum(Sale.total), 0.0))
        .filter(Sale.created_at >= start,
                Sale.status.in_(("paid", "part_paid")))
        .group_by(Sale.branch_id).all())
    counts = dict(
        db.query(Sale.branch_id, func.count(Sale.id))
        .filter(Sale.created_at >= start,
                Sale.status.in_(("paid", "part_paid")))
        .group_by(Sale.branch_id).all())

    # The same window immediately before, so "quiet" is measured against this
    # branch's own normal rather than against the biggest shop in the group.
    previous = dict(
        db.query(Sale.branch_id, func.coalesce(func.sum(Sale.total), 0.0))
        .filter(Sale.created_at >= start - timedelta(days=max(1, days)),
                Sale.created_at < start,
                Sale.status.in_(("paid", "part_paid")))
        .group_by(Sale.branch_id).all())

    branches = (db.query(Branch)
                .options(joinedload(Branch.frozen_by))
                .filter(Branch.active.is_(True))
                .order_by(Branch.name).all())

    rows = []
    for branch in branches:
        now = round(float(taken.get(branch.id, 0.0)), 2)
        before = round(float(previous.get(branch.id, 0.0)), 2)
        change = (round(100.0 * (now - before) / before, 1) if before else None)
        rows.append({
            "branch_id": branch.id, "branch": branch.name, "code": branch.code,
            "city": branch.city or "", "address": branch.address or "",
            "phone": branch.phone or "",
            "latitude": branch.latitude, "longitude": branch.longitude,
            # Said rather than implied. A branch with no coordinates is not at
            # nought degrees, which is in the Gulf of Guinea — it is simply not
            # pinned, and the map has to leave it off and list it instead.
            "pinned": branch.latitude is not None and branch.longitude is not None,
            "frozen": bool(branch.frozen),
            "frozen_reason": branch.frozen_reason or "",
            "frozen_by": branch.frozen_by.full_name if branch.frozen_by else "",
            "taken": now, "sales": int(counts.get(branch.id, 0) or 0),
            "previous": before, "change": change,
        })

    unpinned = [r["branch"] for r in rows if not r["pinned"]]
    frozen = [r["branch"] for r in rows if r["frozen"]]
    total = round(sum(r["taken"] for r in rows), 2)
    quiet = [r for r in rows
             if r["change"] is not None and r["change"] <= -25]
    return {
        "days": days,
        "branches": rows,
        "total": total,
        "unpinned": unpinned,
        "frozen": frozen,
        "quiet": [r["branch"] for r in quiet],
        "headline": (
            f"{', '.join(frozen)} frozen. " if frozen else ""
        ) + (
            f"{total:,.2f} taken across {len(rows)} branch(es)"
            + (f"; {', '.join(r['branch'] for r in quiet)} down more than a "
               f"quarter on the period before"
               if quiet else "")
            + "."
        ),
    }
