import hashlib
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
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


def create_token(user: User) -> str:
    ttl = timedelta(hours=settings.TOKEN_TTL_HOURS)
    # A demo token never outlives the demo. The row is still the authority — see
    # get_current_user — but issuing an eight-hour token for a four-hour account
    # would leave the last four hours of it looking valid right up to the point
    # it is rejected, which reads as a bug rather than an expiry.
    if user.is_demo and user.demo_expires_at is not None:
        remaining = user.demo_expires_at - datetime.now(timezone.utc).replace(tzinfo=None)
        ttl = min(ttl, max(remaining, timedelta(minutes=1)))
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


def require_role(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(roles)}")
        return user
    return checker


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
