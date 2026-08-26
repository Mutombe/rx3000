import hashlib
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
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
