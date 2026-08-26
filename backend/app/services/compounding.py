"""Extemporaneous preparations.

A compound is assembled from stock at the moment it is needed, which makes two
things true that a shelf product never has to worry about:

* **Its cost is the sum of what went into it**, plus the labour of making it up.
  Nothing on a price file describes it.
* **Its schedule is the highest schedule of any ingredient.** A cream containing
  a controlled substance is a controlled substance. Treating the compound as a
  cream would let an S6 walk out of the shop without a register entry, so the
  schedule is derived here rather than typed anywhere.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .. import helpers
from ..config import settings
from ..models import Mixture, Product, StockBatch


class CompoundingError(ValueError):
    """Raised when a preparation cannot be made up."""


@dataclass
class IngredientCost:
    product_id: int
    name: str
    quantity: float
    unit: str
    unit_cost: float
    line_cost: float
    schedule: int
    on_hand: int
    short: bool


def effective_schedule(mixture: Mixture) -> int:
    """The highest schedule among the ingredients, never lower."""
    return max((i.product.schedule or 0) for i in mixture.ingredients) if mixture.ingredients else 0


def cost(db: Session, mixture: Mixture, batches: float = 1.0) -> dict:
    """What one (or several) preparations cost to make, and whether stock allows it."""
    if not mixture.ingredients:
        raise CompoundingError(f"{mixture.name} has no ingredients")

    lines: list[IngredientCost] = []
    for ing in mixture.ingredients:
        product: Product = ing.product
        needed = round(ing.quantity * batches, 3)
        unit_cost = product.cost_price or 0.0
        lines.append(IngredientCost(
            product_id=product.id,
            name=f"{product.name} {product.strength}".strip(),
            quantity=needed,
            unit=ing.unit,
            unit_cost=round(unit_cost, 2),
            line_cost=round(unit_cost * needed, 2),
            schedule=product.schedule or 0,
            on_hand=product.quantity_on_hand,
            short=product.quantity_on_hand < needed,
        ))

    ingredient_cost = round(sum(l.line_cost for l in lines), 2)
    fee = round((mixture.compounding_fee or 0.0) * batches, 2)
    schedule = effective_schedule(mixture)

    return {
        "mixture": mixture.name,
        "code": mixture.code,
        "form": mixture.form,
        "batches": batches,
        "yield_quantity": round(mixture.yield_quantity * batches, 3),
        "yield_unit": mixture.yield_unit,
        "ingredient_cost": ingredient_cost,
        "compounding_fee": fee,
        "total_cost": round(ingredient_cost + fee, 2),
        "effective_schedule": schedule,
        "schedule_source": _schedule_source(mixture, schedule),
        "can_prepare": not any(l.short for l in lines),
        "short_of": [l.name for l in lines if l.short],
        "ingredients": [l.__dict__ for l in lines],
    }


def _schedule_source(mixture: Mixture, schedule: int) -> str:
    if schedule == 0:
        return "No scheduled ingredient."
    driver = next((i.product for i in mixture.ingredients
                   if (i.product.schedule or 0) == schedule), None)
    return (f"Schedule {schedule}, inherited from {driver.name}."
            if driver else f"Schedule {schedule}.")


def prepare(db: Session, mixture: Mixture, user_id: int, batches: float = 1.0,
            reference: str = "") -> dict:
    """Make the preparation up: draw the ingredients and record the result.

    Ingredients leave stock through the ordinary FEFO path, so a compound never
    quietly bypasses batch tracking or expiry rules.
    """
    summary = cost(db, mixture, batches)
    if not summary["can_prepare"]:
        raise CompoundingError(
            f"Not enough stock to make up {mixture.name}: short of "
            + ", ".join(summary["short_of"])
        )

    ref = reference or f"COMPOUND {mixture.code}"
    drawn = []
    for ing in mixture.ingredients:
        needed = ing.quantity * batches
        # Quantities are whole units at stock level; a partial draw still
        # consumes a unit, which is how a dispensary actually works.
        units = int(needed) if float(needed).is_integer() else int(needed) + 1
        helpers.consume_stock_fefo(db, ing.product, units, "compound", user_id, reference=ref)
        # A controlled ingredient going into a mixture is controlled stock
        # leaving the shelf, and the register must show where it went. This was
        # missing: preparing a Schedule 5 cream drew the Tramadol through FEFO and
        # wrote nothing to the register, so the register balanced against a
        # quantity that was no longer there and nobody could say why. The helper
        # is a no-op below S5, so ordinary ingredients cost nothing here.
        helpers.record_register_entry(
            db, ing.product, -units, "compound", user_id, reference=ref)
        drawn.append({"product": ing.product.name, "units": units})

    expiry = date.today() + timedelta(days=mixture.shelf_life_days or 30)
    db.commit()

    return {
        **summary,
        "prepared": True,
        "reference": ref,
        "expiry_date": expiry.isoformat(),
        "drawn": drawn,
        "label_directions": mixture.directions,
        "warning": ("This preparation is Schedule "
                    f"{summary['effective_schedule']}, dispense it under the "
                    "rules for that schedule, not as an ordinary preparation."
                    if summary["effective_schedule"] >= 5 else ""),
    }
