"""Lay-bys: goods set aside, paid off over time, collected when settled.

The whole design turns on two rules that are easy to break in a way that
flatters the figures.

**A deposit is not income.** It is money the pharmacy holds on behalf of a
customer, against which it owes either the goods or a refund. Recognising it as
revenue overstates profit, hides a liability, and has to be unwound the day the
lay-by is cancelled. Nothing here raises a sale until the final payment lands.

**The stock leaves the shelf when the lay-by is raised, not when it is paid.**
It is physically in the back with the customer's name on it and cannot be sold
to anyone else. A system that leaves it on hand will sell the same box twice,
and the second customer is the one who finds out.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import helpers
from ..auth import get_current_user
from ..database import get_db
from ..models import LayBy, LayByItem, LayByPayment, Patient, Product, User
from .periods_router import require_step_up

router = APIRouter(prefix="/api/laybys", tags=["laybys"],
                   dependencies=[Depends(get_current_user)])


class LayByLineIn(BaseModel):
    product_id: int
    quantity: int = Field(1, gt=0)


class LayByIn(BaseModel):
    patient_id: int
    items: list[LayByLineIn]
    deposit: float = 0.0
    due_date: date | None = None
    notes: str = ""
    # Percentage of the total that must be down before goods are held. A
    # pharmacy that takes nothing up front is storing stock for free.
    minimum_deposit_percent: float = 20.0


class PaymentIn(BaseModel):
    amount: float = Field(..., gt=0)
    method: str = "cash"
    reference: str = ""


def _out(layby: LayBy) -> dict:
    return {
        "id": layby.id,
        "layby_number": layby.layby_number,
        "patient_id": layby.patient_id,
        "status": layby.status,
        "total": round(layby.total or 0, 2),
        "paid": layby.paid,
        "balance": layby.balance,
        "minimum_deposit": round(layby.minimum_deposit or 0, 2),
        "due_date": layby.due_date.isoformat() if layby.due_date else None,
        "created_at": layby.created_at.isoformat() if layby.created_at else None,
        # The customer's name and the product names, because a lay-by identified
        # only by numbers cannot be looked up by the person at the counter
        # holding a receipt and asking about "my daughter's inhaler".
        "patient": (f"{layby.patient.first_name} {layby.patient.last_name}"
                    if layby.patient else ""),
        "items": [
            {"product_id": i.product_id,
             "product": i.product.name if i.product else f"#{i.product_id}",
             "quantity": i.quantity,
             "unit_price": round(i.unit_price or 0, 2)}
            for i in layby.items
        ],
        "payments": [
            {"amount": round(p.amount, 2), "method": p.method,
             "at": p.created_at.isoformat()}
            for p in sorted(layby.payments, key=lambda x: x.created_at)
        ],
    }


@router.post("")
def create(body: LayByIn, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    """Raise a lay-by and take the goods off the shelf."""
    if not body.items:
        raise HTTPException(status_code=400, detail="A lay-by needs at least one item.")
    patient = db.query(Patient).get(body.patient_id)
    if not patient:
        # Unlike a walk-in sale, a lay-by is an agreement with a named person
        # held over weeks. There is nobody to call about an anonymous one.
        raise HTTPException(
            status_code=400,
            detail="A lay-by has to be in a customer's name — it is an agreement, not a sale.",
        )

    total = 0.0
    priced: list[tuple[Product, int, float]] = []
    for line in body.items:
        product = db.query(Product).get(line.product_id)
        if not product:
            raise HTTPException(status_code=404,
                                detail=f"Product {line.product_id} no longer exists.")
        if (product.schedule or 0) >= 5:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{product.name} is a schedule {product.schedule} item and cannot "
                    "be held on a lay-by. Controlled medicines are dispensed against a "
                    "prescription, not paid off over months."
                ),
            )
        price = round(product.unit_price or 0, 2)
        total = round(total + price * line.quantity, 2)
        priced.append((product, line.quantity, price))

    minimum = round(total * max(0.0, body.minimum_deposit_percent) / 100, 2)
    if body.deposit < minimum:
        raise HTTPException(
            status_code=400,
            detail=(
                f"A deposit of at least {minimum:.2f} is needed on a lay-by of "
                f"{total:.2f}. Holding stock costs the pharmacy the sale it could "
                "have made from the shelf."
            ),
        )

    layby = LayBy(
        layby_number=helpers.next_number(db, LayBy, "LAY", "layby_number"),
        patient_id=patient.id,
        status="open",
        total=total,
        minimum_deposit=minimum,
        due_date=body.due_date,
        notes=body.notes.strip(),
        created_by_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(layby)
    db.flush()

    for product, quantity, price in priced:
        db.add(LayByItem(layby_id=layby.id, product_id=product.id,
                         quantity=quantity, unit_price=price))
        # Off the shelf now. This is the rule that stops the same box being sold
        # to somebody else while the first customer is still paying for it.
        #
        # Drawn through the FEFO consumer rather than move_stock: on-hand is
        # summed from batches, so adjusting the product row alone leaves the
        # goods visible and sellable everywhere it actually matters. Written
        # that way first, and the stock did not move at all.
        helpers.consume_stock_fefo(db, product, quantity, "layby", user.id,
                                   reference=layby.layby_number)

    if body.deposit:
        db.add(LayByPayment(layby_id=layby.id, amount=round(body.deposit, 2),
                            method="cash", user_id=user.id,
                            created_at=datetime.utcnow()))
    db.commit()
    db.refresh(layby)
    return {
        **_out(layby),
        "message": (
            f"{layby.layby_number} raised for {patient.first_name} {patient.last_name}. "
            f"{layby.balance:.2f} outstanding. The stock is now held and is not "
            "available to sell."
        ),
    }


@router.post("/{layby_id}/pay")
def pay(layby_id: int, body: PaymentIn, db: Session = Depends(get_db),
        user: User = Depends(get_current_user)):
    """Take an instalment. Nothing is a sale until the balance reaches zero."""
    layby = db.query(LayBy).get(layby_id)
    if not layby:
        raise HTTPException(status_code=404, detail="That lay-by no longer exists.")
    if layby.status != "open":
        raise HTTPException(
            status_code=400,
            detail=f"This lay-by is {layby.status} and cannot take a payment.",
        )
    if body.amount > layby.balance + 0.005:
        raise HTTPException(
            status_code=400,
            detail=(
                f"That is more than the {layby.balance:.2f} outstanding. Take the "
                "balance and settle it, or correct the amount."
            ),
        )

    db.add(LayByPayment(layby_id=layby.id, amount=round(body.amount, 2),
                        method=body.method, reference=body.reference.strip(),
                        user_id=user.id, created_at=datetime.utcnow()))
    db.commit()
    db.refresh(layby)
    settled = layby.balance <= 0.005
    return {
        **_out(layby),
        "settled": settled,
        "message": (
            f"{body.amount:.2f} received. Balance settled — the goods can be collected."
            if settled else
            f"{body.amount:.2f} received. {layby.balance:.2f} still outstanding."
        ),
    }


@router.post("/{layby_id}/complete")
def complete(layby_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """Hand the goods over and recognise the sale.

    This is the only point at which a lay-by becomes revenue. The stock already
    left on the day it was raised, so nothing moves here — booking it out again
    would take the same goods off twice.
    """
    from ..models import Sale, SaleItem

    layby = db.query(LayBy).get(layby_id)
    if not layby:
        raise HTTPException(status_code=404, detail="That lay-by no longer exists.")
    if layby.status != "open":
        raise HTTPException(status_code=400,
                            detail=f"This lay-by is already {layby.status}.")
    if layby.balance > 0.005:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{layby.balance:.2f} is still outstanding. Goods on a lay-by are "
                "handed over when it is settled, not before."
            ),
        )

    sale = Sale(
        sale_number=helpers.next_number(db, Sale, "INV", "sale_number"),
        patient_id=layby.patient_id,
        cashier_id=user.id,
        subtotal=layby.total,
        total=layby.total,
        payment_method="layby",
        amount_tendered=layby.paid,
        status="paid",
        created_at=datetime.utcnow(),
    )
    db.add(sale)
    db.flush()
    for item in layby.items:
        db.add(SaleItem(sale_id=sale.id, product_id=item.product_id,
                        quantity=item.quantity, unit_price=item.unit_price,
                        line_total=round(item.unit_price * item.quantity, 2)))

    layby.status = "completed"
    layby.completed_at = datetime.utcnow()
    layby.sale_id = sale.id
    db.commit()
    return {
        "ok": True, "sale_number": sale.sale_number,
        "message": (
            f"{layby.layby_number} completed and invoiced as {sale.sale_number}. "
            "The stock left the shelf when the lay-by was raised, so it is not "
            "moved again here."
        ),
    }


@router.post("/{layby_id}/cancel")
def cancel(layby_id: int, fee: float = 0.0, db: Session = Depends(get_db),
           user: User = Depends(get_current_user),
           _grant=Depends(require_step_up("layby.cancel"))):
    """Put the goods back and work out what is refundable."""
    layby = db.query(LayBy).get(layby_id)
    if not layby:
        raise HTTPException(status_code=404, detail="That lay-by no longer exists.")
    if layby.status != "open":
        raise HTTPException(status_code=400,
                            detail=f"This lay-by is already {layby.status}.")

    paid = layby.paid
    fee = round(max(0.0, min(fee, paid)), 2)
    for item in layby.items:
        product = db.query(Product).get(item.product_id)
        if product:
            # Back on the shelf as a batch, because that is where on-hand is
            # counted. The goods never sold, so they return to stock.
            helpers.receive_stock_batch(
                db, product, item.quantity, user.id,
                batch_number=f"{layby.layby_number}-RET",
                unit_cost=product.cost_price or None,
                reference=layby.layby_number,
            )
    layby.status = "cancelled"
    layby.cancelled_at = datetime.utcnow()
    layby.cancellation_fee = fee
    db.commit()
    refund = round(paid - fee, 2)
    return {
        "ok": True,
        "paid": paid, "fee": fee, "refund": refund,
        "message": (
            f"{layby.layby_number} cancelled. Stock returned to the shelf. "
            f"{refund:.2f} refundable"
            + (f" after a {fee:.2f} fee." if fee else " — no fee charged.")
        ),
    }


LISTING_CAP = 200


@router.get("")
def listing(status: str = "open", db: Session = Depends(get_db)):
    query = db.query(LayBy)
    if status:
        query = query.filter(LayBy.status == status)
    total = query.count()
    rows = query.order_by(LayBy.created_at.desc()).limit(LISTING_CAP).all()
    # The count is of everything, the list is of what fits. Reporting the cap as
    # the total is the mistake this codebase has made in five separate places,
    # and it reads as "the pharmacy has 200 lay-bys" when it has more.
    return {"laybys": [_out(r) for r in rows], "total": total,
            "showing": len(rows)}


@router.get("/{layby_id}")
def detail(layby_id: int, db: Session = Depends(get_db)):
    layby = db.query(LayBy).get(layby_id)
    if not layby:
        raise HTTPException(status_code=404, detail="That lay-by no longer exists.")
    return _out(layby)
