"""What needs doing, per section of the navigation.

One query per badge, counted in SQL. The rule that matters here is accuracy: a
number in the sidebar is a promise about the screen it points at, and a badge
that disagrees with its own page is worse than no badge — it teaches an operator
to stop believing the sidebar.

So each count reuses the query the page itself uses, rather than a second one
written to look similar. That is not a style preference: the dispensary once
showed "Repeats due 53" beside "Due 0" because two identical filters had been
written twice with different horizons.

Zero is not reported. A badge is a call to act, and a permanent grey nought on
fourteen links is furniture — it trains the eye to skip exactly the place a real
number will one day appear.
"""
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    Authorisation, Claim, LayBy, MedicalAid, Message, OwedItem, Product,
    PurchaseOrder, Ticket, Waybill,
)
from . import era, to_follows, worklist


def _count(query) -> int:
    return int(query.with_entities(func.count()).order_by(None).scalar() or 0)


def for_nav(db: Session) -> dict[str, int]:
    """Counts keyed by the route each badge belongs to. Zeros are dropped."""
    out: dict[str, int] = {}

    # --- dispensary ---------------------------------------------------------
    # The worklist's own filter, counted in SQL. `pending()` builds the whole
    # panel and then measures it, which is 1.4s — acceptable once for a panel
    # somebody is reading, not for a badge that refreshes on every navigation.
    out["/dispense"] = worklist.pending_count(db)

    # One horizon, owned by the worklist service.
    horizon = date.today() + timedelta(days=worklist.REPEAT_HORIZON_DAYS)
    from ..models import PrescriptionItem
    out["/repeats"] = _count(
        db.query(PrescriptionItem).filter(
            PrescriptionItem.next_repeat_date.isnot(None),
            PrescriptionItem.next_repeat_date <= horizon,
            PrescriptionItem.repeats_used < PrescriptionItem.repeats_allowed,
        ))

    # Owed and not yet settled. `to_follows.ready()` additionally checks stock
    # per line, which means a query per row — the right answer for the page,
    # the wrong shape for a badge. Counting what is owed is the figure the
    # section header leads with anyway.
    out["/to-follows"] = _count(
        db.query(OwedItem).filter(OwedItem.status == "outstanding"))

    # A waybill that has neither arrived nor been called off is still somebody's
    # job. Expressed as "not finished" rather than a list of in-flight states, so
    # a new state added later counts as work instead of silently vanishing.
    out["/deliveries"] = _count(
        db.query(Waybill).filter(~Waybill.status.in_(("delivered", "cancelled"))))

    # --- front shop ---------------------------------------------------------
    out["/laybys"] = _count(
        db.query(LayBy).filter(LayBy.status == "active",
                               LayBy.due_date.isnot(None),
                               LayBy.due_date < date.today()))

    # --- stock --------------------------------------------------------------
    out["/stock"] = _count(
        db.query(Product).filter(Product.active,
                                 Product.reorder_level > 0,
                                 Product.quantity_on_hand <= Product.reorder_level))
    out["/orders"] = _count(
        db.query(PurchaseOrder).filter(PurchaseOrder.status.in_(("draft", "sent"))))

    # --- accounts -----------------------------------------------------------
    # Exactly the filter behind /api/claiming/unbatched, which is the list the
    # page shows: claims not yet in a batch, excluding real-time schemes that
    # never batch at all.
    out["/claiming"] = _count(
        db.query(Claim)
        .join(MedicalAid, Claim.medical_aid_id == MedicalAid.id)
        .filter(Claim.batch_id.is_(None), MedicalAid.realtime.is_(False)))

    # Authorisations about to lapse — the only ones worth interrupting for.
    out["/authorisations"] = _count(
        db.query(Authorisation).filter(
            Authorisation.status == "approved",
            Authorisation.valid_to.isnot(None),
            Authorisation.valid_to <= date.today() + timedelta(days=7)))

    # Over every open shortfall, never over a page.
    count, _total = era.outstanding_totals(db)
    out["/remittances"] = count

    # --- business -----------------------------------------------------------
    out["/helpdesk"] = _count(
        db.query(Ticket).filter(Ticket.status.in_(("open", "pending"))))

    # A message that failed to reach a patient fails silently by nature.
    out["/reminders"] = _count(db.query(Message).filter(Message.status == "failed"))

    return {route: n for route, n in out.items() if n > 0}
