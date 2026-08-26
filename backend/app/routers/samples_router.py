"""The sample register and the consent register.

Two compliance records that a retail pharmacy is expected to keep and that no
system here kept: medicine a representative left, and permission to send
somebody a message. Both are the kind of thing nobody looks at until they are
asked for, at which point the answer has to already exist.
"""
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import User
from ..services import consent, samples

router = APIRouter(prefix="/api", tags=["compliance"],
                   dependencies=[Depends(get_current_user)])


# ------------------------------------------------------------ sample register

@router.get("/samples")
def sample_register(only_open: bool = False, limit: int = 200,
                    db: Session = Depends(get_db)):
    return samples.register(db, only_open=only_open, limit=max(1, min(limit, 500)))


@router.post("/samples")
def receive_samples(product_id: int = Body(...), quantity: int = Body(...),
                    supplier_name: str = Body(...),
                    representative: str = Body(default=""),
                    batch_number: str = Body(default=""),
                    expiry_date: date | None = Body(default=None),
                    notes: str = Body(default=""),
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Book in what a representative left on the counter."""
    try:
        r = samples.receive(db, product_id=product_id, quantity=quantity,
                            supplier_name=supplier_name, representative=representative,
                            batch_number=batch_number, expiry_date=expiry_date,
                            user_id=user.id, notes=notes)
    except samples.SampleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "id": r.id, "reference": r.reference}


@router.get("/samples/{receipt_id}/history")
def sample_history(receipt_id: int, db: Session = Depends(get_db)):
    return {"movements": samples.history(db, receipt_id)}


@router.post("/samples/{receipt_id}/movements")
def move_samples(receipt_id: int, movement: str = Body(...), quantity: int = Body(...),
                 patient_id: int | None = Body(default=None),
                 given_to: str = Body(default=""),
                 witness_id: int | None = Body(default=None),
                 reason: str = Body(default=""),
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Record a sample being issued, returned, destroyed, expired or counted."""
    try:
        m = samples.move(db, receipt_id, movement=movement, quantity=quantity,
                         patient_id=patient_id, given_to=given_to,
                         witness_id=witness_id, reason=reason, user_id=user.id)
    except samples.SampleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "balance_after": m.balance_after}


# ----------------------------------------------------------- consent register

@router.get("/consent/{subject_type}/{subject_id}")
def consent_state(subject_type: str, subject_id: int, db: Session = Depends(get_db)):
    """What is permitted, per channel, and the evidence for each answer."""
    try:
        return consent.state_for(db, subject_type, subject_id)
    except consent.ConsentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/consent/{subject_type}/{subject_id}")
def record_consent(subject_type: str, subject_id: int,
                   state: str = Body(...), channel: str = Body(default="all"),
                   captured_via: str = Body(default="counter"),
                   wording: str = Body(default=""), note: str = Body(default=""),
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Record a grant or a withdrawal. Never overwrites what came before."""
    try:
        e = consent.record(db, subject_type=subject_type, subject_id=subject_id,
                           state=state, channel=channel, captured_via=captured_via,
                           wording=wording, note=note, user_id=user.id)
    except consent.ConsentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "id": e.id}
