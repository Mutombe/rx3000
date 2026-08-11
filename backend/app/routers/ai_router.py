from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Company, Deal, Patient, Product, Ticket
from ..services import ai_service

router = APIRouter(prefix="/api/ai", tags=["ai"], dependencies=[Depends(get_current_user)])


@router.get("/status")
def status():
    return {"enabled": ai_service.ai_enabled(), "model": ai_service.MODEL}


@router.post("/interaction-check", response_model=schemas.AITextResponse)
def interaction_check(body: schemas.AIInteractionRequest, db: Session = Depends(get_db)):
    patient = db.get(Patient, body.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    products = [p for pid in body.product_ids if (p := db.get(Product, pid))]
    if not products:
        raise HTTPException(status_code=400, detail="No valid products supplied")
    return schemas.AITextResponse(
        text=ai_service.interaction_check(db, patient, products),
        enabled=ai_service.ai_enabled(),
    )


@router.post("/patient-summary/{patient_id}", response_model=schemas.AITextResponse)
def patient_summary(patient_id: int, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return schemas.AITextResponse(
        text=ai_service.patient_summary(db, patient),
        enabled=ai_service.ai_enabled(),
    )


@router.post("/counseling/{product_id}", response_model=schemas.AITextResponse)
def counseling(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return schemas.AITextResponse(
        text=ai_service.counseling_notes(product),
        enabled=ai_service.ai_enabled(),
    )


class CampaignCopyRequest(schemas.BaseModel):
    name: str
    channel: str = "sms"
    segment_label: str = "patients"
    goal: str


@router.post("/campaign-copy", response_model=schemas.AITextResponse)
def campaign_copy(body: CampaignCopyRequest):
    return schemas.AITextResponse(
        text=ai_service.campaign_copy(body.name, body.channel, body.segment_label, body.goal),
        enabled=ai_service.ai_enabled(),
    )


@router.post("/ticket-reply/{ticket_id}", response_model=schemas.AITextResponse)
def ticket_reply(ticket_id: int, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return schemas.AITextResponse(
        text=ai_service.ticket_reply(ticket, ticket.messages),
        enabled=ai_service.ai_enabled(),
    )


@router.post("/account-summary/{company_id}", response_model=schemas.AITextResponse)
def account_summary(company_id: int, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    deals = db.query(Deal).filter(Deal.company_id == company_id).all()
    tickets = db.query(Ticket).filter(Ticket.company_id == company_id).all()
    return schemas.AITextResponse(
        text=ai_service.account_summary(db, company, deals, tickets, company.contacts),
        enabled=ai_service.ai_enabled(),
    )


@router.post("/ask", response_model=schemas.AITextResponse)
def ask(body: schemas.AIAskRequest, db: Session = Depends(get_db)):
    return schemas.AITextResponse(
        text=ai_service.business_answer(db, body.question),
        enabled=ai_service.ai_enabled(),
    )
