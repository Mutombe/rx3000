"""A second signature on a purchase order, above a value the pharmacy sets.

WHY THIS EXISTS

No purchase order needed anybody's approval, at any value. One login could
commit thousands of dollars to a wholesaler, and the first place that showed
up was a bank statement six weeks later. Every other irreversible act in this
system asks for a second person — a stock write-off, a supplier return, a
stock take that adjusts the shelves — and the one that actually spends money
did not.

WHY IT IS A THRESHOLD AND NOT A SWITCH

A pharmacy orders every day. Making a manager sign off a forty dollar top-up
does not add control, it adds a step people learn to click through, and an
approval that is always given is not a control at all. The pharmacy says what
is worth a second look; below it nothing changes.

WHY THE APPROVED VALUE IS KEPT

Otherwise approving a small order and then adding lines to it is a way to get
anything signed off: the approval stays attached while the order grows
underneath it. The value at approval is compared on send, and a changed order
needs looking at again.

WHY THE RAISER CANNOT APPROVE THEIR OWN

That is the whole of the control. One person deciding to spend and the same
person approving it is the arrangement this is meant to prevent, and it is
also the one that turns up in every account of a small business being
defrauded by somebody it trusted.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import PurchaseOrder, User
from . import config

#: Orders worth more than this need a second signature. Nought means every
#: order does; a negative number turns approval off entirely, which is the
#: behaviour a pharmacy had before this existed and is theirs to choose.
SETTING = "orders.approve_over"
DEFAULT_OVER = -1.0


def threshold(db: Session) -> float:
    return config.number(db, SETTING, DEFAULT_OVER)


def value_of(order: PurchaseOrder) -> float:
    """What this order commits, at the costs on it now."""
    return round(sum((i.unit_cost or 0.0) * (i.quantity_ordered or 0)
                     for i in order.items), 2)


def required(db: Session, order: PurchaseOrder) -> bool:
    """Whether this order needs signing off before it can be sent."""
    over = threshold(db)
    if over < 0:
        return False
    return value_of(order) > over


def approved(order: PurchaseOrder) -> bool:
    """Whether a valid approval is attached to what is on the order NOW."""
    if order.approved_at is None:
        return False
    # A changed order is a different order. Compared in cents, because two
    # floats that came from the same arithmetic are not reliably equal.
    return abs(value_of(order) - (order.approved_value or 0.0)) < 0.005


def why_refused(db: Session, order: PurchaseOrder) -> str:
    """Why this cannot be sent yet, in words, or "" when it can.

    Said rather than implied. A disabled button that does not explain itself
    is how a person concludes the software is broken and telephones the order
    through instead, which is the one outcome that defeats the whole control.
    """
    if not required(db, order):
        return ""
    if approved(order):
        return ""
    worth = value_of(order)
    over = threshold(db)
    if order.approved_at is not None:
        return (f"{order.order_number} was approved at {order.approved_value:,.2f} "
                f"and is now worth {worth:,.2f}. A changed order needs looking "
                "at again before it goes.")
    return (f"{order.order_number} is worth {worth:,.2f}, which is over the "
            f"{over:,.2f} this pharmacy asks a second person to sign off. It "
            "needs approving before it can be sent.")


class CannotApprove(Exception):
    """Why this person cannot sign off this order."""


def approve(db: Session, order: PurchaseOrder, *, user: User) -> dict:
    """Sign an order off, at the value it is worth right now."""
    if order.status not in ("draft",):
        raise CannotApprove(
            f"{order.order_number} is {order.status}. Only a draft is waiting "
            "to be approved.")
    if not order.items:
        raise CannotApprove(
            f"{order.order_number} has no lines on it. There is nothing to "
            "approve.")
    if order.created_by_id and order.created_by_id == getattr(user, "id", None):
        raise CannotApprove(
            "You raised this order, so you cannot also approve it. That is the "
            "whole of the control: the person who decides to spend and the "
            "person who signs it off are different people.")

    worth = value_of(order)
    order.approved_by_id = getattr(user, "id", None)
    order.approved_at = datetime.utcnow()
    order.approved_value = worth
    return {
        "approved_value": worth,
        "message": (f"{order.order_number} approved at {worth:,.2f}. It can "
                    "be sent now."),
    }


def awaiting(db: Session) -> list[PurchaseOrder]:
    """Draft orders that are over the threshold and not signed off.

    The queue. Without one an approval step is a thing that happens to
    somebody at the moment they try to send, which is the worst time to
    discover it and the wrong person to discover it.
    """
    over = threshold(db)
    if over < 0:
        return []
    return [o for o in db.query(PurchaseOrder)
            .filter(PurchaseOrder.status == "draft").all()
            if value_of(o) > over and not approved(o)]
