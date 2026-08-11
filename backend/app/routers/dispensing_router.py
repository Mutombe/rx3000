"""Dispensing routes split by medicine schedule.

Three distinct workflows:
  * OTC / pharmacy medicine (S0-S2) — counter sale, no script, counselling recorded
  * Prescription (S3-S4)            — ordinary script dispensing
  * Controlled / dangerous drugs    — S5/S6, with the full compliance record
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import helpers, schedule_policy, schemas
from ..auth import get_current_user
from ..database import get_db
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
            detail=f"{product.name} is {policy.label} — it requires a prescription and cannot be "
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


@router.get("/otc", response_model=list[schemas.OTCSaleOut])
def list_otc_sales(days: int = 30, schedule: int | None = None, limit: int = 200, db: Session = Depends(get_db)):
    """The pharmacy-medicine sales register (S1/S2 record keeping)."""
    query = db.query(OTCSale).filter(OTCSale.created_at >= datetime.utcnow() - timedelta(days=days))
    if schedule is not None:
        query = query.filter(OTCSale.schedule == schedule)
    return query.order_by(OTCSale.created_at.desc()).limit(limit).all()


# ---------- controlled substances ----------
@router.get("/controlled/log", response_model=list[schemas.DispensingOut])
def controlled_log(days: int = 90, limit: int = 200, db: Session = Depends(get_db)):
    """Every controlled-substance hand-over with its compliance record."""
    return (
        db.query(Dispensing)
        .filter(Dispensing.dispense_type == "controlled",
                Dispensing.dispensed_at >= datetime.utcnow() - timedelta(days=days))
        .order_by(Dispensing.dispensed_at.desc())
        .limit(limit)
        .all()
    )


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
