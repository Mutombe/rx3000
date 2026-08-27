from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Message, Patient
from ..services import messaging, paging, scheduler

router = APIRouter(prefix="/api/messages", tags=["reminders"], dependencies=[Depends(get_current_user)])


def _reminder_query(db: Session, status: str, message_type: str):
    # Each row shows who it went to. That was a query a row.
    query = db.query(Message).options(joinedload(Message.patient))
    if status:
        query = query.filter(Message.status == status)
    if message_type:
        query = query.filter(Message.message_type == message_type)
    return query.order_by(Message.scheduled_for.desc())


@router.get("", response_model=list[schemas.MessageOut])
def list_messages(status: str = "", message_type: str = "", limit: int = 200,
                  db: Session = Depends(get_db)):
    """The capped list. `/paged` is what the screen uses."""
    return _reminder_query(db, status, message_type).limit(limit).all()


@router.get("/paged")
def list_messages_paged(status: str = "", message_type: str = "", page: int = 1,
                        per_page: int = paging.DEFAULT_PER_PAGE,
                        db: Session = Depends(get_db)):
    """Reminders, a page at a time, with the true total.

    The screen rendered every row the cap returned and offered no way to move
    through them — a list that says nothing about what it is not showing.
    """
    result = paging.page(_reminder_query(db, status, message_type),
                         page=page, per_page=per_page)
    return result.envelope(lambda m: schemas.MessageOut.model_validate(m, from_attributes=True).model_dump())


@router.post("", response_model=schemas.MessageOut)
def send_message(body: schemas.MessageCreate, db: Session = Depends(get_db)):
    """Free-type message to a patient, delivered immediately."""
    patient = db.get(Patient, body.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    message = Message(
        patient_id=body.patient_id,
        channel=body.channel,
        message_type=body.message_type,
        subject=body.subject,
        body=body.body,
    )
    db.add(message)
    db.flush()
    messaging.deliver(message)
    db.commit()
    db.refresh(message)
    return message


@router.post("/run-jobs")
def run_jobs():
    """Manually trigger the reminder pipeline (repeats, birthdays, delivery)."""
    return scheduler.run_all_jobs()
