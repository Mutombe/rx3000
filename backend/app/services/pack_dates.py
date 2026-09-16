"""The expiry printed on the pack, asked for once and written onto the shelf.

Stock that carries no expiry date cannot be sold or dispensed. That is not a
technicality: the whole point of drawing First-Expiry-First-Out is that the
oldest pack leaves first and an out-of-date one never leaves at all, and a batch
with no date cannot be placed in that order or ruled out of it.

It matters because of how a pharmacy's first day works. An opening count says
how many of each medicine are on the shelf; it does not say what is printed on
each box, because nobody is going to read four thousand expiry dates into a
spreadsheet before they can open. So every opening batch arrives undated, and
without this the shop cannot sell a single thing.

The answer is to ask the one person who is holding the box. When a line can only
go out from undated stock, the counter is asked for the date on the pack, the
batch is dated with it, and the shelf dates itself one sale at a time. The next
person to reach for that medicine is not asked again.

Both doors ask the same question through this module: the dispensary, where the
quantity is in units, and the till, where it is in packs. They diverged once
already — dispensing learned to ask and the till did not, which left a pharmacy
whose every unit was undated able to dispense a script and unable to sell a
tube of cream.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import helpers
from ..models import Product


def needed(db: Session, branch_id: int, lines: list[tuple[Product, int]]) -> list[dict]:
    """Which of these lines can only be met from stock with no expiry recorded.

    `lines` is (product, quantity in units). A line qualifies when this branch's
    in-date stock does not cover it and undated stock exists to make up the
    difference: there is no point asking for a date on a pack that is not needed,
    and no point asking when the shortfall is a genuine shortage instead.
    """
    out: list[dict] = []
    for product, wanted in lines:
        if product is None or wanted <= 0:
            continue
        dated = helpers.dated_stock(db, product, branch_id)
        if dated >= wanted:
            continue
        undated, _expired = helpers.stock_without_a_good_date(db, product, branch_id)
        if not undated:
            continue
        out.append({
            "product_id": product.id,
            "name": f"{product.name} {product.strength or ''}".strip(),
            "needed_units": wanted,
            "dated_units": dated,
            "undated_units": undated,
        })
    return out


def apply(db: Session, branch_id: int, user_id: int | None,
          products: dict[int, Product], given: dict[int, date] | None) -> int:
    """Write the dates the counter read off the packs onto this branch's stock.

    Called immediately before the stock is drawn, so that what the sale takes is
    the batch that has just been dated. Returns how many batches were dated,
    which is worth having for the audit trail rather than for the caller.

    Silently ignores a date for a product that is not in the basket, and a
    product that had nothing undated to date: both mean the counter answered a
    question that had already stopped being asked, which is what happens when
    two tills are on the same medicine at once.
    """
    if not given:
        return 0
    dated = 0
    for product_id, expiry in given.items():
        product = products.get(int(product_id))
        if product is None or expiry is None:
            continue
        dated += len(helpers.date_undated_stock(db, product, expiry, user_id,
                                                branch_id=branch_id))
    return dated
