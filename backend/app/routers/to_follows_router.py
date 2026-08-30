"""To follows. The medicine the pharmacy still owes."""
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import OwedItem, Patient, Product, User
from ..services import to_follows

router = APIRouter(prefix="/api/to-follows", tags=["to-follows"],
                   dependencies=[Depends(get_current_user)])


@router.get("")
def queue(status: str = "outstanding", patient_id: int = 0, product_id: int = 0,
          limit: int = 200, db: Session = Depends(get_db)):
    """Everything owed. The list a pharmacy currently keeps on paper."""
    return to_follows.queue(db, status=status, patient_id=patient_id,
                            product_id=product_id, limit=limit)


@router.get("/ready")
def ready(limit: int = 200, db: Session = Depends(get_db)):
    """What is owed *and* now in stock — the list of patients to telephone.

    The incumbent can tell a pharmacy what it owes. This tells it what it can
    honour today, which is the part that gets the medicine to the patient and
    the money off the shelf. Stock arriving is the event that matters and
    nothing else in the shop connects it to a waiting patient.
    """
    return to_follows.ready(db, limit)


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    return to_follows.totals(db)


@router.post("")
def create(product_id: int = Body(...), quantity: int = Body(...),
           patient_id: int | None = Body(default=None),
           sale_id: int | None = Body(default=None),
           promised_for: date | None = Body(default=None),
           notes: str = Body(default=""),
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Record a debt raised outside the dispensing flow, an OTC short supply."""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if patient_id and not db.get(Patient, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    try:
        owed = to_follows.record(db, product=product, quantity_owed=quantity,
                                 patient_id=patient_id, sale_id=sale_id,
                                 user_id=user.id, promised_for=promised_for,
                                 notes=notes)
    except to_follows.OwedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return to_follows.summarise(owed)


@router.post("")
def promise(product_id: int = Body(...), quantity: int = Body(...),
            patient_id: int | None = Body(default=None),
            promised_for: date | None = Body(default=None),
            notes: str = Body(default=""),
            db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """Record a promise made at the counter.

    Most of these are raised by a dispensing that came up short, and that is
    the common case. This is the other one: somebody asks for something the
    shelf does not have, is told it will be in on Friday, and walks out. Until
    now that promise lived in whatever the pharmacy writes it on, which is the
    paper list this whole feature exists to replace — so the one route into it
    that a person actually uses was the one that was missing.
    """
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if patient_id and not db.get(Patient, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    try:
        owed = to_follows.record(
            db, product=product, quantity_owed=int(quantity),
            patient_id=patient_id, user_id=user.id,
            promised_for=promised_for, notes=notes.strip())
    except to_follows.OwedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return to_follows.summarise(owed)


@router.get("/{owed_id}")
def detail(owed_id: int, db: Session = Depends(get_db)):
    owed = db.get(OwedItem, owed_id)
    if not owed:
        raise HTTPException(status_code=404, detail="To-follow not found")
    return to_follows.summarise(owed)


@router.post("/{owed_id}/settle")
def settle(owed_id: int, quantity: int = Body(default=0, embed=True),
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Hand over what was owed. Omit the quantity to settle the balance in full."""
    owed = db.get(OwedItem, owed_id)
    if not owed:
        raise HTTPException(status_code=404, detail="To-follow not found")
    amount = quantity or to_follows.outstanding_quantity(owed)
    try:
        return to_follows.settle(db, owed, amount, user.id)
    except to_follows.OwedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{owed_id}/cancel")
def cancel(owed_id: int, reason: str = Body(..., embed=True),
           db: Session = Depends(get_db)):
    """Write the debt off. The patient got it elsewhere or no longer needs it."""
    owed = db.get(OwedItem, owed_id)
    if not owed:
        raise HTTPException(status_code=404, detail="To-follow not found")
    try:
        to_follows.cancel(db, owed, reason)
    except to_follows.OwedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return to_follows.summarise(owed)
