"""Creating pharmacies, and deciding who belongs to which.

This is the one part of the system that deliberately crosses tenants, so it is
the one part worth reading twice. Everything here runs `unscoped`, which turns
off the filter that keeps two pharmacies apart — and every endpoint is behind
`require_platform_admin`, which a customer's own administrator does not pass.

The distinction matters more than it looks. `admin` means "runs this pharmacy"
and belongs to a customer; if that role could assign users to tenants, an
administrator could read another pharmacy's patient list by moving themselves
into it and back. The guard therefore checks a flag rather than a role, because
`require_role` treats `admin` as passing everything, which is right inside a
pharmacy and precisely wrong here.

Creating a pharmacy creates three things at once — the pharmacy, its first
branch, and its first administrator. A tenant with no branch cannot hold stock
and a tenant with no user cannot be signed into, so creating them separately
just means a half-made pharmacy sitting there until somebody notices.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import auth
from ..auth import require_platform_admin
from ..database import get_db
from ..models import Branch, Pharmacy, User
from .. import tenancy

router = APIRouter(prefix="/api/pharmacies", tags=["pharmacies"])


def _counts(db: Session) -> dict[int, dict]:
    """Users and branches per pharmacy, grouped rather than counted per row."""
    users = dict(db.query(User.pharmacy_id, func.count(User.id))
                 .group_by(User.pharmacy_id).all())
    branches = dict(db.query(Branch.pharmacy_id, func.count(Branch.id))
                    .group_by(Branch.pharmacy_id).all())
    return {"users": users, "branches": branches}


def _out(p: Pharmacy, counts: dict) -> dict:
    return {
        "id": p.id, "name": p.name, "trading_name": p.trading_name or "",
        "registration_no": p.registration_no or "",
        "phone": p.phone or "", "email": p.email or "",
        "city": p.city or "", "address": p.address or "",
        "active": bool(p.active),
        "created_at": p.created_at,
        "users": counts["users"].get(p.id, 0),
        "branches": counts["branches"].get(p.id, 0),
    }


@router.get("")
def list_pharmacies(db: Session = Depends(get_db),
                    _: User = Depends(require_platform_admin)):
    """Every pharmacy on this deployment."""
    with tenancy.unscoped():
        rows = db.query(Pharmacy).order_by(Pharmacy.name).all()
        counts = _counts(db)
        return {"items": [_out(p, counts) for p in rows]}


@router.post("")
def create_pharmacy(body: dict, db: Session = Depends(get_db),
                    _: User = Depends(require_platform_admin)):
    """Create a pharmacy, its first branch and its first administrator.

    All three together, deliberately. A pharmacy with no branch cannot hold
    stock and one with no user cannot be signed into, so making them separately
    leaves a half-built tenant that looks finished from this screen.
    """
    name = " ".join((body.get("name") or "").split())
    username = (body.get("admin_username") or "").strip()
    password = body.get("admin_password") or ""

    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Give the pharmacy a name.")
    if len(username) < 3:
        raise HTTPException(status_code=400,
                            detail="The first administrator needs a username of "
                                   "at least three characters.")
    if len(password) < 8:
        raise HTTPException(status_code=400,
                            detail="Give the first administrator a password of at "
                                   "least eight characters.")

    with tenancy.unscoped():
        if db.query(Pharmacy).filter(func.lower(Pharmacy.name) == name.lower()).first():
            raise HTTPException(status_code=400,
                                detail=f"There is already a pharmacy called {name}.")
        # Usernames are global to the deployment — see `auth.find_by_username`
        # for why — so this has to be checked across every tenant, not within
        # this one.
        if db.query(User).filter(func.lower(User.username) == username.lower()).first():
            raise HTTPException(
                status_code=400,
                detail=f"The username {username} is already taken. Sign-in names "
                       "are shared across every pharmacy on this system.")

        pharmacy = Pharmacy(
            name=name,
            trading_name=(body.get("trading_name") or "").strip(),
            registration_no=(body.get("registration_no") or "").strip(),
            phone=(body.get("phone") or "").strip(),
            email=(body.get("email") or "").strip(),
            address=(body.get("address") or "").strip(),
            city=(body.get("city") or "").strip(),
            active=True,
        )
        db.add(pharmacy)
        db.flush()

        # Its first shop. Branch codes are unique across the deployment, so it
        # is derived from the pharmacy's id rather than from its name — two
        # pharmacies both calling their first shop "MAIN" is the ordinary case,
        # not a clash worth refusing.
        branch = Branch(
            pharmacy_id=pharmacy.id,
            code=f"P{pharmacy.id}-MAIN"[:12],
            name=(body.get("branch_name") or "Main branch").strip() or "Main branch",
            city=pharmacy.city, phone=pharmacy.phone, address=pharmacy.address,
            registration_no=pharmacy.registration_no,
            is_default=True, active=True,
        )
        db.add(branch)

        admin = User(
            pharmacy_id=pharmacy.id,
            username=username,
            full_name=(body.get("admin_name") or username).strip(),
            role="admin",
            password_hash=auth.hash_password(password),
            active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(pharmacy)
        counts = _counts(db)
        return _out(pharmacy, counts)


@router.put("/{pharmacy_id}")
def update_pharmacy(pharmacy_id: int, body: dict, db: Session = Depends(get_db),
                    _: User = Depends(require_platform_admin)):
    """Change a pharmacy's details, or suspend it."""
    with tenancy.unscoped():
        pharmacy = db.get(Pharmacy, pharmacy_id)
        if pharmacy is None:
            raise HTTPException(status_code=404, detail="No such pharmacy.")
        for field in ("name", "trading_name", "registration_no", "phone",
                      "email", "address", "city"):
            if field in body:
                setattr(pharmacy, field, (body.get(field) or "").strip())
        if "active" in body:
            # Suspending, never deleting. A pharmacy that stops paying still
            # owns its patients' dispensing histories and the regulator requires
            # those be kept — so the tenant is closed off, not removed.
            pharmacy.active = bool(body["active"])
        db.commit()
        db.refresh(pharmacy)
        return _out(pharmacy, _counts(db))


@router.get("/{pharmacy_id}/users")
def pharmacy_users(pharmacy_id: int, db: Session = Depends(get_db),
                   _: User = Depends(require_platform_admin)):
    """Who belongs to this pharmacy."""
    with tenancy.unscoped():
        if db.get(Pharmacy, pharmacy_id) is None:
            raise HTTPException(status_code=404, detail="No such pharmacy.")
        rows = (db.query(User).filter(User.pharmacy_id == pharmacy_id)
                .order_by(User.full_name).all())
        return {"items": [{
            "id": u.id, "username": u.username, "full_name": u.full_name,
            "role": u.role, "active": bool(u.active),
            "is_platform_admin": bool(u.is_platform_admin),
        } for u in rows]}


@router.get("/unassigned/users")
def unassigned_users(db: Session = Depends(get_db),
                     _: User = Depends(require_platform_admin)):
    """People who belong to no pharmacy at all.

    They can sign in and then see nothing, because the scoping fails closed —
    which is the safe failure but a baffling one for whoever it happens to. This
    list is how that gets noticed and fixed rather than reported as "the system
    is empty".
    """
    with tenancy.unscoped():
        rows = (db.query(User).filter(User.pharmacy_id.is_(None))
                .order_by(User.username).all())
        return {"items": [{
            "id": u.id, "username": u.username, "full_name": u.full_name,
            "role": u.role, "active": bool(u.active),
        } for u in rows]}


@router.post("/{pharmacy_id}/users/{user_id}")
def assign_user(pharmacy_id: int, user_id: int, db: Session = Depends(get_db),
                actor: User = Depends(require_platform_admin)):
    """Move a person to a pharmacy.

    Their existing work does not move with them, and that is deliberate: the
    sales they rang up and the scripts they dispensed belong to the pharmacy
    where they happened. Moving those too would take one pharmacy's records into
    another's books, which is the exact thing the tenancy exists to stop.
    """
    with tenancy.unscoped():
        pharmacy = db.get(Pharmacy, pharmacy_id)
        if pharmacy is None:
            raise HTTPException(status_code=404, detail="No such pharmacy.")
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="No such user.")
        if user.is_platform_admin and user.id == actor.id:
            # Cheap, and it prevents the one mistake that locks everybody out of
            # this screen: moving yourself somewhere and losing the flag's
            # usefulness before anybody else has it.
            raise HTTPException(
                status_code=400,
                detail="Move somebody else, or make a second platform "
                       "administrator first. Reassigning yourself is how this "
                       "screen becomes unreachable.")
        user.pharmacy_id = pharmacy.id
        db.commit()
        return {"id": user.id, "username": user.username,
                "pharmacy_id": user.pharmacy_id, "pharmacy": pharmacy.name}
