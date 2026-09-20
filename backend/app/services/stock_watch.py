"""Stock that somebody should be told about, rather than have to go and look for.

Expiry, low stock and out of stock were all visible here and none of them was
ever told to anybody. A sidebar badge counts lines below reorder level, the
command centre lists what to do today with the money attached, and there are
reports for every one of them. All of that is PULL. A batch expires whether or
not anybody opened the dashboard that morning, and the branch that most needs
telling is the one whose manager is busiest.

WHAT IT WATCHES, AND WHY THESE FOUR

    expired          stock on the shelf that may not be dispensed. The till
                     already refuses it, so this is not a safety net; it is
                     money sitting in a box that has to be written off, and
                     until it is, the valuation is wrong.
    expiring         short dated stock, while there is still time to move it,
                     return it or use it first. After the date it is a loss;
                     before it, it is a decision.
    out_of_stock     nothing on the shelf of something this branch actually
                     dispenses. Not every zero: a line nobody has dispensed in
                     six months is a line that should be zero.
    below_reorder    the ordinary reorder signal, kept because it is the one
                     that prevents the one above.

WHAT IT DELIBERATELY DOES NOT WATCH

Anything the till already refuses at the point of sale. A warning about a thing
that cannot happen teaches people to close warnings.

HOW IT AVOIDS BECOMING NOISE

A finding is written once and not written again while it stands. A line that
has been below its reorder level since March stops shouting after the first
morning, and `last_seen_at` moves instead. That is the whole difference
between an alert somebody reads and one they filter.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import config, quarantine, valuation
from ..models import (Branch, Dispensing, PrescriptionItem, Product,
                      StockAlert, StockBatch)

log = logging.getLogger("rx5000.stock_watch")

#: How short dated is worth mentioning, where nobody has said otherwise.
#:
#: Ninety days is what the command centre and the expiry report already use,
#: so the three agree out of the box. It is now a floor rather than a rule:
#: `stock.expiry_alert_days` on the settings screen overrides it, because a
#: pharmacy that returns short dated stock to its wholesaler on sixty days
#: needs to hear about it before day sixty, and one that cannot return
#: anything wants longer.
EXPIRING_DAYS = 90

#: How recently a line must have moved before an empty shelf is a problem
#: rather than a tidy catalogue. Six months is one repeat cycle plus room.
STILL_WANTED_DAYS = 180

URGENCY = {"expired": 3, "out_of_stock": 3, "expiring": 2, "below_reorder": 1}


def _open(db: Session, kind: str, product_id: int, branch_id: int | None):
    return (
        db.query(StockAlert)
        .filter(StockAlert.kind == kind,
                StockAlert.product_id == product_id,
                StockAlert.branch_id == branch_id,
                StockAlert.resolved_at.is_(None))
        .first()
    )


def _raise(db: Session, kind: str, product: Product, *, branch_id=None,
           batch_id=None, detail="", worth=0.0, seen: set) -> bool:
    """Record a finding, or note that one already standing is still true.

    Returns True only when it is NEW, so a caller can say how many things
    somebody has not been told yet rather than how many things are wrong.
    """
    seen.add((kind, product.id, branch_id))
    row = _open(db, kind, product.id, branch_id)
    now = datetime.utcnow()
    if row:
        row.last_seen_at = now
        # The figures move even while the finding stands: three more boxes
        # expire, the shortfall deepens. The row should say what is true now.
        row.detail = detail or row.detail
        row.worth = round(worth or 0.0, 2)
        return False

    db.add(StockAlert(
        kind=kind, product_id=product.id, branch_id=branch_id, batch_id=batch_id,
        detail=detail[:300], worth=round(worth or 0.0, 2),
        urgency=URGENCY.get(kind, 1),
        first_seen_at=now, last_seen_at=now,
        # WHOSE FINDING THIS IS, taken from the medicine it is about.
        #
        # The automatic stamp fills this from the pharmacy in force, and the
        # sweep runs unscoped because a scheduled job has no request behind
        # it. So there is no pharmacy in force and the stamp leaves it null,
        # which is the one value that is invisible to every tenant: the first
        # run wrote 1,081 findings nobody could see. An alert belongs to
        # whoever owns the stock it is about, and that is on the product.
        pharmacy_id=product.pharmacy_id,
    ))
    return True


def sweep(db: Session, *, today: date | None = None) -> dict:
    """Look at the shelves and write down what is worth saying.

    Returns counts rather than rows: the caller is a scheduled job with
    nowhere to display a list, and the rows are read back through the API by
    whoever opens the screen.
    """
    today = today or date.today()
    seen: set = set()
    new = {"expired": 0, "expiring": 0, "out_of_stock": 0, "below_reorder": 0}

    # What this pharmacy calls short dated, rather than what this module used
    # to assume. Read once per sweep: the job runs over every branch and the
    # answer cannot change while it does.
    warn_within = config.whole(db, "stock.expiry_alert_days", EXPIRING_DAYS)
    # And what each DEPARTMENT calls short dated, where it has said.
    #
    # A wholesaler takes short dated antibiotics back at sixty days and will
    # not look at cosmetics at any notice, so one number for the whole shop is
    # either too late to return the medicines or too noisy about the shampoo.
    # Read once for the sweep: there are tens of departments, not thousands.
    from ..models import StockCategory
    by_department = {c.id: c.expiry_alert_days
                     for c in db.query(StockCategory).all()
                     if c.expiry_alert_days}
    widest = max([warn_within, *by_department.values()]) if by_department else warn_within

    # ---- what is on the shelf past its date, and what is nearly there -----
    batches = (
        db.query(StockBatch, Product)
        .join(Product, StockBatch.product_id == Product.id)
        .filter(StockBatch.quantity_remaining > 0,
                StockBatch.expiry_date.isnot(None),
                # The WIDEST window any department asks for, narrowed per
                # line below. One query rather than one per department, and
                # nothing is missed by a department that wants longer notice.
                StockBatch.expiry_date <= today + timedelta(days=widest))
        .all()
    )
    for batch, product in batches:
        worth = round((batch.quantity_remaining or 0) * (batch.unit_cost or 0.0), 2)
        days = (batch.expiry_date - today).days
        if days < 0:
            made = _raise(db, "expired", product, branch_id=batch.branch_id,
                          batch_id=batch.id, worth=worth,
                          detail=f"{batch.quantity_remaining} unit(s) of batch "
                                 f"{batch.batch_number or 'with no number'} expired "
                                 f"{abs(days)} day(s) ago and are still on the shelf.",
                          seen=seen)
            new["expired"] += made
        else:
            # Narrowed to what THIS department asked for. The query above used
            # the widest window any department wants, so a cosmetics line with
            # a thirty day rule does not appear on day eighty-nine merely
            # because the dispensary wants ninety.
            mine = by_department.get(product.category_id) or warn_within
            if days > mine:
                continue
            made = _raise(db, "expiring", product, branch_id=batch.branch_id,
                          batch_id=batch.id, worth=worth,
                          detail=f"{batch.quantity_remaining} unit(s) of batch "
                                 f"{batch.batch_number or 'with no number'} expire in "
                                 f"{days} day(s).",
                          seen=seen)
            new["expiring"] += made

    # ---- what the shelf is out of, that people still ask for --------------
    #
    # Not every zero. A line nobody has dispensed in six months SHOULD be
    # zero, and telling somebody about it every morning is how an alert list
    # becomes something people close without reading.
    wanted_since = datetime.utcnow() - timedelta(days=STILL_WANTED_DAYS)
    moved = {
        pid for (pid,) in
        db.query(PrescriptionItem.product_id)
        .join(Dispensing, Dispensing.prescription_item_id == PrescriptionItem.id)
        .filter(Dispensing.dispensed_at >= wanted_since)
        .distinct().all()
    }

    low = (
        db.query(Product)
        .filter(Product.active.is_(True),
                Product.quantity_on_hand <= Product.reorder_level)
        .all()
    )
    for product in low:
        on_hand = product.quantity_on_hand or 0
        # reorder_quantity and reorder_level are held in UNITS, the same as
        # quantity_on_hand they are compared against, so the cost of making
        # the shortfall up is a per unit cost.
        cost = valuation.at_cost(
            product, max(0, (product.reorder_quantity or product.reorder_level or 0)))
        if on_hand <= 0:
            if product.id not in moved:
                continue            # empty on purpose, not a problem
            made = _raise(db, "out_of_stock", product, worth=cost,
                          detail="Nothing on the shelf, and it has been dispensed "
                                 "in the last six months.",
                          seen=seen)
            new["out_of_stock"] += made
        else:
            made = _raise(db, "below_reorder", product, worth=cost,
                          detail=f"{on_hand} left, at or below the reorder level "
                                 f"of {product.reorder_level or 0}.",
                          seen=seen)
            new["below_reorder"] += made

    # ---- and what is no longer true ---------------------------------------
    #
    # Closed rather than deleted. "This was short for eleven days in March" is
    # a question somebody asks when a patient complains.
    closed = 0
    for row in db.query(StockAlert).filter(StockAlert.resolved_at.is_(None)).all():
        if (row.kind, row.product_id, row.branch_id) not in seen:
            row.resolved_at = datetime.utcnow()
            closed += 1

    # ---- a branch that has set its own level, judged against its own shelf --
    #
    # The pass above compares the GROUP's shelf against the GROUP's reorder
    # level, which is right for a pharmacy that runs one set of figures and
    # blind for one that does not. The shop beside the clinic gets through
    # four times the amoxicillin: the group looks comfortable while that shelf
    # empties every Friday.
    #
    # Only branches that have SAID they differ are walked. A pharmacy with no
    # overrides sees exactly what it saw before, and one that has set twenty
    # gets twenty more findings rather than three times everything, which is
    # the difference between a list somebody reads and a list somebody mutes.
    from ..models import BranchStockLevel
    from . import branches as branch_svc

    own = (db.query(BranchStockLevel)
           .filter(BranchStockLevel.reorder_level.isnot(None))
           .all())
    for rule in own:
        product = db.get(Product, rule.product_id)
        if product is None or not product.active:
            continue
        here = branch_svc.on_hand(db, product.id, rule.branch_id)
        level = int(rule.reorder_level or 0)
        if here > level:
            continue
        branch = db.get(Branch, rule.branch_id)
        where = branch.name if branch else f"branch {rule.branch_id}"
        made = _raise(
            db, "below_reorder", product, branch_id=rule.branch_id,
            worth=valuation.at_cost(product, max(0, level - here)),
            detail=(f"{here} left at {where}, at or below the {level} that "
                    f"branch asks for. The group holds "
                    f"{product.quantity_on_hand or 0}."),
            seen=seen)
        new["below_reorder"] += made

    # ---- and hold what has gone past its date ------------------------------
    #
    # The sweep has just walked these rows to raise the alert; enforcing what
    # the alert is ABOUT costs one more pass and turns "somebody should look
    # at this" into stock that cannot leave the building while they do.
    held = quarantine.sweep_expired(db, today=today)

    db.commit()
    total_new = sum(new.values())
    log.info("Stock watch: %s new finding(s), %s resolved, %s batch(es) held",
             total_new, closed, held)
    return {"new": new, "new_total": total_new, "resolved": closed,
            "quarantined": held}


def standing(db: Session, *, include_seen: bool = True, limit: int = 200) -> list[dict]:
    """What is currently worth telling somebody, most pressing first."""
    query = db.query(StockAlert).filter(StockAlert.resolved_at.is_(None))
    if not include_seen:
        query = query.filter(StockAlert.seen_at.is_(None))
    rows = (query.order_by(StockAlert.urgency.desc(),
                           StockAlert.worth.desc(),
                           StockAlert.first_seen_at.desc())
            .limit(max(1, min(limit, 500))).all())

    products = {p.id: p for p in db.query(Product).filter(
        Product.id.in_({r.product_id for r in rows} or [0])).all()}
    branches = {b.id: b.name for b in db.query(Branch).filter(
        Branch.id.in_({r.branch_id for r in rows if r.branch_id} or [0])).all()}

    out = []
    for r in rows:
        product = products.get(r.product_id)
        out.append({
            "id": r.id,
            "kind": r.kind,
            "what": WHAT.get(r.kind, r.kind),
            "product_id": r.product_id,
            "product": f"{product.name} {product.strength or ''}".strip() if product else "",
            "branch_id": r.branch_id,
            "branch": branches.get(r.branch_id, ""),
            "detail": r.detail,
            "worth": round(r.worth or 0.0, 2),
            "urgency": r.urgency,
            "since": r.first_seen_at,
            "seen": bool(r.seen_at),
            # Where to go and do something about it. An alert that does not
            # lead anywhere is a complaint.
            "to": TO.get(r.kind, "/stock"),
        })
    return out


#: Our token, and what it says to somebody reading a list.
WHAT = {
    "expired": "Expired stock still on the shelf",
    "expiring": "Short dated",
    "out_of_stock": "Out of stock, and still being asked for",
    "below_reorder": "At the reorder level",
}

TO = {
    "expired": "/stock?tab=batches&expiring=1",
    "expiring": "/stock?tab=batches&expiring=1",
    "out_of_stock": "/orders?tab=reorder",
    "below_reorder": "/orders?tab=reorder",
}
