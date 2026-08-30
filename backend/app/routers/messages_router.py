"""Counter messages, and reprints."""
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..services import paging
from ..models import (
    CounterMessage as Message, Prescription, Reprint, Sale, User,
)
from ..services import messages

router = APIRouter(prefix="/api", tags=["messages"],
                   dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@router.get("/counter-messages/for-dispensing")
def for_dispensing(patient_id: int = 0, medical_aid_id: int = 0, doctor_id: int = 0,
                   product_ids: list[int] = Query(default=[]),
                   db: Session = Depends(get_db)):
    """Everything the pharmacist must see about this patient and these products.

    One call, because a screen that needs five requests to assemble a warning
    will show it late or not at all.
    """
    return messages.for_dispensing(
        db, patient_id=patient_id or None, product_ids=list(product_ids),
        medical_aid_id=medical_aid_id or None, doctor_id=doctor_id or None)


def _message_row(m):
    return {
        "id": m.id, "scope": m.scope, "target_id": m.target_id,
        "severity": m.severity, "category": m.category, "body": m.body,
        "active": m.active, "expires_on": m.expires_on,
        "created_at": m.created_at,
        "created_by": m.created_by.full_name if m.created_by else "",
    }


def _message_query(db, scope, target_id, severity, active_only):
    query = db.query(Message)
    if scope:
        query = query.filter(Message.scope == scope)
    if target_id:
        query = query.filter(Message.target_id == target_id)
    if severity:
        query = query.filter(Message.severity == severity)
    if active_only:
        query = query.filter(Message.active.is_(True))
    return query.order_by(desc(Message.created_at))


# GET /counter-messages was here, unpaged. /counter-messages/paged replaced
# it and is what the admin screen reads.


@router.get("/counter-messages/paged")
def list_messages_paged(scope: str = "", target_id: int = 0, severity: str = "",
                        active_only: bool = True, page: int = 1,
                        per_page: int = paging.DEFAULT_PER_PAGE,
                        db: Session = Depends(get_db)):
    """Counter messages, paged. 7,001 behind a cap of 200."""
    result = paging.page(_message_query(db, scope, target_id, severity, active_only),
                         page=page, per_page=per_page)
    return result.envelope(_message_row)


@router.post("/counter-messages")
def create_message(scope: str = Body(...), body: str = Body(...),
                   target_id: int | None = Body(default=None),
                   severity: str = Body(default="info"),
                   category: str = Body(default=""),
                   expires_on: date | None = Body(default=None),
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    if severity not in messages.SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"'{severity}' is not a severity, use"
                   f"{', '.join(messages.SEVERITIES)}.")
    if scope not in ("patient", "member", "scheme", "product", "doctor"):
        raise HTTPException(status_code=400, detail=f"'{scope}' is not a message scope.")
    if not (body or "").strip():
        raise HTTPException(status_code=400, detail="A message needs a body.")
    record = Message(scope=scope, target_id=target_id, severity=severity,
                     category=category, body=body.strip(), expires_on=expires_on,
                     created_by_id=user.id)
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "scope": record.scope, "severity": record.severity,
            "body": record.body, "target_id": record.target_id}


@router.post("/counter-messages/{message_id}/retire")
def retire(message_id: int, db: Session = Depends(get_db)):
    """Stop showing a message. Retired rather than deleted — it was shown to
    somebody, and why it was shown may be asked about later."""
    record = db.get(Message, message_id)
    if not record:
        raise HTTPException(status_code=404, detail="Message not found")
    record.active = False
    db.commit()
    return {"id": record.id, "active": record.active}


@router.post("/counter-messages/{message_id}/acknowledge")
def acknowledge(message_id: int, prescription_id: int = Body(..., embed=True),
                note: str = Body(default="", embed=True),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Take responsibility for proceeding past a blocking message, by name."""
    # A negative id is a derived warning (an allergy match), which has no stored
    # row but still has to be acknowledgeable — otherwise the script can never
    # be dispensed.
    if message_id > 0 and not db.get(Message, message_id):
        raise HTTPException(status_code=404, detail="Message not found")
    ack = messages.acknowledge(db, message_id=message_id,
                               prescription_id=prescription_id,
                               user_id=user.id, note=note)
    return {"acknowledged": True, "message_id": message_id,
            "prescription_id": prescription_id,
            "by": user.full_name, "at": ack.acknowledged_at}


# ---------------------------------------------------------------------------
# Reprints
# ---------------------------------------------------------------------------

@router.post("/reprints")
def reprint(kind: str = Body(...), prescription_id: int | None = Body(default=None),
            sale_id: int | None = Body(default=None),
            reason: str = Body(default=""),
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Reprint a script or its labels, and record that it happened.

    A second label for a controlled substance is the easiest way to make one
    dispensing look like two, so the reprint is recorded rather than merely
    performed. The record costs nothing and answers the question later.
    """
    if kind not in ("script", "label"):
        raise HTTPException(status_code=400, detail="Reprint kind is 'script' or 'label'.")
    if not prescription_id and not sale_id:
        raise HTTPException(status_code=400,
                            detail="A reprint needs a prescription or a sale.")
    rx = db.get(Prescription, prescription_id) if prescription_id else None
    if prescription_id and not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if rx and rx.status == "draft":
        raise HTTPException(status_code=400,
                            detail="An unfinished script has nothing to reprint.")
    if sale_id and not db.get(Sale, sale_id):
        raise HTTPException(status_code=404, detail="Sale not found")

    record = Reprint(kind=kind, prescription_id=prescription_id, sale_id=sale_id,
                     reason=reason[:200], printed_by_id=user.id)
    db.add(record)
    db.commit()
    db.refresh(record)

    payload = {"reprint_id": record.id, "kind": kind,
               "printed_by": user.full_name, "printed_at": record.printed_at,
               "previously_printed": db.query(Reprint).filter(
                   Reprint.prescription_id == prescription_id,
                   Reprint.kind == kind).count() if prescription_id else 0}
    if rx:
        payload["rx_number"] = rx.rx_number
        payload["labels"] = [{
            "patient_name": f"{rx.patient.first_name} {rx.patient.last_name}".strip(),
            "product_name": f"{i.product.name} {i.product.strength}".strip(),
            "quantity": i.quantity,
            "directions": i.dosage_instructions,
            "rx_number": rx.rx_number,
            "repeats_remaining": max(0, (i.repeats_allowed or 0) - (i.repeats_used or 0)),
        } for i in rx.items]
    return payload


@router.get("/reprints")
def reprint_log(prescription_id: int = 0, kind: str = "", limit: int = 100,
                db: Session = Depends(get_db)):
    """What has been reprinted, by whom. Read when a count does not add up."""
    query = db.query(Reprint)
    if prescription_id:
        query = query.filter(Reprint.prescription_id == prescription_id)
    if kind:
        query = query.filter(Reprint.kind == kind)
    rows = query.order_by(desc(Reprint.printed_at)).limit(limit).all()
    return [{
        "id": r.id, "kind": r.kind, "prescription_id": r.prescription_id,
        "rx_number": r.prescription.rx_number if r.prescription else "",
        "sale_id": r.sale_id, "reason": r.reason,
        "printed_by": r.printed_by.full_name if r.printed_by else "",
        "printed_at": r.printed_at,
    } for r in rows]
