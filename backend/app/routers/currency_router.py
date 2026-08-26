from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import ExchangeRate, User
from ..services import currency

router = APIRouter(prefix="/api/currency", tags=["currency"],
                   dependencies=[Depends(get_current_user)])


@router.get("", response_model=schemas.CurrencyState)
def currency_state(db: Session = Depends(get_db)):
    """Trading currencies and the rate in force right now."""
    j = settings.jurisdiction
    return {
        "base": j.base_currency.code,
        "currencies": [
            {"code": c.code, "symbol": c.symbol, "decimals": c.decimals,
             "rate": currency.rate_table(db).get(c.code, 0.0),
             "is_base": c.code == j.base_currency.code}
            for c in j.currencies
        ],
        "multi_currency": len(j.currencies) > 1,
    }


@router.get("/rates", response_model=list[schemas.ExchangeRateOut])
def list_rates(currency_code: str = "", limit: int = 100, db: Session = Depends(get_db)):
    """Rate history, append-only, newest first."""
    query = db.query(ExchangeRate)
    if currency_code:
        query = query.filter(ExchangeRate.currency_code == currency_code.upper())
    return query.order_by(desc(ExchangeRate.effective_from), desc(ExchangeRate.id)).limit(limit).all()


@router.post("/rates", response_model=schemas.ExchangeRateOut)
def set_rate(body: schemas.ExchangeRateCreate, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """Publish a new rate. Rates are never edited, a correction is a new entry."""
    code = body.currency_code.upper()
    if code == currency.base_code():
        raise HTTPException(status_code=400,
                            detail=f"{code} is the base currency and is always 1")
    if code not in currency.supported():
        raise HTTPException(
            status_code=400,
            detail=f"{code} is not a trading currency for {settings.jurisdiction.name}",
        )
    if body.units_per_base <= 0:
        raise HTTPException(status_code=400, detail="Rate must be greater than zero")

    rate = ExchangeRate(
        currency_code=code,
        units_per_base=body.units_per_base,
        effective_from=body.effective_from or datetime.utcnow(),
        source=body.source or "manual",
        note=body.note,
        created_by_id=user.id,
    )
    db.add(rate)
    db.commit()
    db.refresh(rate)
    return rate


@router.get("/convert")
def convert(amount: float, from_code: str, to_code: str = "", db: Session = Depends(get_db)):
    """Convert between trading currencies at the rates in force."""
    to_code = (to_code or currency.base_code()).upper()
    try:
        from_rate = currency.current_rate(db, from_code)
        to_rate = currency.current_rate(db, to_code)
    except currency.CurrencyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    in_base = currency.to_base(amount, from_code, from_rate)
    return {
        "amount": amount, "from": from_code.upper(), "to": to_code,
        "in_base": in_base, "base": currency.base_code(),
        "converted": currency.from_base(in_base, to_code, to_rate),
        "from_rate": from_rate, "to_rate": to_rate,
    }
