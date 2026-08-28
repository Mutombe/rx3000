"""How each branch of this pharmacy is actually doing.

A group with four shops has one question the single-shop screens cannot answer:
which of them is working, and which is quietly not. Every existing report is
about the pharmacy as a whole, so a branch losing forty dollars a week at
cash-up or claiming nothing at all disappears into the group's totals.

Two rules this file is written to.

**One query per metric, not one per branch.** Everything below groups in the
database. A dashboard that loops over branches asking each the same question is
the shape that made the dispensary worklist take a hundred and eighty seconds
against a hosted database — and this screen has fifteen metrics, so the same
mistake would be fifteen times worse.

**Say when a thing is not measured.** Several of what a group manager would want
here has nothing behind it yet: there is no SOP register, and purchase orders do
not record which branch raised them. The honest answer is to return `None` and
have the screen say "not recorded", because a confident zero is read as "we did
none" and acted on. A dashboard that invents a number is worse than one that
admits a gap.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import Float, case, distinct, func
from sqlalchemy.orm import Session

from ..models import (
    Branch, Claim, Dispensing, OTCSale, Patient, PrescriptionItem, Sale,
    SaleItem, SaleTender, Shift, StockBatch, User, Waybill,
)


def _window(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=max(1, days))


def _rows(query) -> dict[int, tuple]:
    """Group a result by branch id, so every metric merges by the same key."""
    return {r[0]: tuple(r[1:]) for r in query.all() if r[0] is not None}


def scorecard(db: Session, *, days: int = 30) -> dict:
    """Every branch, every measure, in a handful of grouped queries."""
    since = _window(days)

    branches = db.query(Branch).order_by(Branch.name).all()
    out: dict[int, dict] = {
        b.id: {
            "branch_id": b.id, "branch": b.name, "code": b.code,
            "city": b.city or "", "active": bool(b.active),
            "is_default": bool(b.is_default),
        } for b in branches
    }
    if not out:
        return {"days": days, "branches": [], "totals": {}, "not_measured": []}

    # ---- money taken, and how ------------------------------------------------
    sales = _rows(
        db.query(Sale.branch_id,
                 func.count(Sale.id),
                 func.coalesce(func.sum(Sale.total), 0.0),
                 # A sale nobody has paid for yet is not takings. Counted
                 # separately because a branch dispensing plenty and settling
                 # none is the specific failure this screen should surface.
                 func.sum(case((Sale.status == "pending", 1), else_=0)),
                 func.sum(case((Sale.status == "part_paid", 1), else_=0)))
        .filter(Sale.created_at >= since)
        .group_by(Sale.branch_id))

    # How the money actually arrived, which is the question when a drawer is
    # short. Read from two places on purpose.
    #
    # A split payment writes tender rows; an ordinary one records the method on
    # the sale and writes none. Counting only tenders therefore reported four
    # hundred dollars of cash against thirty-four thousand of sales — not
    # wrong so much as answering a different question, and read as a branch
    # taking almost nothing in cash. Sales that have tenders are counted from
    # those (they are the finer truth); the rest are counted from the sale.
    tenders: dict[int, dict[str, dict]] = {}

    def _add(branch_id, method, count, amount):
        if branch_id is None or not method:
            return
        slot = tenders.setdefault(branch_id, {}).setdefault(
            method, {"count": 0, "amount": 0.0})
        slot["count"] += count or 0
        slot["amount"] = round(slot["amount"] + (amount or 0.0), 2)

    tendered_sales = {
        r[0] for r in db.query(distinct(SaleTender.sale_id)).all() if r[0]}

    for branch_id, method, count, amount in (
        db.query(Sale.branch_id, SaleTender.method,
                 func.count(SaleTender.id),
                 func.coalesce(func.sum(SaleTender.amount_in_base), 0.0))
        .join(Sale, SaleTender.sale_id == Sale.id)
        .filter(SaleTender.created_at >= since,
                SaleTender.is_change.is_(False))
        .group_by(Sale.branch_id, SaleTender.method).all()
    ):
        _add(branch_id, method, count, amount)

    settled = (db.query(Sale.branch_id, Sale.payment_method,
                        func.count(Sale.id),
                        func.coalesce(func.sum(Sale.total), 0.0))
               .filter(Sale.created_at >= since,
                       Sale.status.in_(("paid", "part_paid")))
               .group_by(Sale.branch_id, Sale.payment_method))
    if tendered_sales:
        settled = settled.filter(~Sale.id.in_(tendered_sales))
    for branch_id, method, count, amount in settled.all():
        # "split" is not a way of paying; those sales have tender rows and were
        # counted above.
        if method != "split":
            _add(branch_id, method, count, amount)

    # ---- what is on the shelf ------------------------------------------------
    stock = _rows(
        db.query(StockBatch.branch_id,
                 func.count(StockBatch.id),
                 func.coalesce(func.sum(StockBatch.quantity_remaining), 0),
                 func.coalesce(func.sum(StockBatch.quantity_remaining
                                        * StockBatch.unit_cost), 0.0),
                 # Short-dated stock is the number a group manager acts on:
                 # it is money about to be thrown away, and it is branch-local.
                 func.sum(case((StockBatch.expiry_date
                                <= date.today() + timedelta(days=90), 1), else_=0)))
        .filter(StockBatch.quantity_remaining > 0)
        .group_by(StockBatch.branch_id))

    # How wide a range each shop actually sells, which is a different question
    # from how much: a branch turning over one line is fragile.
    lines = _rows(
        db.query(Sale.branch_id, func.count(distinct(SaleItem.product_id)))
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .filter(Sale.created_at >= since)
        .group_by(Sale.branch_id))

    # ---- the people, the tills, and whether the drawer balanced --------------
    shifts = _rows(
        db.query(Shift.branch_id,
                 func.count(Shift.id),
                 func.count(distinct(Shift.user_id)),
                 func.count(distinct(Shift.till_no)),
                 # Accuracy is about the size of the error either way, so the
                 # absolute variance is summed: a branch two dollars over and
                 # two under has made two mistakes, not none.
                 func.coalesce(func.sum(func.abs(Shift.variance)), 0.0),
                 # Closed *and* balanced. An open shift carries a variance of
                 # zero because nothing has been counted yet, not because the
                 # drawer was right — counting those as exact made a hundred and
                 # one shifts that all missed read as one per cent accurate, and
                 # in a shop with several tills open it would read far better
                 # than that.
                 func.sum(case(((Shift.status != "open")
                                & (func.abs(Shift.variance) < 0.005), 1), else_=0)),
                 func.sum(case((Shift.status == "open", 1), else_=0)),
                 # Only a closed shift has been counted, so only a closed shift
                 # can have balanced. Including open ones in the denominator
                 # made a branch mid-morning look like it could not count money.
                 func.sum(case((Shift.status != "open", 1), else_=0)))
        .filter(Shift.opened_at >= since)
        .group_by(Shift.branch_id))

    # ---- dispensing, claiming, delivering -----------------------------------
    dispensed = _rows(
        db.query(Sale.branch_id,
                 func.count(Dispensing.id),
                 func.sum(case((Dispensing.collected_at.is_(None), 1), else_=0)),
                 func.sum(case((Dispensing.schedule >= 5, 1), else_=0)),
                 # The record that says a pharmacist checked it. A branch
                 # dispensing without one is the compliance finding.
                 func.sum(case((func.coalesce(Dispensing.pharmacist_initial, "") != "", 1),
                               else_=0)))
        .join(Sale, Dispensing.sale_id == Sale.id)
        .filter(Dispensing.dispensed_at >= since)
        .group_by(Sale.branch_id))

    otc = _rows(
        db.query(Sale.branch_id,
                 func.count(OTCSale.id),
                 func.sum(case((OTCSale.counselling_given.is_(True), 1), else_=0)),
                 func.sum(case((OTCSale.referred_to_doctor.is_(True), 1), else_=0)))
        .join(Sale, OTCSale.sale_id == Sale.id)
        .filter(OTCSale.created_at >= since)
        .group_by(Sale.branch_id))

    claims = _rows(
        db.query(Sale.branch_id,
                 func.count(Claim.id),
                 func.coalesce(func.sum(Claim.amount_claimed), 0.0),
                 func.coalesce(func.sum(Claim.settled_amount), 0.0),
                 func.sum(case((Claim.status == "rejected", 1), else_=0)),
                 func.sum(case((Claim.status == "held", 1), else_=0)))
        .join(Sale, Claim.sale_id == Sale.id)
        .filter(Claim.created_at >= since)
        .group_by(Sale.branch_id))

    deliveries = _rows(
        db.query(Sale.branch_id,
                 func.count(Waybill.id),
                 func.sum(case((Waybill.status == "delivered", 1), else_=0)),
                 func.sum(case((Waybill.status == "failed", 1), else_=0)))
        .join(Sale, Waybill.sale_id == Sale.id)
        .filter(Waybill.created_at >= since)
        .group_by(Sale.branch_id))

    # ---- whether patients are actually coming back --------------------------
    #
    # Adherence, as far as a dispensary can see it: a repeat that fell due and
    # was collected. It is a proxy and the screen says so — the pharmacy cannot
    # know whether the tablets were taken, only whether they were fetched.
    adherence = _rows(
        db.query(Sale.branch_id,
                 func.count(distinct(Sale.patient_id)))
        .filter(Sale.created_at >= since, Sale.patient_id.isnot(None))
        .group_by(Sale.branch_id))

    repeats_due = (db.query(func.count(PrescriptionItem.id))
                   .filter(PrescriptionItem.next_repeat_date.isnot(None),
                           PrescriptionItem.next_repeat_date < date.today(),
                           PrescriptionItem.repeats_used
                           < PrescriptionItem.repeats_allowed)
                   .scalar() or 0)

    for branch_id, row in out.items():
        s = sales.get(branch_id, (0, 0.0, 0, 0))
        st = stock.get(branch_id, (0, 0, 0.0, 0))
        sh = shifts.get(branch_id, (0, 0, 0, 0.0, 0, 0, 0))
        dp = dispensed.get(branch_id, (0, 0, 0, 0))
        oc = otc.get(branch_id, (0, 0, 0))
        cl = claims.get(branch_id, (0, 0.0, 0.0, 0, 0))
        dl = deliveries.get(branch_id, (0, 0, 0))
        money = tenders.get(branch_id, {})

        row.update({
            "sales": {
                "count": s[0], "value": round(s[1] or 0.0, 2),
                "pending": s[2] or 0, "part_paid": s[3] or 0,
                "average": round((s[1] or 0.0) / s[0], 2) if s[0] else 0.0,
            },
            "money": {
                "cash": money.get("cash", {"count": 0, "amount": 0.0}),
                "card": money.get("card", {"count": 0, "amount": 0.0}),
                "mobile_money": money.get("mobile_money", {"count": 0, "amount": 0.0}),
                "medical_aid": money.get("medical_aid", {"count": 0, "amount": 0.0}),
                "other": {
                    "count": sum(v["count"] for k, v in money.items()
                                 if k not in ("cash", "card", "mobile_money", "medical_aid")),
                    "amount": round(sum(v["amount"] for k, v in money.items()
                                        if k not in ("cash", "card", "mobile_money",
                                                     "medical_aid")), 2),
                },
            },
            "stock": {
                "batches": st[0], "units": int(st[1] or 0),
                "at_cost": round(st[2] or 0.0, 2),
                "short_dated": st[3] or 0,
                "product_lines_sold": lines.get(branch_id, (0,))[0],
            },
            "people": {
                "shifts": sh[0], "staff": sh[1], "tills": sh[2],
                "open_now": sh[5] or 0,
            },
            "cashup": {
                "shifts_counted": sh[6] or 0,
                "exact": sh[4] or 0,
                "total_variance": round(sh[3] or 0.0, 2),
                # The number a group manager reads first: of the drawers that
                # have actually been counted, what proportion balanced to the
                # cent. None when nothing has been counted yet — which is not
                # nought per cent, and must not read as it.
                "accuracy": (round(100.0 * (sh[4] or 0) / sh[6], 1) if sh[6] else None),
            },
            "dispensing": {
                "items": dp[0], "uncollected": dp[1] or 0,
                "controlled": dp[2] or 0,
                "checked": dp[3] or 0,
                "checked_rate": (round(100.0 * (dp[3] or 0) / dp[0], 1) if dp[0] else None),
            },
            "counter": {
                "sales": oc[0],
                "counselled": oc[1] or 0,
                "referred": oc[2] or 0,
                "counselling_rate": (round(100.0 * (oc[1] or 0) / oc[0], 1) if oc[0] else None),
            },
            "claims": {
                "raised": cl[0],
                "claimed": round(cl[1] or 0.0, 2),
                "settled": round(cl[2] or 0.0, 2),
                "rejected": cl[3] or 0,
                "held": cl[4] or 0,
                "recovery": (round(100.0 * (cl[2] or 0.0) / cl[1], 1)
                             if cl[1] else None),
            },
            "deliveries": {
                "raised": dl[0], "delivered": dl[1] or 0, "failed": dl[2] or 0,
                "success": (round(100.0 * (dl[1] or 0) / dl[0], 1) if dl[0] else None),
            },
            "patients": {
                "served": adherence.get(branch_id, (0,))[0],
            },
        })

    rows = sorted(out.values(), key=lambda r: -r["sales"]["value"])
    totals = {
        "branches": len(rows),
        "sales_value": round(sum(r["sales"]["value"] for r in rows), 2),
        "sales_count": sum(r["sales"]["count"] for r in rows),
        "stock_at_cost": round(sum(r["stock"]["at_cost"] for r in rows), 2),
        "cash": round(sum(r["money"]["cash"]["amount"] for r in rows), 2),
        "mobile_money": round(sum(r["money"]["mobile_money"]["amount"] for r in rows), 2),
        "card": round(sum(r["money"]["card"]["amount"] for r in rows), 2),
        "claims_raised": sum(r["claims"]["raised"] for r in rows),
        "repeats_overdue": repeats_due,
    }

    return {
        "days": days,
        "as_at": datetime.utcnow(),
        "branches": rows,
        "totals": totals,
        #: Said out loud rather than shown as zero. A group manager reading
        #: "SOP compliance 0%" will act on it; reading "not recorded" will ask
        #: for the feature. Only one of those is honest about what the system
        #: knows.
        "not_measured": [
            {"metric": "Standard operating procedures",
             "why": "There is no SOP register. Nothing records which procedures "
                    "a branch has signed off, so no figure here would mean anything."},
            {"metric": "Purchasing by branch",
             "why": "Purchase orders are raised for the pharmacy, not a branch — "
                    "they carry no branch, so buying cannot be split between shops."},
            {"metric": "Patient portal use",
             "why": "Portal access is issued per patient, and a patient belongs to "
                    "the pharmacy rather than to one shop. It cannot honestly be "
                    "attributed to a branch."},
            {"metric": "Patient health outcomes",
             "why": "A dispensary sees collections, not outcomes. Adherence below "
                    "is how reliably repeats are fetched, which is the nearest "
                    "honest proxy — it does not say whether anybody got better."},
        ],
    }
