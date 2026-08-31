from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .. import helpers
from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..services import paging
from ..models import FiscalDay, FiscalReceipt, Patient, Sale, User
from ..services import claims_engine, fiscal, fiscal_devices
from .periods_router import require_step_up

router = APIRouter(prefix="/api/fiscal", tags=["fiscal"],
                   dependencies=[Depends(get_current_user)])


@router.get("/status")
def status(db: Session = Depends(get_db)):
    """Whether this till is fiscally compliant right now."""
    day = fiscal.current_day(db)
    queued = db.query(FiscalReceipt).filter(FiscalReceipt.status == "queued").count()
    rejected = db.query(FiscalReceipt).filter(FiscalReceipt.status == "rejected").count()
    device = fiscal.device()
    return {
        "required": fiscal.is_required(),
        "regime": settings.jurisdiction.fiscalisation,
        # ZIMRA publishes no driver to install: compliance is reached by one of
        # several routes, and which one this till is on is a decision the
        # pharmacy makes before RX5000 arrives. Say plainly who files.
        "route": fiscal_devices.route_for(device.name),
        "routes_available": fiscal_devices.ROUTES,
        "device": device.status(),
        "open_day": None if not day else {
            "id": day.id, "day_number": day.day_number, "opened_at": day.opened_at,
            "receipt_count": day.receipt_count, "total_sales": day.total_sales,
            "total_vat": day.total_vat, "total_credit_notes": day.total_credit_notes,
        },
        "queued_receipts": queued,
        "rejected_receipts": rejected,
        "chain": fiscal.verify_chain(db),
    }


@router.post("/day/open")
def open_day(db: Session = Depends(get_db)):
    day = fiscal.open_day(db)
    return {"id": day.id, "day_number": day.day_number, "opened_at": day.opened_at,
            "status": day.status}


@router.post("/day/close")
def close_day(db: Session = Depends(get_db)):
    """Close the open day and file its Z-report."""
    try:
        day = fiscal.close_day(db)
    except fiscal.FiscalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": day.id, "day_number": day.day_number, "status": day.status,
        "closed_at": day.closed_at, "receipt_count": day.receipt_count,
        "total_sales": day.total_sales, "total_vat": day.total_vat,
        "total_credit_notes": day.total_credit_notes,
        "response_ref": day.response_ref, "error": day.error,
    }


@router.get("/days")
def list_days(limit: int = 60, db: Session = Depends(get_db)):
    days = db.query(FiscalDay).order_by(desc(FiscalDay.day_number)).limit(limit).all()
    return [{
        "id": d.id, "day_number": d.day_number, "status": d.status,
        "opened_at": d.opened_at, "closed_at": d.closed_at,
        "receipt_count": d.receipt_count, "total_sales": d.total_sales,
        "total_vat": d.total_vat, "total_credit_notes": d.total_credit_notes,
        "response_ref": d.response_ref, "error": d.error,
    } for d in days]


def _receipt_row(r):
    return {
        "id": r.id, "sale_id": r.sale_id, "receipt_type": r.receipt_type,
        "receipt_counter": r.receipt_counter, "global_counter": r.global_counter,
        "currency_code": r.currency_code, "total": r.total, "vat_amount": r.vat_amount,
        "receipt_hash": r.receipt_hash, "previous_hash": r.previous_hash,
        "status": r.status, "attempts": r.attempts, "submitted_at": r.submitted_at,
        "response_code": r.response_code, "response_message": r.response_message,
        "verification_url": r.verification_url, "created_at": r.created_at,
        "reverses_receipt_id": r.reverses_receipt_id,
    }


@router.get("/days/{day_id}")
def z_report(day_id: int, db: Session = Depends(get_db)):
    """One fiscal day in full — the Z-report, and the chain across it.

    Registered above /receipts, which is a different path entirely, but kept
    beside /days so the two read together.
    """
    try:
        return fiscal.z_report(db, day_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/receipts")
def list_receipts(status_filter: str = "", sale_id: int = 0, limit: int = 200,
                  db: Session = Depends(get_db)):
    """Filed receipts. `sale_id` narrows it to one sale.

    A sale screen has to know whether the sale was fiscalised before it can
    offer the right way to reverse it: a receipt filed with the authority can
    never be withdrawn, only credited.
    """
    query = db.query(FiscalReceipt)
    if sale_id:
        query = query.filter(FiscalReceipt.sale_id == sale_id)
    if status_filter:
        query = query.filter(FiscalReceipt.status == status_filter)
    receipts = query.order_by(desc(FiscalReceipt.global_counter)).limit(limit).all()
    return [_receipt_row(r) for r in receipts]


@router.get("/receipts/paged")
def list_receipts_paged(status_filter: str = "", receipt_type: str = "",
                        page: int = 1,
                        per_page: int = paging.DEFAULT_PER_PAGE,
                        db: Session = Depends(get_db)):
    """Fiscal receipts, paged. 1,635 behind a cap of 200.

    These are the records ZIMRA can ask to see, and the hash chain that links
    them only means anything if you can walk the whole of it. A view that stops
    at the newest 200 cannot answer a question about last month.
    """
    query = db.query(FiscalReceipt)
    if status_filter:
        query = query.filter(FiscalReceipt.status == status_filter)
    # Credit notes are what an auditor asks about first, and finding them by
    # eye in a list of several thousand receipts is not a search.
    if receipt_type:
        query = query.filter(FiscalReceipt.receipt_type == receipt_type)
    result = paging.page(query.order_by(desc(FiscalReceipt.global_counter)),
                         page=page, per_page=per_page)
    return result.envelope(_receipt_row)


@router.post("/flush")
def flush(db: Session = Depends(get_db)):
    """Re-file everything that queued while the authority was unreachable."""
    return fiscal.flush_queue(db)


# Walking the hash chain used to be its own route. /fiscal/status computes it
# and returns it under "chain", which is what the fiscal screen reads and where
# the alarm is raised — so this was the same walk, reachable twice, with only
# one of the two ever looked at.

@router.post("/credit-note/{sale_id}")
def credit_note(sale_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user),
                _grant=Depends(require_step_up("sale.void"))):
    """Reverse a filed sale. A fiscalised receipt can never be withdrawn."""
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    original = fiscal.receipt_for(db, sale_id)
    if not original:
        raise HTTPException(status_code=400, detail="This sale has no fiscal receipt")
    existing = (
        db.query(FiscalReceipt)
        .filter(FiscalReceipt.reverses_receipt_id == original.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400,
                            detail=f"Already reversed by credit note {existing.global_counter}")
    note = fiscal.fiscalise(db, sale, receipt_type="credit_note", reverses=original)

    # A credit note is not only a fiscal document — it is the sale coming back.
    # Where fiscalisation is in force it is the *only* way to reverse a filed
    # sale, so everything a void would undo has to be undone here too, or the
    # goods stay sold in inventory while the revenue authority has been told
    # they were returned.
    helpers.return_sale_stock(db, sale, user.id, reference=f"CREDIT NOTE {note.global_counter}")
    if sale.claim and sale.claim.status in ("approved", "partial"):
        claims_engine.reverse_claim(db, sale.claim)
    if sale.patient_id:
        patient = db.get(Patient, sale.patient_id)
        if patient:
            patient.loyalty_points = max(
                0, patient.loyalty_points - sale.loyalty_points_earned
                + sale.loyalty_points_redeemed)
    # Not "void": the original receipt stands and is still reported. The sale is
    # reversed, which is a different thing, and reports must be able to tell them
    # apart.
    sale.status = "credited"
    db.commit()

    return {"credit_note": note.global_counter, "reverses": original.global_counter,
            "status": note.status, "total": note.total, "sale_status": sale.status,
            "stock_returned": True}
