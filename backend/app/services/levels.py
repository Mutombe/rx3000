"""What a branch wants of a line, and where that answer comes from.

Reorder levels live on the product, so every shop in a group shares one. That
is right for most of a catalogue and wrong for the lines that matter: the
branch beside the clinic gets through four times the amoxicillin, and one
level for all three either leaves it short every week or leaves the other two
holding stock they cannot sell.

`BranchStockLevel` holds only what a branch has decided to differ on. This is
the one place the two are resolved, so nothing else has to know there are two.

WHY NULL AND ZERO ARE NOT THE SAME

A branch that never wants to stock a line sets its maximum to zero, and that
is an instruction. A branch that has never been asked has null, and that
inherits. Collapsing them would make "do not hold this here" impossible to
say, and it is exactly the thing a group wants to say about the shop that
does not have a fridge.

WHY IT IS READ IN BULK

The reorder screen asks this of every line in a catalogue at once. One query
per product is how a page that should take a moment takes ten seconds, and
this codebase has been bitten by that shape before, so `for_branch` takes the
whole list and answers in one.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import BranchStockLevel, Product, User

#: The three figures a branch may hold an opinion about.
FIELDS = ("reorder_level", "max_level", "reorder_quantity")


def _merge(product: Product, row: BranchStockLevel | None) -> dict:
    """The group's answer, with the branch's on top of it where it has one."""
    out = {field: getattr(product, field, 0) or 0 for field in FIELDS}
    out["from_branch"] = {}
    if row is not None:
        for field in FIELDS:
            value = getattr(row, field)
            if value is not None:           # zero is an answer; null is not
                out[field] = int(value)
                out["from_branch"][field] = True
    return out


def for_product(db: Session, product: Product, branch_id: int | None) -> dict:
    """What THIS branch wants of this line."""
    if branch_id is None:
        return _merge(product, None)
    row = (db.query(BranchStockLevel)
           .filter(BranchStockLevel.branch_id == branch_id,
                   BranchStockLevel.product_id == product.id)
           .first())
    return _merge(product, row)


def for_branch(db: Session, branch_id: int | None,
               products: list[Product]) -> dict[int, dict]:
    """The same, for a whole page of products, in one query."""
    rows: dict[int, BranchStockLevel] = {}
    if branch_id is not None and products:
        found = (db.query(BranchStockLevel)
                 .filter(BranchStockLevel.branch_id == branch_id,
                         BranchStockLevel.product_id.in_([p.id for p in products]))
                 .all())
        rows = {r.product_id: r for r in found}
    return {p.id: _merge(p, rows.get(p.id)) for p in products}


def set_for(db: Session, *, product: Product, branch_id: int,
            values: dict, user: User | None = None,
            note: str = "") -> BranchStockLevel:
    """Record what one branch wants, or clear it back to the group's.

    A field passed as None is cleared, which is how a branch says "go back to
    whatever the group says" rather than having to guess the group's number
    and type it in.
    """
    row = (db.query(BranchStockLevel)
           .filter(BranchStockLevel.branch_id == branch_id,
                   BranchStockLevel.product_id == product.id)
           .first())
    if row is None:
        row = BranchStockLevel(branch_id=branch_id, product_id=product.id,
                               pharmacy_id=product.pharmacy_id)
        db.add(row)
    for field in FIELDS:
        if field in values:
            given = values[field]
            setattr(row, field, None if given in (None, "") else int(given))
    row.note = (note or "")[:200]
    row.set_by_id = getattr(user, "id", None)
    row.updated_at = datetime.utcnow()
    return row


def differences(db: Session, branch_id: int) -> list[dict]:
    """Every line this branch has chosen to treat differently, and how.

    The list is the point: a group that cannot see where its branches have
    departed from the standard cannot tell a deliberate decision from a
    forgotten experiment.
    """
    rows = (db.query(BranchStockLevel, Product)
            .join(Product, Product.id == BranchStockLevel.product_id)
            .filter(BranchStockLevel.branch_id == branch_id)
            .all())
    out = []
    for row, product in rows:
        merged = _merge(product, row)
        out.append({
            "product_id": product.id,
            "product": f"{product.name} {product.strength or ''}".strip(),
            "reorder_level": merged["reorder_level"],
            "max_level": merged["max_level"],
            "reorder_quantity": merged["reorder_quantity"],
            "group": {field: getattr(product, field, 0) or 0 for field in FIELDS},
            "overridden": sorted(merged["from_branch"].keys()),
            "note": row.note or "",
            "by": row.set_by.username if row.set_by else "",
            "at": row.updated_at.isoformat() if row.updated_at else "",
        })
    out.sort(key=lambda r: r["product"].upper())
    return out
