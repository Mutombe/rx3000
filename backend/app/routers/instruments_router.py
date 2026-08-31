"""The payment instruments a pharmacy takes money on.

One list, read by the till and by the cash-up. They used to hold their own
ideas of this and disagreed — see `services.instruments`.
"""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import PaymentInstrument, SaleTender, User
from ..services import instruments as svc

router = APIRouter(prefix="/api/payment-instruments", tags=["payments"],
                   dependencies=[Depends(get_current_user)])


def _row(i: PaymentInstrument) -> dict:
    return {
        "id": i.id, "code": i.code, "name": i.name, "method": i.method,
        "currencies": i.currency_list, "settles_to": i.settles_to or "",
        "is_cash_drawer": bool(i.is_cash_drawer),
        "is_delivery": bool(i.is_delivery),
        "active": bool(i.active), "sort_order": i.sort_order,
    }


@router.get("")
def listing(include_retired: bool = False, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """What this pharmacy takes money on.

    Seeded on first read rather than at sign-up, so a pharmacy that existed
    before this feature gets the list the first time somebody opens a till
    instead of a blank cash-up sheet.
    """
    if svc.ensure(db, user.pharmacy_id):
        db.commit()
    return [_row(i) for i in svc.listing(db, include_retired=include_retired)]


@router.post("")
def create(body: dict = Body(...), db: Session = Depends(get_db)):
    code = (body.get("code") or "").strip().lower().replace(" ", "_")
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(400, "An instrument needs a code and a name.")
    if db.query(PaymentInstrument).filter(PaymentInstrument.code == code).first():
        raise HTTPException(400, f"There is already an instrument coded {code}.")
    inst = PaymentInstrument(code=code[:30], name=name[:60])
    _apply(inst, body)
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return _row(inst)


@router.put("/{instrument_id}")
def update(instrument_id: int, body: dict = Body(...),
           db: Session = Depends(get_db)):
    inst = db.get(PaymentInstrument, instrument_id)
    if not inst:
        raise HTTPException(404, "Instrument not found")
    if "name" in body and (body.get("name") or "").strip():
        inst.name = body["name"].strip()[:60]
    _apply(inst, body)
    db.commit()
    return _row(inst)


@router.delete("/{instrument_id}")
def retire(instrument_id: int, db: Session = Depends(get_db)):
    """Retired, never deleted.

    Tenders point at the code. Deleting the row does not remove the payments —
    it removes the ability to say what they came in on, which is the whole
    reason the column exists.
    """
    inst = db.get(PaymentInstrument, instrument_id)
    if not inst:
        raise HTTPException(404, "Instrument not found")
    used = db.query(SaleTender).filter(
        SaleTender.instrument == inst.code).count()
    inst.active = False
    db.commit()
    return {"ok": True, "used_by": used,
            "message": (f"{inst.name} retired. It stays on the "
                        f"{used:,} payment(s) already taken on it."
                        if used else f"{inst.name} retired.")}


def _apply(inst: PaymentInstrument, body: dict) -> None:
    if "method" in body and body["method"]:
        inst.method = str(body["method"]).strip()[:20]
    if "currencies" in body:
        value = body["currencies"]
        codes = value if isinstance(value, list) else str(value).split(",")
        inst.currencies = ",".join(
            c.strip().upper() for c in codes if str(c).strip())[:60]
    if "settles_to" in body:
        inst.settles_to = str(body["settles_to"] or "").strip()[:120]
    for flag in ("is_cash_drawer", "is_delivery", "active"):
        if flag in body:
            setattr(inst, flag, bool(body[flag]))
    if "sort_order" in body and body["sort_order"] is not None:
        inst.sort_order = int(body["sort_order"])
