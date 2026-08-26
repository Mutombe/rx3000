"""Short codes for a shared till.

A PIN is not a smaller password. It answers a different question: the password
says *this session belongs to a person*, the PIN says *this person is standing
here now*. On a till that stays signed in all day those are not the same claim,
and the second one is the one an audit trail needs.

The rules exist because four digits is ten thousand combinations:

  - **Never a session.** A PIN unlocks a screen and signs one action. It does not
    log anybody in, so a stolen PIN cannot open a session anywhere.
  - **Rate limited, and locked after a handful of failures.** Without that, ten
    thousand combinations is an afternoon.
  - **Hashed like any other secret**, so a database dump does not hand over the
    codes for every till in the pharmacy.
  - **Refused if it is guessable.** 1234 and 0000 are the first two anybody tries,
    and a repeated digit is the third.

What it is not: a signature. It is deterrence and a record, enough to answer
"who dispensed this" and not enough for a court. Staff sharing PINs defeats it
entirely; the audit trail's job is to make that visible, not impossible.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..auth import hash_password, verify_password
from ..models import User

PIN_LENGTH = 4
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=10)

WEAK = {"0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888",
        "9999", "1234", "4321", "0123", "3210", "1212", "2121"}


class PinError(Exception):
    """Refused, with a sentence a person at a till can act on."""


def _sequential(pin: str) -> bool:
    digits = [int(c) for c in pin]
    steps = {b - a for a, b in zip(digits, digits[1:])}
    return steps in ({1}, {-1})


def validate(pin: str) -> str:
    pin = (pin or "").strip()
    if not pin.isdigit() or len(pin) != PIN_LENGTH:
        raise PinError(f"A PIN is {PIN_LENGTH} digits.")
    if pin in WEAK or _sequential(pin) or len(set(pin)) == 1:
        raise PinError(
            "That PIN is one of the first anybody tries. Choose digits that are "
            "not all the same, in order, or a common pattern.")
    return pin


def set_pin(db: Session, user: User, pin: str) -> None:
    """Set or replace somebody's PIN. The caller proves who they are first."""
    user.pin_hash = hash_password(validate(pin))
    user.pin_set_at = datetime.utcnow()
    user.pin_failures = 0
    user.pin_locked_until = None
    db.commit()


def locked_for(user: User) -> int:
    """Seconds remaining on a lockout, or 0."""
    if not user.pin_locked_until:
        return 0
    remaining = (user.pin_locked_until - datetime.utcnow()).total_seconds()
    return max(0, int(remaining))


def check(db: Session, user: User, pin: str) -> User:
    """Verify a PIN, counting failures. Raises rather than returning False, so a
    caller cannot forget to look at the answer."""
    if not user or not user.pin_hash:
        raise PinError("No PIN is set for that person yet.")

    waiting = locked_for(user)
    if waiting:
        raise PinError(
            f"Too many wrong PINs. Try again in {max(1, waiting // 60)} minute(s), "
            f"or sign in with a password.")

    if not verify_password((pin or "").strip(), user.pin_hash):
        user.pin_failures = (user.pin_failures or 0) + 1
        if user.pin_failures >= MAX_FAILURES:
            user.pin_locked_until = datetime.utcnow() + LOCKOUT
            user.pin_failures = 0
            db.commit()
            raise PinError(
                "That PIN was wrong too many times, so it is locked for ten "
                "minutes. A password still works.")
        left = MAX_FAILURES - user.pin_failures
        db.commit()
        raise PinError(f"That PIN was not accepted. {left} attempt(s) left.")

    user.pin_failures = 0
    user.pin_locked_until = None
    db.commit()
    return user
