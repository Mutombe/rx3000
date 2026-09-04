from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth, schemas
from ..auth import get_current_user, verify_password
from ..database import get_db
from datetime import date

from ..services import auth_rules, demo, pins
from ..services import placement as placement_service
from .. import models
from ..models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=schemas.TokenResponse)
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = auth.find_by_username(db, body.username)
    if not user or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.active:
        raise HTTPException(status_code=403, detail="Account disabled")
    if demo.is_expired(user):
        raise HTTPException(
            status_code=403,
            detail="This demo has ended. Everything you entered has been kept, "
                   "so ask us for an account and you can carry on from where you stopped.",
        )
    return schemas.TokenResponse(access_token=auth.create_token(user, db), user=user)


@router.get("/me", response_model=schemas.MeOut)
def me(user: User = Depends(auth.get_current_user),
       db: Session = Depends(get_db)):
    """Who is signed in, what they may do, and which shop they are in.

    The capabilities are resolved here and sent as a flat set of booleans, so
    the screens never work out an answer for themselves. Two implementations of
    one rule disagree eventually, and the way this particular disagreement
    presents is a button that is visible, enabled, and refused — which teaches
    people that the software is unreliable rather than that they lack the
    authority.

    So the server decides and the client reads. A screen that hides a button it
    should have shown is a bug report; a screen that shows one the server will
    refuse is an argument at a counter.
    """
    from ..services import permissions as _permissions
    from .. import branch_scope as _branch_scope

    visible = _branch_scope.visible_branch_ids()
    with _branch_scope.every_branch():
        branches = [
            {"id": b.id, "name": b.name, "code": b.code}
            for b in db.query(models.Branch)
            .filter(models.Branch.id.in_(visible)).all()
        ] if visible is not None else [
            {"id": b.id, "name": b.name, "code": b.code}
            for b in db.query(models.Branch).all()
        ]

    out = schemas.UserOut.model_validate(user).model_dump()
    # All seventeen from two queries. Asking one at a time meant thirty-four
    # sequential round trips to Neon on every page load, which is what made
    # this endpoint take four and a half seconds.
    out["can"] = _permissions.everything(db, user)
    out["branches"] = branches
    out["all_branches"] = visible is None
    out["branch"] = next((b for b in branches if b["id"] == user.branch_id), None)
    return out


@router.post("/users", response_model=schemas.UserOut)
def create_user(
    body: schemas.UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(auth.require_role("admin")),
):
    if auth.find_by_username(db, body.username):
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(
        username=body.username,
        password_hash=auth.hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(auth.require_role("admin"))):
    """The pharmacy's staff. Demo visitors are not staff and are left out."""
    return db.query(User).filter(User.is_demo.is_(False)).all()


@router.put("/users/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: int, body: dict = Body(...),
                db: Session = Depends(get_db),
                actor: User = Depends(auth.require_role("admin"))):
    """Correct a staff record: their name, their role, whether they still work here.

    Staff could be created and listed and never changed. Two consequences, and
    the second is a control failure rather than an inconvenience:

    A role typed wrong was permanent. Somebody set up as an assistant who
    qualifies as a pharmacist needed a second account, and now two logins
    belong to one person and the register cannot say which of them checked a
    controlled item.

    **A staff member who left could not be deactivated.** Their login stayed
    live for as long as the pharmacy existed. That is the single most ordinary
    security failure in a small business — the departed employee who can still
    sign in, and nothing here could prevent it.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Staff member not found")

    if "full_name" in body and str(body["full_name"]).strip():
        user.full_name = str(body["full_name"]).strip()[:120]
    if "role" in body and body["role"]:
        role = str(body["role"]).strip()
        if role not in auth.ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"{role} is not a role. Choose one of: "
                       f"{', '.join(sorted(auth.ROLES))}.")
        # The last administrator cannot demote themselves. A pharmacy locked
        # out of its own user management has to be recovered from the database,
        # which on a hosted install means somebody else's engineer.
        if user.role == "admin" and role != "admin":
            others = (db.query(User)
                      .filter(User.role == "admin", User.active.is_(True),
                              User.id != user.id).count())
            if not others:
                raise HTTPException(
                    status_code=400,
                    detail="This is the only active administrator. Give "
                           "somebody else the role first, or the pharmacy "
                           "locks itself out of its own user management.")
        user.role = role
    if "active" in body:
        active = bool(body["active"])
        if not active:
            if user.id == actor.id:
                raise HTTPException(
                    status_code=400,
                    detail="You cannot deactivate the account you are signed "
                           "in with.")
            if user.role == "admin":
                others = (db.query(User)
                          .filter(User.role == "admin", User.active.is_(True),
                                  User.id != user.id).count())
                if not others:
                    raise HTTPException(
                        status_code=400,
                        detail="This is the only active administrator.")
        user.active = active

    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}")
def deactivate_user(user_id: int, db: Session = Depends(get_db),
                    actor: User = Depends(auth.require_role("admin"))):
    """Retire a staff member. Never deleted.

    Their name is on every dispensing they checked, every controlled-register
    entry they signed and every till they cashed up. Deleting the row does not
    remove those — it removes the ability to say who did them, which is the
    opposite of what a pharmacy record is for.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if user.id == actor.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot deactivate the account you are signed in with.")
    if user.role == "admin":
        others = (db.query(User)
                  .filter(User.role == "admin", User.active.is_(True),
                          User.id != user.id).count())
        if not others:
            raise HTTPException(
                status_code=400,
                detail="This is the only active administrator. Give somebody "
                       "else the role first.")
    user.active = False
    db.commit()
    return {"ok": True,
            "message": (f"{user.full_name} can no longer sign in. Their name "
                        f"stays on everything they did.")}


# ---------------------------------------------------------------- shared tills
@router.post("/pin")
def set_own_pin(pin: str = Body(...), password: str = Body(...),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Set or change your own till PIN. Proved with your password.

    Deliberately not something an administrator can do for somebody: a PIN that
    another person chose, or knows, attributes an action to the wrong human, and
    the whole point of the code is the attribution.
    """
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=403, detail="That password was not accepted.")
    try:
        pins.set_pin(db, user, pin)
    except pins.PinError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "pin_set": True}


@router.get("/pin")
def own_pin_state(user: User = Depends(get_current_user)):
    """Whether a PIN is set, and whether it is locked. Never the PIN."""
    return {
        "pin_set": bool(user.pin_hash),
        "locked_for_seconds": pins.locked_for(user),
        "length": pins.PIN_LENGTH,
    }


@router.post("/unlock")
def unlock_till(pin: str = Body(...), username: str = Body(default=""),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Unlock a locked screen with a PIN, without ending the session.

    A till locks rather than logs out on purpose. Logging out loses the basket
    and the open script, so staff turn the lock off and the machine then sits
    signed in all day with nothing attributable to anybody. Locking keeps the
    work and asks only who is back at the keyboard.

    `username` lets a different person take the till over mid-shift: the session
    continues, and the actor recorded against what happens next is them.
    """
    who = user
    if username and username != user.username:
        who = (lambda u: u if u and u.active else None)(auth.find_by_username(db, username))
        if not who:
            raise HTTPException(status_code=403, detail=f"No active user is called '{username}'.")
    try:
        pins.check(db, who, pin)
    except pins.PinError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "ok": True,
        "user": {"id": who.id, "username": who.username,
                 "full_name": who.full_name, "role": who.role},
        "took_over": who.id != user.id,
    }


@router.post("/demo", response_model=schemas.TokenResponse)
def start_demo(full_name: str = Body(default="", embed=True),
               db: Session = Depends(get_db)):
    """Start a demo session that stops working after four hours.

    No password is issued and none is needed: the visitor gets a session, not
    credentials, so there is nothing to write down and nothing that could later
    be tried against a live install.

    Deliberately not rate-limited by IP here. A pharmacy evaluating this is
    usually behind one address with several people on it, and locking the second
    person out of a demo is a worse failure than a handful of extra rows.
    """
    user, expires = demo.start(db, full_name)
    return schemas.TokenResponse(access_token=auth.create_token(user, db), user=user)


@router.get("/demo/length")
def demo_length():
    """How long a demo lasts, for the sign-in screen.

    Public, because the screen that quotes it has nobody signed in yet. It is
    read rather than written into the frontend so the number lives in one place;
    the alternative is "four hours" hardcoded across a login form, a banner, two
    emails and a landing page, and wrong in most of them the day it changes.
    """
    return {"hours": demo.DEMO_HOURS}


@router.get("/demo/state")
def demo_state(user: User = Depends(get_current_user)):
    """How long is left, for the banner. Silent for a normal account."""
    left = demo.seconds_left(user)
    return {
        "is_demo": bool(user.is_demo),
        "seconds_left": left,
        "hours": demo.DEMO_HOURS,
    }


@router.post("/reset-with-pin", response_model=schemas.TokenResponse)
def reset_with_pin(username: str = Body(...), pin: str = Body(...),
                   new_password: str = Body(...), db: Session = Depends(get_db)):
    """Set a new password using the till PIN, without an administrator.

    There is no email on a user here, and there should not be: this runs on a
    pharmacy's own machines, often without a mail server, and inventing an SMTP
    dependency to recover a password would make the product harder to install
    for the one week a year anybody needs it.

    The PIN is the second factor that already exists. It is hashed, it has a
    five-failure lockout, and its whole purpose is proving who is at the
    keyboard. Proving that is exactly what a password reset needs.

    Somebody with no PIN set cannot use this, and is told to ask an
    administrator rather than being left guessing.
    """
    user = auth.find_by_username(db, username.strip())
    # The same answer whether the name is wrong or the PIN is: a reset form that
    # distinguishes them is a list of valid usernames.
    generic = "That username and PIN were not accepted."
    if not user or not user.active:
        raise HTTPException(status_code=403, detail=generic)
    if not user.pin_hash:
        raise HTTPException(
            status_code=400,
            detail="No till PIN is set for this account, so it cannot be reset here. "
                   "Ask an administrator to set a new password for you.",
        )
    try:
        pins.check(db, user, pin)
    except pins.PinError as exc:
        # A lockout is worth saying out loud: it is the one refusal that goes
        # away on its own, and silence sends somebody looking for an admin.
        detail = str(exc) if "locked" in str(exc).lower() else generic
        raise HTTPException(status_code=403, detail=detail) from exc

    problem = auth_rules.password_problem(new_password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    user.password_hash = auth.hash_password(new_password)
    db.commit()
    db.refresh(user)
    # Signed in on the spot. Being bounced back to a login form to retype a
    # password chosen four seconds ago is friction with no security in it.
    return schemas.TokenResponse(access_token=auth.create_token(user, db), user=user)


# --------------------------------------------------------- where they work --
#
# `branch_scope` narrows what somebody sees once they have a branch, and until
# these existed nothing could give them one. A scoping rule with no way to
# assign a branch never narrows anybody, which is the same as not having
# written it — and it is the shape of failure this codebase keeps producing:
# the capability is present, complete, and unreachable.


@router.get("/users/{user_id}/placement")
def placement(user_id: int, db: Session = Depends(get_db),
              _: User = Depends(auth.requires("staff.manage"))):
    """Where somebody works, what else they cover, and every move they made."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Staff member not found")
    return placement_service.describe(db, user)


@router.post("/users/{user_id}/placement")
def move_staff(user_id: int, branch_id: int | None = Body(default=None),
               reason: str = Body(default=""),
               db: Session = Depends(get_db),
               actor: User = Depends(auth.requires("staff.manage"))):
    """Put somebody in a shop, or move them to another one.

    A move is written to the history as well as to the column. The column
    answers "where is she now" and the rows answer "where was she in March",
    and only the second can be asked of a controlled register.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Staff member not found")
    try:
        placement_service.place(db, user, branch_id, actor=actor, reason=reason)
    except placement_service.PlacementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return placement_service.describe(db, user)


@router.post("/users/{user_id}/reach")
def set_reach(user_id: int, all_branches: bool = Body(..., embed=True),
              db: Session = Depends(get_db),
              actor: User = Depends(auth.requires("staff.manage"))):
    """Let somebody see the whole group, or stop them."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Staff member not found")
    # The last person who can see the group must not remove their own sight of
    # it. A group with nobody able to read across its branches cannot reconcile
    # anything, and recovering from it means editing the database.
    if not all_branches and user.all_branches:
        others = (db.query(User)
                  .filter(User.all_branches.is_(True), User.active.is_(True),
                          User.id != user.id).count())
        if not others:
            raise HTTPException(
                status_code=400,
                detail="This is the only person who can see every branch. "
                       "Give somebody else group-wide sight first, or nobody "
                       "will be able to reconcile across the shops.")
    placement_service.set_reach(db, user, all_branches, actor=actor)
    return placement_service.describe(db, user)


@router.post("/users/{user_id}/cover")
def add_cover(user_id: int, branch_id: int = Body(...),
              until: date | None = Body(default=None),
              reason: str = Body(default=""),
              db: Session = Depends(get_db),
              actor: User = Depends(auth.requires("staff.manage"))):
    """A shop somebody covers besides their own, ending on its own if it should."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Staff member not found")
    try:
        placement_service.add_cover(db, user, branch_id, actor=actor,
                                    until=until, reason=reason)
    except placement_service.PlacementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return placement_service.describe(db, user)


@router.delete("/users/{user_id}/cover/{branch_id}")
def drop_cover(user_id: int, branch_id: int, db: Session = Depends(get_db),
               _: User = Depends(auth.requires("staff.manage"))):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Staff member not found")
    try:
        placement_service.drop_cover(db, user, branch_id)
    except placement_service.PlacementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return placement_service.describe(db, user)


# ----------------------------------------------------- what a role may do --
#
# The built-in defaults in `permissions.CAPABILITIES` are defaults, and a
# default is all they can be. One pharmacy lets any cashier take a return
# because the shop is small and the owner is always there; another lets nobody
# but a manager touch one. Both are right about their own shop, and without a
# way to say so the first has to grant it to eleven people by name and again to
# every new starter — which in practice means making the eleven people
# managers, and the role column stops meaning anything.


@router.get("/role-matrix")
def role_matrix(db: Session = Depends(get_db),
                _: User = Depends(auth.requires("staff.manage"))):
    """Every capability against every role, as this pharmacy has it.

    Carries the built-in default alongside the effective answer, so the screen
    can mark what has been changed from standard. A grid of toggles that cannot
    say which ones somebody moved is a grid nobody dares touch.
    """
    from ..services import permissions as _permissions

    return {
        "roles": [r for r in auth.ROLES],
        "rows": _permissions.role_matrix(db),
    }


@router.put("/role-matrix")
def set_role_matrix(role: str = Body(...), capability: str = Body(...),
                    allowed: bool = Body(...),
                    db: Session = Depends(get_db),
                    actor: User = Depends(auth.requires("staff.manage"))):
    """Move the floor for one role and one capability.

    One cell at a time rather than the whole grid. A save that posts fifty-odd
    booleans overwrites whatever somebody else changed in the meantime, and on
    a permissions screen that is the one place a silent overwrite must not
    happen.
    """
    from ..services import permissions as _permissions

    try:
        _permissions.set_role_capability(db, role, capability, allowed,
                                         actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "rows": _permissions.role_matrix(db)}
