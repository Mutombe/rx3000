"""The wholesaler's own view of the orders a pharmacy has sent them.

WHY THIS EXISTS

The quotation portal removed one telephone call: the pharmacy no longer rings
round for prices. This removes the other one, which is the commoner of the
two and goes the other way.

"When is it coming." A pharmacy sends an order and then waits, with no way to
tell an order the wholesaler is packing from one that fell off a fax machine.
So somebody rings, gets told "Thursday" by whoever answered, writes Thursday
on a scrap of paper, and the answer lives on that scrap. If they are told
three lines are short, that lives there too, until the van arrives without
them.

WHAT A SUPPLIER CAN DO HERE, AND WHAT THEY CANNOT

They can say they have the order, when it will arrive, how much of each line
they will actually send, and anything they need to add. That is the whole of
it.

They cannot change a price, a quantity ordered, or anything else the pharmacy
decided. A portal where the other side of a transaction can edit the
transaction is not a portal, it is a shared document with no owner, and the
first dispute about what was agreed ends it. What they say is recorded AS
WHAT THEY SAID, beside what the pharmacy ordered, and the two are compared
rather than merged.

CONFIRMING LESS THAN WAS ORDERED IS THE POINT

A wholesaler who can only send sixty of the hundred is not being difficult;
they are telling the pharmacy something worth knowing on Monday rather than
on Thursday when the van arrives. A NULL confirmed quantity means they have
not said, which is a different fact from confirming nought, and the two are
kept apart for the same reason the quotation comparison keeps silence apart
from a price of nothing.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import PurchaseOrder, PurchaseOrderItem, Supplier

#: A quoting link is for one request and dies with it. This one is for a
#: standing trading relationship, so it lives longer and is re-issued rather
#: than renewed. Still not forever: a link in a forwarded email is a
#: permanent leak if it never expires.
TTL = 90 * 24 * 3600

#: How far back their own history goes on the page. Enough to settle "we sent
#: that in July" without turning the screen into an archive.
RECENT_DAYS = 120


class PortalError(Exception):
    """Why a wholesaler cannot do that, in words they will read."""


def _line(item: PurchaseOrderItem) -> dict:
    product = item.product
    name = (product.name if product else f"#{item.product_id}")
    strength = (product.strength or "") if product else ""
    if strength and strength.lower() not in name.lower():
        name = f"{name} {strength}"
    return {
        "item_id": item.id,
        "product": name,
        "code": ((product.stock_code or product.barcode or "")
                 if product else ""),
        "pack": (product.pack_size if product else "") or "",
        "quantity_ordered": item.quantity_ordered or 0,
        # NULL means they have not said. Not nought.
        "quantity_confirmed": item.quantity_confirmed,
        "unit_cost": round(item.unit_cost or 0.0, 4),
    }


def _order(order: PurchaseOrder) -> dict:
    lines = [_line(i) for i in order.items]
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "sent_at": order.sent_at,
        "created_at": order.created_at,
        "received_at": order.received_at,
        "acknowledged_at": order.acknowledged_at,
        "promised_date": order.promised_date,
        "supplier_note": order.supplier_note or "",
        "notes": order.notes or "",
        "lines": lines,
        "value": round(sum((i["unit_cost"] * i["quantity_ordered"])
                           for i in lines), 2),
        # What this order is waiting on, said from THEIR side of it.
        "needs_answer": bool(order.status == "sent" and not order.acknowledged_at),
    }


def view(db: Session, supplier: Supplier, *, pharmacy_name: str = "") -> dict:
    """Everything this wholesaler can see: their orders, newest first."""
    since = datetime.utcnow() - timedelta(days=RECENT_DAYS)
    rows = (
        db.query(PurchaseOrder)
        .options(joinedload(PurchaseOrder.items))
        .filter(PurchaseOrder.supplier_id == supplier.id)
        # A draft is the pharmacy's own thinking and is none of their
        # business until it is sent.
        .filter(PurchaseOrder.status != "draft")
        .filter(PurchaseOrder.created_at >= since)
        .order_by(PurchaseOrder.created_at.desc())
        .limit(50)
        .all()
    )
    orders = [_order(o) for o in rows]
    return {
        "supplier": supplier.name,
        "pharmacy": pharmacy_name,
        "orders": orders,
        # The only number on the page that is asking them for something.
        "waiting": sum(1 for o in orders if o["needs_answer"]),
        "note": ("You can confirm what you are sending and when. Prices and "
                 "quantities ordered are the pharmacy's and cannot be "
                 "changed here."),
    }


def acknowledge(db: Session, supplier: Supplier, order: PurchaseOrder, *,
                promised: str = "", note: str = "",
                lines: list[dict] | None = None) -> dict:
    """Record what the wholesaler says about one order."""
    if order.supplier_id != supplier.id:
        raise PortalError("That order was not sent to you.")
    if order.status == "cancelled":
        raise PortalError(
            f"{order.order_number} was cancelled. Please ring the pharmacy "
            "rather than sending anything against it.")
    if order.status == "received":
        raise PortalError(
            f"{order.order_number} has already been received, so there is "
            "nothing left to confirm.")

    when: date | None = None
    if promised:
        try:
            when = date.fromisoformat(promised)
        except ValueError:
            raise PortalError("Enter the date as YYYY-MM-DD.") from None
        if when < date.today():
            raise PortalError("That date has already passed. Give the date "
                              "you expect to deliver.")

    by_item = {i.id: i for i in order.items}
    said = 0
    for line in (lines or []):
        item = by_item.get(int(line.get("item_id") or 0))
        if item is None:
            continue
        given = line.get("quantity_confirmed")
        if given in (None, ""):
            # Leaving a line alone is allowed, and is not the same as
            # confirming nought. See the note at the top of this file.
            continue
        try:
            want = int(given)
        except (TypeError, ValueError):
            raise PortalError("Quantities have to be whole numbers.") from None
        if want < 0:
            raise PortalError("A quantity cannot be less than nought.")
        # More than was ordered is refused rather than silently accepted: a
        # pharmacy that ordered ten does not want thirty arriving, and this
        # is almost always a typing slip.
        if want > (item.quantity_ordered or 0):
            raise PortalError(
                f"{_line(item)['product']} was ordered "
                f"{item.quantity_ordered}. You cannot confirm more than was "
                "asked for; ring the pharmacy if you want to offer more.")
        item.quantity_confirmed = want
        said += 1

    order.acknowledged_at = datetime.utcnow()
    order.promised_date = when
    order.supplier_note = (note or "").strip()[:500]

    short = [i for i in order.items
             if i.quantity_confirmed is not None
             and i.quantity_confirmed < (i.quantity_ordered or 0)]
    return {
        "order_number": order.order_number,
        "acknowledged_at": order.acknowledged_at,
        "promised_date": order.promised_date,
        "lines_confirmed": said,
        "lines_short": len(short),
        "message": (
            f"Thank you. {order.order_number} is confirmed"
            + (f" for {when:%d %B}" if when else "")
            + (f", with {len(short)} line(s) short of what was ordered"
               if short else "")
            + ". The pharmacy can see this now."),
    }
