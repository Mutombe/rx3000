"""Actually sending a purchase order to the wholesaler.

WHAT "SEND" USED TO MEAN

It set a string to "sent". The order did not go anywhere. `Supplier.email`
had been stored since suppliers existed and was never read by anything, and
afterwards there was no way to tell an order that had reached a wholesaler
from one somebody had clicked a button on. The first anybody knew was a
telephone call saying no order had ever arrived, and by then the answer to
"did we send it" was a shrug.

That is worse than having no button. A button that claims to have done
something is trusted, and a pharmacy plans around stock it believes is coming.

WHAT IT MEANS NOW

The order is written out as a document, emailed to the address on the
supplier record, and the fact of it recorded: when, by whom, and the address
it actually went to — that last one because the supplier record changes, and
six weeks later "which address did it go to" is the only question that
matters.

WHY THE DOCUMENT IS PLAIN TEXT

A wholesaler's order desk reads it, prints it, or pastes it into their own
system. Every one of those is easier with text than with an attachment, and
a PDF that cannot be opened on the machine behind the counter is a purchase
order nobody can fill. The same text is what the screen prints, so the copy
on file and the copy that was sent are the same document.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Product, PurchaseOrder, Supplier, User
from . import messaging


def _named(product: Product) -> str:
    """The medicine, without saying its strength twice.

    Plenty of catalogues carry the strength inside the name already, so
    appending it produced "Amoxicillin 500mg 500mg" on a document going to
    somebody else's order desk.
    """
    name = (product.name or "").strip()
    strength = (product.strength or "").strip()
    if strength and strength.lower() not in name.lower():
        return f"{name} {strength}"
    return name


def _line(product_name: str, qty: int, cost: float, code: str) -> str:
    return f"{qty:>6}  {(code or 'no code'):<14}  {product_name[:44]:<44}  {cost:>10,.2f}"


def document(db: Session, order: PurchaseOrder, *, pharmacy_name: str = "") -> str:
    """The order, as the wholesaler's order desk will read it.

    Quantities first. An order desk picks by quantity and code, and a document
    that leads with a forty character medicine name makes them hunt for the
    number that tells them how many to put in the box.
    """
    supplier = db.get(Supplier, order.supplier_id) if order.supplier_id else None
    products = {
        p.id: p for p in db.query(Product).filter(
            Product.id.in_([i.product_id for i in order.items])).all()
    } if order.items else {}

    total = 0.0
    rows = []
    for item in order.items:
        product = products.get(item.product_id)
        qty = item.quantity_ordered or 0
        cost = (item.unit_cost or 0.0) * qty
        total += cost
        rows.append(_line(
            (_named(product) if product else f"#{item.product_id}"),
            qty, cost,
            (product.stock_code or product.barcode or "") if product else ""))

    when = order.created_at.strftime("%d %B %Y") if order.created_at else "undated"
    head = [
        f"PURCHASE ORDER  {order.order_number}",
        f"Raised {when}",
        "",
        f"From:  {pharmacy_name or 'the pharmacy'}",
        f"To:    {supplier.name if supplier else 'the supplier'}",
    ]
    if supplier and supplier.contact_person:
        head.append(f"       attn {supplier.contact_person}")
    if supplier and supplier.payment_terms:
        head.append(f"Terms: {supplier.payment_terms}")
    head += [
        "",
        f"{'QTY':>6}  {'CODE':<14}  {'ITEM':<44}  {'VALUE':>10}",
        "-" * 80,
    ]
    foot = [
        "-" * 80,
        f"{'':>6}  {'':<14}  {'TOTAL':<44}  {total:>10,.2f}",
        "",
    ]
    if order.notes:
        foot += [f"Note: {order.notes}", ""]
    foot.append("Please confirm receipt of this order and an expected "
                "delivery date.")
    return "\n".join(head + rows + foot)


class NotSendable(Exception):
    """Why this order cannot be transmitted, in words for the person asking."""


def send(db: Session, order: PurchaseOrder, *, user: User | None = None,
         pharmacy_name: str = "") -> dict:
    """Email the order to its supplier and record that it went.

    Refuses rather than pretending. No supplier, no address, nothing to order
    — each of those is a reason the wholesaler will never see this, and each
    used to end with the order marked sent anyway.
    """
    supplier = db.get(Supplier, order.supplier_id) if order.supplier_id else None
    if supplier is None:
        raise NotSendable(
            "This order has no supplier on it, so there is nobody to send it "
            "to. Set one before sending.")
    if not order.items:
        raise NotSendable(
            f"{order.order_number} has no lines on it. An empty order tells a "
            "wholesaler nothing.")
    address = (supplier.email or "").strip()
    if not address:
        raise NotSendable(
            f"{supplier.name} has no email address on file, so this cannot be "
            "sent. Add one on the supplier, or print the order and send it the "
            "way you do now.")

    body = document(db, order, pharmacy_name=pharmacy_name)
    subject = (f"Purchase order {order.order_number}"
               + (f" from {pharmacy_name}" if pharmacy_name else ""))
    ok, how = messaging.send_email(address, subject, body)
    if not ok:
        # Left as a draft on purpose. An order marked sent that did not send is
        # exactly the state this whole change exists to remove.
        raise NotSendable(
            f"That order could not be emailed to {address}: {how}. It is still "
            "a draft, so nothing about it has changed.")

    order.status = "sent"
    order.sent_at = datetime.utcnow()
    order.sent_by_id = getattr(user, "id", None)
    order.sent_to = address[:200]
    return {
        "sent_to": address,
        "how": how,
        "message": f"{order.order_number} sent to {supplier.name} at {address}.",
    }
