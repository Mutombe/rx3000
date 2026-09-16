"""Give an unpriced medicine the price it last sold for.

A pharmacy that changes systems arrives with two different files: what is on the
shelf today, and what has been sold. CareXpress's stock file covered 6,143
lines; nineteen months of invoices mentioned another ten thousand items that the
stock file does not — water, syringes, the dispensing fee itself — and those
came across with a name and no price at all.

An item priced at nothing is worse than an item that is missing. It sits in the
search, it can be put on a sale, and it rings up as free.

The invoices know what each one sold for. This reads the most recent sale of
every unpriced item and offers that figure, for somebody to look at and accept:
a price is money, so nothing here writes anything until it is asked to, and what
it would write is shown first.

The figure is what was actually charged, which is the right starting point and
not necessarily today's price — an item last sold eighteen months ago is
flagged by its date rather than quietly modernised.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Product, Sale, SaleItem


def plan(db: Session, *, limit: int = 0) -> list[dict]:
    """What every unpriced item last sold for, worst-known first.

    One query, not one per product: the pharmacy this was written for has
    sixteen thousand products and fifty thousand sale lines.
    """
    # The most recent sale line for each product, and how many there have been.
    latest = (
        db.query(SaleItem.product_id.label("product_id"),
                 func.max(SaleItem.id).label("line_id"),
                 func.count(SaleItem.id).label("times"))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(SaleItem.unit_price > 0)
        .group_by(SaleItem.product_id)
        .subquery()
    )
    rows = (
        db.query(Product, SaleItem, Sale.created_at, latest.c.times)
        .join(latest, latest.c.product_id == Product.id)
        .join(SaleItem, SaleItem.id == latest.c.line_id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(func.coalesce(Product.unit_price, 0) <= 0)
        .order_by(latest.c.times.desc())
    )
    if limit:
        rows = rows.limit(limit)

    out = []
    for product, line, sold_at, times in rows.all():
        # What `unit_price` on a sale line means depends on which door the sale
        # came through, and a product's own price is always what a PACK sells
        # for:
        #
        #   the till sells boxes — its line price is already the pack price;
        #   the dispensary sells tablets — its line price is per tablet, and a
        #   pack of thirty is thirty of them.
        #
        # Read the wrong way round, a $2.25 tablet becomes a $2,025 pack, or a
        # $67.50 box becomes $2.25. The line says which it was: a dispensary
        # line is the one attached to a prescription.
        from_dispensary = line.prescription_item_id is not None
        per_pack = round(float(line.unit_price) * (max(1, product.units_per_pack or 1)
                                                   if from_dispensary else 1), 2)
        if per_pack <= 0:
            continue
        out.append({
            "product_id": product.id,
            "name": product.name,
            "pack_size": product.pack_size or "",
            "units_per_pack": product.units_per_pack or 1,
            "times_sold": int(times or 0),
            "last_sold": sold_at,
            "last_price": round(float(line.unit_price), 2),
            "sold_by": "dispensary" if from_dispensary else "till",
            "new_price": per_pack,
            "stale_days": (datetime.utcnow() - sold_at).days if sold_at else None,
        })
    return out


def apply(db: Session, rows: list[dict]) -> int:
    """Write the prices. The caller has already looked at them."""
    priced = 0
    for row in rows:
        product = db.get(Product, row["product_id"])
        # Priced by somebody else between the preview and the button: theirs
        # wins, because it was typed by a person who meant it.
        if product is None or (product.unit_price or 0) > 0:
            continue
        product.unit_price = row["new_price"]
        priced += 1
    return priced
