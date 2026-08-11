"""Leads, conversion, duplicate detection and public web-to-lead / web-to-case intake."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import helpers, schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import (
    Activity, Company, Contact, Deal, Lead, Ticket, TicketMessage, User,
)
from ..services import automation

router = APIRouter(prefix="/api/crm/leads", tags=["crm-leads"], dependencies=[Depends(get_current_user)])
public = APIRouter(prefix="/api/public", tags=["crm-intake"])  # unauthenticated intake

LEAD_STATUSES = ("new", "working", "nurturing", "converted", "disqualified")


def find_duplicates(db: Session, email: str, phone: str, exclude_lead_id: int | None = None) -> list[dict]:
    """Warn about an existing lead or contact with the same email or phone."""
    warnings: list[dict] = []
    for field, value in (("email", email), ("phone", phone)):
        if not value:
            continue
        lead_q = db.query(Lead).filter(
            getattr(Lead, field) == value, Lead.status != "converted",
        )
        if exclude_lead_id:
            lead_q = lead_q.filter(Lead.id != exclude_lead_id)
        for existing in lead_q.limit(3).all():
            warnings.append({
                "field": field, "value": value, "existing_type": "lead",
                "existing_id": existing.id,
                "existing_label": f"{existing.first_name} {existing.last_name}",
            })
        for existing in db.query(Contact).filter(getattr(Contact, field) == value).limit(3).all():
            warnings.append({
                "field": field, "value": value, "existing_type": "contact",
                "existing_id": existing.id,
                "existing_label": f"{existing.first_name} {existing.last_name}",
            })
    return warnings


@router.get("", response_model=list[schemas.LeadOut])
def list_leads(
    q: str = "", status: str = "", rating: str = "", owner_id: int | None = None,
    limit: int = 200, db: Session = Depends(get_db),
):
    query = db.query(Lead)
    if status == "open":
        query = query.filter(Lead.status.in_(["new", "working", "nurturing"]))
    elif status:
        query = query.filter(Lead.status == status)
    if rating:
        query = query.filter(Lead.rating == rating)
    if owner_id:
        query = query.filter(Lead.owner_id == owner_id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Lead.first_name.ilike(like), Lead.last_name.ilike(like),
            Lead.company_name.ilike(like), Lead.email.ilike(like), Lead.phone.ilike(like),
        ))
    return query.order_by(Lead.score.desc(), Lead.created_at.desc()).limit(limit).all()


@router.get("/duplicates", response_model=list[schemas.DuplicateWarning])
def check_duplicates(email: str = "", phone: str = "", db: Session = Depends(get_db)):
    return find_duplicates(db, email, phone)


@router.post("", response_model=schemas.LeadOut)
def create_lead(body: schemas.LeadBase, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lead = Lead(**body.model_dump())
    db.add(lead)
    db.flush()
    automation.score_lead(db, lead)
    automation.assign_lead(db, lead)
    if lead.owner_id is None:
        lead.owner_id = user.id
    db.commit()
    db.refresh(lead)
    return lead


@router.get("/{lead_id}", response_model=schemas.LeadOut)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get("/{lead_id}/score", response_model=schemas.LeadScoreExplanation)
def explain_score(lead_id: int, db: Session = Depends(get_db)):
    """Break a lead's score down into the factors that produced it."""
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return automation.explain_lead_score(db, lead)


@router.post("/bulk/assign", response_model=list[schemas.LeadOut])
def bulk_assign(body: schemas.LeadBulkAssign, db: Session = Depends(get_db)):
    """Reassign several leads to one owner in a single action."""
    owner = db.get(User, body.owner_id)
    if not owner:
        raise HTTPException(status_code=400, detail="Owner not found")
    leads = db.query(Lead).filter(Lead.id.in_(body.lead_ids)).all()
    if not leads:
        raise HTTPException(status_code=400, detail="No matching leads")
    for lead in leads:
        if lead.status == "converted":
            continue
        lead.owner_id = owner.id
    db.commit()
    for lead in leads:
        db.refresh(lead)
    return leads


@router.put("/{lead_id}", response_model=schemas.LeadOut)
def update_lead(lead_id: int, body: schemas.LeadBase, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.status == "converted":
        raise HTTPException(status_code=400, detail="A converted lead can no longer be edited")
    for key, value in body.model_dump().items():
        setattr(lead, key, value)
    automation.score_lead(db, lead)
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/{lead_id}/status", response_model=schemas.LeadOut)
def set_status(lead_id: int, body: schemas.LeadStatusUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if body.status not in LEAD_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {', '.join(LEAD_STATUSES)}")
    if body.status == "converted":
        raise HTTPException(status_code=400, detail="Use the convert endpoint to convert a lead")
    lead.status = body.status
    lead.disqualified_reason = body.disqualified_reason if body.status == "disqualified" else ""
    db.add(Activity(
        activity_type="note", subject=f"Lead status → {body.status}",
        body=body.disqualified_reason, owner_id=user.id, completed_at=datetime.utcnow(),
    ))
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/{lead_id}/convert", response_model=schemas.LeadConvertResult)
def convert_lead(
    lead_id: int,
    body: schemas.LeadConvert,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Convert a lead into an Account, a Contact and (optionally) an Opportunity."""
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.status == "converted":
        raise HTTPException(status_code=400, detail="Lead has already been converted")
    if lead.status == "disqualified":
        raise HTTPException(status_code=400, detail="A disqualified lead cannot be converted — requalify it first")

    company = None
    if body.create_company and lead.company_name:
        company = db.query(Company).filter(Company.name.ilike(lead.company_name)).first()
        if not company:
            company = Company(
                name=lead.company_name, account_type=body.account_type,
                phone=lead.phone, email=lead.email, owner_id=lead.owner_id or user.id,
                status="prospect", notes=lead.interest,
            )
            db.add(company)
            db.flush()

    contact = Contact(
        first_name=lead.first_name, last_name=lead.last_name, job_title=lead.job_title,
        email=lead.email, phone=lead.phone,
        company_id=company.id if company else None,
        lifecycle_stage="qualified", source=lead.source,
        owner_id=lead.owner_id or user.id, marketing_opt_in=lead.marketing_opt_in,
        notes=lead.interest,
    )
    db.add(contact)
    db.flush()

    deal = None
    if body.create_deal:
        deal = Deal(
            title=body.deal_title or f"{lead.company_name or lead.last_name} — new opportunity",
            company_id=company.id if company else None,
            contact_id=contact.id,
            value=body.deal_value if body.deal_value is not None else lead.estimated_value,
            stage="qualified", probability=30,
            owner_id=lead.owner_id or user.id, source=lead.source,
            notes=lead.interest, campaign_id=lead.campaign_id,
        )
        db.add(deal)
        db.flush()
        automation.create_deal_tasks(db, deal, user.id)

    lead.status = "converted"
    lead.converted_at = datetime.utcnow()
    lead.converted_company_id = company.id if company else None
    lead.converted_contact_id = contact.id
    lead.converted_deal_id = deal.id if deal else None

    db.add(Activity(
        activity_type="note",
        subject=f"Lead converted: {lead.first_name} {lead.last_name}",
        body=f"Score {lead.score} ({lead.rating}). Source: {lead.source or 'unknown'}.",
        owner_id=user.id, company_id=company.id if company else None,
        contact_id=contact.id, deal_id=deal.id if deal else None,
        completed_at=datetime.utcnow(),
    ))
    db.commit()
    return schemas.LeadConvertResult(
        lead_id=lead.id,
        company_id=company.id if company else None,
        contact_id=contact.id,
        deal_id=deal.id if deal else None,
    )


# ---------- public intake (no authentication) ----------
@public.post("/web-to-lead", response_model=schemas.LeadOut)
def web_to_lead(body: schemas.WebLeadIn, db: Session = Depends(get_db)):
    """Website enquiry form → scored, auto-assigned lead."""
    lead = Lead(**body.model_dump(), status="new")
    db.add(lead)
    db.flush()
    automation.score_lead(db, lead)
    automation.assign_lead(db, lead)
    db.commit()
    db.refresh(lead)
    return lead


@public.post("/web-to-case", response_model=schemas.TicketOut)
def web_to_case(body: schemas.WebCaseIn, db: Session = Depends(get_db)):
    """Website support form → help-desk ticket, auto-assigned and SLA-timed."""
    from datetime import timedelta
    from .helpdesk_router import SLA_HOURS

    ticket = Ticket(
        ticket_number=helpers.next_number(db, Ticket, "TKT", "ticket_number"),
        subject=body.subject,
        description=f"{body.description}\n\nFrom: {body.name} ({body.email or body.phone or 'no contact detail'})",
        category=body.category, priority="normal", channel="web",
        due_at=datetime.utcnow() + timedelta(hours=SLA_HOURS["normal"]),
    )
    db.add(ticket)
    db.flush()
    automation.assign_ticket(db, ticket)
    db.add(TicketMessage(ticket_id=ticket.id, from_customer=True,
                         body=body.description or body.subject))
    db.commit()
    db.refresh(ticket)
    return ticket
