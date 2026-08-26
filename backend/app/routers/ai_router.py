import json
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..models import AiConversation, User
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


@router.post("/ask/stream")
def ask_stream(body: schemas.AIAskRequest, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """The same answer as `/ask`, sent as it is written.

    Server-sent events rather than a websocket: this is one-way, short-lived and
    survives a proxy that would drop an upgrade. Each frame is a JSON object so a
    delta containing a newline cannot be mistaken for the end of an event, which
    is exactly what happens when deltas are written as bare text.
    """
    def frames():
        # `phase` first, so the screen can say what is happening before there is
        # anything to show. Building the data snapshot is the slow part and it
        # happens before the model is even called.
        yield "data: " + json.dumps({"type": "phase", "phase": "reading"}) + "\n\n"
        try:
            system, user = ai_service.business_prompt(db, body.question)
            yield "data: " + json.dumps({"type": "phase", "phase": "thinking"}) + "\n\n"
            for delta in ai_service.stream_claude(system, user):
                yield "data: " + json.dumps({"type": "delta", "text": delta}) + "\n\n"
        except Exception as exc:  # noqa: BLE001 - the client needs the reason
            yield "data: " + json.dumps({"type": "error", "message": str(exc)}) + "\n\n"
        yield "data: " + json.dumps({"type": "done"}) + "\n\n"

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Nginx buffers proxied responses by default, which turns a stream
            # back into one long wait and makes this whole endpoint pointless.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history")
def ai_history(limit: int = 50, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """Your own past questions, newest first.

    Yours only. The questions somebody puts to an assistant are working notes,
    often half-formed, and a shared log of everybody's is something staff learn
    to work around rather than use.
    """
    limit = max(1, min(limit, 200))
    rows = (db.query(AiConversation)
              .filter(AiConversation.user_id == user.id)
              .order_by(AiConversation.created_at.desc())
              .limit(limit + 1)
              .all())
    # Asked for one more than the limit, so "there are older ones" is a fact
    # rather than a guess. Reporting a capped list as the whole history is how a
    # screen ends up quietly telling somebody they have asked fifty questions
    # when they have asked four hundred.
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": r.id,
                "question": r.question,
                "answer": r.answer,
                "model": r.model,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "more": more,
        "total": db.query(AiConversation).filter(AiConversation.user_id == user.id).count(),
    }


@router.delete("/history/{entry_id}")
def delete_ai_entry(entry_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Remove one exchange from your log."""
    row = (db.query(AiConversation)
             .filter(AiConversation.id == entry_id,
                     AiConversation.user_id == user.id)
             .first())
    if not row:
        raise HTTPException(status_code=404, detail="That entry is not in your history.")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.delete("/history")
def clear_ai_history(db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Empty your log. Yours alone, and it does not touch anybody else's."""
    removed = (db.query(AiConversation)
                 .filter(AiConversation.user_id == user.id)
                 .delete(synchronize_session=False))
    db.commit()
    return {"ok": True, "removed": removed}
