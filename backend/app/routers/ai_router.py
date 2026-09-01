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


# The seven non-streaming AI endpoints were here.
#
# Each had an exact `/stream` twin, and every screen used the twin — so
# none of these had ever been called. Deleting them is not tidying: `_sse`
# writes the question and the answer to the AI history and these did not,
# so any caller reaching for the simpler-looking one would have got its
# answer and left no record that the pharmacy had asked a machine about a
# patient, which is the one thing that record exists for.


class CampaignCopyRequest(schemas.BaseModel):
    name: str
    channel: str = "sms"
    segment_label: str = "patients"
    goal: str


@router.post("/ask/stream")
def ask_stream(body: schemas.AIAskRequest, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """The same answer as `/ask`, sent as it is written.

    Server-sent events rather than a websocket: this is one-way, short-lived and
    survives a proxy that would drop an upgrade.

    This was the only streaming endpoint, and it carried its own copy of the
    frame protocol and the history logging. Both now live in `_sse` below, so the
    seven AI surfaces cannot disagree about what a frame looks like or which
    answers get written to the log.
    """
    return _sse(lambda: ai_service.business_prompt(db, body.question),
                log_for=user, db=db, question=body.question)


def _sse(build, *, log_for: User | None = None, question: str = "",
         db: Session | None = None):
    """Stream whatever `build()` returns as server-sent events.

    `build` is a callable returning `(system, prompt)`. It is called *inside* the
    generator on purpose: gathering the context is the slow part — a patient's
    medication history, a ticket thread, an account's deals, and doing it before
    the response begins means the screen sits blank for the part of the wait the
    operator most needs explained. Inside, the `reading` phase is already on
    screen while it happens.

    Every AI surface goes through here rather than repeating the frame protocol.
    The first version of streaming existed only on the assistant, and the other
    six surfaces each blocked until the whole answer arrived — twelve seconds of
    nothing, which reads as a system that has hung. A pharmacist reaches for the
    back button at about second five.

    Frames are JSON objects, never bare text: a delta containing a blank line
    would otherwise look like the end of an event and the answer would truncate
    at the first paragraph break.
    """
    def frames():
        yield "data: " + json.dumps({"type": "phase", "phase": "reading"}) + "\n\n"
        written: list[str] = []
        try:
            system, prompt = build()
            yield "data: " + json.dumps({"type": "phase", "phase": "thinking"}) + "\n\n"
            for delta in ai_service.stream_claude(system, prompt):
                written.append(delta)
                yield "data: " + json.dumps({"type": "delta", "text": delta}) + "\n\n"
        except Exception as exc:  # noqa: BLE001 - the client needs the reason
            yield "data: " + json.dumps({"type": "error", "message": str(exc)}) + "\n\n"

        # Logged after the answer is delivered, and never at the cost of it.
        # A failure to write the history entry must not turn a finished answer
        # into an error frame: the reader already has the text.
        entry_id = None
        answer = "".join(written).strip()
        if answer and log_for is not None and db is not None:
            try:
                entry = AiConversation(
                    user_id=log_for.id, question=question or "(no question)",
                    answer=answer, model=ai_service.model_name(),
                )
                db.add(entry)
                db.commit()
                entry_id = entry.id
            except Exception:  # noqa: BLE001 - never break a delivered answer
                db.rollback()
        yield "data: " + json.dumps({"type": "done", "id": entry_id}) + "\n\n"

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Nginx buffers proxied responses by default, which turns a stream
            # back into one long wait and makes the whole endpoint pointless.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/interaction-check/stream")
def interaction_check_stream(body: schemas.AIInteractionRequest,
                             db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    """The clinical second opinion, written as it is thought.

    The deterministic screen in `/api/dispensing/interaction-screen` is the one
    that runs on every basket change and gates the dispense. This is the wider
    read: it sees the whole medication history, the allergies and the chronic
    conditions, and it is advisory. Both are on the same screen and they are
    labelled differently on purpose.
    """
    patient = db.get(Patient, body.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    products = db.query(Product).filter(Product.id.in_(body.product_ids)).all()
    if not products:
        raise HTTPException(status_code=400, detail="No products to check")
    return _sse(lambda: ai_service.interaction_check_prompt(db, patient, products),
                log_for=user, db=db,
                question=f"Interaction check for {patient.first_name} {patient.last_name}: "
                         + ", ".join(p.name for p in products))


@router.post("/patient-summary/{patient_id}/stream")
def patient_summary_stream(patient_id: int, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return _sse(lambda: ai_service.patient_summary_prompt(db, patient),
                log_for=user, db=db,
                question=f"Hand-over summary for {patient.first_name} {patient.last_name}")


@router.post("/counseling/{product_id}/stream")
def counseling_stream(product_id: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _sse(lambda: ai_service.counseling_notes_prompt(product),
                log_for=user, db=db,
                question=f"Counselling points for {product.name}")


@router.post("/campaign-copy/stream")
def campaign_copy_stream(body: CampaignCopyRequest,
                         db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    return _sse(lambda: ai_service.campaign_copy_prompt(
                    body.name, body.channel, body.segment_label, body.goal),
                log_for=user, db=db,
                question=f"Campaign copy for {body.name} ({body.channel})")


@router.post("/ticket-reply/{ticket_id}/stream")
def ticket_reply_stream(ticket_id: int, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return _sse(lambda: ai_service.ticket_reply_prompt(ticket, ticket.messages),
                log_for=user, db=db,
                question=f"Reply draft for ticket {ticket.ticket_number}: {ticket.subject}")


@router.post("/account-summary/{company_id}/stream")
def account_summary_stream(company_id: int, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    deals = db.query(Deal).filter(Deal.company_id == company_id).all()
    tickets = db.query(Ticket).filter(Ticket.company_id == company_id).all()
    return _sse(lambda: ai_service.account_summary_prompt(
                    db, company, deals, tickets, company.contacts),
                log_for=user, db=db,
                question=f"Account review for {company.name}")


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
