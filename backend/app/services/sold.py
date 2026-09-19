"""What actually sold, as one rule the whole product agrees on.

Lifted out of the reports because the product page needed the same answer and
had the same bug. Two places computing "how much of this goes out" from two
different sources is how a page and a report disagree about the same medicine
in front of the person who has to decide whether to order it.
"""
from __future__ import annotations

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..models import Sale, SaleItem


def units_sold_since(db: Session, since, until=None) -> dict[int, float]:
    """How many units of each line actually sold in a period.

    READ OFF SALE LINES, NOT OFF THE STOCK LEDGER, AND THAT IS THE FIX

    Both movers reports used to count StockMovement rows of type "sale". It
    reads as the more careful choice, because a movement is written whether
    goods go over the counter or out on a script. It is also empty for every
    pharmacy that brought its history with it.

    An invoice import deliberately writes no stock movements: the closing
    figures come from the same system's stock export and already reflect those
    sales, so replaying two years of deductions would take the shelf count down
    twice. Correct, and the consequence was that CareXpress had 45,728 sales
    and 70,305 sale lines on file, and Fast movers, Slow movers and Stock usage
    per item all returned nothing at all. The one thing a pharmacy asks an
    inventory to tell them, answered with an empty table, on their own data.

    A sale line is the record of goods leaving, it exists for a script line as
    well as a counter sale (`prescription_item_id` says which), and it is
    written by the importer and by the till alike. So it is what these count.

    Revenue comes back with the units for the same reason: it is what the
    pharmacy was actually paid, rather than this month's shelf price applied
    to last quarter's sales.

    Returns are taken off rather than ignored: four sold and one brought back
    is three sold, and a line with a high return rate is one somebody should be
    looking at, not one that should read as a fast mover.

    Voided and credited sales are left out entirely. Both mean the sale did not
    happen; a void reverses it on the day and a credit note gives the money
    back later, and counting either as demand puts phantom lines at the top of
    a reorder list.

    WHAT THIS COUNTS, AND THE ONE PLACE IT IS KNOWN TO UNDERSTATE

    `SaleItem.quantity` does not mean the same thing on every line, and that is
    a fault in the column rather than in this function. A script line records
    UNITS and prices per unit: thirty tablets, priced per tablet. A till line
    records PACKS and prices per pack: one box. Both are correct for what the
    customer was charged, and the pack size is the factor between them.

    The quantity is therefore counted exactly as recorded, with no conversion.
    On 13,923 of this catalogue's 15,541 lines the pack IS the unit and the
    question does not arise. On the rest it can only be resolved by knowing
    which door the sale came through, and on imported history that cannot be
    known: the invoice importer links no line to a script item, so all 70,305
    of CareXpress's lines look identical to a till sale whether they were one
    or not.

    Multiplying by the pack size on a guess would turn a dispensed line of
    thirty capsules from a tub of a thousand into thirty thousand and put it at
    the top of the fast movers list. Not converting understates a till sale of
    a multi pack. The second error is the small one and it is in the safe
    direction, so it is the one taken, and it is written down here rather than
    discovered later in a figure nobody can explain.
    """
    net = SaleItem.quantity - func.coalesce(SaleItem.quantity_returned, 0)
    query = (
        db.query(SaleItem.product_id,
                 func.sum(net),
                 # What it was actually charged at, which is the other thing a
                 # stock movement could not say. Fast movers used to multiply
                 # units by TODAY'S price, so a line repriced last month
                 # restated last quarter's takings every time somebody opened
                 # the report.
                 func.sum(net * SaleItem.unit_price))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.status.notin_(("void", "credited")))
        .filter(func.date(Sale.created_at) >= since)
    )
    if until is not None:
        query = query.filter(func.date(Sale.created_at) <= until)
    return {pid: {"units": float(units or 0), "revenue": round(float(paid or 0), 2)}
            for pid, units, paid in query.group_by(SaleItem.product_id).all()
            if (units or 0) > 0}


def for_product(db: Session, product_id: int, since, until=None) -> dict:
    """What one line sold, what it was paid, and what the pharmacy kept.

    The product page's own question, and the one it could not answer. "How
    much have we made from this drug" was on the page only as a unit margin:
    the percentage between today's shelf price and today's average cost. That
    is a fact about the price list, not about the trade. It says nothing about
    whether the line earns anything, because it is the same number whether
    four boxes went out in a year or four hundred.

    Cost follows the rule the margin reports use, and it has to: the cost
    captured when the sale happened where there is one, today's cost where
    there is not. Reading today's cost for everything restates last year's
    profit upwards every time a supplier raises a price, which is the flattering
    direction and therefore the one worth guarding against.
    """
    net = SaleItem.quantity - func.coalesce(SaleItem.quantity_returned, 0)
    cost = func.coalesce(func.nullif(SaleItem.unit_cost, 0.0), 0.0)
    # How much of the period is actually costed, so a blank profit can say why
    # it is blank. The alternative was falling back to today's catalogue cost,
    # which the margin reports do and document: it restates last year's profit
    # every time a supplier raises a price, and it multiplies a PACK cost by a
    # line that may be counted in units. On a page somebody reads to decide
    # whether a medicine is worth stocking, an invented number is worse than
    # an admitted gap.
    costed = func.sum(case((SaleItem.unit_cost > 0, net), else_=0))
    query = (
        db.query(func.sum(net),
                 func.sum(net * SaleItem.unit_price),
                 func.sum(net * cost),
                 costed)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(SaleItem.product_id == product_id)
        .filter(Sale.status.notin_(("void", "credited")))
        .filter(func.date(Sale.created_at) >= since)
    )
    if until is not None:
        query = query.filter(func.date(Sale.created_at) <= until)

    units, paid, spent, costed_units = query.one()
    units = float(units or 0)
    paid = round(float(paid or 0), 2)
    spent = round(float(spent or 0), 2)
    return {
        "units": int(units),
        "revenue": paid,
        "cost": spent,
        # Blank rather than zero where no cost was ever captured. A line
        # showing its whole revenue as profit because nobody recorded what it
        # cost is worse than a line showing nothing, because somebody believes
        # the first one.
        "profit": round(paid - spent, 2) if spent > 0 else None,
        "margin": (round((paid - spent) / paid * 100, 1)
                   if paid > 0 and spent > 0 else None),
        # Units whose cost was recorded at the time. Less than `units` means
        # the profit above covers only part of the trade, and the screen says
        # which part rather than presenting a partial figure as the whole.
        "costed_units": int(costed_units or 0),
    }
