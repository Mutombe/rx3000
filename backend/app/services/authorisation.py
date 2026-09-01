"""Pre-authorisation: asking a funder to commit before the medicine leaves the shelf.

The naive version of this feature stores an authorisation number against a claim.
That version fails in a specific and expensive way, and it is worth being clear
about why, because it is the shape most systems get wrong.

An authorisation is a **promise with three limits**: a validity window, a
quantity, and an amount. A pharmacy holding authorisation number A12345 for six
months' supply will happily dispense the seventh month, or dispense in March
against an authorisation that lapsed in February, and the claim is rejected
weeks later, after the medicine has gone. By then it is a bad debt, not a
decision.

So consumption is tracked here, and `check()` is what the dispensing path asks
before it commits. What is left on an authorisation is a fact derived from draws
against it, not a field somebody remembered to decrement.

Reversals matter for the same reason: a voided or credit-noted sale must give
the authorisation back, or a patient loses cover they never used.
"""
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from ..models import Authorisation, AuthorisationUse

# States in which an authorisation can still be drawn against.
USABLE = ("approved", "partial")


class AuthorisationError(ValueError):
    """Raised when an authorisation cannot be used for what is being asked."""


@dataclass
class Balance:
    quantity_authorised: float
    quantity_used: float
    quantity_remaining: float
    amount_authorised: float
    amount_used: float
    amount_remaining: float


def balance(auth: Authorisation) -> Balance:
    """What is left, computed from the draws rather than stored."""
    live = [u for u in auth.uses if not u.reversed]
    quantity_used = round(sum(u.quantity for u in live), 3)
    amount_used = round(sum(u.amount for u in live), 2)
    return Balance(
        quantity_authorised=auth.approved_quantity or 0.0,
        quantity_used=quantity_used,
        quantity_remaining=round((auth.approved_quantity or 0.0) - quantity_used, 3),
        amount_authorised=auth.approved_amount or 0.0,
        amount_used=amount_used,
        amount_remaining=round((auth.approved_amount or 0.0) - amount_used, 2),
    )


def effective_status(auth: Authorisation, today: date | None = None) -> str:
    """The status as it actually stands, not as it was when the funder answered.

    An approved authorisation becomes expired or exhausted on its own, without
    anyone touching it, so the stored status is never trusted for those two.
    """
    if auth.status not in USABLE:
        return auth.status
    today = today or date.today()
    if auth.valid_to and today > auth.valid_to:
        return "expired"
    if auth.valid_from and today < auth.valid_from:
        return "pending_start"
    left = balance(auth)
    if auth.approved_quantity and left.quantity_remaining <= 0:
        return "exhausted"
    if auth.approved_amount and left.amount_remaining <= 0.005:
        return "exhausted"
    return auth.status


def check(auth: Authorisation, quantity: float = 0.0, amount: float = 0.0,
          today: date | None = None) -> dict:
    """Can this authorisation cover this dispensing, right now?

    Returns rather than raises, because the till needs to *show* the reason —
    "authorised until 14 July" is actionable, an exception is not.
    """
    today = today or date.today()
    status = effective_status(auth, today)
    left = balance(auth)
    reasons = []

    if status == "expired":
        reasons.append(f"The authorisation expired on {auth.valid_to:%d %b %Y}.")
    elif status == "pending_start":
        reasons.append(f"The authorisation is not valid until {auth.valid_from:%d %b %Y}.")
    elif status == "exhausted":
        reasons.append("The authorisation has been fully used.")
    elif status not in USABLE:
        reasons.append(f"The authorisation is {status}, not approved.")

    if not reasons:
        if quantity and auth.approved_quantity and quantity > left.quantity_remaining + 1e-6:
            reasons.append(
                f"Only {left.quantity_remaining:g} of {left.quantity_authorised:g} "
                f"remain authorised; {quantity:g} was requested.")
        if amount and auth.approved_amount and amount > left.amount_remaining + 0.005:
            reasons.append(
                f"Only {left.amount_remaining:.2f} {auth.currency_code} remains "
                f"authorised; {amount:.2f} was requested.")

    return {
        "usable": not reasons,
        "status": status,
        "reasons": reasons,
        "authorisation_number": auth.authorisation_number,
        "valid_from": auth.valid_from,
        "valid_to": auth.valid_to,
        **left.__dict__,
    }


def consume(db: Session, auth: Authorisation, quantity: float = 0.0, amount: float = 0.0,
            reference: str = "", claim_id: int | None = None,
            today: date | None = None) -> AuthorisationUse:
    """Draw against an authorisation. Refuses if it would exceed what was granted."""
    verdict = check(auth, quantity, amount, today)
    if not verdict["usable"]:
        raise AuthorisationError(" ".join(verdict["reasons"]))
    use = AuthorisationUse(authorisation_id=auth.id, quantity=quantity, amount=amount,
                           reference=reference, claim_id=claim_id)
    db.add(use)
    db.flush()
    auth.uses.append(use)
    # Mark exhaustion the moment it happens, so a listing shows the truth without
    # every caller having to recompute it.
    if effective_status(auth, today) == "exhausted":
        auth.status = "exhausted"
    db.commit()
    return use


def release(db: Session, reference: str = "", claim_id: int | None = None) -> int:
    """Give back what a reversed sale had drawn.

    A void or a credit note means the medicine came back over the counter. If the
    authorisation is not released with it, the patient has silently lost cover
    they never received, which surfaces as an unexplained rejection the next
    time they collect.
    """
    query = db.query(AuthorisationUse).filter(AuthorisationUse.reversed.is_(False))
    if claim_id is not None:
        query = query.filter(AuthorisationUse.claim_id == claim_id)
    elif reference:
        query = query.filter(AuthorisationUse.reference == reference)
    else:
        return 0

    released = 0
    for use in query.all():
        use.reversed = True
        released += 1
        auth = use.authorisation
        # An exhausted authorisation that gets stock back is usable again.
        if auth and auth.status == "exhausted" and balance(auth).quantity_remaining > 0:
            auth.status = "approved"
    db.commit()
    return released


def next_reference(db: Session) -> str:
    count = db.query(Authorisation).count() + 1
    return f"AUTH{datetime.utcnow():%y%m}{count:05d}"


def summarise(db: Session, auth: Authorisation, today: date | None = None) -> dict:
    """One authorisation as the UI shows it: the decision, the limits, what is left."""
    left = balance(auth)
    return {
        "id": auth.id,
        "reference": auth.reference,
        "authorisation_number": auth.authorisation_number,
        "funder_id": auth.funder_id,
        "switch_id": auth.switch_id,
        "patient_id": auth.patient_id,
        "policy_number": auth.policy_number,
        "product_id": auth.product_id,
        "description": auth.description,
        "icd10_code": auth.icd10_code,
        "motivation": auth.motivation,
        "requested_quantity": auth.requested_quantity,
        "requested_amount": auth.requested_amount,
        "currency_code": auth.currency_code,
        "valid_from": auth.valid_from,
        "valid_to": auth.valid_to,
        "status": auth.status,
        "effective_status": effective_status(auth, today),
        "decision_reason": auth.decision_reason,
        "conditions": auth.conditions,
        "switch_reference": auth.switch_reference,
        "transaction_id": auth.transaction_id,
        "created_at": auth.created_at,
        "decided_at": auth.decided_at,
        "uses": [{"id": u.id, "quantity": u.quantity, "amount": u.amount,
                  "reference": u.reference, "claim_id": u.claim_id,
                  "reversed": u.reversed, "created_at": u.created_at}
                 for u in auth.uses],
        **left.__dict__,
    }
