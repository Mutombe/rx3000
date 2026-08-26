"""Dispensing routes split by medicine schedule.

Three distinct workflows:
  * OTC / pharmacy medicine (S0-S2) — counter sale, no script, counselling recorded
  * Prescription (S3-S4)            — ordinary script dispensing
  * Controlled / dangerous drugs    — S5/S6, with the full compliance record
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import helpers, schedule_policy, schemas
from ..auth import get_current_user
from ..database import get_db
from ..services import interactions, paging
from ..models import (
    Dispensing, OTCSale, Patient, Prescription, PrescriptionItem, Product,
    Sale, SaleItem, User,
)
from . import shifts_router

router = APIRouter(prefix="/api/dispensing", tags=["dispensing"], dependencies=[Depends(get_current_user)])


@router.get("/policy", response_model=list[schemas.SchedulePolicyOut])
def dispensing_policy():
    """The schedule rulebook the UI uses to pick the right workflow."""
    return schedule_policy.all_policies()


@router.get("/products", response_model=list[schemas.ProductOut])
def products_by_route(route: str = "otc", q: str = "", limit: int = 40, db: Session = Depends(get_db)):
    """Products available on a given dispensing route (otc | prescription | controlled)."""
    schedules = schedule_policy.schedules_for_route(route)
    if not schedules:
        raise HTTPException(status_code=400, detail="Route must be otc, prescription or controlled")
    query = db.query(Product).filter(Product.active, Product.schedule.in_(schedules))
    if route == "otc":
        query = query.filter(Product.category != "airtime")
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    return query.order_by(Product.name).limit(limit).all()


# ---------- OTC / pharmacy medicine ----------
@router.post("/otc", response_model=schemas.OTCSaleOut)
def otc_sale(
    body: schemas.OTCSaleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Sell a pharmacy medicine over the counter and record the consultation."""
    product = db.get(Product, body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    policy = schedule_policy.policy_for(product.schedule)
    if policy.route != "otc":
        raise HTTPException(
            status_code=400,
            detail=f"{product.name} is {policy.label}. It requires a prescription and cannot be "
                   "sold over the counter.",
        )
    if policy.requires_pharmacist and user.role not in ("pharmacist", "admin"):
        raise HTTPException(
            status_code=403,
            detail=f"{policy.label} must be handed over by a pharmacist.",
        )
    if policy.counselling_required and not body.counselling_given:
        raise HTTPException(
            status_code=400,
            detail=f"{policy.label} requires the patient to be counselled before hand-over.",
        )
    if body.quantity < 1:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")

    shift = shifts_router.current_open_shift(db, user.id)
    sale = Sale(
        sale_number=helpers.next_number(db, Sale, "INV", "sale_number"),
        patient_id=body.patient_id,
        cashier_id=user.id,
        shift_id=shift.id if shift else None,
    )
    db.add(sale)
    db.flush()

    line_total = round(product.unit_price * body.quantity, 2)
    line_ex = round(line_total / (1 + product.vat_rate), 2)
    sale_item = SaleItem(
        sale_id=sale.id, product_id=product.id,
        description=f"{product.name} {product.strength}".strip(),
        quantity=body.quantity, unit_price=product.unit_price,
        unit_cost=product.cost_price or 0.0,
        vat_rate=product.vat_rate, line_total=line_total,
    )
    db.add(sale_item)
    db.flush()

    helpers.consume_stock_fefo(
        db, product, body.quantity, "sale", user.id,
        reference=sale.sale_number, sale_item_id=sale_item.id,
    )
    sale.subtotal = line_ex
    sale.vat_amount = round(line_total - line_ex, 2)
    sale.total = line_total
    sale.payment_method = body.payment_method
    if body.payment_method == "cash":
        if body.amount_tendered + 0.005 < sale.total:
            raise HTTPException(status_code=400, detail="Amount tendered is less than the total")
        sale.amount_tendered = body.amount_tendered
        sale.change_due = round(body.amount_tendered - sale.total, 2)
    else:
        sale.amount_tendered = sale.total
    sale.status = "paid"

    record = OTCSale(
        product_id=product.id, quantity=body.quantity, schedule=product.schedule or 0,
        patient_id=body.patient_id, customer_name=body.customer_name,
        pharmacist_id=user.id, indication=body.indication,
        counselling_given=body.counselling_given, referred_to_doctor=body.referred_to_doctor,
        notes=body.notes, sale_id=sale.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _otc_query(db: Session, days: int, schedule: int | None):
    query = db.query(OTCSale).filter(OTCSale.created_at >= datetime.utcnow() - timedelta(days=days))
    if schedule is not None:
        query = query.filter(OTCSale.schedule == schedule)
    return query.order_by(OTCSale.created_at.desc())


@router.get("/otc", response_model=list[schemas.OTCSaleOut])
def list_otc_sales(days: int = 30, schedule: int | None = None, limit: int = 200, db: Session = Depends(get_db)):
    """The pharmacy-medicine sales register (S1/S2 record keeping)."""
    return _otc_query(db, days, schedule).limit(limit).all()


@router.get("/otc/paged")
def list_otc_sales_paged(days: int = 30, schedule: int | None = None, page: int = 1,
                         per_page: int = paging.DEFAULT_PER_PAGE, db: Session = Depends(get_db)):
    """The same register, a page at a time, with the true total.

    A register is the wrong place to show a capped list with no total: the screen
    said nothing about the difference between "this is everything" and "this is
    the most recent two hundred".
    """
    result = paging.page(_otc_query(db, days, schedule), page=page, per_page=per_page)
    return result.envelope(lambda r: schemas.OTCSaleOut.model_validate(r, from_attributes=True).model_dump())


# ---------- controlled substances ----------
def _controlled_query(db: Session, days: int):
    return (db.query(Dispensing)
            .filter(Dispensing.dispense_type == "controlled",
                    Dispensing.dispensed_at >= datetime.utcnow() - timedelta(days=days))
            .order_by(Dispensing.dispensed_at.desc()))


@router.get("/controlled/log", response_model=list[schemas.DispensingOut])
def controlled_log(days: int = 90, limit: int = 200, db: Session = Depends(get_db)):
    """Every controlled-substance hand-over with its compliance record."""
    return _controlled_query(db, days).limit(limit).all()


@router.get("/controlled/log/paged")
def controlled_log_paged(days: int = 90, page: int = 1,
                         per_page: int = paging.DEFAULT_PER_PAGE,
                         db: Session = Depends(get_db)):
    """The controlled register, paged, with the count over the whole period.

    This is the list an inspector reads. Showing the most recent two hundred
    hand-overs with nothing saying so is the one place a silent cap is not a
    presentation choice.
    """
    result = paging.page(_controlled_query(db, days), page=page, per_page=per_page)
    return result.envelope(lambda d: schemas.DispensingOut.model_validate(d, from_attributes=True).model_dump())


@router.get("/stats")
def dispensing_stats(days: int = 30, db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(days=days)
    controlled = db.query(func.count(Dispensing.id)).filter(
        Dispensing.dispense_type == "controlled", Dispensing.dispensed_at >= since
    ).scalar()
    scripts = db.query(func.count(Dispensing.id)).filter(
        Dispensing.dispense_type == "prescription", Dispensing.dispensed_at >= since
    ).scalar()
    otc = db.query(func.count(OTCSale.id)).filter(OTCSale.created_at >= since).scalar()
    referrals = db.query(func.count(OTCSale.id)).filter(
        OTCSale.created_at >= since, OTCSale.referred_to_doctor.is_(True)
    ).scalar()
    return {
        "days": days,
        "controlled_dispensings": controlled,
        "prescription_dispensings": scripts,
        "otc_sales": otc,
        "otc_referrals": referrals,
    }


@router.post("/interaction-screen")
def interaction_screen(patient_id: int | None = Body(default=None),
                       product_ids: list[int] = Body(default_factory=list),
                       db: Session = Depends(get_db)):
    """Screen a basket, and screen it against what the patient already takes.

    Called by the dispensing screen every time the basket changes, not from a
    button. A safety check somebody has to remember to run is a safety check that
    gets skipped on exactly the busy afternoon it was written for.

    **The medication history is the point.** Two new lines interacting with each
    other is the case that is easy to picture and uncommon in practice: one
    prescriber wrote both and has usually thought about it. The dangerous case is
    a new line against a repeat from two years ago — warfarin from a cardiologist
    in March, ibuprofen for a sore back today, different prescriber, nobody
    holding both facts. The pharmacy counter is the only place both are visible.

    Deliberately does not block on its own. The checker holds twelve pairs and
    says so in every response; blocking on twelve while missing thousands would
    teach a pharmacist that a clear result means safe, which is the failure this
    whole module is written against. The screen asks for an acknowledgement on a
    major finding and never claims more than it knows.
    """
    products = db.query(Product).filter(Product.id.in_(product_ids)).all() if product_ids else []

    history: list[dict] = []
    if patient_id:
        # What this patient is actually on: every line dispensed in the last six
        # months, most recent first, one row per product. Six months because a
        # chronic repeat cycles monthly and a quarterly script is ordinary; much
        # longer and a course finished in March starts flagging in September.
        cutoff = datetime.utcnow() - timedelta(days=182)
        rows = (db.query(Product, func.max(Dispensing.dispensed_at))
                  .join(PrescriptionItem, PrescriptionItem.product_id == Product.id)
                  .join(Dispensing, Dispensing.prescription_item_id == PrescriptionItem.id)
                  .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
                  .filter(Prescription.patient_id == patient_id,
                          Dispensing.dispensed_at >= cutoff)
                  .group_by(Product.id)
                  .all())
        basket = {p.id for p in products}
        for product, last in rows:
            # A product already in the basket is not also "history": flagging a
            # repeat against itself would report every chronic refill as a
            # duplicate.
            if product.id in basket:
                continue
            history.append({
                "product_id": product.id,
                "name": f"{product.name} {product.strength or ''}".strip(),
                "active_ingredient": product.active_ingredient or "",
                "since": last.strftime("%d %b") if last else "",
            })

    result = interactions.check(
        [{"product_id": p.id,
          "name": f"{p.name} {p.strength or ''}".strip(),
          "active_ingredient": p.active_ingredient or ""}
         for p in products],
        existing=history,
    )
    result["history_source"] = (
        f"{len(history)} medicine(s) dispensed to this patient in the last six months"
        if history else
        ("Nothing dispensed to this patient in the last six months"
         if patient_id else "No patient selected, so nothing was checked against history")
    )
    return result
