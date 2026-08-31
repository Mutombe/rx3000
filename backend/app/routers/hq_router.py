"""Head office: branches, people, authority, and the map.

Everything a group needs and a single shop never thinks about — stopping a
branch, seeing what a branch user sees, granting one person one bounded
authority, and looking at the estate rather than reading a list of it.
"""
from datetime import date, datetime, timedelta

import jwt
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .. import auth as auth_module
from ..auth import get_current_user, require_role
from ..config import settings
from ..database import get_db
from ..models import AuditLog, Branch, Sale, User, UserPermission
from ..services import hq, permissions
from ..tenancy import unscoped

router = APIRouter(prefix="/api/hq", tags=["head office"],
                   dependencies=[Depends(get_current_user)])


def _guard(db: Session, user: User, capability: str):
    decision = permissions.check(db, user, capability)
    if not decision["allowed"]:
        raise HTTPException(403, decision["why"])


# ------------------------------------------------------------- the estate --

@router.get("/overview")
def overview(days: int = 1, db: Session = Depends(get_db)):
    """Every branch, where it is, what it has taken, and whether it is stopped.

    Twelve branches in a list is a list. This is the same twelve as a business.
    """
    return hq.map_view(db, days=days)


@router.get("/branches/{branch_id}/people")
def branch_people(branch_id: int, db: Session = Depends(get_db)):
    """Who works here, and what each of them may do.

    A branch is its people. "Who can void a sale at Chinamano" had no answer
    anywhere — it was a role column read one user at a time.
    """
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(404, "That branch does not exist.")

    people = (db.query(User)
              .filter(User.branch_id == branch_id, User.is_demo.is_(False))
              .order_by(User.full_name).all()
              if hasattr(User, "branch_id") else
              db.query(User).filter(User.is_demo.is_(False))
              .order_by(User.full_name).all())

    return {
        "branch_id": branch.id, "branch": branch.name,
        "frozen": bool(branch.frozen), "frozen_reason": branch.frozen_reason,
        "people": [{
            "id": u.id, "full_name": u.full_name, "username": u.username,
            "role": u.role, "active": bool(u.active),
            "extra": [g.capability for g in permissions.grants_for(db, u.id)
                      if g.allow],
            "denied": [g.capability for g in permissions.grants_for(db, u.id)
                       if not g.allow],
        } for u in people],
    }


# ------------------------------------------------------------- freezing ----

@router.post("/branches/{branch_id}/freeze")
def freeze(branch_id: int, reason: str = Body(..., embed=True),
           db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    """Stop a branch trading, now, from here."""
    _guard(db, user, "branch.freeze")
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(404, "That branch does not exist.")
    try:
        result = hq.freeze(db, branch, by=user, reason=reason)
    except hq.HQError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return result


@router.post("/branches/{branch_id}/unfreeze")
def unfreeze(branch_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    _guard(db, user, "branch.freeze")
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(404, "That branch does not exist.")
    try:
        result = hq.unfreeze(db, branch, by=user)
    except hq.HQError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return result


@router.put("/branches/{branch_id}/location")
def set_location(branch_id: int, latitude: float = Body(...),
                 longitude: float = Body(...),
                 db: Session = Depends(get_db),
                 user: User = Depends(require_role("admin", "manager"))):
    """Pin a branch on the map.

    Refused outside sane bounds rather than accepted and drawn in the sea. A
    transposed pair — longitude typed into latitude — is the commonest way a
    branch ends up in the Indian Ocean, and it looks like a bug in the map.
    """
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        raise HTTPException(
            400,
            f"{latitude}, {longitude} is not a place on Earth. Latitude runs "
            f"-90 to 90 and longitude -180 to 180 — the usual cause is the two "
            f"the wrong way round.")
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(404, "That branch does not exist.")
    branch.latitude = latitude
    branch.longitude = longitude
    db.commit()
    return {"ok": True, "message": f"{branch.name} pinned."}


# -------------------------------------------------------- impersonation ----

@router.post("/impersonate/{user_id}")
def impersonate(user_id: int, reason: str = Body(..., embed=True),
                db: Session = Depends(get_db),
                actor: User = Depends(get_current_user)):
    """Sign in as somebody, to see what they see.

    "It does not work on my screen" is unanswerable from head office, and the
    alternative — asking a branch for their password — is how a pharmacy ends
    up with four people sharing one login.

    The session is short and it declares itself. Both names travel in the
    token, so every row written while it lasts records who was really doing it:
    without that, the trail would say a cashier in Bulawayo voided a sale at
    two in the morning.
    """
    _guard(db, actor, "hq.impersonate")
    if not (reason or "").strip():
        raise HTTPException(
            400,
            "Say why. Acting as somebody else is the one thing in this system "
            "that can make the audit trail lie, and the reason is what stops "
            "it being routine.")

    with unscoped():
        target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "That person does not exist.")
    try:
        hq.may_impersonate(actor, target)
    except hq.HQError as exc:
        raise HTTPException(400, str(exc)) from exc

    ttl = timedelta(minutes=hq.IMPERSONATION_MINUTES)
    token = jwt.encode({
        "sub": str(target.id),
        "username": target.username,
        "role": target.role,
        "pharmacy_id": target.pharmacy_id,
        # The two claims that make the trail honest. `imp` is read by the audit
        # middleware; `imp_name` is read by the banner, so the person acting
        # cannot forget they are.
        "imp": actor.id,
        "imp_name": actor.full_name,
        "exp": datetime.utcnow() + ttl,
    }, settings.SECRET_KEY, algorithm="HS256")

    db.add(AuditLog(
        user_id=target.id, username=target.username,
        acted_as_id=actor.id, acted_as=actor.username,
        action="POST", path=f"/api/hq/impersonate/{user_id}",
        summary=f"{actor.full_name} began acting as {target.full_name}: {reason}",
        status_code=200))
    db.commit()

    return {
        "access_token": token, "token_type": "bearer",
        "acting_as": {"id": target.id, "name": target.full_name,
                      "role": target.role, "username": target.username},
        "expires_in_minutes": hq.IMPERSONATION_MINUTES,
        "message": (
            f"You are {target.full_name} for {hq.IMPERSONATION_MINUTES} "
            f"minutes. Everything you do is recorded against both names."),
    }


# --------------------------------------------------------- permissions ----

@router.get("/capabilities")
def capabilities():
    """Everything that can be granted, and which roles already have it."""
    return [{"capability": k, "name": n, "roles": list(r)}
            for k, n, r in permissions.CAPABILITIES]


@router.get("/users/{user_id}/permissions")
def user_permissions(user_id: int, db: Session = Depends(get_db)):
    """What this person may and may not do, and why for each."""
    with unscoped():
        target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "That person does not exist.")
    grants = permissions.grants_for(db, user_id)
    return {
        "user": {"id": target.id, "full_name": target.full_name,
                 "role": target.role, "active": bool(target.active)},
        "capabilities": permissions.for_user(db, target),
        "grants": [{
            "id": g.id, "capability": g.capability, "allow": bool(g.allow),
            "branch_id": g.branch_id,
            "branch": g.branch.name if g.branch else "",
            "limit_value": round(g.limit_value or 0, 2),
            "daily_limit": round(g.daily_limit or 0, 2),
            "escalates": bool(g.escalates),
            "dual_approval": bool(g.dual_approval),
            "hours": g.hours or "", "days": g.days or "",
            "reason": g.reason or "", "expires_on": g.expires_on,
            "granted_by": g.granted_by.full_name if g.granted_by else "",
        } for g in grants],
    }


@router.post("/users/{user_id}/permissions")
def grant(user_id: int, body: dict = Body(...),
          db: Session = Depends(get_db),
          actor: User = Depends(get_current_user)):
    """Give somebody one bounded authority, or take one away.

    Bounded is the point. "May void a sale" is not how anybody delegates: it is
    "may void a sale under twenty dollars, at this branch, until the locum
    leaves, and anything larger needs me".
    """
    _guard(db, actor, "staff.manage")
    with unscoped():
        target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "That person does not exist.")

    capability = (body.get("capability") or "").strip()
    if capability not in permissions.BY_KEY:
        raise HTTPException(
            400,
            f"{capability!r} is not something that can be granted. The list is "
            f"at /api/hq/capabilities.")
    if not (body.get("reason") or "").strip():
        raise HTTPException(
            400,
            "Say why. A grant with no reason is one nobody can review, and "
            "these are reviewed exactly when something has gone wrong.")

    expires = body.get("expires_on")
    try:
        expires_on = date.fromisoformat(expires) if expires else None
    except (TypeError, ValueError):
        raise HTTPException(400, f"{expires!r} is not a date.") from None

    row = UserPermission(
        user_id=user_id, capability=capability,
        allow=bool(body.get("allow", True)),
        branch_id=body.get("branch_id") or None,
        limit_value=round(float(body.get("limit_value") or 0), 2),
        daily_limit=round(float(body.get("daily_limit") or 0), 2),
        escalates=bool(body.get("escalates", True)),
        dual_approval=bool(body.get("dual_approval", False)),
        hours=(body.get("hours") or "")[:20],
        days=(body.get("days") or "")[:7],
        reason=(body.get("reason") or "").strip()[:300],
        expires_on=expires_on,
        granted_by_id=actor.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id,
            "message": permissions.explain(db, target, capability)["why"]}


@router.delete("/permissions/{permission_id}")
def revoke(permission_id: int, db: Session = Depends(get_db),
           actor: User = Depends(get_current_user)):
    """Withdraw a grant. Kept, never deleted — it was true while it stood."""
    _guard(db, actor, "staff.manage")
    row = db.get(UserPermission, permission_id)
    if row is None:
        raise HTTPException(404, "That grant does not exist.")
    row.active = False
    db.commit()
    return {"ok": True,
            "message": "Withdrawn. The record of it stays, because it was "
                       "true while it stood and an audit asks about periods."}


@router.post("/check")
def check(capability: str = Body(...), amount: float = Body(default=0.0),
          branch_id: int | None = Body(default=None),
          db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    """May I do this, here, now, for this much — asked by a screen before it
    offers a button somebody cannot press."""
    return permissions.check(db, user, capability,
                             branch_id=branch_id, amount=amount)
