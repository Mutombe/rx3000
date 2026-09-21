"""Signing off who won, before the orders are raised.

WHY THE APPROVAL IS ON THE AWARD AND NOT ON THE REQUEST

Asking three wholesalers for a price commits the pharmacy to nothing. Deciding
which of them gets the business commits it to the money, and that is the
decision somebody asks about afterwards. So nobody has to sign off a request
going out; somebody has to sign off who won.

WHY IT ASKS FOR A REASON WHEN THE CHEAPEST LOSES

This is the part worth having.

The cheapest quote is frequently the wrong buy, for reasons that are perfectly
good on the day and completely unrecoverable six weeks later: they could not
deliver until the 20th, they short-delivered the last three orders, the price
was for a pack size we cannot split. A buyer who knows all that picks the
dearer supplier, and by the time anybody looks at the file the only thing
recorded is that the pharmacy paid more than it had to.

So the reason is asked for at the one moment somebody actually knows it, and
only when it is needed. Pick the cheapest on every line and there is nothing
to explain and nothing to type.

WHY A THRESHOLD RATHER THAN ALWAYS

A pharmacy buys every day. Making a manager sign off a forty dollar award does
not add control, it adds a step people learn to click through, and an approval
that is always given is not a control. Same reasoning, and the same shape, as
the purchase order threshold in `order_approval`; a pharmacy can set them
independently because they guard different things.

WHY THE BUYER CANNOT APPROVE THEIR OWN AWARD

That is the whole of it. One person choosing which supplier gets the money and
the same person approving the choice is the arrangement this exists to
prevent, and it is the one that turns up in every account of a small business
being defrauded by somebody it trusted.

WHAT IS APPROVED IS WHAT GETS RAISED

The choices are written to the lines when the award is proposed, not held on
somebody's screen. Otherwise the approval is attached to a decision that no
longer exists: a manager signs off Datlabs at 12.40 and the orders go to
whoever the buyer had picked by the time they pressed the button.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Rfq, RfqLine, RfqSupplier, User
from . import config

#: Awards worth more than this need a second signature. Nought means every
#: award does; a negative number turns it off, which is how a pharmacy
#: behaved before this existed and is theirs to choose.
SETTING = "rfqs.approve_over"
DEFAULT_OVER = -1.0


class AwardError(Exception):
    """Why this cannot be done, in words for the person trying."""


def threshold(db: Session) -> float:
    return config.number(db, SETTING, DEFAULT_OVER)


def _quote_for(invited: RfqSupplier, line: RfqLine):
    return next((q for q in invited.quotes if q.rfq_line_id == line.id), None)


def value_of(db: Session, rfq: Rfq) -> float:
    """What the award as it stands commits the pharmacy to."""
    total = 0.0
    for line in rfq.lines:
        invited = line.chosen
        if invited is None:
            continue
        quote = _quote_for(invited, line)
        if quote and quote.available:
            total += (quote.unit_price or 0.0) * (line.quantity or 0)
    return round(total, 2)


def dearer_than_cheapest(db: Session, rfq: Rfq) -> list[dict]:
    """Every line where the chosen supplier is not the cheapest that quoted.

    The list a second person actually reads. Not a warning that something is
    wrong, because it routinely is not: it is the list of decisions that need
    a sentence beside them.
    """
    out = []
    for line in rfq.lines:
        invited = line.chosen
        if invited is None:
            continue
        mine = _quote_for(invited, line)
        if mine is None or not mine.available:
            continue
        priced = [(i, _quote_for(i, line)) for i in rfq.invited]
        priced = [(i, q) for i, q in priced
                  if q is not None and q.available and q.unit_price]
        if not priced:
            continue
        best_invited, best = min(priced, key=lambda pair: pair[1].unit_price)
        if best_invited.id == invited.id:
            continue
        extra = round(((mine.unit_price or 0.0) - (best.unit_price or 0.0))
                      * (line.quantity or 0), 2)
        if extra <= 0:
            continue
        out.append({
            "rfq_line_id": line.id,
            "product": (f"{line.product.name} {line.product.strength or ''}".strip()
                        if line.product else f"#{line.product_id}"),
            "chosen": invited.supplier.name if invited.supplier else "",
            "chosen_price": round(mine.unit_price or 0.0, 4),
            "chosen_lead_days": mine.lead_days,
            "cheapest": best_invited.supplier.name if best_invited.supplier else "",
            "cheapest_price": round(best.unit_price or 0.0, 4),
            "cheapest_lead_days": best.lead_days,
            "extra": extra,
        })
    return out


def required(db: Session, rfq: Rfq) -> bool:
    """Whether this award needs signing off before orders can be raised."""
    over = threshold(db)
    if over < 0:
        return False
    return value_of(db, rfq) > over


def approved(db: Session, rfq: Rfq) -> bool:
    """Whether a valid approval is attached to the award AS IT STANDS NOW."""
    if rfq.approved_at is None:
        return False
    # A changed award is a different award. Compared in cents, because two
    # floats that came from the same arithmetic are not reliably equal.
    return abs(value_of(db, rfq) - (rfq.approved_value or 0.0)) < 0.005


def propose(db: Session, rfq: Rfq, *, picks: list[dict], user: User | None,
            reason: str = "") -> dict:
    """Write down who won, and put it up for approval where one is needed.

    The choices are written to the lines here rather than held on the screen,
    so what a second person approves is what gets raised. See the note at the
    top of this file.
    """
    if rfq.status in ("closed", "cancelled"):
        raise AwardError(f"{rfq.reference} is {rfq.status}. Nothing more can "
                         "be awarded on it.")
    if not picks:
        raise AwardError("Nothing was chosen. Pick a supplier for at least "
                         "one line.")

    chosen: dict[int, int] = {}
    for pick in picks:
        line = db.get(RfqLine, int(pick.get("rfq_line_id") or 0))
        invited = db.get(RfqSupplier, int(pick.get("rfq_supplier_id") or 0))
        if line is None or invited is None or line.rfq_id != rfq.id \
                or invited.rfq_id != rfq.id:
            raise AwardError("One of those choices does not belong to this "
                             "request.")
        quote = _quote_for(invited, line)
        if quote is None or not quote.available:
            raise AwardError(
                f"{invited.supplier.name if invited.supplier else 'That supplier'} "
                "did not quote a price for one of the lines chosen.")
        chosen[line.id] = invited.id

    for line in rfq.lines:
        line.chosen_rfq_supplier_id = chosen.get(line.id)

    # An award that changes is no longer the award that was signed off.
    rfq.approved_by_id = None
    rfq.approved_at = None
    rfq.approved_value = 0.0

    rfq.awarded_by_id = getattr(user, "id", None)
    rfq.awarded_at = datetime.utcnow()
    rfq.award_reason = (reason or "").strip()[:500]

    dearer = dearer_than_cheapest(db, rfq)
    if dearer and not rfq.award_reason:
        raise AwardError(
            "The cheapest quote did not win on "
            + (f"{len(dearer)} lines" if len(dearer) > 1 else "one line")
            + ", which costs "
            + f"{sum(d['extra'] for d in dearer):,.2f} more. Say why, in a "
            "sentence. It is usually a perfectly good reason and it is "
            "unrecoverable six weeks from now.")

    worth = value_of(db, rfq)
    if required(db, rfq):
        rfq.status = "awaiting_approval"
        return {
            "status": rfq.status,
            "value": worth,
            "needs_approval": True,
            "message": (f"{rfq.reference} is worth {worth:,.2f}, over the "
                        f"{threshold(db):,.2f} this pharmacy asks a second "
                        "person to sign off. It is waiting for approval."),
        }
    return {"status": rfq.status, "value": worth, "needs_approval": False,
            "message": f"{len(chosen)} line(s) awarded, worth {worth:,.2f}."}


def why_refused(db: Session, rfq: Rfq) -> str:
    """Why the orders cannot be raised yet, in words, or "" when they can.

    Said rather than implied. A disabled button that does not explain itself
    is how a person concludes the software is broken and telephones the order
    through instead, which defeats the whole control.
    """
    if not required(db, rfq):
        return ""
    if approved(db, rfq):
        return ""
    worth = value_of(db, rfq)
    if rfq.approved_at is not None:
        return (f"{rfq.reference} was approved at {rfq.approved_value:,.2f} "
                f"and the award is now worth {worth:,.2f}. A changed award "
                "needs looking at again before the orders go out.")
    return (f"{rfq.reference} is worth {worth:,.2f}, which is over the "
            f"{threshold(db):,.2f} this pharmacy asks a second person to sign "
            "off. It needs approving before the orders can be raised.")


def approve(db: Session, rfq: Rfq, *, user: User) -> dict:
    """Sign the award off, at what it is worth right now."""
    if rfq.status in ("closed", "cancelled"):
        raise AwardError(f"{rfq.reference} is {rfq.status}.")
    if not any(l.chosen_rfq_supplier_id for l in rfq.lines):
        raise AwardError(f"Nothing has been awarded on {rfq.reference} yet, "
                         "so there is nothing to approve.")
    if rfq.awarded_by_id and rfq.awarded_by_id == getattr(user, "id", None):
        raise AwardError(
            "You chose these suppliers, so you cannot also approve the "
            "choice. That is the whole of the control: the person who decides "
            "where the money goes and the person who signs it off are "
            "different people.")

    worth = value_of(db, rfq)
    rfq.approved_by_id = getattr(user, "id", None)
    rfq.approved_at = datetime.utcnow()
    rfq.approved_value = worth
    rfq.status = "sent"
    return {"approved_value": worth,
            "message": (f"{rfq.reference} approved at {worth:,.2f}. The "
                        "orders can be raised now.")}


def send_back(db: Session, rfq: Rfq, *, user: User, reason: str) -> dict:
    """Refuse the award and say why, so the buyer can choose again.

    A refusal with no reason is one the buyer cannot act on, so they propose
    the same thing again and the second person refuses it again. The reason is
    required for the same purpose the award's own reason is: it is the only
    record of a decision that otherwise leaves none.
    """
    said = (reason or "").strip()
    if not said:
        raise AwardError("Say why it is going back. A refusal the buyer "
                         "cannot act on is one that produces the same "
                         "proposal again tomorrow.")
    if rfq.awarded_by_id and rfq.awarded_by_id == getattr(user, "id", None):
        raise AwardError("You made this award yourself. Change it rather than "
                         "sending it back to yourself.")

    rfq.status = "sent"
    rfq.approved_by_id = None
    rfq.approved_at = None
    rfq.approved_value = 0.0
    rfq.award_refused_reason = said[:500]
    rfq.award_refused_by_id = getattr(user, "id", None)
    rfq.award_refused_at = datetime.utcnow()
    return {"message": f"{rfq.reference} sent back to whoever awarded it."}


def awaiting(db: Session) -> list[Rfq]:
    """Awards waiting for a second signature.

    The queue. Without one, approval is a thing that happens to somebody at
    the moment they try to raise the orders, which is the worst time to
    discover it and the wrong person to discover it.
    """
    return (db.query(Rfq)
            .filter(Rfq.status == "awaiting_approval")
            .order_by(Rfq.awarded_at.asc()).all())


def state(db: Session, rfq: Rfq) -> dict:
    """Everything a screen needs to know about where the award stands."""
    over = threshold(db)
    return {
        "threshold": over,
        "approval_used": over >= 0,
        "value": value_of(db, rfq),
        "needs_approval": required(db, rfq),
        "approved": approved(db, rfq),
        "approved_at": rfq.approved_at,
        "approved_by": (rfq.approved_by.full_name
                        if getattr(rfq, "approved_by", None) else ""),
        "awarded_at": rfq.awarded_at,
        "awarded_by": (rfq.awarded_by.full_name
                       if getattr(rfq, "awarded_by", None) else ""),
        "award_reason": rfq.award_reason or "",
        "refused_reason": rfq.award_refused_reason or "",
        "refused_by": (rfq.award_refused_by.full_name
                       if getattr(rfq, "award_refused_by", None) else ""),
        "refused_at": rfq.award_refused_at,
        "dearer_lines": dearer_than_cheapest(db, rfq),
        "why_refused": why_refused(db, rfq),
        "chosen": {l.id: l.chosen_rfq_supplier_id for l in rfq.lines
                   if l.chosen_rfq_supplier_id},
    }
