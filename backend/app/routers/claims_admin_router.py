"""Pre-authorisation and electronic remittance advice.

Two halves of the same problem: knowing what the funder will pay before
dispensing, and knowing what it actually paid afterwards.
"""
import time
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Authorisation, Remittance, RemittanceLine, User
from ..services import authorisation as auth_service
from ..services import era, gateway

router = APIRouter(prefix="/api", tags=["claims-admin"],
                   dependencies=[Depends(get_current_user)])


def _fail(exc: gateway.GatewayError) -> HTTPException:
    detail = {"error_code": exc.code, "message": exc.detail}
    return HTTPException(status_code=exc.http_status, detail=detail)


# ---------------------------------------------------------------------------
# Pre-authorisation
# ---------------------------------------------------------------------------

@router.post("/authorisations")
def request_authorisation(body: schemas.AuthorisationRequest,
                          db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    """Ask the funder to commit, and record the answer with its limits."""
    started = time.monotonic()
    txn = gateway.new_transaction_id()
    payload = body.model_dump()

    try:
        funder = gateway.resolve_funder(db, body.funder_id)
        if body.icd10_code:
            gateway.validate_icd10(db, body.icd10_code, required=False)
        adapter = gateway.adapter_for(funder, body.switch_id)
        decision = adapter.authorisation(payload, funder)
    except gateway.GatewayError as exc:
        gateway.record(db, transaction_id=txn, kind="authorisation",
                       funder_id=body.funder_id, switch_id=body.switch_id or "",
                       status="REJECTED", http_status=exc.http_status,
                       error_code=exc.code, request=payload,
                       response={"error": exc.detail}, started=started)
        raise _fail(exc) from exc

    record = Authorisation(
        reference=auth_service.next_reference(db),
        authorisation_number=decision.get("authorisation_number", ""),
        funder_id=funder.funder_id,
        switch_id=adapter.switch_id,
        patient_id=body.patient_id,
        policy_number=body.policy_number,
        dependent_code=body.dependent_code,
        product_id=body.product_id,
        description=body.description,
        icd10_code=(body.icd10_code or "").upper(),
        motivation=body.motivation,
        requested_quantity=body.requested_quantity,
        requested_amount=body.requested_amount,
        approved_quantity=decision.get("approved_quantity") or 0.0,
        approved_amount=decision.get("approved_amount") or 0.0,
        currency_code=(body.currency_code or funder.currency_code or "USD").upper(),
        valid_from=decision.get("valid_from"),
        valid_to=decision.get("valid_to"),
        status=decision.get("status", "requested"),
        decision_reason=decision.get("decision_reason", ""),
        conditions=decision.get("conditions", ""),
        switch_reference=decision.get("switch_reference", ""),
        transaction_id=txn,
        requested_by_id=user.id,
        decided_at=datetime.utcnow() if decision.get("status") else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    gateway.record(db, transaction_id=txn, kind="authorisation", funder_id=funder.funder_id,
                   switch_id=adapter.switch_id, status=record.status.upper(),
                   http_status=200, request=payload, response=decision,
                   switch_ref=record.switch_reference,
                   funder_ref=record.authorisation_number, started=started)
    return auth_service.summarise(db, record)


@router.get("/authorisations")
def list_authorisations(status: str = "", patient_id: int = 0, funder_id: str = "",
                        usable_only: bool = False, limit: int = 100,
                        db: Session = Depends(get_db)):
    query = db.query(Authorisation)
    if status:
        query = query.filter(Authorisation.status == status)
    if patient_id:
        query = query.filter(Authorisation.patient_id == patient_id)
    if funder_id:
        query = query.filter(Authorisation.funder_id == funder_id.strip().upper())
    rows = query.order_by(desc(Authorisation.created_at)).limit(limit).all()
    out = [auth_service.summarise(db, row) for row in rows]
    if usable_only:
        # Expiry and exhaustion are computed, so they cannot be filtered in SQL.
        out = [a for a in out if a["effective_status"] in auth_service.USABLE]
    return out


@router.get("/authorisations/{authorisation_id}")
def get_authorisation(authorisation_id: int, db: Session = Depends(get_db)):
    record = db.get(Authorisation, authorisation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Authorisation not found")
    return auth_service.summarise(db, record)


@router.get("/authorisations/{authorisation_id}/check")
def check_authorisation(authorisation_id: int, quantity: float = 0.0, amount: float = 0.0,
                        db: Session = Depends(get_db)):
    """Can this cover a dispensing of this size, today? The till asks before committing."""
    record = db.get(Authorisation, authorisation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Authorisation not found")
    return auth_service.check(record, quantity, amount)


@router.post("/authorisations/{authorisation_id}/use")
def use_authorisation(authorisation_id: int, body: schemas.AuthorisationUseIn,
                      db: Session = Depends(get_db)):
    """Draw against an authorisation. Refused if it would exceed what was granted."""
    record = db.get(Authorisation, authorisation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Authorisation not found")
    try:
        auth_service.consume(db, record, quantity=body.quantity, amount=body.amount,
                             reference=body.reference, claim_id=body.claim_id)
    except auth_service.AuthorisationError as exc:
        raise HTTPException(status_code=422, detail={
            "error_code": "AUTH_INVALID", "message": str(exc)}) from exc
    return auth_service.summarise(db, record)


@router.post("/authorisations/{authorisation_id}/release")
def release_authorisation(authorisation_id: int, reference: str = "", claim_id: int = 0,
                          db: Session = Depends(get_db)):
    """Give back what a reversed sale had drawn."""
    record = db.get(Authorisation, authorisation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Authorisation not found")
    released = auth_service.release(db, reference=reference,
                                    claim_id=claim_id or None)
    db.refresh(record)
    return {"released": released, **auth_service.summarise(db, record)}


@router.post("/authorisations/{authorisation_id}/cancel")
def cancel_authorisation(authorisation_id: int, db: Session = Depends(get_db)):
    record = db.get(Authorisation, authorisation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Authorisation not found")
    record.status = "cancelled"
    db.commit()
    return auth_service.summarise(db, record)


# ---------------------------------------------------------------------------
# Electronic remittance advice
# ---------------------------------------------------------------------------

@router.post("/remittances/import")
def import_remittance(body: schemas.RemittanceImport, db: Session = Depends(get_db)):
    """Import an advice supplied as structured lines."""
    try:
        advice = era.import_advice(
            db, funder_id=body.funder_id, remittance_number=body.remittance_number,
            payment_reference=body.payment_reference, payment_date=body.payment_date,
            currency_code=body.currency_code,
            lines=[line.model_dump() for line in body.lines],
            source="upload", notes=body.notes)
    except era.RemittanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return era.reconcile(db, advice)


@router.post("/remittances/import-csv")
def import_remittance_csv(body: schemas.RemittanceCsvImport, db: Session = Depends(get_db)):
    """Import an advice supplied as a spreadsheet export — the common case."""
    try:
        lines = era.parse_csv(body.content)
        advice = era.import_advice(
            db, funder_id=body.funder_id, remittance_number=body.remittance_number,
            payment_reference=body.payment_reference, payment_date=body.payment_date,
            currency_code=body.currency_code, lines=lines, source="upload",
            notes=body.notes)
    except era.RemittanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return era.reconcile(db, advice)


@router.post("/remittances/fetch")
def fetch_remittances(funder_id: str, since: date | None = None,
                      db: Session = Depends(get_db)):
    """Pull advices the funder has published on the switch."""
    try:
        funder = gateway.resolve_funder(db, funder_id)
        adapter = gateway.adapter_for(funder)
        advices = adapter.remittance_advice(db, funder, since)
    except gateway.GatewayError as exc:
        raise _fail(exc) from exc

    imported, skipped = [], []
    for advice in advices:
        try:
            record = era.import_advice(
                db, funder_id=advice["funder_id"],
                remittance_number=advice["remittance_number"],
                payment_reference=advice.get("payment_reference", ""),
                payment_date=advice.get("payment_date"),
                currency_code=advice.get("currency_code", "USD"),
                lines=advice["lines"], source="switch")
            imported.append(era.reconcile(db, record))
        except era.RemittanceError as exc:
            # Re-fetching is normal; an already-imported advice is not an error.
            skipped.append({"remittance_number": advice["remittance_number"],
                            "reason": str(exc)})
    return {"fetched": len(advices), "imported": imported, "skipped": skipped}


@router.get("/remittances")
def list_remittances(funder_id: str = "", status: str = "", limit: int = 100,
                     db: Session = Depends(get_db)):
    query = db.query(Remittance)
    if funder_id:
        query = query.filter(Remittance.funder_id == funder_id.strip().upper())
    if status:
        query = query.filter(Remittance.status == status)
    rows = query.order_by(desc(Remittance.created_at)).limit(limit).all()
    return [era.reconcile(db, row) for row in rows]


@router.get("/remittances/outstanding")
def outstanding(funder_id: str = "", limit: int = 200, db: Session = Depends(get_db)):
    """Every shortfall not yet billed or written off — the money still in the air."""
    lines = era.outstanding_lines(db, funder_id, limit)
    count, total = era.outstanding_totals(db, funder_id)
    return {
        # Over everything open, not over the page. The list below is capped.
        "count": count,
        "total": total,
        "showing": len(lines),
        "lines": [{
            "id": l.id, "remittance_id": l.remittance_id,
            "remittance_number": l.remittance.remittance_number if l.remittance else "",
            "funder_id": l.remittance.funder_id if l.remittance else "",
            "claim_reference": l.claim_reference, "policy_number": l.policy_number,
            "member_name": l.member_name, "service_date": l.service_date,
            "amount_claimed": l.amount_claimed, "amount_paid": l.amount_paid,
            "variance": l.variance, "reason_code": l.reason_code, "reason": l.reason,
            "status": l.status, "claim_id": l.claim_id,
        } for l in lines],
    }


@router.get("/remittances/{remittance_id}")
def get_remittance(remittance_id: int, db: Session = Depends(get_db)):
    advice = db.get(Remittance, remittance_id)
    if not advice:
        raise HTTPException(status_code=404, detail="Remittance not found")
    return {
        **era.reconcile(db, advice),
        "id": advice.id,
        "lines": [{
            "id": l.id, "line_number": l.line_number, "claim_reference": l.claim_reference,
            "policy_number": l.policy_number, "member_name": l.member_name,
            "service_date": l.service_date, "amount_claimed": l.amount_claimed,
            "amount_allowed": l.amount_allowed, "amount_paid": l.amount_paid,
            "variance": l.variance, "reason_code": l.reason_code, "reason": l.reason,
            "status": l.status, "claim_id": l.claim_id,
            "gateway_transaction_id": l.gateway_transaction_id,
            "written_off": l.written_off, "patient_billed": l.patient_billed,
            "resolution_note": l.resolution_note or "",
        } for l in sorted(advice.lines, key=lambda x: x.line_number)],
    }


@router.post("/remittances/lines/{line_id}/resolve")
def resolve(line_id: int, action: str, note: str = "", db: Session = Depends(get_db)):
    """Send a shortfall to the patient or to the write-off account."""
    line = db.get(RemittanceLine, line_id)
    if not line:
        raise HTTPException(status_code=404, detail="Remittance line not found")
    try:
        era.resolve_line(db, line, action, note)
    except era.RemittanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": line.id, "status": line.status, "variance": line.variance,
            "written_off": line.written_off, "patient_billed": line.patient_billed,
            "resolution_note": line.resolution_note or "",
            "reason": line.reason}


@router.get("/remittances/reasons/vocabulary")
def reason_vocabulary():
    """The normalised adjustment reasons, so a caller can code against them."""
    return [{"reason_code": code, "meaning": meaning}
            for code, meaning in sorted(era.REASONS.items())]
