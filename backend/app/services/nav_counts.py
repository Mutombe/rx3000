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
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Dispensing,
    Authorisation, Claim, LayBy, MedicalAid, Message, OwedItem, Product,
    PurchaseOrder, Ticket, Waybill,
)
from . import era, to_follows, worklist


def _count(query) -> int:
    """Count the rows a query would return, without loading them.

    `query.count()` and not `with_entities(func.count())`, and the difference is
    not stylistic. A bare `func.count()` names no column, which takes the entity
    out of the statement, and the tenancy filter attaches to entities. The
    badge counts therefore came back unscoped: a pharmacy created five minutes
    ago showed three hundred and fourteen repeats and two hundred and
    sixty-eight claims, every one of them belonging to somebody else.

    `count()` wraps the query as a subquery with the entity intact, so the
    filter survives. It is the same single round trip and no rows are loaded.

    Kept for the one caller that asks a single question. `_count_many` is what
    the sidebar uses, and it preserves the entity the same way.
    """
    return int(query.count() or 0)


def _count_many(db: Session, queries: dict[str, object]) -> dict[str, int]:
    """Count several queries in one statement.

    The sidebar asked thirteen separate questions, and refreshes on every
    navigation and on a ninety-second timer. Thirteen sequential round trips to
    a database in another region is most of the two seconds that cost.

    Each count is still `count(*)` over the ORM query as a subquery — the same
    shape `Query.count()` produces, with the entity present in the inner select
    so the tenancy filter has something to attach to. They are composed into one
    SELECT of scalar subqueries rather than executed one at a time.

    `qa/nav-counts.py` asserts the scoping survives this, with two pharmacies
    and different numbers of everything, because the failure mode is silent:
    the badges look plausible and are somebody else's.
    """
    labels = list(queries)
    columns = [
        select(func.count()).select_from(queries[name].subquery())
        .scalar_subquery().label(f"c{i}")
        for i, name in enumerate(labels)
    ]
    row = db.execute(select(*columns)).one()
    return {name: int(row[i] or 0) for i, name in enumerate(labels)}


def for_nav(db: Session) -> dict[str, int]:
    """Counts keyed by the route each badge belongs to. Zeros are dropped."""
    out: dict[str, int] = {}
    batch: dict[str, object] = {}

    # --- dispensary ---------------------------------------------------------
    # The worklist's own filter, counted in SQL. `pending()` builds the whole
    # panel and then measures it, which is 1.4s — acceptable once for a panel
    # somebody is reading, not for a badge that refreshes on every navigation.
    out["/dispense"] = worklist.pending_count(db)

    # One horizon, owned by the worklist service.
    horizon = date.today() + timedelta(days=worklist.REPEAT_HORIZON_DAYS)
    from ..models import PrescriptionItem
    batch["/repeats"] = (
        db.query(PrescriptionItem).filter(
            PrescriptionItem.next_repeat_date.isnot(None),
            PrescriptionItem.next_repeat_date <= horizon,
            PrescriptionItem.repeats_used < PrescriptionItem.repeats_allowed,
        ))

    # Owed and not yet settled. `to_follows.ready()` additionally checks stock
    # per line, which means a query per row — the right answer for the page,
    # the wrong shape for a badge. Counting what is owed is the figure the
    # section header leads with anyway.
    batch["/to-follows"] = (
        db.query(OwedItem).filter(OwedItem.status == "outstanding"))

    # A waybill that has neither arrived nor been called off is still somebody's
    # job. Expressed as "not finished" rather than a list of in-flight states, so
    # a new state added later counts as work instead of silently vanishing.
    batch["/deliveries"] = (
        db.query(Waybill).filter(~Waybill.status.in_(("delivered", "cancelled"))))

    # A bag on the shelf a week or more is somebody's job. Fresh ones are not:
    # a badge that counts this morning's dispensings is a badge that always shows
    # a number and therefore means nothing.
    batch["/will-call"] = (
        db.query(Dispensing).filter(
            Dispensing.collected_at.is_(None),
            Dispensing.dispensed_at <= datetime.utcnow() - timedelta(days=7)))

    # --- front shop ---------------------------------------------------------
    batch["/laybys"] = (
        db.query(LayBy).filter(LayBy.status == "active",
                               LayBy.due_date.isnot(None),
                               LayBy.due_date < date.today()))

    # --- stock --------------------------------------------------------------
    batch["/stock"] = (
        db.query(Product).filter(Product.active,
                                 Product.reorder_level > 0,
                                 Product.quantity_on_hand <= Product.reorder_level))
    batch["/orders"] = (
        db.query(PurchaseOrder).filter(PurchaseOrder.status.in_(("draft", "sent"))))

    # --- accounts -----------------------------------------------------------
    # Exactly the filter behind /api/claiming/unbatched, which is the list the
    # page shows: claims not yet in a batch, excluding real-time schemes that
    # never batch at all.
    batch["/claiming"] = (
        db.query(Claim)
        .join(MedicalAid, Claim.medical_aid_id == MedicalAid.id)
        .filter(Claim.batch_id.is_(None), MedicalAid.realtime.is_(False)))

    # Authorisations about to lapse: the only ones worth interrupting for.
    batch["/authorisations"] = (
        db.query(Authorisation).filter(
            Authorisation.status == "approved",
            Authorisation.valid_to.isnot(None),
            Authorisation.valid_to <= date.today() + timedelta(days=7)))

    # Over every open shortfall, never over a page.
    count, _total = era.outstanding_totals(db)
    out["/remittances"] = count

    # --- business -----------------------------------------------------------
    batch["/helpdesk"] = (
        db.query(Ticket).filter(Ticket.status.in_(("open", "pending"))))

    # A message that failed to reach a patient fails silently by nature.
    batch["/reminders"] = db.query(Message).filter(Message.status == "failed")

    # The eleven plain counts, in one statement rather than eleven.
    out.update(_count_many(db, batch))

    return {route: n for route, n in out.items() if n > 0}
