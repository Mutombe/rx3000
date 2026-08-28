"""The will-call shelf: medicine dispensed, bagged, and not yet collected.

Every pharmacy has this shelf and no pharmacy system here models it. Medicine is
checked, labelled and bagged, and then it waits — sometimes an hour, sometimes
forever. Treating the moment of dispensing as the end of the story makes a bag
nobody came back for indistinguishable from one handed over, and the only way to
find it is to look at the shelf and read the names.

That matters three ways, and the third is the one that gets a pharmacy in
trouble:

* **The patient is not taking their medicine.** A chronic script collected three
  weeks late is three weeks unmedicated, and nothing else in the shop notices.
* **The stock is gone but unsold.** It is off the shelf, allocated, and cannot be
  sold to the person standing in front of you.
* **On a scheme script the claim has already been made.** The pharmacy has
  claimed for medicine the patient never received. Left long enough that is a
  reversal at best and a query at worst, and the query arrives months later when
  nobody remembers the bag.

Ageing bands are deliberately short. A bag two days old is ordinary; at a week
somebody should telephone; past a month it is going back on the shelf and the
claim is coming off. The bands say which of those it is rather than printing a
number of days and leaving the reading to whoever is on shift.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import Dispensing, Patient, Prescription, PrescriptionItem, Product

#: Bands, in days, and what each one means to do about it.
BANDS = [
    (2, "fresh", "Bagged today or yesterday. Nothing to do."),
    (7, "waiting", "Nobody has come for it. Worth a telephone call."),
    (30, "stale", "A week or more. Telephone, and check the medicine is still in date."),
    (10**6, "abandoned",
     "Over a month. Return it to stock and reverse the claim if one was made."),
]


def _band(days: int) -> tuple[str, str]:
    for limit, name, action in BANDS:
        if days < limit:
            return name, action
    return BANDS[-1][1], BANDS[-1][2]


def _base(db: Session):
    """Dispensed, not collected. One expression, so the count on the sidebar and
    the list on the screen cannot answer the same question differently."""
    return (db.query(Dispensing)
            .join(PrescriptionItem, Dispensing.prescription_item_id == PrescriptionItem.id)
            .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
            .filter(Dispensing.collected_at.is_(None)))


def waiting_count(db: Session) -> int:
    return _base(db).count()


def waiting(db: Session, *, limit: int = 200) -> dict:
    """Everything on the shelf, oldest first.

    Oldest first rather than newest: the point of the screen is the bag that has
    been there longest, and a list that opens on this morning's dispensings puts
    the thing you need at the bottom.
    """
    # Everything the loop below touches is loaded here, in one query.
    #
    # Only the product was eager-loaded, and the loop then reached for the
    # prescription, the patient on it and the pharmacist who dispensed —
    # three lazy loads a row. On a laptop with SQLite that is invisible. On a
    # hosted database it is three network round trips per bag, so a shelf of
    # two hundred became six hundred round trips and the screen timed out
    # rather than drew.
    rows = (_base(db)
            .options(joinedload(Dispensing.prescription_item)
                     .joinedload(PrescriptionItem.product),
                     joinedload(Dispensing.prescription_item)
                     .joinedload(PrescriptionItem.prescription)
                     .joinedload(Prescription.patient),
                     joinedload(Dispensing.dispensed_by))
            .order_by(Dispensing.dispensed_at.asc())
            .limit(limit + 1)
            .all())
    more = len(rows) > limit
    rows = rows[:limit]

    # What is still owed on each bag, in two queries rather than two a row.
    #
    # A will-call bag is medicine that has been dispensed and not yet handed
    # over, and in this pharmacy it is usually not paid for either — the sale
    # sits pending until somebody comes for it. The shelf could not say that,
    # so a bag was handed over and whether it had been paid for was a separate
    # question nobody was prompted to ask.
    sale_ids = [d.sale_id for d in rows if d.sale_id]
    owed_by_sale: dict[int, float] = {}
    if sale_ids:
        from ..models import Claim, Sale, SaleTender

        paid = dict(
            db.query(SaleTender.sale_id,
                     func.coalesce(func.sum(SaleTender.amount_in_base), 0.0))
              .filter(SaleTender.sale_id.in_(sale_ids))
              .group_by(SaleTender.sale_id).all())
        covered = dict(
            db.query(Claim.sale_id, Claim.amount_approved)
              .filter(Claim.sale_id.in_(sale_ids),
                      Claim.status.notin_(("rejected", "reversed"))).all())
        for sale in db.query(Sale).filter(Sale.id.in_(sale_ids)).all():
            if sale.status in ("paid", "void"):
                continue
            due = (sale.total or 0.0) - float(covered.get(sale.id) or 0.0)
            owed_by_sale[sale.id] = max(0.0, round(due - float(paid.get(sale.id) or 0.0), 2))

    now = datetime.utcnow()
    items = []
    for d in rows:
        item = d.prescription_item
        rx = item.prescription if item else None
        patient = rx.patient if rx else None
        product = item.product if item else None
        days = (now - d.dispensed_at).days if d.dispensed_at else 0
        band, action = _band(days)
        items.append({
            "dispensing_id": d.id,
            "rx_number": rx.rx_number if rx else "",
            "prescription_id": rx.id if rx else None,
            "patient_id": patient.id if patient else None,
            "patient": f"{patient.first_name} {patient.last_name}" if patient else "Walk-in",
            "phone": patient.phone if patient else "",
            "product": f"{product.name} {product.strength or ''}".strip() if product else "",
            "quantity": d.quantity,
            "schedule": d.schedule,
            "dispensed_at": d.dispensed_at,
            "dispensed_by": d.dispensed_by.full_name if d.dispensed_by else "",
            "days_waiting": days,
            "band": band,
            "action": action,
            # A controlled item cannot simply be handed to whoever turns up, and
            # the screen needs to know before the bag is at the counter.
            "needs_id": (d.schedule or 0) >= 5,
            "sale_id": d.sale_id,
            # Nought means nothing to collect: either it was paid at the till
            # or the scheme carried all of it.
            "outstanding": owed_by_sale.get(d.sale_id, 0.0),
        })

    # Counted over the whole shelf, never over the page.
    #
    # These were summed from `items`, which is the first two hundred rows sorted
    # oldest first — so the summary said every bag on the shelf was abandoned
    # while the fresh ones sat on page two. A count taken from a page is the
    # commonest way a screen lies without anybody writing a false statement.
    counts = {name: 0 for _, name, _ in BANDS}
    for (dispensed_at,) in _base(db).with_entities(Dispensing.dispensed_at).all():
        band, _action = _band((now - dispensed_at).days if dispensed_at else 0)
        counts[band] += 1
    return {
        "items": items,
        "more": more,
        # What the shelf is holding in unpaid medicine. A figure worth seeing
        # before it is a figure worth chasing.
        "owed_on_the_shelf": round(sum(owed_by_sale.values()), 2),
        "bags_unpaid": len([v for v in owed_by_sale.values() if v > 0.005]),
        # The real total, not the length of the page. A screen that reports its
        # own page size as the total is the commonest way software lies by
        # accident.
        "total": waiting_count(db),
        "bands": counts,
    }


class CollectionError(ValueError):
    """Raised when a bag cannot be handed over as asked."""


def collect(db: Session, dispensing_id: int, *, user_id: int,
            taken_by: str = "", id_seen: str = "") -> Dispensing:
    """Hand a bag over, and record who took it.

    `taken_by` is often not the patient — a relative, a driver, a neighbour
    going that way — and on a controlled item it is the answer to "who had it",
    so a Schedule 5 or 6 bag will not close without a name.
    """
    d = db.get(Dispensing, dispensing_id)
    if not d:
        raise CollectionError("That dispensing is not on file.")
    if d.collected_at:
        raise CollectionError(
            f"Already collected on {d.collected_at:%d %b %Y} "
            f"by {d.collected_name or 'somebody unrecorded'}.")
    if (d.schedule or 0) >= 5 and not taken_by.strip():
        raise CollectionError(
            "A Schedule 5 or 6 item cannot be handed over without recording who "
            "took it. The register has to answer 'who had it and when'.")
    d.collected_at = datetime.utcnow()
    d.collected_by_id = user_id
    d.collected_name = taken_by.strip()[:120]
    if id_seen.strip():
        d.id_number_seen = id_seen.strip()[:40]
    db.commit()
    db.refresh(d)
    return d


def uncollect(db: Session, dispensing_id: int) -> Dispensing:
    """Put a bag back on the shelf, for the collection marked in error.

    Kept rather than left to a database edit: marking the wrong bag collected is
    an ordinary slip at a counter, and the alternative is a pharmacy that cannot
    correct it without a developer.
    """
    d = db.get(Dispensing, dispensing_id)
    if not d:
        raise CollectionError("That dispensing is not on file.")
    d.collected_at = None
    d.collected_by_id = None
    d.collected_name = ""
    db.commit()
    db.refresh(d)
    return d


def stale_for_reminder(db: Session, days: int = 7) -> list[Dispensing]:
    """Bags old enough to telephone about. Used by the reminder job."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    return (_base(db)
            .filter(Dispensing.dispensed_at <= cutoff)
            .order_by(Dispensing.dispensed_at.asc())
            .all())
