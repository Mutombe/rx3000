"""One opening batch per product per branch, and a ledger that agrees with itself.

    python -m app.importers.one_opening_batch --pharmacy 5
    python -m app.importers.one_opening_batch --pharmacy 5 --apply

WHAT WENT WRONG

The stock count was run twice against the hosted database at the same time. Each
run reads every existing batch once, up front, decides which products already
have an `OPENING` batch, and then writes — so two runs that both read before
either wrote each concluded the batch was missing, and each created one. 864
products at CareXpress ended up with three identical opening batches.

`Product.quantity_on_hand` is right: every run set it to the same figure, so the
last writer wrote the truth. The batch ledger behind it is not — it holds
2,082,736 units where the products say 840,163.

WHY THAT MATTERS MORE THAN IT LOOKS

Dispensing does not draw from `quantity_on_hand`; it draws from batches, FEFO.
A shelf with three copies of the same opening batch will hand out three times
what is actually there and report a cheerful success each time, and the first
anybody knows of it is a stock take that cannot be reconciled — or a patient
sent away because the count finally went negative.

WHAT THIS DOES

Keeps the oldest opening batch for each (product, branch) and deletes its
copies, then sets every touched product's on-hand to the sum of the batches
that remain. Only duplicates are touched: a product with one opening batch, or
with real dated batches from a delivery, is left exactly as it is.

Allocations are checked first. A batch that a sale has already drawn from is
never deleted — the allocation rows point at it, and a delete would orphan the
record of what left the shelf.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from sqlalchemy import func

from ..database import SessionLocal
from ..models import BatchAllocation, Product, StockBatch
from ..tenancy import reset_current_pharmacy, set_current_pharmacy, unscoped


def find(db, pharmacy_id: int) -> dict:
    """Which opening batches are copies of one another."""
    mine = {p.id for p in db.query(Product.id).filter(Product.pharmacy_id == pharmacy_id).all()}
    rows = (db.query(StockBatch)
            .filter(StockBatch.batch_number == "OPENING",
                    StockBatch.product_id.in_(mine))
            .order_by(StockBatch.id).all()) if mine else []

    grouped: dict[tuple, list] = defaultdict(list)
    for batch in rows:
        grouped[(batch.product_id, batch.branch_id)].append(batch)

    drawn = set()
    extra_ids = [b.id for group in grouped.values() for b in group[1:]]
    if extra_ids:
        for (bid,) in (db.query(BatchAllocation.batch_id)
                       .filter(BatchAllocation.batch_id.in_(extra_ids)).distinct().all()):
            drawn.add(bid)

    keep, drop, stuck = [], [], []
    for group in grouped.values():
        if len(group) < 2:
            continue
        keep.append(group[0])
        for batch in group[1:]:
            (stuck if batch.id in drawn else drop).append(batch)
    return {"keep": keep, "drop": drop, "stuck": stuck, "groups": grouped}


def apply(db, found: dict) -> dict:
    touched = {b.product_id for b in found["drop"]}
    for batch in found["drop"]:
        db.delete(batch)
    db.flush()
    fixed = 0
    for product_id in touched:
        held = (db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
                .filter(StockBatch.product_id == product_id).scalar() or 0)
        product = db.get(Product, product_id)
        if product is not None and int(product.quantity_on_hand or 0) != int(held):
            product.quantity_on_hand = int(held)
            fixed += 1
    db.commit()
    return {"deleted": len(found["drop"]), "products": len(touched), "recounted": fixed}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pharmacy", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    token = set_current_pharmacy(args.pharmacy)
    db = SessionLocal()
    try:
        found = find(db, args.pharmacy)
        ledger = (db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
                  .join(Product, Product.id == StockBatch.product_id)
                  .filter(Product.pharmacy_id == args.pharmacy).scalar() or 0)
        onhand = (db.query(func.coalesce(func.sum(Product.quantity_on_hand), 0))
                  .filter(Product.pharmacy_id == args.pharmacy).scalar() or 0)
        print(f"\nbatch ledger holds {int(ledger):,} units; the products say {int(onhand):,}")
        print(f"{len(found['keep']):,} product/branch pair(s) have more than one opening batch")
        print(f"{len(found['drop']):,} duplicate batch(es) would be removed"
              + ("" if args.apply else " — nothing written, this is a preview"))
        if found["stuck"]:
            print(f"  {len(found['stuck'])} left alone: a sale has already drawn from them")
        for batch in found["drop"][:8]:
            product = db.get(Product, batch.product_id)
            print(f"    {(product.name if product else '?')[:36]:<38} "
                  f"branch {batch.branch_id}  {batch.quantity_remaining:,} units")
        if args.apply:
            done = apply(db, found)
            print(f"\n  {done['deleted']:,} duplicate(s) removed, "
                  f"{done['recounted']:,} product(s) recounted from the batches that remain.")
            after = (db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
                     .join(Product, Product.id == StockBatch.product_id)
                     .filter(Product.pharmacy_id == args.pharmacy).scalar() or 0)
            print(f"  the ledger now holds {int(after):,} units.")
        return 0
    finally:
        db.close()
        reset_current_pharmacy(token)


if __name__ == "__main__":
    with unscoped():
        sys.exit(main())
