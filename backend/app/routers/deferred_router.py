"""Claims held at the counter, waiting to be sent."""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user
from ..database import get_db
from ..models import Claim, User
from ..services import claims_engine

router = APIRouter(prefix="/api/claims", tags=["deferred-claims"],
                   dependencies=[Depends(get_current_user)])


def _row(claim: Claim) -> dict:
    return {
        "id": claim.id,
        "claim_number": claim.claim_number,
        "sale_id": claim.sale_id,
        "sale_number": claim.sale.sale_number if claim.sale else "",
        "patient_id": claim.patient_id,
        "patient_name": (f"{claim.patient.first_name} {claim.patient.last_name}".strip()
                         if claim.patient else ""),
        "medical_aid": claim.medical_aid.name if claim.medical_aid else "",
        "amount_claimed": claim.amount_claimed,
        "amount_approved": claim.amount_approved,
        "patient_liable": claim.patient_liable,
        "status": claim.status,
        "deferred_reason": claim.deferred_reason,
        "deferred_at": claim.deferred_at,
        "submitted_at": claim.submitted_at,
        "submit_attempts": claim.submit_attempts,
        "response_message": claim.response_message,
        "created_at": claim.created_at,
    }


@router.get("/deferred")
def deferred(limit: int = 200, db: Session = Depends(get_db)):
    """Claims held rather than sent.

    This is a work queue, not a report. Every row is money the pharmacy has
    dispensed against and not yet asked anybody for, and it stays here until
    somebody sends it, which is exactly why it has to be visible.
    """
    # `_row` names the sale, the patient and the scheme, and all three were
    # fetched one row at a time — thirty held claims cost sixty-five queries.
    rows = (db.query(Claim)
            .options(joinedload(Claim.sale), joinedload(Claim.patient),
                     joinedload(Claim.medical_aid))
            .filter(Claim.status == "deferred")
            .order_by(Claim.created_at).limit(limit).all())
    return [_row(c) for c in rows]


@router.get("/deferred/summary")
def deferred_summary(db: Session = Depends(get_db)):
    count, total = (db.query(func.count(Claim.id),
                             func.coalesce(func.sum(Claim.amount_claimed), 0.0))
                    .filter(Claim.status == "deferred").one())
    oldest = (db.query(Claim).filter(Claim.status == "deferred")
              .order_by(Claim.created_at).first())
    return {
        "held": count,
        "value_held": round(total, 2),
        "oldest_held_at": oldest.created_at if oldest else None,
        "message": ("" if not count else
                    f"{count} claim(s) worth {total:.2f} have been dispensed against "
                    "and not submitted."),
    }


@router.post("/{claim_id}/submit")
def submit(claim_id: int, db: Session = Depends(get_db),
           _user: User = Depends(get_current_user)):
    """Send a held claim. The adjudication is the ordinary one."""
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    try:
        claims_engine.submit_deferred(db, claim)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _row(claim)


@router.post("/deferred/submit-all")
def submit_all(limit: int = Body(default=200, embed=True),
               db: Session = Depends(get_db)):
    """Send everything that is held — what a pharmacy does once the switch is back.

    One failure does not stop the rest: a claim that cannot be sent stays held
    and is reported, rather than aborting the run and leaving the queue in a
    state nobody can reason about.
    """
    rows = (db.query(Claim).filter(Claim.status == "deferred")
            .order_by(Claim.created_at).limit(limit).all())
    sent, failed = [], []
    for claim in rows:
        try:
            claims_engine.submit_deferred(db, claim)
            sent.append(_row(claim))
        except Exception as exc:                                # noqa: BLE001
            failed.append({"claim_number": claim.claim_number, "reason": str(exc)[:160]})
    return {"attempted": len(rows), "submitted": len(sent),
            "still_held": len(failed), "sent": sent, "failed": failed}
