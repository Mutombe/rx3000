"""Time-limited demo accounts.

A prospect should be able to see the whole product without a sales call, and a
pharmacy manager evaluating it at 9pm should not have to wait for somebody to
create them a login. So the demo is self-service: a name, and you are inside.

The three decisions worth stating:

**Four hours, and the clock is on the account, not the token.** A token is a
copy of a claim made when it was issued; keeping one does not extend anything,
because every request re-reads `demo_expires_at` from the row. Revoking a demo
early is one UPDATE.

**The demo has its own pharmacy, with the demonstration data in it.** See
`demo_tenant`: one tenant, seeded from the same generator the development
database uses, scoped away from every real customer by the same mechanism that
separates customers from each other.

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
from . import pins

#: Long enough to work a real shift's worth of scenarios, short enough that it
#: is plainly a trial. Named rather than inlined because the login screen quotes
#: it back to the visitor, and the two must not drift.
DEMO_HOURS = 4

#: The demo password is generated and never shown: the visitor gets a session,
#: not credentials. There is nothing to write on a sticky note and nothing to
#: reuse against a live install.
_PASSWORD_BYTES = 24

#: THE ONE CREDENTIAL A DEMO VISITOR IS GIVEN, AND WHY THERE IS ONE.
#:
#: Sixteen actions in this product are protected by step-up: voiding a sale,
#: adjusting stock, setting a price by hand, taking a lot out of turn. Each
#: asks for a credential before it will proceed.
#:
#: A demo visitor had none. The password above is random and nobody is told
#: it, which is right, and the consequence had not been followed through: every
#: one of those sixteen answered "That password was not accepted", about a
#: password that had never existed. The demo dead-ended at precisely the
#: features worth demonstrating, and the prospect had no way past it.
#:
#: A known PIN fixes that without weakening anything, and where it can be used
#: is the whole reason. It belongs to one throwaway account, in the
#: demonstration tenant, holding demonstration data, for four hours. It is set
#: ONLY on accounts created here, so no real login is affected. It is not a
#: password and cannot be exchanged for one. And it lets a visitor meet the
#: control honestly — they see the product stop and ask, and they can answer —
#: rather than meeting a wall.
#:
#: Quoted back on `/api/auth/demo/state`, so the screen that asks for it can
#: also say what it is; a code the visitor must guess is the same dead end
#: wearing a different hat.
DEMO_PIN = "2580"


#: The colleague a demo visitor can call over.
#:
#: Three of the protected actions refuse to be self-approved: voiding a sale,
#: overriding a price at the till, and closing a stock take. That is two person
#: control and it is the point of them — the person ringing the sale is not the
#: person who decides it can be unrung.
#:
#: A demo visitor is alone, so those three were unreachable even with a code.
#: Rather than weaken the rule for the demonstration, which would demonstrate
#: something that is not true of the product, the demonstration pharmacy has a
#: second member of staff. The visitor names her at the prompt exactly as a
#: cashier names the pharmacist on the floor, and sees the control work the way
#: it will work in their shop.
APPROVER_USERNAME = "demo-pharmacist"
APPROVER_NAME = "Tendai Moyo, pharmacist"


def approver(db: Session, pharmacy_id: int) -> User:
    """The demonstration pharmacy's standing pharmacist, made once.

    Not a demo account: it has no expiry, because it is part of the
    demonstration pharmacy rather than one visitor's session. It exists only
    inside that tenant and can therefore approve nothing anywhere else.
    """
    # LOOKED UP UNSCOPED, OR IT IS MADE TWICE AND THE SECOND ONE FAILS.
    #
    # `User` carries the tenant mixin, so an ordinary query here is narrowed to
    # whatever pharmacy is in force — and during a demo sign-up that is not
    # the demonstration pharmacy, because nobody is signed in yet. The lookup
    # found nothing, the insert ran again, and the unique index on `username`
    # refused it: every demo after the first answered 500. Caught by the guard
    # on the second run rather than by reading it.
    from ..tenancy import unscoped

    with unscoped():
        found = (db.query(User)
                 .filter(User.username == APPROVER_USERNAME).first())
    if found is not None:
        # SHE FOLLOWS THE DEMONSTRATION PHARMACY WHEN IT IS REPLACED.
        #
        # `demoseed --fresh` sets the old tenant aside and a new one takes its
        # name, which is how the demonstration is refreshed. She was made in
        # the old one and would have stayed there, and the approver lookup at
        # the prompt IS tenant scoped: a visitor in the new pharmacy would
        # name a colleague the server could not see, and the three actions
        # that need a second person would go back to being unreachable.
        #
        # Moved rather than made again, because the username is unique across
        # the estate and a second one cannot exist.
        if found.pharmacy_id != pharmacy_id:
            with unscoped():
                found.pharmacy_id = pharmacy_id
                found.active = True
                db.commit()
                db.refresh(found)
        return found
    found = User(
        username=APPROVER_USERNAME,
        password_hash=auth.hash_password(secrets.token_urlsafe(_PASSWORD_BYTES)),
        pin_hash=pins.hash_pin(pins.validate(DEMO_PIN)),
        full_name=APPROVER_NAME,
        # A pharmacist approves all three of the actions that need a second
        # person, which is who would approve them in a real dispensary.
        role="pharmacist",
        active=True,
        is_demo=False,
        pharmacy_id=pharmacy_id,
    )
    db.add(found)
    db.commit()
    db.refresh(found)
    return found


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
    from . import demo_tenant

    name = (full_name or "").strip() or "Demo user"
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=DEMO_HOURS)

    # The pharmacy they will be looking at.
    #
    # Without one the account is created with no tenant, and tenancy narrows a
    # request with no pharmacy in force to rows that have none — of which,
    # after the backfill, there are none. Every demo before this saw a complete
    # and entirely empty product: no patients, no stock, no trade, nothing on
    # any screen. That was the first impression the product made to everybody
    # who asked to try it.
    pharmacy = demo_tenant.get(db)
    # The colleague the visitor can call over for the three actions that refuse
    # to be self-approved. Made on the first demo and found thereafter.
    approver(db, pharmacy.id)

    user = User(
        username=_unique_username(db),
        password_hash=auth.hash_password(secrets.token_urlsafe(_PASSWORD_BYTES)),
        # Set here rather than through `pins.set_pin`, which commits, and this
        # row does not exist yet. Hashed the same way every other PIN is, so
        # the check at the prompt is the ordinary one and not a demo path.
        pin_hash=pins.hash_pin(pins.validate(DEMO_PIN)),
        full_name=name[:120],
        role=role,
        active=True,
        is_demo=True,
        demo_expires_at=expires,
        pharmacy_id=pharmacy.id,
        # Sees the whole demonstration group rather than one shop of it: an
        # evaluation that opens on a branch with three of the six screens
        # populated is an evaluation of a different product.
        all_branches=True,
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
