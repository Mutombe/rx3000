import hashlib
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from . import branch_scope as _branch_scope
from . import tenancy
from .models import User

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
        return digest.hex() == digest_hex
    except Exception:
        return False


def find_by_username(db: Session, username: str) -> User | None:
    """Look a person up to sign them in, across every pharmacy.

    Authentication is the one thing that cannot be scoped by pharmacy, because
    the pharmacy is what it is about to establish. Somebody typing their
    username has not told us which tenant they are yet — the user record is what
    says so.

    That makes usernames global to a deployment, which is the ordinary trade and
    the one worth taking: the alternative is asking a pharmacist to pick their
    employer from a list before typing a password.

    Every other query about users stays scoped. This function exists so that the
    exception is one named thing that can be read and audited, rather than an
    `unscoped()` block copied into four routers by somebody who needed a login
    to work.
    """
    with tenancy.unscoped():
        return db.query(User).filter(User.username == username).first()


def create_token(user: User, db: Session | None = None) -> str:
    ttl = timedelta(hours=settings.TOKEN_TTL_HOURS)
    # A demo token never outlives the demo. The row is still the authority — see
    # get_current_user, but issuing an eight-hour token for a four-hour account
    # would leave the last four hours of it looking valid right up to the point
    # it is rejected, which reads as a bug rather than an expiry.
    if user.is_demo and user.demo_expires_at is not None:
        remaining = user.demo_expires_at - datetime.now(timezone.utc).replace(tzinfo=None)
        ttl = min(ttl, max(remaining, timedelta(minutes=1)))

    # Without a session there is nothing to read the cover rows from, so the
    # token says "every branch". Callers that have one pass it; the only ones
    # that do not are tests and the demo issuer, where a single branch is the
    # whole estate anyway.
    visible = _branch_scope.for_user(db, user) if db is not None else None
    branches = sorted(visible) if visible is not None else None

    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        # Which pharmacy's data this token may see.
        #
        # Carried in the token rather than looked up, because the lookup is the
        # thing that needs scoping: loading the user to find their pharmacy is
        # itself a query against a scoped table, and at that moment no pharmacy
        # is in force. Putting it in the token breaks that circle — the tenant
        # is known from the first line of the request, before anything reads.
        "pharmacy_id": user.pharmacy_id,
        # Which shops inside that pharmacy this token may see. `null` means all
        # of them, which is what the owner, head office and anybody not yet
        # placed in a branch get.
        #
        # In the token for the same reason the pharmacy is, and stale for the
        # same twelve hours. That staleness is right rather than merely
        # tolerable here: a token lasts about a shift, so somebody transferred
        # on Tuesday afternoon carries Avondale until Wednesday morning, which
        # is when they actually start working at Borrowdale. Recomputed at every
        # sign-in, so a transfer needs no intervention to take effect.
        #
        # Note what this is not. Tenancy is the boundary between two customers
        # and is enforced from the first line of the request. This is a boundary
        # inside one customer's own group, between shops whose staff already
        # work for the same owner.
        "branches": branches,
        "exp": datetime.now(timezone.utc) + ttl,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    # Deliberately unscoped, and the only place in the application that is.
    # The user record is what *says* which pharmacy is in force; scoping it by
    # the pharmacy in force would mean nobody could ever sign in.
    with tenancy.unscoped():
        user = db.get(User, int(payload["sub"]))
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Only staff reach the application.
    #
    # A patient's login belongs to their own record and a prescriber's to the
    # prescribing portal. Neither has a role that means anything here, and a
    # patient login treated as staff would default to `assistant`, which is a
    # real set of permissions over somebody else's pharmacy.
    #
    # Asked as a positive: is this staff. A user type nobody has thought of yet
    # must be refused the application rather than admitted by falling through a
    # list of exclusions.
    from .services import user_types

    if not user_types.may_use_application(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("This sign-in belongs to "
                    + ("a patient" if user_types.of(user) == "patient"
                       else "a prescriber")
                    + ", not to a member of staff. "
                    + ("Open the link the pharmacy sent you instead."
                       if user_types.of(user) == "patient"
                       else "Use the prescriber portal instead.")))
    # Checked here rather than only at login, so a demo ends four hours after it
    # started and not four hours after the last sign-in. The message is written
    # for the person reading it, because for a prospect this is the last thing
    # the product ever says to them.
    if user.is_demo and user.demo_expires_at is not None:
        if user.demo_expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This demo has ended. Everything you entered has been kept, "
                       "so ask us for an account and you can carry on from where you stopped.",
            )
    return user


#: The roles a staff member can hold, so a role can be validated rather than
#: accepted as free text. A user set to "pharmasist" is a user with no
#: permissions at all, silently, and it took a database to find out why.
ROLES = ("admin", "pharmacist", "assistant", "cashier", "manager")


def require_role(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(roles)}")
        return user
    return checker


def requires(capability: str):
    """Gate an endpoint on a capability rather than on a role.

    `require_role("admin", "manager")` is what this codebase had, and it is the
    thing `services/permissions` was written to replace: it cannot express "this
    assistant may void a sale under twenty dollars at Avondale until the locum
    leaves", so a pharmacy that needs that gives her a manager's login and every
    record afterwards says manager.

    The refusal carries the service's own sentence, which says who may do the
    thing and how to get it, rather than "Requires role: admin". A message that
    only says no is one that gets answered by sharing a password.

    Deliberately without an amount. A ceiling needs the body, which a dependency
    would have to read and rewind; the endpoints that have ceilings call
    `permissions.check(..., amount=)` themselves, where the figure is in hand.
    This is the yes/no half, which is what nearly every endpoint needs.
    """

    def gate(user: User = Depends(get_current_user),
             db: Session = Depends(get_db)) -> User:
        from .services import permissions as _permissions

        # Where somebody works in exactly one shop, that is where they are
        # standing, and a grant scoped to a branch should apply there. Somebody
        # covering several has no single answer, so only their unscoped grants
        # count — the narrower reading, which is the right way for a permission
        # check to be uncertain.
        visible = _branch_scope.visible_branch_ids()
        branch_id = next(iter(visible)) if visible and len(visible) == 1 else None

        decision = _permissions.check(db, user, capability, branch_id=branch_id)
        if decision["allowed"]:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=decision["why"],
            headers=({"X-Needs-Approval": "1"}
                     if decision.get("needs_approval") else None),
        )

    return gate


def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    """Only whoever operates the platform, never a customer's administrator.

    This guards the one part of the system that deliberately crosses tenants:
    creating pharmacies and deciding which pharmacy a person belongs to. A
    pharmacy's own `admin` must not reach it — an administrator who can move a
    user between tenants can read another pharmacy's patients by moving
    themselves, which undoes the whole of `tenancy` from the inside.

    So this checks the flag and nothing else. `require_role` deliberately treats
    `admin` as passing every check, which is right within a pharmacy and exactly
    wrong here.
    """
    if not user.is_platform_admin:
        raise HTTPException(
            status_code=403,
            detail="This is reserved for whoever operates RX5000, not for a "
                   "pharmacy's own administrator.")
    return user
