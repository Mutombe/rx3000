"""The four digits that stand between a forwarded link and somebody's record.

WHY EVERY PORTAL NEEDS ONE, INCLUDING THE WHOLESALERS

The link is signed, scoped and expiring, which answers forgery. It does not
answer forwarding, and forwarding is what actually happens: a quotation request
lands in a shared sales inbox and is passed to whoever is free, a patient's SMS
is read out by a relative, a driver's shift link sits in a WhatsApp group. The
URL travels; the code is told to a person. So the code goes in the body of the
message and the link in its own line, and forwarding the link alone opens
nothing.

It applies to companies too. "They are a business, they have their own
security" is an argument about the wholesaler's front door, not about the
message sitting in a mailbox six people read.

WHY THIS IS NOT `pins.py`

`pins.py` is bound to `User`: a member of staff, with a password behind the PIN
and a session to fall back on. Nobody here has either. A patient who is locked
out has no other way in — so the wording of every refusal says how to get back,
which is always the same sentence: ring the pharmacy.

The hashing is `pins.py`'s, unchanged and for its stated reasons: the code is
mixed with the application secret before it is stretched, so a stolen database
is not enough to attack four digits, and the online guessing is answered by the
lockout rather than by the work factor.

WHAT THIS REPLACES

The patient's code was kept in clear text in `patients.portal_code`, written
unhashed, and returned to the staff screen in the clear. A pharmacy's database
backup therefore carried the working code to every patient portal in the shop.
That is now a hash like any other secret, and the counter sees a code once,
when it is issued, which is the only moment anybody needs to read it out.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import pins

#: Wrong tries before the link stops answering. Four digits is ten thousand
#: combinations; five tries and a wait is what makes that a wall rather than an
#: afternoon.
MAX_TRIES = 5
LOCK_MINUTES = 15

#: The columns every portal subject carries. Named identically on `Patient`,
#: `Supplier`, `Doctor` and `Driver` on purpose, so this module needs to know
#: nothing about which kind of row it has been handed.
HASH = "portal_pin_hash"
SET_AT = "portal_pin_set_at"
FAILED = "portal_failed"
LOCKED = "portal_locked_until"
SEEN = "portal_last_seen"


class PortalPinError(RuntimeError):
    """Refused, with the sentence to show the person who was refused.

    Every message here ends somewhere a person can actually go, because
    nobody reading it has a password to fall back on.
    """


def has_pin(subject) -> bool:
    return bool(getattr(subject, HASH, "") or "")


def locked_for(subject) -> int:
    """Seconds left on a lockout, or 0."""
    until = getattr(subject, LOCKED, None)
    if not until:
        return 0
    return max(0, int((until - datetime.utcnow()).total_seconds()))


def generate() -> str:
    """A code worth having.

    `secrets` rather than `random`: four digits is a small space already and a
    predictable generator makes it a certainty. Re-rolled rather than accepted
    when it lands on one of the patterns anybody tries first — 1234 generated
    by chance is as guessable as 1234 chosen on purpose.
    """
    while True:
        code = f"{secrets.randbelow(10000):04d}"
        try:
            return validate(code)
        except PortalPinError:
            continue


def validate(code: str) -> str:
    """The digits, or a refusal naming what is wrong with them."""
    code = (code or "").strip()
    if not code.isdigit() or len(code) != pins.PIN_LENGTH:
        raise PortalPinError(f"A code is {pins.PIN_LENGTH} digits.")
    if code in pins.WEAK or len(set(code)) == 1:
        raise PortalPinError(
            "That code is one of the first anybody tries. Choose digits that "
            "are not all the same or in order.")
    # `pins._sequential` is the same test staff PINs are held to.
    if pins._sequential(code):
        raise PortalPinError(
            "That code is one of the first anybody tries. Choose digits that "
            "are not all the same or in order.")
    return code


def issue(db: Session, subject, code: str = "") -> str:
    """Set a code and hand it back once.

    The returned string is the only time the plain code exists outside the
    person's head: it is shown to the member of staff issuing it, or put in
    the message the link is sent with, and then it is a hash. Nothing reads it
    back out of the database afterwards, because nothing can.
    """
    code = validate(code) if code else generate()
    setattr(subject, HASH, pins.hash_pin(code))
    setattr(subject, SET_AT, datetime.utcnow())
    setattr(subject, FAILED, 0)
    setattr(subject, LOCKED, None)
    db.commit()
    return code


def clear(db: Session, subject) -> None:
    """Take the code away, closing the portal for this subject."""
    setattr(subject, HASH, "")
    setattr(subject, SET_AT, None)
    setattr(subject, FAILED, 0)
    setattr(subject, LOCKED, None)
    db.commit()


def check(db: Session, subject, code: str) -> None:
    """Verify a code, counting failures. Raises rather than returning False,
    so a caller cannot forget to look at the answer."""
    now = datetime.utcnow()

    waiting = locked_for(subject)
    if waiting:
        raise PortalPinError(
            f"Too many tries. Please wait {max(1, waiting // 60)} minute(s), "
            f"or ring the pharmacy and they will give you a new code.")

    if not has_pin(subject):
        raise PortalPinError(
            "There is no code on this link yet. Ring the pharmacy and they "
            "will give you one.")

    matched, stale = pins.verify_pin((code or "").strip(),
                                     getattr(subject, HASH))
    if not matched:
        tried = (getattr(subject, FAILED, 0) or 0) + 1
        setattr(subject, FAILED, tried)
        left = MAX_TRIES - tried
        if left <= 0:
            setattr(subject, LOCKED, now + timedelta(minutes=LOCK_MINUTES))
            setattr(subject, FAILED, 0)
            db.commit()
            raise PortalPinError(
                f"That code is wrong, and this link is now closed for "
                f"{LOCK_MINUTES} minutes. Ring the pharmacy if you need it "
                f"sooner.")
        db.commit()
        # Said as a count rather than "invalid code", because a person who can
        # see how many tries are left stops guessing and rings; one who cannot
        # keeps guessing until the link closes and then rings anyway, crosser.
        raise PortalPinError(
            f"That code is not right. {left} more "
            f"{'try' if left == 1 else 'tries'} before the link closes for a "
            f"while.")

    # Only written when there is something to write. The happy path is the one
    # somebody is standing there waiting on.
    changed = False
    if getattr(subject, FAILED, 0):
        setattr(subject, FAILED, 0)
        changed = True
    if getattr(subject, LOCKED, None) is not None:
        setattr(subject, LOCKED, None)
        changed = True
    if stale:
        # A code written before this scheme, rewritten now that the only thing
        # that cannot be recovered from the database is in hand.
        setattr(subject, HASH, pins.hash_pin((code or "").strip()))
        changed = True
    if hasattr(subject, SEEN):
        setattr(subject, SEEN, now)
        changed = True
    if changed:
        db.commit()
