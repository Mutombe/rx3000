"""Marketing: data-driven audience segments and campaign sends.

Segments are computed live from real pharmacy data (chronic conditions,
loyalty, lapsed customers, repeats due) so a campaign always targets the
current audience. Every segment respects POPIA marketing consent.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user, require_role
from ..database import get_db
from ..models import Campaign, Message, Patient, PrescriptionItem, Sale, User
from ..services import messaging, paging

router = APIRouter(prefix="/api/marketing", tags=["marketing"], dependencies=[Depends(get_current_user)])

SEGMENTS = {
    "all_patients": ("All opted-in patients", "Every patient who has consented to marketing"),
    "chronic": ("Chronic patients", "Patients with a chronic condition on file"),
    "birthday_month": ("Birthdays this month", "Patients whose birthday falls this month"),
    "loyalty_members": ("Loyalty members", "Patients holding loyalty points"),
    "lapsed_90d": ("Lapsed customers", "No purchase in the last 90 days"),
    "repeats_due_14d": ("Repeats due soon", "A repeat prescription falls due within 14 days"),
    "medical_aid": ("Medical aid members", "Patients on a medical aid scheme"),
    "private": ("Private patients", "Patients with no medical aid"),
}


def segment_query(db: Session, key: str, channel: str = "sms"):
    """Patients in a segment who have consented and have the right contact detail."""
    query = db.query(Patient).filter(Patient.marketing_opt_in.is_(True))
    query = query.filter(Patient.email != "") if channel == "email" else query.filter(Patient.phone != "")

    today = date.today()
    if key == "chronic":
        query = query.filter(Patient.chronic_conditions != "")
    elif key == "birthday_month":
        query = query.filter(Patient.date_of_birth.isnot(None),
                             extract("month", Patient.date_of_birth) == today.month)
    elif key == "loyalty_members":
        query = query.filter(Patient.loyalty_points > 0)
    elif key == "lapsed_90d":
        cutoff = datetime.utcnow() - timedelta(days=90)
        recent = db.query(Sale.patient_id).filter(
            Sale.status == "paid", Sale.created_at >= cutoff, Sale.patient_id.isnot(None)
        ).distinct()
        query = query.filter(Patient.id.notin_(recent))
    elif key == "repeats_due_14d":
        due = (
            db.query(PrescriptionItem.prescription_id)
            .filter(PrescriptionItem.next_repeat_date.isnot(None),
                    PrescriptionItem.next_repeat_date <= today + timedelta(days=14))
            .subquery()
        )
        from ..models import Prescription
        patient_ids = db.query(Prescription.patient_id).filter(Prescription.id.in_(due)).distinct()
        query = query.filter(Patient.id.in_(patient_ids))
    elif key == "medical_aid":
        query = query.filter(Patient.medical_aid_id.isnot(None))
    elif key == "private":
        query = query.filter(Patient.medical_aid_id.is_(None))
    elif key != "all_patients":
        raise HTTPException(status_code=400, detail=f"Unknown segment '{key}'")
    return query


@router.get("/segments", response_model=list[schemas.SegmentOut])
def list_segments(channel: str = "sms", db: Session = Depends(get_db)):
    out = []
    for key, (label, description) in SEGMENTS.items():
        out.append(schemas.SegmentOut(
            key=key, label=label, description=description,
            size=segment_query(db, key, channel).count(),
        ))
    return out


@router.get("/segments/{key}/preview", response_model=list[schemas.PatientOut])
def preview_segment(key: str, channel: str = "sms", limit: int = 25, db: Session = Depends(get_db)):
    return segment_query(db, key, channel).limit(limit).all()


def _campaign_query(db: Session):
    return db.query(Campaign).order_by(Campaign.created_at.desc())


@router.get("/campaigns", response_model=list[schemas.CampaignOut])
def list_campaigns(limit: int = 100, db: Session = Depends(get_db)):
    return _campaign_query(db).limit(limit).all()


@router.get("/campaigns/paged")
def list_campaigns_paged(page: int = 1, per_page: int = paging.DEFAULT_PER_PAGE,
                         db: Session = Depends(get_db)):
    """Campaign history, a page at a time, with the true total."""
    result = paging.page(_campaign_query(db), page=page, per_page=per_page)
    return result.envelope(lambda c: schemas.CampaignOut.model_validate(c, from_attributes=True).model_dump())


@router.post("/campaigns", response_model=schemas.CampaignOut)
def create_campaign(body: schemas.CampaignCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.segment not in SEGMENTS:
        raise HTTPException(status_code=400, detail=f"Unknown segment '{body.segment}'")
    campaign = Campaign(
        **body.model_dump(),
        created_by_id=user.id,
        audience_size=segment_query(db, body.segment, body.channel).count(),
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.post("/campaigns/{campaign_id}/send", response_model=schemas.CampaignOut)
def send_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "pharmacist")),
):
    """Personalise and deliver the campaign to everyone currently in the segment.

    Supported merge fields: {first_name} {last_name} {points} {pharmacy}
    """
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == "sent":
        raise HTTPException(status_code=400, detail="Campaign has already been sent")

    from ..config import settings
    recipients = segment_query(db, campaign.segment, campaign.channel).all()
    sent = failed = 0

    for patient in recipients:
        body = (campaign.body
                .replace("{first_name}", patient.first_name)
                .replace("{last_name}", patient.last_name)
                .replace("{points}", str(patient.loyalty_points))
                .replace("{pharmacy}", settings.PHARMACY_NAME))
        message = Message(
            patient_id=patient.id,
            channel=campaign.channel,
            message_type="campaign",
            subject=campaign.subject,
            body=body,
            campaign_id=campaign.id,
        )
        db.add(message)
        db.flush()
        messaging.deliver(message)
        if message.status == "sent":
            sent += 1
        else:
            failed += 1

    campaign.audience_size = len(recipients)
    campaign.sent_count = sent
    campaign.failed_count = failed
    campaign.status = "sent"
    campaign.sent_at = datetime.utcnow()
    db.commit()
    db.refresh(campaign)
    return campaign


@router.get("/campaigns/{campaign_id}/messages", response_model=list[schemas.MessageOut])
def campaign_messages(campaign_id: int, limit: int = 200, db: Session = Depends(get_db)):
    return (
        db.query(Message)
        .filter(Message.campaign_id == campaign_id)
        .order_by(Message.scheduled_for.desc())
        .limit(limit)
        .all()
    )


# Marketing consent used to be set here, as one boolean overwritten in place.
# The real record is /api/consent/{subject_type}/{subject_id}, which the consent
# panel uses: permission per channel, with the evidence for each answer, and it
# never overwrites what came before. Consent you cannot show the history of is
# consent you cannot prove, which is the whole point of recording it.


