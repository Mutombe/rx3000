from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Message, Patient
from ..services import messaging, scheduler

router = APIRouter(prefix="/api/messages", tags=["reminders"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[schemas.MessageOut])
def list_messages(status: str = "", message_type: str = "", limit: int = 200, db: Session = Depends(get_db)):
    query = db.query(Message)
    if status:
        query = query.filter(Message.status == status)
    if message_type:
        query = query.filter(Message.message_type == message_type)
    return query.order_by(Message.scheduled_for.desc()).limit(limit).all()


@router.post("", response_model=schemas.MessageOut)
def send_message(body: schemas.MessageCreate, db: Session = Depends(get_db)):
    """Free-type message to a patient — delivered immediately."""
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
