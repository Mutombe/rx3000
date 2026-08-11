"""Multi-currency money handling.

A pharmacy in a dual-currency market prices in one currency of account and
takes payment in several. Three rules keep the books honest:

1. **Line prices are always held in the base currency.** Converting on display
   is safe; converting on storage compounds rounding into the VAT figures.
2. **Every tender records the rate used.** Rates move; a sale settled last week
   must keep last week's rate or historical totals silently drift.
3. **Change is a negative tender**, not a subtraction, so the drawer can be
   reconciled per currency — a customer paying USD and taking ZiG change moves
   both drawers, and only a per-tender record shows that.
"""
from datetime import datetime

from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ExchangeRate, Sale, SaleTender


class CurrencyError(ValueError):
    """Raised for an unknown currency or a missing rate."""


def base_code() -> str:
    return settings.jurisdiction.base_currency.code


def supported() -> list[str]:
    return [c.code for c in settings.jurisdiction.currencies]


def decimals_for(code: str) -> int:
    for c in settings.jurisdiction.currencies:
        if c.code == code.upper():
            return c.decimals
    return 2


def quantise(amount: float, code: str) -> float:
    return round(amount, decimals_for(code))


def current_rate(db: Session, code: str, at: datetime | None = None) -> float:
    """Units of `code` that buy one unit of the base currency.

    The base currency is always 1. Any other currency needs a rate on record —
    guessing one would silently misstate takings, so this raises instead.
    """
    code = (code or "").upper()
    if not code:
        raise CurrencyError("No currency supplied")
    if code == base_code():
        return 1.0
    if code not in supported():
        raise CurrencyError(
            f"{code} is not a trading currency for {settings.jurisdiction.name} "
            f"(expected one of {', '.join(supported())})"
        )
    query = db.query(ExchangeRate).filter(ExchangeRate.currency_code == code)
    if at:
        query = query.filter(ExchangeRate.effective_from <= at)
    rate = query.order_by(desc(ExchangeRate.effective_from), desc(ExchangeRate.id)).first()
    if not rate:
        raise CurrencyError(f"No exchange rate on record for {code}")
    if rate.units_per_base <= 0:
        raise CurrencyError(f"Exchange rate for {code} is not positive")
    return rate.units_per_base


def to_base(amount: float, code: str, rate: float) -> float:
    """Convert an amount in `code` into the base currency at `rate`."""
    if rate <= 0:
        raise CurrencyError("Exchange rate must be positive")
    return round(amount / rate, 2)


def from_base(amount: float, code: str, rate: float) -> float:
    return quantise(amount * rate, code)


def rate_table(db: Session, at: datetime | None = None) -> dict[str, float]:
    """Every trading currency and its current rate, for display and receipts."""
    table = {}
    for code in supported():
        try:
            table[code] = current_rate(db, code, at)
        except CurrencyError:
            table[code] = 0.0      # no rate yet — the UI shows it as unusable
    return table


def record_tender(db: Session, sale: Sale, *, method: str, currency_code: str,
                  amount: float, reference: str = "", is_change: bool = False) -> SaleTender:
    """Attach one payment (or one lot of change) to a sale."""
    code = (currency_code or base_code()).upper()
    rate = current_rate(db, code)
    signed = -abs(amount) if is_change else amount
    tender = SaleTender(
        sale_id=sale.id, method=method, currency_code=code,
        amount=quantise(signed, code), rate_used=rate,
        amount_in_base=to_base(signed, code, rate),
        is_change=is_change, reference=reference,
    )
    db.add(tender)
    return tender


def settled_in_base(sale: Sale) -> float:
    """What the sale actually collected, net of change, in base currency."""
    return round(sum(t.amount_in_base for t in sale.tenders), 2)


def takings_by_currency(sales: list[Sale]) -> dict:
    """Per-currency, per-method takings — what the drawer should hold.

    Cash is reported net of change because change physically leaves the drawer
    in whichever currency it was given.
    """
    out: dict[str, dict] = {}
    for sale in sales:
        for tender in sale.tenders:
            bucket = out.setdefault(tender.currency_code, {
                "currency": tender.currency_code, "cash": 0.0, "card": 0.0,
                "mobile_money": 0.0, "medical_aid": 0.0, "other": 0.0,
                "total": 0.0, "in_base": 0.0,
            })
            key = tender.method if tender.method in bucket else "other"
            bucket[key] = round(bucket[key] + tender.amount, 2)
            bucket["total"] = round(bucket["total"] + tender.amount, 2)
            bucket["in_base"] = round(bucket["in_base"] + tender.amount_in_base, 2)
    return out
