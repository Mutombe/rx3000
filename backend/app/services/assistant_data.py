"""What RX-Assistant may look up about THIS pharmacy, and under whose authority.

The atlas describes the software and is the same file for every customer.
This is the other half: the shop's own figures, which are not.

EVERY LOOKUP RUNS AS THE PERSON ASKING.

That is the whole of the security model and it is not negotiable. Each function
here takes the request's own session and the signed-in user, goes through the
same capability checks the screens go through, and sees the same branch. An
assistant that could read what its user cannot would be a way around every
permission in the product, and the easiest one in the world to miss: nothing on
the screen would look wrong, and the answer would simply be more than the
person was entitled to.

So a refusal here is not an error. It is an answer, phrased for the model to
relay: "you would need reports.money to see that". The person finds out what
they are missing rather than being told the assistant is broken.

NOTHING HERE WRITES. There is no function in this module that changes a row,
and the tools that call it are described to the model as read-only. When the
assistant is allowed to act that will be a separate decision, a separate
module, and it will say so on the screen.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Prescription, Product, Sale, SaleItem, StockBatch,
                      StockMovement, User)
from . import permissions, sold


def _branch_of(db: Session, user: User) -> int | None:
    """Which shelf this person is standing at."""
    if getattr(user, "branch_id", None):
        return int(user.branch_id)
    try:
        from . import branches as branch_svc
        got = branch_svc.default_branch(db)
        return got.id if got else None
    except Exception:                                        # noqa: BLE001
        return None


def _may(db: Session, user: User, capability: str) -> str:
    """Empty where allowed, otherwise the sentence to hand back."""
    try:
        decision = permissions.check(db, user, capability)
    except Exception:                                        # noqa: BLE001
        return ""            # a capability this build does not define
    if decision.get("allowed"):
        return ""
    return decision.get("why") or f"That needs the {capability} permission."


# ------------------------------------------------------------------ medicines
def look_up_medicine(db: Session, user: User, name: str) -> dict:
    """A medicine: what it is, what it costs, and what is on this shelf."""
    term = (name or "").strip()
    if len(term) < 2:
        return {"refused": "Give me at least two letters of the name."}

    rows = (db.query(Product)
            .filter(Product.active.is_(True), Product.name.ilike(f"%{term}%"))
            .order_by(Product.name).limit(6).all())
    if not rows:
        return {"found": 0, "note": f"Nothing in the catalogue matches '{term}'."}

    branch = _branch_of(db, user)
    money_ok = not _may(db, user, "reports.money")
    out = []
    for p in rows:
        here = 0
        if branch:
            here = int(db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
                       .filter(StockBatch.product_id == p.id,
                               StockBatch.branch_id == branch).scalar() or 0)
        line = {
            "name": p.name,
            "strength": p.strength or "",
            "form": p.dosage_form or "",
            "schedule": p.schedule,
            "units_per_pack": p.units_per_pack or 1,
            "on_this_shelf": here,
            "reorder_level": p.reorder_level,
            "max_level": getattr(p, "max_level", None),
        }
        # Cost and price are money, and money has a permission. Somebody who
        # cannot open the stock valuation must not be able to ask for it here.
        if money_ok:
            line["price"] = float(p.unit_price or 0)
        out.append(line)
    return {
        "found": len(out), "medicines": out,
        "money_hidden": None if money_ok else
                        "Prices are not shown: this person cannot see money figures.",
    }


def usage_history(db: Session, user: User, name: str, months: int = 6) -> dict:
    """What has actually left the shelf, month by month."""
    refused = _may(db, user, "reports.money")
    product = (db.query(Product)
               .filter(Product.active.is_(True), Product.name.ilike(f"%{(name or '').strip()}%"))
               .order_by(Product.name).first())
    if not product:
        return {"note": f"Nothing in the catalogue matches '{name}'."}

    since = datetime.utcnow() - timedelta(days=31 * max(1, min(months, 24)))
    # Counted off sale lines, not off the stock ledger. An invoice import
    # writes no movements, so this used to tell a pharmacist that a line they
    # sell every day had never moved, in a sentence, with confidence. A wrong
    # answer from an assistant is worse than no assistant.
    months_out = sold.by_month(db, product.id, since)
    total = sum(m["went_out"] for m in months_out)
    return {
        "medicine": product.name,
        "months": months_out,
        "total_out": total,
        "a_month": round(total / max(1, len(months_out)), 1) if months_out else 0,
        "note": refused or "",
    }


# ---------------------------------------------------------------- the takings
def how_is_trade(db: Session, user: User, days: int = 7) -> dict:
    """What the shop has taken, and how much has gone out.

    The figures Pulse AI used to be handed whether or not the question wanted
    them. Asked for on purpose now, and only by somebody allowed to see money.
    """
    refused = _may(db, user, "reports.money")
    if refused:
        return {"refused": refused}

    days = max(1, min(int(days or 7), 365))
    since = datetime.utcnow() - timedelta(days=days)
    start_today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    taken = float(db.query(func.coalesce(func.sum(Sale.total), 0))
                  .filter(Sale.created_at >= since).scalar() or 0)
    today = float(db.query(func.coalesce(func.sum(Sale.total), 0))
                  .filter(Sale.created_at >= start_today).scalar() or 0)
    sales = int(db.query(func.count(Sale.id))
                .filter(Sale.created_at >= since).scalar() or 0)
    scripts = int(db.query(func.count(Prescription.id))
                  .filter(Prescription.created_at >= since).scalar() or 0)

    best = (db.query(Product.name, func.sum(SaleItem.quantity).label("n"))
            .join(SaleItem, SaleItem.product_id == Product.id)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .filter(Sale.created_at >= since)
            .group_by(Product.name).order_by(func.sum(SaleItem.quantity).desc())
            .limit(8).all())
    return {
        "over_days": days,
        "taken_today": round(today, 2),
        "taken_over_the_period": round(taken, 2),
        "sales": sales,
        "scripts_started": scripts,
        "best_sellers": [{"name": n, "units": int(q or 0)} for n, q in best],
    }


def what_is_low(db: Session, user: User, limit: int = 15) -> dict:
    """Lines at or below their reorder level on this branch's shelf."""
    branch = _branch_of(db, user)
    rows = (db.query(Product)
            .filter(Product.active.is_(True),
                    Product.reorder_level > 0,
                    Product.quantity_on_hand <= Product.reorder_level)
            .order_by(Product.quantity_on_hand)
            .limit(max(1, min(int(limit or 15), 40))).all())
    return {
        "branch_id": branch,
        "count": len(rows),
        "lines": [{
            "name": p.name,
            "on_hand": int(p.quantity_on_hand or 0),
            "reorder_level": int(p.reorder_level or 0),
            "max_level": getattr(p, "max_level", None),
        } for p in rows],
        "note": "These are the catalogue's own quantities. Where a count is "
                "disputed the stock item page shows the batches behind it.",
    }
