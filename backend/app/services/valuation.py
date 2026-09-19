"""What stock is worth, with the pack and the unit kept straight.

THE MISTAKE THIS EXISTS TO STOP

`Product.cost_price` is the cost of ONE PACK. `Product.unit_price` is the
price of ONE PACK. `Product.quantity_on_hand` counts DISPENSABLE UNITS, so a
tub of a thousand capsules is a thousand. Multiply the first by the third and
the answer is wrong by the pack size, silently, in the flattering direction.

It was being done in fifteen places. On the client's own catalogue the stock
came to 13,380,343.88 at cost against the 377,357.90 their own export totals,
which is 35.5 times over. Nothing about the number looks wrong: it is a
plausible figure, it is consistent between screens because they all make the
same mistake, and it is the figure an owner would use to insure the shop.

The model has had the right accessors all along. `unit_cost()` and
`per_unit()` divide by the pack size and are documented as the ones that mean
what their names say. They were simply not reached for, because
`product.cost_price * product.quantity_on_hand` reads like it is correct.

So the rule is named once, here, and every screen calls it. A rule spelled out
fifteen times is a rule that is right in fourteen places.

HOW IT WAS CHECKED

Against the pharmacy's own TOTALCOST column rather than against reasoning. For
METOCLOPRAMIDE 10MG TABS 500S they hold 292,648 units at 19.00 a tub of 500
and total it at 11,120.62; unit_cost times units gives 11,120.62 exactly, and
cost_price times units gives 5,560,312.00.
"""
from __future__ import annotations

from ..models import Product


def at_cost(product: Product, units: float | int | None = None) -> float:
    """What `units` of this line cost, where `units` are DISPENSABLE UNITS.

    Defaults to everything on hand, which is what nearly every caller wants
    and what nearly every caller was getting wrong.
    """
    if units is None:
        units = product.quantity_on_hand or 0
    return round((units or 0) * product.unit_cost(), 2)


def at_retail(product: Product, units: float | int | None = None) -> float:
    """What `units` of this line sell for, where `units` are DISPENSABLE UNITS."""
    if units is None:
        units = product.quantity_on_hand or 0
    return round((units or 0) * product.per_unit(), 2)


def packs_at_cost(product: Product, packs: float | int) -> float:
    """What `packs` of this line cost, where the quantity really is packs.

    A purchase order line is in packs, and so is a supplier's invoice. Those
    callers are already right and this is here so they can say which they mean
    rather than being changed to look like the others.
    """
    return round((packs or 0) * (product.cost_price or 0.0), 2)


def cost_column():
    """The same rule as `at_cost`, for a query that sums in the database.

    Returns an expression, so a report that groups ten thousand rows does not
    have to load ten thousand products to value them. `per_pack` cannot be
    zero on a stored row, but a database with an older row that says zero
    would divide by it, so the divisor is floored here the way the model's
    `per_pack` property floors it in Python.
    """
    from sqlalchemy import case
    per_pack = case((Product.units_per_pack > 1, Product.units_per_pack), else_=1)
    return Product.quantity_on_hand * Product.cost_price / per_pack


def retail_column():
    """`at_retail` as a database expression. See `cost_column`."""
    from sqlalchemy import case
    per_pack = case((Product.units_per_pack > 1, Product.units_per_pack), else_=1)
    return Product.quantity_on_hand * Product.unit_price / per_pack
