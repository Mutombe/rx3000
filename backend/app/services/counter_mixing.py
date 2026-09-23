"""Something made up at the counter, while the patient waits.

A dispenser mixes calamine with menthol, or halves a cream into an ointment
base, and hands it over on the same script. The incumbent called it a free-type
label: type a name, print a sticker, and nothing else in the system ever heard
of it. That is fast and it is untraceable — no stock came off the ingredients,
the preparation has no batch, and a recall on the menthol cannot reach the
patient who was given it.

So a preparation made here is a real thing from the moment it exists:

  its ingredients leave stock through the ordinary FEFO path, batch by batch,
    and a controlled ingredient writes its register entry like any other;
  it becomes a product of its own, with a batch number, an expiry taken from
    its shelf life, and the schedule of its strongest ingredient;
  it goes onto the script as a line like any other, so it is dispensed,
    labelled, priced, claimed and recalled by everything already built.

The schedule is the strongest ingredient's, never lower: a cream with tramadol
in it is a schedule 5 preparation, and the dispenser is told so before they
make it up rather than after they have handed it over.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from .. import helpers
from ..models import Mixture, MixtureIngredient, Product, StockCategory
from . import compounding

#: Where preparations are filed, so the dispensary searches them and the shop
#: reports on them separately from bought-in stock.
DEPARTMENT = "COMPOUNDED PREPARATIONS"


class MixingError(Exception):
    """Something about the request makes the preparation impossible."""


def _department(db: Session, pharmacy_id: int | None) -> StockCategory:
    existing = (db.query(StockCategory)
                .filter(StockCategory.name == DEPARTMENT).first())
    if existing:
        return existing
    made = StockCategory(name=DEPARTMENT, code="MIX", dispensable=True, active=True,
                         pharmacy_id=pharmacy_id)
    db.add(made)
    db.flush()
    return made


def quote(db: Session, *, ingredients: list[dict], fee: float = 0.0) -> dict:
    """What it would cost, what schedule it would be, and whether stock allows it.

    Asked while the dispenser is still typing, so nothing is written and the
    mixture it is costed against never reaches the database.
    """
    if not ingredients:
        raise MixingError("A preparation needs at least one ingredient.")
    draft = Mixture(code="DRAFT", name="draft", yield_quantity=1.0,
                    compounding_fee=fee, shelf_life_days=30)
    draft.ingredients = []
    for line in ingredients:
        product = db.get(Product, int(line.get("product_id") or 0))
        if product is None:
            raise MixingError("One of the ingredients is not a product this pharmacy has.")
        quantity = float(line.get("quantity") or 0)
        if quantity <= 0:
            raise MixingError(f"Say how much {product.name} goes into it.")
        draft.ingredients.append(
            MixtureIngredient(product_id=product.id, quantity=quantity))
    # The relationship is not loaded from the database here, so the products the
    # costing walks to are attached by hand.
    for ing, line in zip(draft.ingredients, ingredients):
        ing.product = db.get(Product, int(line["product_id"]))
    return compounding.cost(db, draft, 1.0)


def make(db: Session, *, name: str, ingredients: list[dict], user_id: int,
         makes: int = 1, unit: str = "", shelf_life_days: int = 30,
         directions: str = "", price: float = 0.0, fee: float = 0.0,
         keep_formula: bool = False, branch_id: int | None = None,
         pharmacy_id: int | None = None) -> dict:
    """Make it up: draw the ingredients, and give the result a batch of its own."""
    name = " ".join((name or "").split())
    if len(name) < 3:
        raise MixingError("Give the preparation a name the patient will read.")
    if makes < 1:
        raise MixingError("Say how many it makes.")
    summary = quote(db, ingredients=ingredients, fee=fee)
    if not summary["can_prepare"]:
        raise MixingError("Not enough stock to make it up: short of "
                          + ", ".join(summary["short_of"]))

    # NUMBERED FROM THE PRODUCT, WHICH IS ALWAYS WRITTEN.
    #
    # This read the highest MIX code on the Mixture table. A counter mix only
    # creates a Mixture when the pharmacist ticks "keep this formula", which is
    # off by default, so the counter never advanced: four different
    # preparations on this database all carry MIX260900001 as their stock code,
    # their batch number and the reference on every ingredient movement.
    #
    # That is worse than a failed insert. A recall on that batch returns four
    # preparations, and there is no way to tell which ingredients went into
    # which, which is exactly what the reference exists to answer. The
    # preparation itself is always created as a Product carrying the reference
    # as its stock code, so the numbering reads from there.
    reference = helpers.next_number(db, Product, "MIX", "stock_code")
    schedule = int(summary["effective_schedule"] or 0)
    unit_cost = round(float(summary["total_cost"]) / max(1, makes), 2)

    # The preparation as a product, so everything downstream — dispensing, the
    # label, the claim, a recall — works on it without knowing it was mixed here.
    preparation = Product(
        name=name[:200],
        stock_code=reference,
        category="medicine",
        category_id=_department(db, pharmacy_id).id,
        dosage_form=(unit or "preparation")[:40],
        schedule=schedule,
        units_per_pack=1,
        unit_price=round(float(price or 0) or unit_cost * 2, 2),
        cost_price=unit_cost,
        vat_rate=0.0,
        reorder_level=0,
        reorder_quantity=0,
        # Made for this patient, on this day. Not something to reorder, and not
        # something anybody should find on tomorrow's shelf report as a gap.
        active=True,
        pharmacy_id=pharmacy_id,
    )
    db.add(preparation)
    db.flush()

    # The ingredients leave stock, batch by batch, exactly as a dispensing does.
    for line in ingredients:
        product = db.get(Product, int(line["product_id"]))
        needed = float(line["quantity"])
        units = int(needed) if float(needed).is_integer() else int(needed) + 1
        helpers.consume_stock_fefo(db, product, units, "compound", user_id,
                                   reference=reference, branch_id=branch_id)
        helpers.record_register_entry(db, product, -units, "compound", user_id,
                                      reference=reference)

    expiry = date.today() + timedelta(days=max(1, shelf_life_days))
    helpers.receive_stock_batch(db, preparation, makes, user_id,
                                batch_number=reference, expiry_date=expiry,
                                unit_cost=unit_cost, reference=reference,
                                movement_type="compound", branch_id=branch_id)

    formula_id = None
    if keep_formula:
        # Worth keeping: a pharmacy that makes this up twice a week should not
        # rebuild it from memory each time.
        formula = Mixture(code=reference, name=name[:200], form=(unit or "mixture")[:40],
                          yield_quantity=float(makes), yield_unit=(unit or "unit")[:20],
                          compounding_fee=fee, shelf_life_days=shelf_life_days,
                          directions=directions, active=True, pharmacy_id=pharmacy_id)
        db.add(formula)
        db.flush()
        for line in ingredients:
            db.add(MixtureIngredient(mixture_id=formula.id,
                                     product_id=int(line["product_id"]),
                                     quantity=float(line["quantity"]),
                                     pharmacy_id=pharmacy_id))
        formula_id = formula.id

    db.commit()
    db.refresh(preparation)
    return {
        "product_id": preparation.id,
        "name": preparation.name,
        "reference": reference,
        "batch_number": reference,
        "expiry_date": expiry.isoformat(),
        "schedule": schedule,
        "quantity": makes,
        "unit_cost": unit_cost,
        "unit_price": preparation.unit_price,
        "directions": directions,
        "formula_id": formula_id,
        "drawn": [{"product": db.get(Product, int(l["product_id"])).name,
                   "quantity": float(l["quantity"])} for l in ingredients],
        "warning": (f"This preparation is Schedule {schedule}: dispense it under the rules "
                    "for that schedule." if schedule >= 5 else ""),
    }


# ---------------------------------------------------------------------------
# WHAT HAS ACTUALLY BEEN MADE UP
#
# Every preparation already leaves a complete trail: the ingredients go out as
# stock movements of type "compound" carrying the reference, and the
# preparation comes back in as a batch under the same reference. Nothing
# recorded it as a *job* anybody could look at, so a pharmacy could make up
# forty preparations in a month and have no screen that said so.
#
# Read from the movements rather than stored again as a third copy: a separate
# log would be one more thing to keep in step with the stock, and the moment it
# disagreed the stock would be right and the log would be believed.
# ---------------------------------------------------------------------------

def history(db: Session, *, limit: int = 100, q: str = "") -> list[dict]:
    """Every preparation made up at the counter, most recent first.

    Grouped by the reference, which since the numbering fix is unique per
    preparation. Four older rows on this database share MIX260900001 and will
    group together: that is the damage the old numbering did, shown rather than
    hidden, because pretending they were one job would be a worse lie than
    admitting the reference cannot separate them.
    """
    from ..models import StockBatch, StockMovement, User

    rows = (db.query(StockMovement)
            .filter(StockMovement.movement_type == "compound",
                    StockMovement.reference.like("MIX%"))
            .order_by(StockMovement.created_at.desc())
            .limit(max(1, min(limit, 500)) * 12)
            .all())

    made: dict[str, dict] = {}
    for m in rows:
        job = made.setdefault(m.reference, {
            "reference": m.reference, "made_at": m.created_at,
            "made_by": "", "made_by_id": m.user_id,
            "product_id": None, "preparation": "", "quantity": 0,
            "unit_cost": 0.0, "expiry": None, "schedule": 0,
            "ingredients": [], "ingredient_count": 0,
        })
        # A positive movement is the preparation coming in; the negatives are
        # what went into it.
        if (m.quantity_delta or 0) > 0:
            product = db.get(Product, m.product_id)
            job["product_id"] = m.product_id
            job["preparation"] = product.name if product else ""
            job["quantity"] = m.quantity_delta
            job["unit_cost"] = round(product.cost_price or 0.0, 2) if product else 0.0
            job["schedule"] = int(product.schedule or 0) if product else 0
            if m.created_at and (not job["made_at"] or m.created_at > job["made_at"]):
                job["made_at"] = m.created_at
        else:
            product = db.get(Product, m.product_id)
            job["ingredients"].append({
                "product_id": m.product_id,
                "product": product.name if product else "",
                "quantity": abs(m.quantity_delta or 0),
            })

    # Who made it, and what it expires on, in two queries rather than two a row.
    who = {u.id: u.full_name for u in db.query(User).all()} if made else {}
    refs = list(made)
    if refs:
        for batch in (db.query(StockBatch)
                      .filter(StockBatch.batch_number.in_(refs)).all()):
            job = made.get(batch.batch_number)
            if job and batch.expiry_date and not job["expiry"]:
                job["expiry"] = batch.expiry_date.isoformat()

    out = []
    for job in made.values():
        job["made_by"] = who.get(job["made_by_id"], "")
        job["ingredient_count"] = len(job["ingredients"])
        job["made_at"] = job["made_at"].isoformat() if job["made_at"] else ""
        job["cost"] = round(job["unit_cost"] * (job["quantity"] or 0), 2)
        out.append(job)

    needle = (q or "").strip().lower()
    if needle:
        out = [j for j in out
               if needle in j["preparation"].lower()
               or needle in j["reference"].lower()
               or needle in (j["made_by"] or "").lower()
               or any(needle in i["product"].lower() for i in j["ingredients"])]

    out.sort(key=lambda j: j["made_at"], reverse=True)
    return out[:limit]
