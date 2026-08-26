"""Time-limited demo accounts.

A prospect should be able to see the whole product without a sales call, and a
pharmacy manager evaluating it at 9pm should not have to wait for somebody to
create them a login. So the demo is self-service: a name, and you are inside.

The three decisions worth stating:

**Four hours, and the clock is on the account, not the token.** A token is a
copy of a claim made when it was issued; keeping one does not extend anything,
because every request re-reads `demo_expires_at` from the row. Revoking a demo
early is one UPDATE.

**The demo is a real account with a real role, not a read-only mode.** A
dispensing system evaluated without dispensing anything tells a pharmacist
nothing. The protection is the expiry and the separate data, not a crippled UI.

**Nothing is deleted when it expires.** The account is deactivated and the rows
stay. A prospect who comes back the next day and asks "what happened to what I
entered" gets an answer, and a sales conversation that starts with their own
data is worth more than a clean table.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .. import auth
from ..models import User

#: Long enough to work a real shift's worth of scenarios, short enough that it
#: is plainly a trial. Named rather than inlined because the login screen quotes
#: it back to the visitor, and the two must not drift.
DEMO_HOURS = 4

#: The demo password is generated and never shown: the visitor gets a session,
#: not credentials. There is nothing to write on a sticky note and nothing to
#: reuse against a live install.
_PASSWORD_BYTES = 24


def _unique_username(db: Session) -> str:
    for _ in range(20):
        candidate = f"demo-{secrets.token_hex(3)}"
        if not db.query(User).filter(User.username == candidate).first():
            return candidate
    raise RuntimeError("Could not allocate a demo username.")


def start(db: Session, full_name: str, role: str = "admin") -> tuple[User, datetime]:
    """Create a demo account and return it with its expiry.

    The role defaults to admin because the point of a demo is to see everything;
    an evaluation that hides the settings, the reports and the claiming screens
    is an evaluation of a different product.
    """
    name = (full_name or "").strip() or "Demo user"
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=DEMO_HOURS)
    user = User(
        username=_unique_username(db),
        password_hash=auth.hash_password(secrets.token_urlsafe(_PASSWORD_BYTES)),
        full_name=name[:120],
        role=role,
        active=True,
        is_demo=True,
        demo_expires_at=expires,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, expires


def seconds_left(user: User) -> int | None:
    """Whole seconds until this demo ends. None for a normal account."""
    if not user.is_demo or user.demo_expires_at is None:
        return None
    delta = user.demo_expires_at - datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0, int(delta.total_seconds()))


def is_expired(user: User) -> bool:
    left = seconds_left(user)
    return left is not None and left <= 0
