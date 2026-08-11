from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Sale, Shift, User
from ..services import currency

router = APIRouter(prefix="/api/shifts", tags=["shifts"])

LOYALTY_POINT_VALUE = 1.0


def current_open_shift(db: Session, user_id: int) -> Shift | None:
    return (
        db.query(Shift)
        .filter(Shift.user_id == user_id, Shift.status == "open")
        .order_by(Shift.opened_at.desc())
        .first()
    )


def _shift_sales(db: Session, shift: Shift) -> list[Sale]:
    return db.query(Sale).filter(Sale.shift_id == shift.id, Sale.status == "paid").all()


def _totals(db: Session, shift: Shift) -> dict:
    """Cash expected in the drawer, plus card / medical-aid takings, in base currency.

    A sale settled with split tender has no single payment_method, so its
    tenders are used when present and the legacy fields only when it has none.
    """
    sales = _shift_sales(db, shift)
    cash = card = aid = 0.0
    for sale in sales:
        if sale.tenders:
            for tender in sale.tenders:
                # amount_in_base is already signed: change is negative
                if tender.method == "cash":
                    cash += tender.amount_in_base
                elif tender.method == "card":
                    card += tender.amount_in_base
                elif tender.method == "medical_aid":
                    aid += tender.amount_in_base
        elif sale.payment_method == "cash":
            cash += sale.total - sale.loyalty_points_redeemed * LOYALTY_POINT_VALUE
        elif sale.payment_method == "card":
            card += sale.total
        elif sale.payment_method == "medical_aid":
            aid += sale.total
    return {
        "expected_cash": round(shift.opening_float + cash, 2),
        "card_total": round(card, 2),
        "medical_aid_total": round(aid, 2),
        "sales_count": len(sales),
    }


@router.get("/{shift_id}/takings")
def takings(shift_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Takings split by currency — what each drawer should physically hold.

    Cash is net of change, because change leaves the drawer in whichever
    currency it was handed over.
    """
    shift = db.get(Shift, shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    sales = _shift_sales(db, shift)
    by_currency = currency.takings_by_currency(sales)

    # Sales with no tender rows predate split tender — fold them into the base
    # currency so the totals still reconcile.
    legacy = [s for s in sales if not s.tenders]
    if legacy:
        bucket = by_currency.setdefault(currency.base_code(), {
            "currency": currency.base_code(), "cash": 0.0, "card": 0.0,
            "mobile_money": 0.0, "medical_aid": 0.0, "other": 0.0,
            "total": 0.0, "in_base": 0.0,
        })
        for sale in legacy:
            method = sale.payment_method if sale.payment_method in bucket else "other"
            net = sale.total - sale.loyalty_points_redeemed * LOYALTY_POINT_VALUE \
                if sale.payment_method == "cash" else sale.total
            bucket[method] = round(bucket[method] + net, 2)
            bucket["total"] = round(bucket["total"] + net, 2)
            bucket["in_base"] = round(bucket["in_base"] + net, 2)

    base = currency.base_code()
    for code, bucket in by_currency.items():
        bucket["is_base"] = code == base
        if code == base:
            bucket["opening_float"] = shift.opening_float
            bucket["expected_cash"] = round(shift.opening_float + bucket["cash"], 2)
        else:
            bucket["opening_float"] = 0.0
            bucket["expected_cash"] = bucket["cash"]

    return {
        "shift_id": shift.id,
        "base_currency": base,
        "sales_count": len(sales),
        "currencies": sorted(by_currency.values(), key=lambda b: (not b["is_base"], b["currency"])),
    }


@router.get("/current", response_model=schemas.ShiftOut | None)
def get_current(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    shift = current_open_shift(db, user.id)
    if shift:
        for key, value in _totals(db, shift).items():
            setattr(shift, key, value)
    return shift


@router.post("/open", response_model=schemas.ShiftOut)
def open_shift(body: schemas.ShiftOpen, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if current_open_shift(db, user.id):
        raise HTTPException(status_code=400, detail="You already have an open shift — close it first")
    shift = Shift(user_id=user.id, opening_float=body.opening_float, status="open")
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


@router.post("/close", response_model=schemas.ShiftOut)
def close_shift(body: schemas.ShiftClose, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    shift = current_open_shift(db, user.id)
    if not shift:
        raise HTTPException(status_code=400, detail="No open shift to close")

    totals = _totals(db, shift)
    shift.expected_cash = totals["expected_cash"]
    shift.card_total = totals["card_total"]
    shift.medical_aid_total = totals["medical_aid_total"]
    shift.sales_count = totals["sales_count"]
    shift.counted_cash = body.counted_cash
    shift.variance = round(body.counted_cash - shift.expected_cash, 2)
    shift.notes = body.notes
    shift.closed_at = datetime.utcnow()
    shift.status = "closed"
    db.commit()
    db.refresh(shift)
    return shift


@router.get("", response_model=list[schemas.ShiftOut])
def list_shifts(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Shift).order_by(Shift.opened_at.desc()).limit(limit).all()
