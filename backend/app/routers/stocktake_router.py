"""Counting the shelves against what the system believes.

Shrinkage is invisible without this. A pharmacy can reconcile its till to the
cent every day and still be quietly losing stock, because a till only knows
about things that were sold.

Three decisions shape the design:

**A count is a session, not an event.** It opens, lines are counted over hours
or days, and it closes once. Nothing is adjusted before the close, so a
half-finished count, the usual outcome of a busy afternoon, leaves the system
exactly as it was rather than half-corrected.

**Expected is captured per line, when the line is counted.** A count spread over
two days would otherwise compare Monday's physical count against Wednesday's
system figure and call the difference shrinkage. That is not shrinkage, it is
two days of trading.

**Closing is where the stock actually moves**, and it is the one step that needs
a second person. A stock take can write off thousands of dollars in one call,
which is exactly the shape of an action that should not rest on one login.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import helpers
from ..auth import get_current_user
from ..database import get_db
from ..models import Product, StockTake, StockTakeLine, User
from .periods_router import require_step_up
from ..services import branches as branch_svc

router = APIRouter(prefix="/api/stock-takes", tags=["stock take"],
                   dependencies=[Depends(get_current_user)])


class OpenIn(BaseModel):
    scope_category: str = ""
    scope_bin: str = ""
    notes: str = ""
    branch_id: int | None = None


class CountIn(BaseModel):
    product_id: int
    counted: int = Field(..., ge=0)
    note: str = ""


def _out(db: Session, take: StockTake) -> dict:
    lines = take.lines
    return {
        "id": take.id,
        "reference": take.reference,
        "status": take.status,
        "scope": {"category": take.scope_category or "", "bin": take.scope_bin or ""},
        "opened_at": take.created_at.isoformat() if take.created_at else None,
        "closed_at": take.closed_at.isoformat() if take.closed_at else None,
        "counted_lines": len(lines),
        "variance_units": sum(l.variance for l in lines),
        "variance_value": round(sum(l.variance * (l.unit_cost or 0) for l in lines), 2),
        # Both directions, separately. A count that is 40 over and 40 short nets
        # to zero and is not a clean count. It is two errors.
        "over_units": sum(l.variance for l in lines if l.variance > 0),
        "short_units": sum(-l.variance for l in lines if l.variance < 0),
    }


@router.post("")
def open_take(body: OpenIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """Open a count. Only one may be open at a time per branch."""
    branch_id = body.branch_id or branch_svc.default_branch(db).id
    existing = (
        db.query(StockTake)
        .filter(StockTake.status == "open")
        .filter(StockTake.branch_id == branch_id)
        .first()
    )
    if existing:
        # Two open counts over the same shelves would each capture their own
        # "expected" and disagree, and whichever closed second would post
        # variances against stock the first had already corrected.
        raise HTTPException(
            status_code=409,
            detail=(
                f"{existing.reference} is already open for this branch. Close or "
                "abandon it before starting another, two counts over the same "
                "shelves will contradict each other."
            ),
        )

    take = StockTake(
        reference=helpers.next_number(db, StockTake, "ST", "reference"),
        branch_id=branch_id,
        status="open",
        scope_category=body.scope_category.strip(),
        scope_bin=body.scope_bin.strip(),
        notes=body.notes.strip(),
        created_by_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(take)
    db.commit()
    db.refresh(take)
    return {**_out(db, take), "message": f"{take.reference} open. Nothing is adjusted until it is closed."}


@router.get("/open")
def current(db: Session = Depends(get_db)):
    take = db.query(StockTake).filter(StockTake.status == "open").first()
    return _out(db, take) if take else None


@router.post("/{take_id}/count")
def count_line(take_id: int, body: CountIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """Record what was physically on the shelf for one product."""
    take = db.query(StockTake).get(take_id)
    if not take:
        raise HTTPException(status_code=404, detail="That stock take no longer exists.")
    if take.status != "open":
        raise HTTPException(status_code=400,
                            detail=f"This count is {take.status} and cannot take entries.")
    product = db.query(Product).get(body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="That product no longer exists.")

    # What the system believes right now, recorded against this line. Read here
    # rather than at close, so a count that spans days is not compared against a
    # figure that moved while it was being taken.
    expected = branch_svc.on_hand(db, product.id, take.branch_id)

    line = (
        db.query(StockTakeLine)
        .filter(StockTakeLine.stock_take_id == take.id)
        .filter(StockTakeLine.product_id == product.id)
        .first()
    )
    if line:
        # Recounting a line is normal. Somebody found another box. The later
        # count replaces the earlier one rather than adding to it.
        line.counted = body.counted
        line.expected = expected
        line.unit_cost = product.cost_price or 0
        line.counted_at = datetime.utcnow()
        line.counted_by_id = user.id
        line.note = body.note.strip()
    else:
        line = StockTakeLine(
            stock_take_id=take.id, product_id=product.id,
            counted=body.counted, expected=expected,
            unit_cost=product.cost_price or 0,
            counted_at=datetime.utcnow(), counted_by_id=user.id,
            note=body.note.strip(),
        )
        db.add(line)
    db.commit()
    db.refresh(line)

    variance = line.variance
    return {
        "product": product.name,
        "counted": line.counted,
        "expected": line.expected,
        "variance": variance,
        "value": round(variance * (line.unit_cost or 0), 2),
        "message": (
            f"{product.name}: counted {line.counted}, system says {line.expected}."
            + ("" if variance == 0 else
               f" {abs(variance)} {'over' if variance > 0 else 'short'}.")
        ),
    }


@router.post("/{take_id}/close")
def close_take(take_id: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user),
               _grant=Depends(require_step_up("stocktake.close"))):
    """Post the variances and bring the system into line with the shelves.

    This is where stock actually moves, and it is deliberately the only step
    that does. Every counted line with a difference becomes a movement, so the
    adjustment is traceable to the count that caused it rather than appearing as
    an unexplained correction.
    """
    take = db.query(StockTake).get(take_id)
    if not take:
        raise HTTPException(status_code=404, detail="That stock take no longer exists.")
    if take.status != "open":
        raise HTTPException(status_code=400, detail=f"This count is already {take.status}.")
    if not take.lines:
        raise HTTPException(
            status_code=400,
            detail="Nothing has been counted, so there is nothing to post. Abandon it instead.",
        )

    posted = 0
    for line in take.lines:
        variance = line.variance
        if variance == 0:
            continue
        product = db.query(Product).get(line.product_id)
        if not product:
            continue
        if variance > 0:
            # Found more than the system knew about. It goes back as a batch,
            # because on-hand is counted from batches.
            helpers.receive_stock_batch(
                db, product, variance, user.id,
                batch_number=f"{take.reference}-FOUND",
                unit_cost=product.cost_price or None,
                reference=take.reference,
            )
        else:
            # Short. Drawn through the FEFO consumer, and expired batches are
            # allowed because a shortage is a write-off, not a dispense.
            helpers.consume_stock_fefo(
                db, product, -variance, "stocktake", user.id,
                reference=take.reference, allow_expired=True,
            )
        posted += 1

    take.status = "closed"
    take.closed_at = datetime.utcnow()
    take.closed_by_id = user.id
    db.commit()
    db.refresh(take)
    summary = _out(db, take)
    return {
        **summary,
        "adjusted_lines": posted,
        "message": (
            f"{take.reference} closed. {posted} line(s) adjusted, "
            f"{summary['short_units']} short and {summary['over_units']} over, "
            f"a net {summary['variance_value']:.2f} at cost."
        ),
    }


@router.post("/{take_id}/abandon")
def abandon(take_id: int, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """Walk away without adjusting anything.

    Kept as a first-class action rather than leaving counts open forever. An
    abandoned count is still a record of what was counted, which is worth
    keeping — somebody spent an afternoon on it.
    """
    take = db.query(StockTake).get(take_id)
    if not take:
        raise HTTPException(status_code=404, detail="That stock take no longer exists.")
    if take.status != "open":
        raise HTTPException(status_code=400, detail=f"This count is already {take.status}.")
    take.status = "abandoned"
    take.closed_at = datetime.utcnow()
    take.closed_by_id = user.id
    db.commit()
    return {"ok": True, "message": f"{take.reference} abandoned. No stock was adjusted."}


@router.get("/{take_id}")
def detail(take_id: int, db: Session = Depends(get_db)):
    take = db.query(StockTake).get(take_id)
    if not take:
        raise HTTPException(status_code=404, detail="That stock take no longer exists.")
    products = {
        p.id: p.name for p in
        db.query(Product).filter(Product.id.in_([l.product_id for l in take.lines])).all()
    } if take.lines else {}
    return {
        **_out(db, take),
        "lines": [
            {
                "product_id": l.product_id,
                "product": products.get(l.product_id, f"#{l.product_id}"),
                "counted": l.counted, "expected": l.expected,
                "variance": l.variance,
                "value": round(l.variance * (l.unit_cost or 0), 2),
                "note": l.note or "",
            }
            for l in sorted(take.lines, key=lambda x: abs(x.variance), reverse=True)
        ],
    }
