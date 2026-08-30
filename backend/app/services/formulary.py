"""Formulary coverage.

A scheme rejecting a line at claim time is the worst possible moment to find
out: the medicine has left the shelf and the patient has left the shop. So
coverage is checked *before* dispensing.

A verdict on its own is not much use — "not covered" leaves the pharmacist
stuck. What makes it actionable is the alternative: another product with the
same active ingredient that the scheme *does* pay for. That turns a rejection
into a substitution, which is the entire point.
"""
from dataclasses import asdict, dataclass, field

from sqlalchemy.orm import Session

from ..models import Formulary, FormularyEntry, MedicalAid, Product

# What each status means for a claim, in one place so the UI and the pricing
# engine can never disagree about it.
CLAIMABLE = {"covered", "reference", "authorisation"}


@dataclass
class Alternative:
    product_id: int
    name: str
    strength: str
    status: str
    unit_price: float
    saving: float          # what the patient stops paying by switching


@dataclass
class Coverage:
    product_id: int
    product: str
    status: str            # covered | reference | authorisation | excluded | unknown
    claimable: bool
    reason: str
    reference_price: float = 0.0
    max_quantity: int = 0
    quantity_exceeded: bool = False
    requires_authorisation: bool = False
    formulary: str = ""
    alternatives: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["alternatives"] = [asdict(a) if not isinstance(a, dict) else a
                             for a in self.alternatives]
        return d


def _alternatives(db: Session, formulary: Formulary, product: Product,
                  limit: int = 5) -> list[Alternative]:
    """Covered products sharing this molecule, cheapest first."""
    if not product.active_ingredient:
        return []

    siblings = (
        db.query(Product)
        .filter(Product.active,
                Product.id != product.id,
                Product.active_ingredient == product.active_ingredient)
        .all()
    )
    if not siblings:
        return []

    entries = {
        e.product_id: e
        for e in db.query(FormularyEntry)
        .filter(FormularyEntry.formulary_id == formulary.id,
                FormularyEntry.product_id.in_([s.id for s in siblings]))
        .all()
    }

    out: list[Alternative] = []
    for sib in siblings:
        entry = entries.get(sib.id)
        status = entry.status if entry else formulary.default_rule
        if status not in CLAIMABLE:
            continue
        out.append(Alternative(
            product_id=sib.id,
            name=sib.name,
            strength=sib.strength or "",
            status=status,
            unit_price=round(sib.unit_price or 0.0, 2),
            saving=round(max(0.0, (product.unit_price or 0) - (sib.unit_price or 0)), 2),
        ))
    out.sort(key=lambda a: a.unit_price)
    return out[:limit]


#: Distinguishes "nobody looked it up" from "looked it up and there is none".
#: `None` is a real answer here — a product absent from a formulary falls to the
#: default rule — so a plain default of None would silently skip the lookup.
_NOT_LOOKED_UP = object()


def check(db: Session, scheme: MedicalAid | None, product: Product,
          quantity: int = 1, entry=_NOT_LOOKED_UP) -> Coverage:
    """Where this product stands with this scheme, and what to do about it.

    `entry` lets a caller that is checking several lines hand over the formulary
    entry it has already fetched. Checking a ten-item script one line at a time
    cost thirteen round trips, and this runs on every basket change while
    somebody is dispensing — about a second of nothing happening on a hosted
    database, on the busiest screen in the product.
    """
    if not scheme or not scheme.formulary_id:
        return Coverage(
            product_id=product.id,
            product=f"{product.name} {product.strength}".strip(),
            status="unknown", claimable=bool(scheme),
            reason="No formulary is attached to this scheme, nothing is enforced.",
        )

    formulary: Formulary | None = scheme.formulary
    if not formulary or not formulary.active:
        return Coverage(
            product_id=product.id,
            product=f"{product.name} {product.strength}".strip(),
            status="unknown", claimable=True,
            reason="The scheme's formulary is inactive, nothing is enforced.",
        )

    if entry is _NOT_LOOKED_UP:
        entry = (
            db.query(FormularyEntry)
            .filter(FormularyEntry.formulary_id == formulary.id,
                    FormularyEntry.product_id == product.id)
            .first()
        )

    status = entry.status if entry else formulary.default_rule
    claimable = status in CLAIMABLE
    over_limit = bool(entry and entry.max_quantity and quantity > entry.max_quantity)

    if not entry:
        reason = (f"Not listed on {formulary.name}; the formulary is open, so it is paid."
                  if formulary.default_rule == "covered"
                  else f"Not listed on {formulary.name}, which is a closed formulary, so "
                       "the scheme will not pay for it.")
    elif status == "covered":
        reason = f"Covered by {formulary.name}."
    elif status == "reference":
        reason = ("Paid up to the reference price. The patient pays anything above it.")
    elif status == "authorisation":
        reason = "Paid only against an authorisation number from the scheme."
    else:
        reason = entry.note or f"Excluded from {formulary.name}, the scheme will not pay."

    if over_limit:
        reason += (f" Quantity {quantity} exceeds the {entry.max_quantity} "
                   "the scheme allows per dispensing.")

    coverage = Coverage(
        product_id=product.id,
        product=f"{product.name} {product.strength}".strip(),
        status=status,
        claimable=claimable and not over_limit,
        reason=reason,
        reference_price=round(entry.reference_price, 2) if entry else 0.0,
        max_quantity=entry.max_quantity if entry else 0,
        quantity_exceeded=over_limit,
        requires_authorisation=bool(entry and entry.requires_authorisation) or status == "authorisation",
        formulary=formulary.name,
    )

    # Only bother looking for a substitute when there is a problem to solve.
    if not coverage.claimable or status in ("reference", "authorisation"):
        coverage.alternatives = _alternatives(db, formulary, product)
    return coverage


def check_basket(db: Session, scheme: MedicalAid | None,
                 lines: list[tuple[Product, int]]) -> dict:
    # Every line's formulary entry in one query rather than one query a line.
    # `_alternatives` below still costs a query, but only for a line that has a
    # problem — which is the minority, and the point at which somebody is
    # willing to wait a moment for an answer.
    entries: dict[int, object] = {}
    looked_up = bool(scheme and scheme.formulary_id and lines)
    if looked_up:
        rows = (db.query(FormularyEntry)
                .filter(FormularyEntry.formulary_id == scheme.formulary_id,
                        FormularyEntry.product_id.in_([p.id for p, _ in lines]))
                .all())
        entries = {r.product_id: r for r in rows}

    # `None` from the map is a real answer — the product is not on the
    # formulary and falls to its default rule — so it is only passed when the
    # lookup actually ran.
    results = [
        check(db, scheme, product, qty,
              entry=entries.get(product.id) if looked_up else _NOT_LOOKED_UP)
        for product, qty in lines
    ]
    blocked = [r for r in results if not r.claimable]
    needs_auth = [r for r in results if r.requires_authorisation]
    return {
        "scheme": scheme.name if scheme else None,
        "formulary": scheme.formulary.name if scheme and scheme.formulary else None,
        "lines": [r.as_dict() for r in results],
        "all_claimable": not blocked,
        "blocked_count": len(blocked),
        "authorisation_required": len(needs_auth) > 0,
    }
