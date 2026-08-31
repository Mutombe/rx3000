"""Regulated medicine pricing.

A dispensed price is **derived, never typed**. It is built from a base price —
the single exit price — plus a professional fee that steps by price band, and
is then capped, discounted and levied according to the scheme being billed.
Typing a price by hand is how a pharmacy ends up short-paid or over-claiming.

The order matters, and it is the order a scheme audits:

    1. base            single exit price × quantity
    2. MMAP cap        where the scheme prices generics off a reference price,
                       the medicine portion is capped and the patient pays the
                       difference — that difference is never claimable
    3. fee             professional fee from the price band
    4. markup          any scheme-specific extra markup
    5. discount        scheme discount off the gross
    6. levy            patient co-payment, fixed or a percentage
    7. claim           what the scheme is asked to pay

Fee bands are data, not code: they are set by regulation and revised, and a
revision must not require a release.
"""
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from ..models import FeeModel, MedicalAid, Product


@dataclass
class PricedLine:
    """Every number a claim line needs, and how it was reached."""
    product_id: int
    description: str
    quantity: int
    base_price: float          # SEP × qty, before anything
    mmap_cap: float            # 0 when no cap applies
    mmap_excess: float         # patient pays this, never claimable
    medicine_portion: float    # after any cap
    dispensing_fee: float
    markup: float
    gross: float               # what the line is worth before scheme rules
    discount: float
    levy: float                # patient co-payment
    claimable: float           # what the scheme is asked to pay
    patient_portion: float     # levy + mmap excess
    fee_model: str
    basis: str
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _tier_for(model: FeeModel, base: float):
    """First band whose ceiling the base price falls within, else the top band."""
    banded = [t for t in model.tiers if t.up_to is not None]
    for tier in sorted(banded, key=lambda t: t.up_to):
        if base <= tier.up_to:
            return tier
    open_ended = [t for t in model.tiers if t.up_to is None]
    return open_ended[0] if open_ended else None


def professional_fee(model: FeeModel | None, base: float) -> float:
    """The fee for a base price under a fee model. No model means no fee."""
    if not model or base <= 0:
        return 0.0
    tier = _tier_for(model, base)
    if not tier:
        return 0.0
    fee = base * (tier.percentage or 0.0) / 100.0 + (tier.fixed_fee or 0.0)
    if tier.min_fee:
        fee = max(fee, tier.min_fee)
    if tier.max_fee is not None:
        fee = min(fee, tier.max_fee)
    return round(fee, 2)


def price_line(db: Session, product: Product, quantity: int,
               scheme: MedicalAid | None = None) -> PricedLine:
    """Price one dispensed line for a scheme (or privately when scheme is None)."""
    quantity = max(1, int(quantity or 1))
    model = scheme.fee_model if scheme and scheme.fee_model else None
    basis = model.basis if model else "sep"

    unit = product.cost_price if basis == "cost" else product.unit_price
    base = round((unit or 0.0) * quantity, 2)

    # MMAP: cap the medicine portion, and remember the excess — the patient pays
    # it and it can never be claimed.
    mmap_cap = 0.0
    mmap_excess = 0.0
    medicine = base
    if model and model.apply_mmap and (product.mmap_price or 0) > 0:
        mmap_cap = round(product.mmap_price * quantity, 2)
        if base > mmap_cap:
            mmap_excess = round(base - mmap_cap, 2)
            medicine = mmap_cap

    fee = professional_fee(model, medicine)
    markup = round(medicine * (scheme.extra_markup_percent or 0.0) / 100.0, 2) if scheme else 0.0
    gross = round(medicine + fee + markup, 2)

    discount = round(gross * (scheme.discount_percent or 0.0) / 100.0, 2) if scheme else 0.0
    after_discount = round(gross - discount, 2)

    levy = 0.0
    if scheme:
        levy = round(max(scheme.levy_fixed or 0.0,
                         after_discount * (scheme.levy_percent or 0.0) / 100.0), 2)
        levy = min(levy, after_discount)

    claimable = round(after_discount - levy, 2) if scheme else 0.0

    notes = ""
    if mmap_excess:
        # "Shortfall" because that is what the pharmacy, the patient and the
        # scheme all call it. It also read "the patient pays the5.00
        # difference": two adjacent f-strings with the space at neither end.
        notes = (f"Priced above the reference price. The {mmap_excess:.2f} "
                 f"difference is a shortfall the patient settles at the "
                 f"counter, and is not claimable.")

    return PricedLine(
        product_id=product.id,
        description=f"{product.name} {product.strength}".strip(),
        quantity=quantity,
        base_price=base,
        mmap_cap=mmap_cap,
        mmap_excess=mmap_excess,
        medicine_portion=medicine,
        dispensing_fee=fee,
        markup=markup,
        gross=gross,
        discount=discount,
        levy=levy,
        claimable=claimable,
        patient_portion=round(levy + mmap_excess, 2),
        fee_model=model.code if model else "",
        basis=basis,
        notes=notes,
    )


def price_basket(db: Session, lines: list[tuple[Product, int]],
                 scheme: MedicalAid | None = None) -> dict:
    """Price a whole script and total it the way a claim is totalled."""
    priced = [price_line(db, product, qty, scheme) for product, qty in lines]
    total = lambda f: round(sum(getattr(p, f) for p in priced), 2)  # noqa: E731
    return {
        "lines": [p.as_dict() for p in priced],
        "gross": total("gross"),
        "dispensing_fee": total("dispensing_fee"),
        "discount": total("discount"),
        "levy": total("levy"),
        "mmap_excess": total("mmap_excess"),
        "claimable": total("claimable"),
        "patient_portion": total("patient_portion"),
        "scheme": scheme.name if scheme else None,
        "fee_model": (scheme.fee_model.code if scheme and scheme.fee_model else None),
    }
