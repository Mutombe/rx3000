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
import hashlib
import hmac
import os
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..auth import verify_password
from ..config import settings
from ..models import User

PIN_LENGTH = 4
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=10)

# ---------------------------------------------------------------- how it is kept
#
# WHY A PIN IS NOT HASHED LIKE A PASSWORD, AND WHY THAT IS NOT A WEAKENING.
#
# A password is hashed slowly because it has entropy worth defending: 200,000
# PBKDF2 rounds multiply an attacker's cost across a search space too large to
# enumerate. That reasoning does not carry to four digits. Ten thousand
# combinations at 200,000 rounds is about twenty minutes of one CPU core per
# user, and PBKDF2-SHA256 is exactly the shape a GPU eats, so it is seconds on
# real hardware. The work factor was buying nothing here. It was being paid in
# full by every dispenser unlocking a till, 150ms at a time, several times a
# day.
#
# What actually defends a four digit code is that it cannot be attacked at all
# without the server's own key. So the code is mixed with the application
# secret before it is stretched: a stolen database is not enough, the attacker
# needs the deployment's secret too, and with it they would already be forging
# sessions. The rounds that remain are there for the case where that secret is
# weak, not as the primary defence.
#
# Online guessing is answered where it always was, by MAX_FAILURES and the
# lockout below, which is the control that was doing the real work all along.
#
# Passwords are untouched and still take the full 200,000. See app/auth.py.
PIN_ROUNDS = 15_000
_PIN_V2 = "pin2"
#: Domain separation, so this use of the application secret cannot interact
#: with the others (session tokens, portal links) that share it.
_PEPPER_LABEL = b"rx5000.pin.v2:"


def _digest(pin: str, salt: bytes) -> bytes:
    keyed = hmac.new(settings.SECRET_KEY.encode(),
                     _PEPPER_LABEL + salt + pin.encode(), hashlib.sha256).digest()
    return hashlib.pbkdf2_hmac("sha256", keyed, salt, PIN_ROUNDS)


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    return f"{_PIN_V2}${salt.hex()}${_digest(pin, salt).hex()}"


def verify_pin(pin: str, stored: str) -> tuple[bool, bool]:
    """Check a PIN. Returns (whether it matched, whether it should be rewritten).

    Codes set before this existed are PBKDF2 over the raw digits, in the same
    format a password uses. They still verify, at the old cost, and the second
    flag asks the caller to write the code back in the new form now that it has
    the only thing that cannot be recovered from the database: the PIN itself.
    """
    pin = (pin or "").strip()
    if not stored:
        return False, False
    if stored.startswith(_PIN_V2 + "$"):
        try:
            _, salt_hex, want = stored.split("$")
            # Constant time: a comparison that returns early on the first wrong
            # byte tells an attacker how much of a guess was right.
            return hmac.compare_digest(
                _digest(pin, bytes.fromhex(salt_hex)).hex(), want), False
        except Exception:
            return False, False
    return verify_password(pin, stored), True

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
    user.pin_hash = hash_pin(validate(pin))
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

    matched, stale = verify_pin(pin, user.pin_hash)
    if not matched:
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

    # Only write when there is something to write.
    #
    # This used to commit on every single unlock, resetting a failure count that
    # was already zero and clearing a lockout that was already clear. On SQLite
    # that is a few milliseconds nobody notices. Against the production database,
    # which is in another continent from the pharmacy, it is a network round trip
    # on the one path where somebody is standing at a till waiting for the screen
    # to come back.
    changed = False
    if user.pin_failures:
        user.pin_failures = 0
        changed = True
    if user.pin_locked_until is not None:
        user.pin_locked_until = None
        changed = True
    # A code from before the cheap scheme, rewritten now that the PIN itself is
    # in hand. It costs one write, once, and every unlock after it is fast.
    if stale:
        user.pin_hash = hash_pin(pin.strip())
        changed = True
    if changed:
        db.commit()
    return user
