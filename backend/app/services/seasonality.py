"""What sells in which month, per branch and across the group.

A pharmacy's year is not flat and everybody in one knows it. Malaria treatment
moves from November to April with the rains; cough and cold and antibiotics
climb through the cold months; antihistamines rise with the jacaranda; school
things go in January. A shop that orders on last month's usage is permanently
one month behind its own season — ordering antimalarials in March, when the
rains are ending, and running out in December when they are not.

The buying decision is not "what did we sell last month". It is "what will we
sell next month, and when must it be on the shelf". Nothing here answered that.

WHAT AN HONEST SEASONAL READ REQUIRES, AND WHAT THIS DATA HAS

Two years, at least. A seasonal index is a claim that *this month* differs from
the average month **repeatedly** — and one observation of December is not a
pattern, it is a December. With a single year a growing shop reads as seasonal
in every later month, and a shrinking one as seasonal in every earlier one,
because trend and season are the same shape when you only see them once.

This estate holds sixteen months. So every figure below is reported with the
number of years it was computed from, and a month seen once is labelled as a
single observation rather than dressed as a season. That label is the most
useful thing on the report: a buyer who knows a number is one December's worth
treats it differently from one who does not, and the difference is whether they
commit to an order on it.

BRANCH AND GROUP

Both, because they disagree in ways that matter. A branch by a clinic and a
branch in a shopping centre have different years, and a group figure averages
them into a shape neither of them has. The group number is right for buying
from a wholesaler; the branch number is right for what goes on which shelf.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Branch, Dispensing, Prescription, PrescriptionItem,
                      Product, Sale, SaleItem, StockCategory)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

#: A month has to be this far from the average to be called a season rather
#: than noise. Twenty-five per cent: below that, a buyer would not change an
#: order, and a report that flags what nobody would act on is one nobody reads.
THRESHOLD = 0.25

#: Fewer observations than this and the month is reported as an observation,
#: not a season. See the module docstring — this is the honest half.
YEARS_FOR_A_SEASON = 2

#: How much of the year has to have been seen before its shape is described at
#: all. A line seen in half the year has as many missing months as present
#: ones, and the shape of the missing ones is precisely what is being claimed.
MONTHS_FOR_A_SHAPE = 9

#: Times a line must go out in a typical month before a busier month is worth
#: reporting. Below this the index is arithmetic on noise: a line asked for
#: once or twice a month reads as ten times seasonal the week three people
#: happen to want it.
MIN_TYPICAL_MONTH = 4.0


def _monthly(db: Session, *, branch_id: int | None,
             years_back: int = 3) -> dict:
    """Units out per product per calendar month, from sales and dispensings.

    Both, because neither alone is the shop's usage: a front-shop line never
    appears in a dispensing and a scheme script often never reaches a sale.

    Counted as OCCASIONS — how many times it went out — rather than as units.
    Two reasons, and the first is not obvious until you see what it does:

    Pack sizes differ by three orders of magnitude on the same shelf. A bottle
    of a thousand tablets sold once in September is a thousand units in
    September, and against a typical month of eight it reads as a thirty-eight
    times seasonal peak. The first version of this reported exactly that, for
    every line whose name ended in "1000S" — arithmetic performed correctly on
    the wrong quantity.

    And seasonality is a claim about DEMAND: how often somebody comes in
    wanting the thing. Twice as many people asking in April is the fact a buyer
    acts on. One person buying a big box is not a season, it is a big box.

    Money is not used either, so a price rise in June does not read as a June
    season.
    """
    since = datetime.utcnow() - timedelta(days=365 * years_back + 30)

    # (product_id, year, month) -> units
    units: dict[tuple, float] = defaultdict(float)
    seen_years: dict[tuple, set] = defaultdict(set)
    names: dict[int, tuple] = {}

    sale_q = (
        db.query(SaleItem.product_id, Sale.created_at, SaleItem.quantity,
                 Product.name, Product.category_id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(Sale.created_at >= since,
                Sale.status.in_(("paid", "part_paid"))))
    if branch_id:
        sale_q = sale_q.filter(Sale.branch_id == branch_id)
    for product_id, at, quantity, name, category_id in sale_q.all():
        if not at:
            continue
        # One occasion, whatever the pack size. See the docstring.
        units[(product_id, at.month)] += 1
        seen_years[(product_id, at.month)].add(at.year)
        names.setdefault(product_id, (name, category_id))

    disp_q = (
        db.query(PrescriptionItem.product_id, Dispensing.dispensed_at,
                 Dispensing.quantity, Product.name, Product.category_id)
        .join(PrescriptionItem,
              PrescriptionItem.id == Dispensing.prescription_item_id)
        .join(Product, Product.id == PrescriptionItem.product_id)
        .filter(Dispensing.dispensed_at >= since))
    if branch_id:
        # A dispensing has no branch of its own; it belongs to the script's.
        disp_q = (disp_q
                  .join(Prescription,
                        Prescription.id == PrescriptionItem.prescription_id)
                  .filter(Prescription.branch_id == branch_id))
    for product_id, at, quantity, name, category_id in disp_q.all():
        if not at:
            continue
        units[(product_id, at.month)] += 1
        seen_years[(product_id, at.month)].add(at.year)
        names.setdefault(product_id, (name, category_id))

    return {"units": units, "years": seen_years, "names": names}


def products(db: Session, *, branch_id: int | None = None,
             limit: int = 40, min_units: float = 24.0) -> dict:
    """Which medicines have a season, and when it is.

    Ordered by how pronounced the season is rather than by volume: a line that
    triples in April is worth a buyer's attention even if it is small, and a
    line that sells two hundred a month every month needs no seasonal decision
    at all.
    """
    data = _monthly(db, branch_id=branch_id)
    units, years, names = data["units"], data["years"], data["names"]

    by_product: dict[int, list[float]] = defaultdict(lambda: [0.0] * 12)
    year_count: dict[int, list[int]] = defaultdict(lambda: [0] * 12)
    for (product_id, month), n in units.items():
        by_product[product_id][month - 1] = n
        year_count[product_id][month - 1] = len(years[(product_id, month)])

    rows = []
    for product_id, months in by_product.items():
        # Times it went out across the whole period, not units.
        total = sum(months)
        if total < min_units:
            continue
        # Divide each month by the years it was actually observed in, or a
        # product recorded twice in July and once in March looks like a July
        # medicine when it is only an older one.
        observed = year_count[product_id]
        per_year = [
            (months[i] / observed[i]) if observed[i] else 0.0
            for i in range(12)
        ]
        active = [v for v, o in zip(per_year, observed) if o]
        if len(active) < MONTHS_FOR_A_SHAPE:
            # Too little of the year seen to say anything about its shape. Nine
            # months, not six: a line seen in half the year has as many missing
            # months as present ones, and the shape of what is missing is the
            # thing being claimed.
            continue

        # Against the MEDIAN month, not the mean, and peak-over-typical rather
        # than peak-minus-trough.
        #
        # The first version used (peak − trough) / mean and called 534 of 537
        # lines seasonal, which is the same as calling none of them seasonal.
        # One thin month drags the trough to nearly zero and the mean down with
        # it, so every line with a quiet August looked like it had a season. A
        # median is not moved by one quiet month, which is exactly the property
        # wanted: a season is a month that stands out from a TYPICAL month, and
        # the typical month is what a median is.
        ordered = sorted(active)
        middle = len(ordered) // 2
        median = (ordered[middle] if len(ordered) % 2
                  else (ordered[middle - 1] + ordered[middle]) / 2)
        # A typical month has to hold enough units for a busier one to mean
        # anything. A line averaging one or two a month gives an index of
        # thirty the first time three go out together, and thirty is a number
        # somebody would act on — it is noise wearing a decimal point.
        #
        # This is the guard that took the report from "302 of 340 lines are
        # seasonal", which is the same statement as "none of them are", down to
        # something a buyer can read.
        if median < MIN_TYPICAL_MONTH:
            continue
        mean = median

        index = [round(v / median, 2) if observed[i] else None
                 for i, v in enumerate(per_year)]
        peak_i = max(range(12), key=lambda i: per_year[i] if observed[i] else -1)
        trough_i = min(range(12),
                       key=lambda i: per_year[i] if observed[i] else 1e18)
        swing = round(per_year[peak_i] / median - 1, 2)

        # Is this a season, or one month we happened to see once?
        confident = min(o for o in observed if o) >= YEARS_FOR_A_SEASON \
            if any(observed) else False
        peak_years = observed[peak_i]

        name, category_id = names.get(product_id, ("", None))
        rows.append({
            "product_id": product_id,
            "product": name,
            "category_id": category_id,
            "occasions": round(total, 1),
            "index": index,
            "peak_month": MONTHS[peak_i],
            "peak_index": index[peak_i],
            "trough_month": MONTHS[trough_i],
            "swing": swing,
            # A month has to stand half again above a typical one before a
            # buyer would change an order for it.
            "seasonal": swing >= THRESHOLD * 2,
            "years_at_peak": peak_years,
            "confident": confident and peak_years >= YEARS_FOR_A_SEASON,
            # What a buyer does about it, said as an instruction rather than
            # left for them to derive from an index.
            "action": _action(MONTHS[peak_i], index[peak_i], peak_years, swing),
        })

    rows.sort(key=lambda r: -r["swing"])
    seasonal = [r for r in rows if r["seasonal"]]
    confident = [r for r in seasonal if r["confident"]]

    return {
        "branch_id": branch_id,
        "products": rows[:limit],
        "counted": len(rows),
        "seasonal": len(seasonal),
        "confident": len(confident),
        "years_needed": YEARS_FOR_A_SEASON,
        "note": _note(len(rows), len(seasonal), len(confident)),
    }


def _action(peak: str, peak_index: float | None, peak_years: int,
            swing: float) -> str:
    if peak_years < YEARS_FOR_A_SEASON:
        return (f"Busiest in {peak}, seen once. Watch it next {peak} before "
                f"buying to it — one {peak} is not a season.")
    if peak_index and peak_index >= 1.5:
        return (f"Runs at {peak_index:.1f}× the average in {peak}. Have it on "
                f"the shelf by the end of the month before.")
    return (f"Busiest in {peak}. Worth a larger order the month before, not "
            f"a standing increase.")


def _note(counted: int, seasonal: int, confident: int) -> str:
    if not counted:
        return ("Not enough history to read a season. This needs a year of "
                "trading before it says anything, and two before it says it "
                "with confidence.")
    if not confident:
        return (f"{seasonal} of {counted} lines move with the calendar, and "
                f"none has been seen in {YEARS_FOR_A_SEASON} separate years "
                f"yet — so these are observations rather than seasons. A "
                f"growing shop looks seasonal in every later month when you "
                f"only have one year of it. Treat them as a watch list.")
    return (f"{seasonal} of {counted} lines move with the calendar; {confident} "
            f"have done it in {YEARS_FOR_A_SEASON} or more separate years and "
            f"can be bought to.")


def by_month(db: Session, *, branch_id: int | None = None) -> list[dict]:
    """The shop's own year: units and money out per calendar month.

    The shape a manager recognises before they trust anything else on the
    screen — if the whole-shop curve does not look like their year, nothing
    built on it will.
    """
    since = datetime.utcnow() - timedelta(days=365 * 3 + 30)
    # The month, spelt the way each database spells it. `group_by(1)` is
    # standard SQL and SQLAlchemy's ORM will not take it, so the expression is
    # named once and used in both places.
    month_of = (func.strftime("%m", Sale.created_at) if _is_sqlite(db)
                else func.to_char(Sale.created_at, "MM"))
    q = (db.query(month_of,
                  func.count(func.distinct(Sale.id)),
                  func.coalesce(func.sum(Sale.total), 0.0))
         .filter(Sale.created_at >= since,
                 Sale.status.in_(("paid", "part_paid"))))
    if branch_id:
        q = q.filter(Sale.branch_id == branch_id)
    rows = dict()
    for month, sales, total in q.group_by(month_of).all():
        try:
            rows[int(month)] = (int(sales), round(float(total or 0), 2))
        except (TypeError, ValueError):
            continue

    total_money = sum(v[1] for v in rows.values()) or 1.0
    return [{
        "month": MONTHS[m - 1],
        "sales": rows.get(m, (0, 0.0))[0],
        "value": rows.get(m, (0, 0.0))[1],
        "share": round(100.0 * rows.get(m, (0, 0.0))[1] / total_money, 1),
    } for m in range(1, 13)]


def _is_sqlite(db: Session) -> bool:
    return db.bind.dialect.name == "sqlite" if db.bind else True


def group(db: Session, *, limit: int = 15) -> dict:
    """Every branch's year beside the group's.

    A branch by a clinic and one in a shopping centre have different years, and
    the group figure averages them into a shape neither has. Both are here
    because they are used for different decisions: the group number buys from a
    wholesaler, the branch number decides what goes on which shelf.
    """
    branches = db.query(Branch).order_by(Branch.name).all()
    out = []
    for branch in branches[:limit]:
        months = by_month(db, branch_id=branch.id)
        busiest = max(months, key=lambda m: m["value"])
        quietest = min((m for m in months if m["value"]),
                       key=lambda m: m["value"], default=busiest)
        traded = [m for m in months if m["value"]]
        traded_at_all = any(m["value"] for m in months)
        out.append({
            "branch_id": branch.id, "branch": branch.name,
            "months": months,
            "traded": traded_at_all,
            # A branch that has taken nothing has no busiest month, and saying
            # "busiest January" of one is the same lie as a 0.00 on an unpriced
            # line: a real-looking answer to a question that has none.
            "busiest": busiest["month"] if traded_at_all else "",
            "quietest": quietest["month"] if traded_at_all else "",
            "value": round(sum(m["value"] for m in months), 2),
            # The gap between the best and worst month, as a proportion. A
            # branch that swings 60% needs a different float and a different
            # order pattern from one that swings 10%.
            "swing": (round((busiest["value"] - quietest["value"])
                            / (sum(m["value"] for m in traded) / len(traded)), 2)
                      if traded else 0.0),
        })
    out.sort(key=lambda b: -b["value"])

    consolidated = by_month(db, branch_id=None)
    busiest = max(consolidated, key=lambda m: m["value"])
    return {
        "group": consolidated,
        "group_busiest": busiest["month"],
        "group_value": round(sum(m["value"] for m in consolidated), 2),
        "branches": out,
        # Where a branch's year disagrees with the group's. The interesting
        # rows: a branch whose busiest month is not the group's is one the
        # group buying pattern is actively wrong for.
        "disagree": [b["branch"] for b in out
                     if b["value"] and b["busiest"] != busiest["month"]],
    }
