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
import json
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .. import concurrency
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


def branch_of(db: Session, user_id: int | None) -> int | None:
    """Which shelf this person is standing at.

    Every path that consumes stock fell back to the DEFAULT branch when nobody
    said otherwise, and no caller ever said otherwise — so a dispenser at
    CareXpress Chinamano, with 1,936 products on the shelf beside them, was
    drawing against Central's and being told "not enough stock at this branch".
    The message was true; the branch was the wrong one.

    Returns None for a user with no branch on record, so the default still
    applies for the single-shop pharmacy that never thinks about any of this.
    """
    if not user_id:
        return None
    from ..models import User
    user = db.get(User, user_id)
    return int(user.branch_id) if user is not None and user.branch_id else None


def ensure_backfilled(db: Session) -> int:
    """Give every pre-branch row a home.

    Run once on startup. A nullable branch_id on historical stock would make
    every branch query silently wrong rather than loudly wrong: the rows would
    simply not appear anywhere, and a batch that exists but belongs to no branch
    is stock that has vanished from the system while sitting on a shelf.
    """
    branch = default_branch(db)
    filled = 0

    # Every model that has a branch, asked of the models themselves.
    #
    # This used to name three of them — stock batches, movements and sales —
    # and shifts, lay-bys, petty cash and stock takes all have a branch too.
    # They were never filled, so a hundred and two shifts belonged to no shop
    # and the branch scorecard showed every one of them zero staff, zero tills
    # and no cash-up accuracy at all. That is the failure this docstring already
    # warns about, and the list was how it happened: a list is a thing somebody
    # has to remember to add to.
    from ..database import Base

    for mapper in Base.registry.mappers:
        model = mapper.class_
        if not hasattr(model, "branch_id"):
            continue
        rows = db.query(model).filter(model.branch_id.is_(None)).count()
        if rows:
            db.query(model).filter(model.branch_id.is_(None)).update(
                {model.branch_id: branch.id}, synchronize_session=False)
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
    found = (db.query(Product)
             .filter(Product.id.in_(list(by_product))).all())
    products = {p.id: p for p in found}

    # WHAT THIS BRANCH WANTS, NOT WHAT THE GROUP WANTS.
    #
    # This compared each branch's shelf against the PRODUCT's reorder level,
    # which is the group's. So the shop beside the clinic, which gets through
    # four times the amoxicillin, was judged against a figure set for three
    # shops, and read as comfortable while it ran out every Friday.
    #
    # Resolved in one query for the whole page. See services/levels: a branch
    # that has never been asked inherits the group's, which is every branch
    # and every line until somebody says otherwise.
    from . import levels
    wanted = levels.for_branch(db, branch_id, found)

    out = []
    for pid, qty in by_product.items():
        product = products.get(pid)
        if not product:
            continue
        mine = wanted.get(pid, {})
        level = int(mine.get("reorder_level") or 0)
        if low_only and qty > level:
            continue
        out.append({
            "product_id": pid,
            "name": product.name,
            "here": qty,
            "group_total": product.quantity_on_hand or 0,
            "reorder_level": level,
            "below_reorder": qty <= level,
            # Whether this shop has an opinion of its own, so a screen can say
            # so rather than leaving somebody to wonder why two branches show
            # different levels for the same medicine.
            "own_level": bool(mine.get("from_branch", {}).get("reorder_level")),
            "group_level": int(product.reorder_level or 0),
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

    # ASK FIRST, IF THIS ONE IS BIG ENOUGH TO NEED ASKING.
    #
    # Moving stock between shops had no gate at all: anybody holding
    # `stock.transfer` could send any branch's stock anywhere, instantly.
    # The blueprint asks for a supervisor to agree one before the stock
    # leaves, and then lists the model as a decision still to be confirmed
    # with the pharmacy: every transfer, or only those above a threshold.
    #
    # So `stock.transfer_threshold` is the value above which a transfer is
    # only REQUESTED, and it ships at zero, which asks for nobody. Until a
    # pharmacy names a figure this behaves exactly as it did.
    #
    # Nothing is drawn off the shelf for a request. The sending branch may
    # still need those boxes while the paperwork waits, and holding them for
    # a transfer that might be refused is the wrong trade. Approval re-checks
    # availability, which is the honest place to find out.
    from . import config, valuation
    from ..models import Product as _Product
    threshold = config.number(db, "stock.transfer_threshold", 0.0)
    product = db.get(_Product, product_id)
    worth = valuation.at_cost(product, quantity) if product else 0.0
    if threshold > 0 and worth > threshold:
        asked = BranchTransfer(
            reference=_next_reference(db),
            from_branch_id=from_branch_id, to_branch_id=to_branch_id,
            product_id=product_id, quantity=quantity, drawn_json="[]",
            status="requested", notes=notes, requested_by_id=user_id)
        db.add(asked)
        db.commit()
        db.refresh(asked)
        return asked

    # Oldest expiry first: a transfer should not leave the short-dated stock
    # behind for the sending branch to write off.
    remaining = quantity
    batches = (db.query(StockBatch)
               .filter(StockBatch.product_id == product_id,
                       StockBatch.branch_id == from_branch_id,
                       StockBatch.quantity_remaining > 0,
                       # Quarantined goods do not move between shops either.
                       # Sending a damaged or recalled batch to another branch
                       # is the failure this state exists to stop, and it is
                       # the one that would look like ordinary housekeeping.
                       StockBatch.status != "quarantined")
               .order_by(StockBatch.expiry_date.asc()).all())
    # What physically left, batch by batch, so the receiving branch can put the
    # same boxes on its shelf rather than one anonymous undated heap. A transfer
    # used to erase the expiry off everything it moved.
    drawn: list[dict] = []
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.quantity_remaining, remaining)
        batch.quantity_remaining -= take
        remaining -= take
        drawn.append({
            "batch_number": batch.batch_number or "",
            "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
            "quantity": int(take),
            "unit_cost": float(batch.unit_cost or 0.0),
        })

    transfer = BranchTransfer(
        reference=_next_reference(db),
        from_branch_id=from_branch_id, to_branch_id=to_branch_id,
        product_id=product_id, quantity=quantity, drawn_json=json.dumps(drawn),
        status="despatched", notes=notes, despatched_by_id=user_id,
        requested_by_id=user_id)
    db.add(transfer)
    db.add(StockMovement(
        product_id=product_id, movement_type="transfer_out",
        quantity_delta=-quantity, balance_after=available - quantity,
        reference=transfer.reference, branch_id=from_branch_id, user_id=user_id))
    db.commit()
    db.refresh(transfer)
    return transfer


def receive(db: Session, *, transfer_id: int, user_id: int | None,
            quantity: int | None = None) -> BranchTransfer:
    """Book in stock that has arrived at the destination branch.

    PART OF IT, IF THAT IS WHAT ARRIVED

    A lorry that brings eight of ten is the ordinary case, not an exotic one,
    and a transfer that could only be received whole forced somebody to lie
    about one or the other: book in ten that are not there, or leave the
    eight in transit and dispense from stock the system says is elsewhere.

    `quantity` defaults to whatever is still outstanding, so the common case
    of everything arriving needs nothing new from the caller. The transfer
    stays in transit until the last unit is booked in, which is what keeps
    the shortfall visible instead of quietly closing it.

    WHERE THE BOXES COME FROM ON A SECOND RECEIPT

    `drawn` is the manifest of what left, batch by batch. Rather than storing
    which of it has arrived, the walk skips the first `quantity_received`
    units of that manifest, because those have been booked in already. The
    manifest is ordered and does not change, so the arithmetic is the record:
    one number, and no second list to keep in step with the first.

    Serialised on the transfer itself. The status check below and the commit at
    the end were not, so two people clicking "Confirm arrival" at the same
    moment both passed the check and both booked the stock in: the shop ended
    up with twice what arrived, and the only trace was two transfer_in rows.
    """
    # Held for the rest of this transaction, so the status check below and the
    # commit at the end cannot be interleaved with another receive of the same
    # transfer.
    concurrency.serialise(db, f"branch-transfer-{transfer_id}")
    transfer = db.get(BranchTransfer, transfer_id)
    if not transfer:
        raise BranchError("That transfer does not exist.")
    if transfer.status != "despatched":
        raise BranchError(
            f"This transfer is already '{transfer.status}'. Only stock in "
            "transit can be received.")

    already = int(transfer.quantity_received or 0)
    outstanding = int(transfer.quantity or 0) - already
    if outstanding <= 0:
        raise BranchError("Every unit on this transfer has already arrived.")
    taking = outstanding if quantity is None else int(quantity)
    if taking <= 0:
        raise BranchError("Say how many arrived.")
    if taking > outstanding:
        raise BranchError(
            f"This transfer has {outstanding} unit(s) still in transit and "
            f"{taking} were entered. Book in what arrived; if more turned up "
            "than was sent, that is a separate receipt.")

    # New batches at the destination rather than moved ones: the receiving
    # branch needs its own batch records to dispense and to recall against.
    #
    # One per batch that actually left, carrying the expiry and the batch number
    # it left with. The alternative — a single batch for the whole transfer —
    # threw the dates away, so stock that had been checked at one shop arrived at
    # the next as undated, and a pack with three weeks on it arrived looking like
    # every other box on the shelf.
    #
    # `drawn` is empty on transfers raised before this was recorded, and those
    # fall back to the old single undated batch: there is nothing else to know
    # about them, and refusing to receive stock that is physically standing in
    # the shop would be worse than booking it in for somebody to date.
    # Read before the new batches are added. Taken afterwards, the `on_hand`
    # query autoflushes them into the sum and the movement's balance_after
    # double-counts the whole transfer: the stock figure was right and the
    # ledger beside it said something that never happened.
    before = on_hand(db, transfer.product_id, transfer.to_branch_id)

    moved = transfer.drawn_lines() or [{"batch_number": transfer.reference,
                                        "expiry_date": None,
                                        "quantity": transfer.quantity,
                                        "unit_cost": 0.0}]

    # Walk the manifest, skipping what has already been booked in and stopping
    # once this receipt is satisfied. On a transfer received in one go this is
    # the whole list, which is what it always was.
    skip = already
    want = taking
    arriving: list[dict] = []
    for line in moved:
        have = int(line.get("quantity") or 0)
        if skip >= have:
            skip -= have
            continue
        usable = have - skip
        skip = 0
        take = min(usable, want)
        if take <= 0:
            break
        arriving.append({**line, "quantity": take})
        want -= take
        if want <= 0:
            break

    for line in arriving:
        expiry = line.get("expiry_date")
        wanted = date.fromisoformat(expiry) if expiry else None
        number = (f"{line.get('batch_number')}" if line.get("batch_number")
                  else f"{transfer.reference}")[:50]

        # ONE LOT, ONE ROW, HERE TOO.
        #
        # A transfer received in two parts is one lot arriving twice, and
        # creating a second row for the second half is exactly what the
        # receiving path was taught not to do: a recall traces one of them,
        # and FEFO treats them as separate queues. The rule is the same
        # wherever stock lands, so it applies here as well.
        same = (db.query(StockBatch)
                .filter(StockBatch.product_id == transfer.product_id,
                        StockBatch.branch_id == transfer.to_branch_id,
                        StockBatch.batch_number == number,
                        StockBatch.expiry_date == wanted)
                .first())
        if same is not None:
            same.quantity_received = (same.quantity_received or 0) + int(line.get("quantity") or 0)
            same.quantity_remaining = (same.quantity_remaining or 0) + int(line.get("quantity") or 0)
            continue

        db.add(StockBatch(
            product_id=transfer.product_id,
            # The batch as the manufacturer numbered it, with the transfer that
            # carried it, so a recall finds it at whichever shop it ended up in.
            batch_number=number,
            quantity_received=int(line.get("quantity") or 0),
            quantity_remaining=int(line.get("quantity") or 0),
            expiry_date=wanted,
            unit_cost=float(line.get("unit_cost") or 0.0),
            reference=transfer.reference,
            branch_id=transfer.to_branch_id))
    db.add(StockMovement(
        product_id=transfer.product_id, movement_type="transfer_in",
        quantity_delta=taking,
        balance_after=before + taking,
        reference=transfer.reference,
        notes=("" if taking == outstanding else
               f"Part receipt: {taking} of {outstanding} still in transit."),
        branch_id=transfer.to_branch_id, user_id=user_id))
    transfer.quantity_received = already + taking
    # In transit until the last unit is here. Closing it early is what makes a
    # shortfall disappear rather than be chased.
    if transfer.quantity_received >= (transfer.quantity or 0):
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
    # and the product, so a list of transfers cost 1 + 3n queries. Joined in one.
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
        "product_id": t.product_id,
        "product": t.product.name if t.product else "",
        "quantity": t.quantity,
        "despatched_at": t.despatched_at,
        "days_in_transit": (datetime.utcnow() - t.despatched_at).days
        if t.despatched_at else 0,
    } for t in rows]


def approve_transfer(db: Session, *, transfer_id: int,
                     user_id: int | None) -> BranchTransfer:
    """Agree a requested transfer, and only now take the stock off the shelf.

    Availability is re-checked rather than trusted. A request sits for as long
    as it takes somebody to look at it, and the sending branch has been
    dispensing from those shelves the whole time: the figure that mattered
    when it was asked for may not be the figure now, and finding that out at
    approval is better than finding it out when a lorry is loaded.
    """
    concurrency.serialise(db, f"branch-transfer-{transfer_id}")
    transfer = db.get(BranchTransfer, transfer_id)
    if not transfer:
        raise BranchError("That transfer does not exist.")
    if transfer.status != "requested":
        raise BranchError(
            f"That transfer is already '{transfer.status}', so there is "
            "nothing to approve.")

    available = on_hand(db, transfer.product_id, transfer.from_branch_id)
    if available < transfer.quantity:
        source = db.get(Branch, transfer.from_branch_id)
        raise BranchError(
            f"{source.name if source else 'That branch'} now holds "
            f"{available}, fewer than the {transfer.quantity} this transfer "
            "asks for. Stock has moved since it was requested: reduce it or "
            "cancel it.")

    remaining = transfer.quantity
    batches = (db.query(StockBatch)
               .filter(StockBatch.product_id == transfer.product_id,
                       StockBatch.branch_id == transfer.from_branch_id,
                       StockBatch.quantity_remaining > 0,
                       StockBatch.status != "quarantined")
               .order_by(StockBatch.expiry_date.asc()).all())
    drawn: list[dict] = []
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.quantity_remaining, remaining)
        batch.quantity_remaining -= take
        remaining -= take
        drawn.append({
            "batch_number": batch.batch_number or "",
            "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
            "quantity": int(take),
            "unit_cost": float(batch.unit_cost or 0.0),
        })

    transfer.drawn_json = json.dumps(drawn)
    transfer.status = "despatched"
    transfer.approved_by_id = user_id
    transfer.approved_at = datetime.utcnow()
    transfer.despatched_by_id = user_id
    db.add(StockMovement(
        product_id=transfer.product_id, movement_type="transfer_out",
        quantity_delta=-transfer.quantity,
        balance_after=available - transfer.quantity,
        reference=transfer.reference, branch_id=transfer.from_branch_id,
        user_id=user_id))
    db.commit()
    db.refresh(transfer)
    return transfer


def refuse_transfer(db: Session, *, transfer_id: int, user_id: int | None,
                    why: str = "") -> BranchTransfer:
    """Turn down a request. Nothing has moved, so nothing has to move back."""
    transfer = db.get(BranchTransfer, transfer_id)
    if not transfer:
        raise BranchError("That transfer does not exist.")
    if transfer.status != "requested":
        raise BranchError(
            f"That transfer is '{transfer.status}'. Stock that has already "
            "left cannot be refused: cancel it at the far end instead.")
    transfer.status = "cancelled"
    transfer.notes = ((transfer.notes or "") + (" " if transfer.notes else "")
                      + f"Refused. {why}".strip())
    db.commit()
    db.refresh(transfer)
    return transfer
