"""Asking around, without waiting for somebody to remember to.

WHY THIS EXISTS

A line runs out on a Tuesday. The stock watch says so on Wednesday morning.
Somebody raises a purchase order on Thursday, to whichever wholesaler they
last used, at whatever that wholesaler charges. The quotation screen was
built so that three suppliers could be asked instead, and it was used the way
every optional extra step is used: almost never, and never on the busy days,
which are the days lines run out.

So the asking happens by itself. Every morning, anything that has actually
finished and is not already on order or already out for quotation is put on
one draft request, with the wholesalers who have actually supplied those
lines invited.

WHAT IT DELIBERATELY DOES NOT DO

It does not send. Not to one supplier, not to any.

A machine that emails wholesalers at a quarter past seven, unattended, is one
bad night's data away from asking eleven suppliers to quote for a line that
was miscounted, or sending the same request three mornings running because a
receipt was not entered. Both cost the pharmacy something that does not
appear in any ledger: a wholesaler's willingness to answer the next one. The
judgement that the request is worth sending stays with a person, and all this
removes is the typing.

That also makes the whole thing safe to leave on. The worst a bad night can
produce is a draft nobody sends, sitting on a screen with everything it
proposes to ask visible before anybody commits to it.

WHY ONE REQUEST AND NOT ONE PER LINE

Because a wholesaler receiving eight separate emails on a Tuesday morning
answers the first and bins the rest, and because the quotation screen
compares across a request. One request, every finished line on it, is also
the shape a buyer would have produced by hand.

WHY "FINISHED" AND NOT "LOW"

The reorder level is a floor for ordering, not for asking, and half a
pharmacy's catalogue sits near it on any given day. A request naming forty
lines is one nobody reads and no wholesaler prices properly. Empty is
unambiguous, it is already costing the pharmacy sales, and it is the case
where a second price is worth waiting a day for. A pharmacy that wants the
wider net can say so; see `TRIGGERS`.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..models import (Product, PurchaseOrder, PurchaseOrderItem, Rfq, RfqLine,
                      Supplier)
from . import config
from . import rfq as rfq_svc

log = logging.getLogger(__name__)

#: What counts as worth asking about.
#:
#: "off"          nothing is raised, which is what a pharmacy that does its
#:                buying on the telephone should choose rather than having
#:                drafts pile up unread.
#: "out_of_stock" anything that has actually finished. The default.
#: "reorder"      anything at or below its reorder level as well, for a
#:                pharmacy that plans further ahead and will read a longer
#:                request.
TRIGGERS = ("off", "out_of_stock", "reorder")
SETTING = "rfqs.auto"
DEFAULT_TRIGGER = "out_of_stock"

#: A request longer than this is one nobody reads and no wholesaler prices
#: properly, so the rest wait for tomorrow. Worst first, so what waits is
#: what is least urgent.
MOST_LINES = 25

#: How many wholesalers to invite. Three is the number a buyer comparing
#: quotes on paper uses, and the number past which nobody actually compares.
INVITE = 3


def trigger(db: Session) -> str:
    """What this pharmacy has asked to be told about."""
    said = (config.text(db, SETTING, DEFAULT_TRIGGER) or "").strip().lower()
    return said if said in TRIGGERS else DEFAULT_TRIGGER


def _already_asked(db: Session) -> set[int]:
    """Products already out for quotation, on a request still open.

    Without this the job raises the same request every morning until somebody
    acts on it, and a screen with nine identical drafts on it is one nobody
    opens again.
    """
    rows = (db.query(RfqLine.product_id)
              .join(Rfq, RfqLine.rfq_id == Rfq.id)
              .filter(Rfq.status.in_(("draft", "sent"))).all())
    return {pid for (pid,) in rows}


def _already_ordered(db: Session) -> set[int]:
    """Products already on a purchase order that has not arrived.

    A line somebody ordered yesterday is not a line to go asking about this
    morning. Asking anyway is how a wholesaler learns that these requests
    mean nothing.
    """
    rows = (db.query(PurchaseOrderItem.product_id)
              .join(PurchaseOrder, PurchaseOrderItem.order_id == PurchaseOrder.id)
              .filter(PurchaseOrder.status.in_(("draft", "sent"))).all())
    return {pid for (pid,) in rows}


def wanted(product: Product) -> int:
    """How many to ask about.

    The pharmacy's own reorder quantity where it has one, because that is the
    number somebody already thought about. Failing that the reorder level,
    which at least gets the line back onto the shelf.
    """
    return int(product.reorder_quantity or product.reorder_level or 0) or 1


def candidates(db: Session) -> list[Product]:
    """What is worth asking about this morning, worst first."""
    how = trigger(db)
    if how == "off":
        return []

    query = db.query(Product).filter(Product.active.is_(True))
    if how == "reorder":
        query = query.filter(Product.quantity_on_hand <= Product.reorder_level)
    else:
        query = query.filter(Product.quantity_on_hand <= 0)

    skip = _already_asked(db) | _already_ordered(db)
    rows = [p for p in query.all() if p.id not in skip]
    # Emptiest first, so what gets left for tomorrow is what is least short.
    rows.sort(key=lambda p: ((p.quantity_on_hand or 0), p.name or ""))
    return rows[:MOST_LINES]


def raise_one(db: Session, *, pharmacy_name: str = "") -> Rfq | None:
    """One draft request for everything that has run out. Never sent."""
    lines = candidates(db)
    if not lines:
        return None

    how = trigger(db)
    row = rfq_svc.create(db, notes=(
        "Raised automatically: "
        + ("everything at or below its reorder level"
           if how == "reorder" else "everything that has run out")
        + ". Check it, then send it."))
    row.raised_automatically = True

    for product in lines:
        try:
            rfq_svc.add_line(db, row, product_id=product.id,
                             quantity=wanted(product))
        except rfq_svc.RfqError:
            # One unusable line must not cost the pharmacy the other
            # twenty four. A scheduled job has nobody to tell, so it is
            # logged and the request goes on being built.
            log.warning("Left product %s off the automatic request", product.id)

    # Who has actually supplied these lines, rather than whoever is first
    # alphabetically. Falls back to the supplier named on the product, which
    # is the only thing a pharmacy that has never used this system has.
    for who in rfq_svc.suggest_suppliers(db, row, limit=INVITE):
        try:
            rfq_svc.invite(db, row, supplier_id=who["supplier_id"])
        except rfq_svc.RfqError:
            continue
    if not row.invited:
        named = {p.supplier_id for p in lines if p.supplier_id}
        for supplier_id in list(named)[:INVITE]:
            try:
                rfq_svc.invite(db, row, supplier_id=supplier_id)
            except rfq_svc.RfqError:
                continue
    return row


def run(db: Session, pharmacies) -> dict:
    """Raise this morning's request for every pharmacy that wants one.

    Each pharmacy is done under its own tenancy, deliberately: the reference
    number is per pharmacy and the rows being written belong to one shop. A
    job that runs unscoped and writes would stamp nothing, and a null
    pharmacy is the one value invisible to every tenant, which is how the
    first stock watch wrote 1,081 findings nobody could see.
    """
    from .. import tenancy

    raised, skipped = 0, 0
    for pharmacy in pharmacies:
        try:
            tenancy.set_current_pharmacy(pharmacy.id)
            tenancy.stamp(db)
            row = raise_one(db, pharmacy_name=pharmacy.name)
            if row is None:
                skipped += 1
                continue
            db.commit()
            raised += 1
            log.info("Raised %s for %s with %s line(s)",
                     row.reference, pharmacy.name, len(row.lines))
        except Exception:                                      # noqa: BLE001
            # One pharmacy's bad data must not stop the other twenty two.
            db.rollback()
            log.exception("No automatic request raised for %s", pharmacy.name)
    return {"raised": raised, "nothing_to_ask": skipped}
