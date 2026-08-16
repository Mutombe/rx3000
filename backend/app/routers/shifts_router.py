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

    # The same rule as /current: what should be in the drawer is not knowable
    # from the browser until a count exists. This endpoint computes it per
    # currency, which made it the more useful back door of the two.
    if not getattr(shift, "counted_at", None):
        for bucket in by_currency.values():
            bucket.pop("expected_cash", None)

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
        # The blind count only works if the expected figure is genuinely not in
        # the browser. This endpoint was sending it, which meant the count screen
        # could show a live variance as the operator typed — and a count that can
        # be adjusted until it balances is not a count.
        #
        # Withheld until a count has been committed. Everything else the shift
        # knows stays: how many sales, how long it has been open, the float.
        # None of those tell you what should be in the drawer.
        if not getattr(shift, "counted_at", None):
            shift.expected_cash = 0.0
            shift.variance = 0.0
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


# ------------------------------------------------------------------ cash-up
#
# The contract here is the whole point: there is no endpoint that returns the
# expected figure before a count has been submitted. Not "we choose not to show
# it" — it is not obtainable. A control that depends on the front end declining
# to display something it was given is not a control.
from pydantic import BaseModel, Field  # noqa: E402

from ..services import cashup as cashup_svc  # noqa: E402


class CountIn(BaseModel):
    """A committed count. Submitting this is what makes the expected visible."""
    counted: dict[str, float] = Field(default_factory=dict)
    # {"100": 3, "20": 5, "0.5": 2} — what was physically in the drawer.
    coinage: dict[str, int] = Field(default_factory=dict)
    currency: str = "USD"
    notes: str = ""
    till_no: str = ""
    draw_no: str = ""


@router.get("/cashup/denominations")
def cashup_denominations(currency: str = ""):
    """The notes and coins to count, biggest first.

    From the jurisdiction pack rather than hard-coded. The system we are
    replacing lists pounds, which is a locale default nobody ever changed, and
    a Zimbabwean drawer holds neither pounds nor a single currency.
    """
    from ..config import settings

    pack = settings.jurisdiction
    codes = [c.code for c in pack.currencies]
    chosen = (currency or pack.base_currency.code).upper()
    return {
        "currencies": codes,
        "currency": chosen,
        "denominations": cashup_svc.denominations(chosen),
        "tenders": [{"method": m, "label": l} for m, l in cashup_svc.TENDERS],
    }


@router.post("/{shift_id}/cashup")
def submit_cashup(
    shift_id: int, body: CountIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Commit a count and get the reconciliation back.

    One shot. Re-counting after seeing the variance is exactly the behaviour a
    blind count exists to prevent, so a shift that has been counted is refused
    rather than quietly overwritten — a correction is a supervisor's job and
    leaves its own record.
    """
    shift = db.query(Shift).get(shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="That shift no longer exists.")
    if getattr(shift, "counted_at", None):
        raise HTTPException(
            status_code=409,
            detail=(
                "This till has already been cashed up. Counting again after the "
                "variance is known would defeat the point of the count; ask a "
                "manager to record a correction instead."
            ),
        )

    counted = dict(body.counted or {})
    # Where a denomination count was entered, it wins. It is the only figure in
    # the whole exercise that was produced by counting objects rather than by
    # someone doing arithmetic in their head.
    if body.coinage:
        counted["cash"] = cashup_svc.count_from_coinage(body.coinage)

    result = cashup_svc.reconcile(db, shift, counted)
    result["currency"] = body.currency

    if body.till_no:
        shift.till_no = body.till_no
    if body.draw_no:
        shift.draw_no = body.draw_no
    shift.counted_by_id = user.id
    shift.counted_at = datetime.utcnow()
    cashup_svc.store(shift, result, body.coinage, body.notes)

    # Counting the drawer is what ends the shift. Leaving it open afterwards
    # would mean sales could land in a run that has already been reconciled,
    # and the count would silently stop being true.
    if shift.status == "open":
        shift.status = "closed"
        shift.closed_at = datetime.utcnow()
    db.commit()
    result["shift_closed"] = True
    return result


@router.get("/{shift_id}/cashup")
def read_cashup(shift_id: int, db: Session = Depends(get_db)):
    """Read a cash-up back, after it has been committed."""
    shift = db.query(Shift).get(shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="That shift no longer exists.")
    if not getattr(shift, "counted_at", None):
        # Deliberately not the figures. Until a count exists there is nothing
        # to report, and answering with the expected total here would be a
        # back door around the blind count.
        raise HTTPException(
            status_code=404,
            detail="This till has not been cashed up yet.",
        )
    import json as _json

    stored = _json.loads(shift.cashup_json or "{}")
    return {
        "counted_at": shift.counted_at.isoformat(),
        "counted_by": shift.counted_by_id,
        **stored,
    }


# ---------------------------------------------------------------- petty cash
class PettyCashIn(BaseModel):
    """Money out of the drawer, or into it.

    Signed: negative is a payout, positive is a top-up. One field and a sign
    beats two fields and a rule about which one to use.
    """
    amount: float
    category: str = ""
    description: str = ""
    reference: str = ""
    receipt_seen: bool = False


@router.post("/petty-cash")
def add_petty_cash(
    body: PettyCashIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    from ..models import PettyCash

    if not body.amount:
        raise HTTPException(status_code=400, detail="Enter an amount.")
    if not body.description.strip():
        # The whole value of this record is what the money was for. An entry
        # reading "-20.00" and nothing else is not a record, it is a hole with
        # a number beside it.
        raise HTTPException(
            status_code=400,
            detail="Say what the money was for — that is the point of the record.",
        )

    shift = current_open_shift(db, user.id)
    row = PettyCash(
        shift_id=shift.id if shift else None,
        branch_id=getattr(shift, "branch_id", None) if shift else None,
        amount=round(body.amount, 2),
        category=body.category.strip(),
        description=body.description.strip(),
        reference=body.reference.strip(),
        receipt_seen=body.receipt_seen,
        user_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    direction = "out of" if row.amount < 0 else "into"
    return {
        "id": row.id,
        "amount": row.amount,
        "message": f"{abs(row.amount):.2f} recorded {direction} the drawer.",
    }


@router.get("/petty-cash")
def list_petty_cash(
    limit: int = 50, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """This shift's entries, so the person at the till can see what they logged."""
    from ..models import PettyCash

    shift = current_open_shift(db, user.id)
    query = db.query(PettyCash)
    if shift:
        query = query.filter(PettyCash.shift_id == shift.id)
    rows = query.order_by(PettyCash.created_at.desc()).limit(max(1, min(limit, 200))).all()
    return {
        "net": round(sum(r.amount for r in rows), 2),
        "entries": [
            {
                "id": r.id, "amount": r.amount, "category": r.category,
                "description": r.description, "reference": r.reference,
                "receipt_seen": r.receipt_seen,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }
