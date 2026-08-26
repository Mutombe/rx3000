"""Background jobs: repeat-prescription reminders, auto-refill queueing,
birthday messages, and delivery of pending messages.
"""
import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import extract

from ..config import settings
from ..database import SessionLocal
from ..models import Message, Patient, PrescriptionItem
from . import messaging

log = logging.getLogger("rx5000.scheduler")

REMIND_DAYS_AHEAD = 3


def _already_queued(db, patient_id: int, message_type: str, ref_body_fragment: str) -> bool:
    cutoff = datetime.utcnow() - timedelta(days=14)
    return (
        db.query(Message)
        .filter(
            Message.patient_id == patient_id,
            Message.message_type == message_type,
            Message.scheduled_for >= cutoff,
            Message.body.contains(ref_body_fragment),
        )
        .count()
        > 0
    )


def queue_repeat_reminders() -> int:
    """Queue reminders for repeats due within the next few days."""
    db = SessionLocal()
    created = 0
    try:
        horizon = date.today() + timedelta(days=REMIND_DAYS_AHEAD)
        items = (
            db.query(PrescriptionItem)
            .filter(
                PrescriptionItem.next_repeat_date.isnot(None),
                PrescriptionItem.next_repeat_date <= horizon,
                PrescriptionItem.repeats_used < PrescriptionItem.repeats_allowed,
            )
            .all()
        )
        for item in items:
            patient = item.prescription.patient
            product = item.product
            if _already_queued(db, patient.id, "repeat", product.name):
                continue
            msg_type = "auto_refill" if item.auto_refill else "repeat"
            if item.auto_refill:
                body = (
                    f"Hi {patient.first_name}, your repeat of {product.name} is being prepared "
                    f"automatically and will be ready for collection from {item.next_repeat_date:%d %b}. "
                    f"- {settings.PHARMACY_NAME}"
                )
            else:
                body = (
                    f"Hi {patient.first_name}, your repeat of {product.name} is due on "
                    f"{item.next_repeat_date:%d %b}. Reply or visit us to have it ready. "
                    f"- {settings.PHARMACY_NAME}"
                )
            db.add(Message(
                patient_id=patient.id,
                channel="sms" if patient.phone else "email",
                message_type="repeat",
                subject=f"Repeat prescription due: {product.name}",
                body=body,
            ))
            created += 1
        db.commit()
        if created:
            log.info("Queued %d repeat reminders", created)
        return created
    finally:
        db.close()


def queue_birthday_messages() -> int:
    db = SessionLocal()
    created = 0
    try:
        today = date.today()
        patients = (
            db.query(Patient)
            .filter(
                Patient.date_of_birth.isnot(None),
                extract("month", Patient.date_of_birth) == today.month,
                extract("day", Patient.date_of_birth) == today.day,
            )
            .all()
        )
        for patient in patients:
            if _already_queued(db, patient.id, "birthday", "birthday"):
                continue
            db.add(Message(
                patient_id=patient.id,
                channel="sms" if patient.phone else "email",
                message_type="birthday",
                subject="Happy birthday!",
                body=(
                    f"Happy birthday {patient.first_name}! Wishing you a healthy year ahead "
                    f"from all of us at {settings.PHARMACY_NAME}."
                ),
            ))
            created += 1
        db.commit()
        return created
    finally:
        db.close()


def send_pending_messages() -> int:
    db = SessionLocal()
    sent = 0
    try:
        pending = (
            db.query(Message)
            .filter(Message.status == "pending", Message.scheduled_for <= datetime.utcnow())
            .limit(50)
            .all()
        )
        for message in pending:
            messaging.deliver(message)
            if message.status == "sent":
                sent += 1
        db.commit()
        return sent
    finally:
        db.close()


def nightly_backup() -> str:
    """Automated database backup (keeps the most recent 20)."""
    from ..routers.admin_router import create_backup
    try:
        path = create_backup()
        log.info("Backup written: %s", path.name)
        return path.name
    except Exception as exc:  # noqa: BLE001
        log.error("Backup failed: %s", exc)
        return ""


def escalate_tickets() -> int:
    """Raise the priority of help-desk tickets that have blown their SLA."""
    from . import automation
    db = SessionLocal()
    try:
        return automation.escalate_overdue_tickets(db)
    finally:
        db.close()


def run_all_jobs() -> dict:
    """Run the full reminder pipeline once (also exposed via the API)."""
    return {
        "repeat_reminders_queued": queue_repeat_reminders(),
        "birthday_messages_queued": queue_birthday_messages(),
        "messages_sent": send_pending_messages(),
        "tickets_escalated": escalate_tickets(),
    }


scheduler = BackgroundScheduler()


def start() -> None:
    scheduler.add_job(queue_repeat_reminders, "cron", hour=7, minute=0, id="repeats")
    scheduler.add_job(queue_birthday_messages, "cron", hour=7, minute=5, id="birthdays")
    scheduler.add_job(send_pending_messages, "interval", minutes=5, id="sender")
    scheduler.add_job(nightly_backup, "cron", hour=23, minute=30, id="backup")
    scheduler.start()
    log.info("Scheduler started")


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
