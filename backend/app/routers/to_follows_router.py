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


def _branch(db: Session, user: User) -> int | None:
    """The shelf the person asking is standing at, or None if nobody knows.

    None rather than the default branch on purpose: a head office user covering
    every shop has no one shelf, and answering with the default branch's would
    tell them a product is out of stock because it is out at a shop they were
    not asking about.
    """
    from ..services import branches as branch_svc
    return branch_svc.branch_of(db, user.id)


@router.get("")
def queue(status: str = "outstanding", patient_id: int = 0, product_id: int = 0,
          limit: int = 200, db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    """Everything owed. The list a pharmacy currently keeps on paper."""
    return to_follows.queue(db, status=status, patient_id=patient_id,
                            product_id=product_id, limit=limit,
                            branch_id=_branch(db, user))


@router.get("/ready")
def ready(limit: int = 200, db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    """What is owed *and* now in stock: the list of patients to telephone.

    The incumbent can tell a pharmacy what it owes. This tells it what it can
    honour today, which is the part that gets the medicine to the patient and
    the money off the shelf. Stock arriving is the event that matters and
    nothing else in the shop connects it to a waiting patient.
    """
    return to_follows.ready(db, limit, branch_id=_branch(db, user))


@router.get("/summary")
def summary(db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    return to_follows.totals(db, branch_id=_branch(db, user))


@router.post("")
def create(product_id: int = Body(...), quantity: int = Body(...),
           patient_id: int | None = Body(default=None),
           sale_id: int | None = Body(default=None),
           promised_for: date | None = Body(default=None),
           notes: str = Body(default=""),
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Record a promise made at the counter.

    Most to-follows are raised by a dispensing that came up short, and that is
    the common case. This is the other one: somebody asks for something the
    shelf does not have, is told it will be in on Friday, and walks out. Until
    this existed that promise lived on whatever the pharmacy writes it on,
    which is the paper list this whole feature exists to replace.

    THERE WERE TWO OF THESE, AND ONLY ONE OF THEM RAN.

    A second `@router.post("")` was declared below this one, with the docstring
    above and a body that was this one minus `sale_id`. FastAPI matches routes
    in the order they are registered, so every request has always been served
    here — while the OpenAPI schema, which is a dict keyed by path and method,
    kept the LAST declaration and published the other one.

    So the contract said one thing, the server did another, and the difference
    was invisible: the two bodies agreed except for a field, and the one the
    schema omitted is the one that ties a short supply to the sale it came
    from. Anybody editing the dead handler would have watched their change do
    nothing.
    """
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
    # The whole unit of work here is this one record, so this is where it is
    # committed — `record` no longer does it for everybody.
    db.commit()
    db.refresh(owed)
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
