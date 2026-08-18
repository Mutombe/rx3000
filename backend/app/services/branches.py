"""Branches: more than one shop, one set of books.

The single idea this module protects is that **stock is held per branch**. Once
a business has two shops, `Product.quantity_on_hand` stops being a fact and
becomes an average nobody asked for: twenty boxes across the group tells a
dispenser in Bulawayo nothing about whether they can serve the patient in front
of them. So on-hand is computed from the batches at a branch, never read from
the product row.

The product column is not deleted, because a single-shop pharmacy is the common
case and every existing screen relies on it. It is treated as the group total
and labelled as such.

Transfers are two-sided for the same reason. Goods despatched from Avondale are
not on the shelf in Bulawayo yet; showing them as available at the destination
invites someone to sell stock that is in a car on the Harare road. Despatch
removes, receipt adds, and the gap between the two is stock in transit.
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import Branch, BranchTransfer, Product, StockBatch, StockMovement


class BranchError(ValueError):
    """Raised when a branch operation cannot be completed."""


def default_branch(db: Session) -> Branch:
    """The branch a till belongs to when nobody has said otherwise.

    Every installation has one, created on first use. Without it, rows written
    before branches existed would have nowhere to belong, and "we do not know
    which shop sold this" is not a state worth allowing into a ledger.
    """
    branch = db.query(Branch).filter(Branch.is_default.is_(True)).first()
    if branch:
        return branch
    branch = db.query(Branch).order_by(Branch.id).first()
    if branch:
        branch.is_default = True
        db.commit()
        return branch
    branch = Branch(code="MAIN", name="Main branch", is_default=True, active=True)
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return branch


def ensure_backfilled(db: Session) -> int:
    """Give every pre-branch row a home.

    Run once on startup. A nullable branch_id on historical stock would make
    every branch query silently wrong rather than loudly wrong: the rows would
    simply not appear anywhere, and a batch that exists but belongs to no branch
    is stock that has vanished from the system while sitting on a shelf.
    """
    branch = default_branch(db)
    filled = 0
    for model in (StockBatch, StockMovement):
        rows = db.query(model).filter(model.branch_id.is_(None)).count()
        if rows:
            db.query(model).filter(model.branch_id.is_(None)).update(
                {model.branch_id: branch.id}, synchronize_session=False)
            filled += rows
    from ..models import Sale
    rows = db.query(Sale).filter(Sale.branch_id.is_(None)).count()
    if rows:
        db.query(Sale).filter(Sale.branch_id.is_(None)).update(
            {Sale.branch_id: branch.id}, synchronize_session=False)
        filled += rows
    if filled:
        db.commit()
    return filled


def on_hand(db: Session, product_id: int, branch_id: int) -> int:
    """What is actually on the shelf at this branch.

    Summed from batches rather than read from `Product.quantity_on_hand`, which
    is the group total and is the wrong number to answer a dispenser's question.
    """
    total = (db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
             .filter(StockBatch.product_id == product_id,
                     StockBatch.branch_id == branch_id)
             .scalar())
    return int(total or 0)


def stock_at(db: Session, branch_id: int, *, low_only: bool = False) -> list[dict]:
    """Everything this branch holds, with the group total alongside it.

    Both numbers are shown because both get asked: "can I serve this patient"
    is a branch question, and "should we reorder" is usually a group one.
    """
    rows = (db.query(StockBatch.product_id,
                     func.sum(StockBatch.quantity_remaining).label("qty"))
            .filter(StockBatch.branch_id == branch_id,
                    StockBatch.quantity_remaining > 0)
            .group_by(StockBatch.product_id).all())
    by_product = {r.product_id: int(r.qty or 0) for r in rows}
    if not by_product:
        return []
    products = {p.id: p for p in db.query(Product)
                .filter(Product.id.in_(list(by_product))).all()}
    out = []
    for pid, qty in by_product.items():
        product = products.get(pid)
        if not product:
            continue
        if low_only and qty > (product.reorder_level or 0):
            continue
        out.append({
            "product_id": pid,
            "name": product.name,
            "here": qty,
            "group_total": product.quantity_on_hand or 0,
            "reorder_level": product.reorder_level or 0,
            "below_reorder": qty <= (product.reorder_level or 0),
        })
    return sorted(out, key=lambda r: r["name"])


def _next_reference(db: Session) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d")
    n = db.query(BranchTransfer).count() + 1
    return f"TRF-{stamp}-{n:04d}"


def despatch(db: Session, *, from_branch_id: int, to_branch_id: int,
             product_id: int, quantity: int, user_id: int | None,
             notes: str = "") -> BranchTransfer:
    """Send stock from one branch to another.

    Removes it from the sending branch immediately, because it has physically
    left. It does not arrive anywhere until somebody receives it.
    """
    if from_branch_id == to_branch_id:
        raise BranchError("A transfer needs two different branches.")
    if quantity <= 0:
        raise BranchError("The quantity must be at least 1.")
    source = db.get(Branch, from_branch_id)
    target = db.get(Branch, to_branch_id)
    if not source or not target:
        raise BranchError("One of those branches does not exist.")
    if not target.active:
        raise BranchError(f"{target.name} is closed, so stock cannot be sent there.")

    available = on_hand(db, product_id, from_branch_id)
    if available < quantity:
        raise BranchError(
            f"{source.name} holds {available}, so {quantity} cannot be sent. "
            "Transfer what is there or receive stock first.")

    # Oldest expiry first: a transfer should not leave the short-dated stock
    # behind for the sending branch to write off.
    remaining = quantity
    batches = (db.query(StockBatch)
               .filter(StockBatch.product_id == product_id,
                       StockBatch.branch_id == from_branch_id,
                       StockBatch.quantity_remaining > 0)
               .order_by(StockBatch.expiry_date.asc()).all())
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.quantity_remaining, remaining)
        batch.quantity_remaining -= take
        remaining -= take

    transfer = BranchTransfer(
        reference=_next_reference(db),
        from_branch_id=from_branch_id, to_branch_id=to_branch_id,
        product_id=product_id, quantity=quantity,
        status="despatched", notes=notes, despatched_by_id=user_id)
    db.add(transfer)
    db.add(StockMovement(
        product_id=product_id, movement_type="transfer_out",
        quantity_delta=-quantity, balance_after=available - quantity,
        reference=transfer.reference, branch_id=from_branch_id, user_id=user_id))
    db.commit()
    db.refresh(transfer)
    return transfer


def receive(db: Session, *, transfer_id: int, user_id: int | None) -> BranchTransfer:
    """Book in stock that has arrived at the destination branch."""
    transfer = db.get(BranchTransfer, transfer_id)
    if not transfer:
        raise BranchError("That transfer does not exist.")
    if transfer.status != "despatched":
        raise BranchError(
            f"This transfer is already '{transfer.status}'. Only stock in "
            "transit can be received.")

    # A new batch at the destination rather than a moved one: the receiving
    # branch needs its own batch record to dispense and to recall against.
    db.add(StockBatch(
        product_id=transfer.product_id,
        batch_number=f"{transfer.reference}",
        quantity_received=transfer.quantity,
        quantity_remaining=transfer.quantity,
        reference=transfer.reference,
        branch_id=transfer.to_branch_id))
    db.add(StockMovement(
        product_id=transfer.product_id, movement_type="transfer_in",
        quantity_delta=transfer.quantity,
        balance_after=on_hand(db, transfer.product_id, transfer.to_branch_id)
        + transfer.quantity,
        reference=transfer.reference,
        branch_id=transfer.to_branch_id, user_id=user_id))
    transfer.status = "received"
    transfer.received_by_id = user_id
    transfer.received_at = datetime.utcnow()
    db.commit()
    db.refresh(transfer)
    return transfer


def in_transit(db: Session) -> list[dict]:
    """Stock that has left one branch and not arrived at another.

    A group that cannot see this number loses stock in the gap and blames the
    count.
    """
    # Three many-to-ones read per row — the sending branch, the receiving branch
    # and the product — so a list of transfers cost 1 + 3n queries. Joined in one.
    rows = (db.query(BranchTransfer)
            .options(joinedload(BranchTransfer.from_branch),
                     joinedload(BranchTransfer.to_branch),
                     joinedload(BranchTransfer.product))
            .filter(BranchTransfer.status == "despatched")
            .order_by(BranchTransfer.despatched_at.desc()).all())
    return [{
        "id": t.id, "reference": t.reference,
        "from_branch": t.from_branch.name if t.from_branch else "",
        "to_branch": t.to_branch.name if t.to_branch else "",
        "product": t.product.name if t.product else "",
        "quantity": t.quantity,
        "despatched_at": t.despatched_at,
        "days_in_transit": (datetime.utcnow() - t.despatched_at).days
        if t.despatched_at else 0,
    } for t in rows]
