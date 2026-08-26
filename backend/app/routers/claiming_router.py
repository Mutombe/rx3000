import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from .. import helpers, icd10, schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import (
    Claim, ClaimBatch, DiagnosisCode, FeeModel, FeeTier, Formulary,
    FormularyEntry, MedicalAid, PayOffice, Product, User,
)
from ..services import formulary as formulary_service, pricing
from .periods_router import require_step_up

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/claiming", tags=["claiming"],
                   dependencies=[Depends(get_current_user)])


# ---------- ICD-10 ----------
@router.get("/diagnoses", response_model=list[schemas.DiagnosisCodeOut])
def search_diagnoses(q: str = "", chapter: str = "", limit: int = 30,
                     db: Session = Depends(get_db)):
    """Type-ahead over ICD-10. Matches on code prefix or description.

    `chapter` narrows to one body system, given as a range like "J00-J99".
    """
    query = db.query(DiagnosisCode).filter(DiagnosisCode.active)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            DiagnosisCode.code.ilike(f"{q.strip()}%"),
            DiagnosisCode.description.ilike(like),
        ))
    rows = query.order_by(DiagnosisCode.code).limit(limit).all()
    if chapter:
        rows = [r for r in rows if icd10.in_chapter(r.code, chapter)]
    return rows


@router.get("/diagnoses/chapters")
def diagnosis_chapters():
    """The ICD-10 chapter structure.

    Published so a picker can browse by body system instead of demanding the
    user already know the code — which is the difference between a searchable
    reference and a field you have to guess at.
    """
    return icd10.chapters()


@router.get("/diagnoses/validate")
def validate_diagnosis(code: str, db: Session = Depends(get_db)):
    """What is knowable about a code, without pretending the local table is the WHO release.

    Returns a verdict rather than a 404, because "we do not hold a description
    for this" and "this is not a real code" are completely different answers and
    a pharmacist needs to be able to tell them apart.
    """
    verdict = icd10.classify(code)
    found = None
    if verdict["valid_structure"] and verdict["chapter"]:
        found = (db.query(DiagnosisCode)
                 .filter(DiagnosisCode.code == icd10.normalise(code)).first())
    return {
        **verdict,
        "acceptable": bool(verdict["valid_structure"] and verdict["chapter"]
                           and (found is None or found.active)),
        "in_local_table": found is not None,
        "description": found.description if found else "",
        "active": found.active if found else None,
        "note": ("" if found else
                 "This code is well formed and sits in a real ICD-10 chapter, but "
                 "no description is held locally. The local table is a subset of "
                 "the WHO release, not the whole of it, so the code is accepted."),
    }


@router.get("/diagnoses/{code}", response_model=schemas.DiagnosisCodeOut)
def get_diagnosis(code: str, db: Session = Depends(get_db)):
    found = db.query(DiagnosisCode).filter(DiagnosisCode.code == code.upper()).first()
    if not found:
        raise HTTPException(status_code=404, detail=f"ICD-10 code {code} not found")
    return found


# ---------- pay offices ----------
@router.get("/pay-offices", response_model=list[schemas.PayOfficeOut])
def list_pay_offices(db: Session = Depends(get_db)):
    return db.query(PayOffice).order_by(PayOffice.name).all()


@router.post("/pay-offices", response_model=schemas.PayOfficeOut)
def create_pay_office(body: schemas.PayOfficeBase, db: Session = Depends(get_db)):
    if db.query(PayOffice).filter(PayOffice.code == body.code.upper()).first():
        raise HTTPException(status_code=400, detail=f"Pay office {body.code} already exists")
    office = PayOffice(**{**body.model_dump(), "code": body.code.upper()})
    db.add(office)
    db.commit()
    db.refresh(office)
    return office


# ---------- fee models ----------
@router.get("/fee-models", response_model=list[schemas.FeeModelOut])
def list_fee_models(db: Session = Depends(get_db)):
    return db.query(FeeModel).order_by(FeeModel.name).all()


@router.post("/fee-models", response_model=schemas.FeeModelOut)
def create_fee_model(body: schemas.FeeModelCreate, db: Session = Depends(get_db)):
    if db.query(FeeModel).filter(FeeModel.code == body.code.upper()).first():
        raise HTTPException(status_code=400, detail=f"Fee model {body.code} already exists")
    if not body.tiers:
        raise HTTPException(status_code=400, detail="A fee model needs at least one price band")
    open_ended = [t for t in body.tiers if t.up_to is None]
    if len(open_ended) > 1:
        raise HTTPException(status_code=400,
                            detail="Only one band may be open-ended (no ceiling)")
    model = FeeModel(**{**body.model_dump(exclude={"tiers"}), "code": body.code.upper()})
    db.add(model)
    db.flush()
    for tier in body.tiers:
        db.add(FeeTier(fee_model_id=model.id, **tier.model_dump()))
    db.commit()
    db.refresh(model)
    return model


class FeeModelPatch(BaseModel):
    """A change to an existing fee model.

    Separate from FeeModelCreate, and partial, because the two are different
    acts. Creating asks for the bands; changing one usually means flipping a
    single switch, and a payload that had to restate every band would let a
    stale screen flatten the pricing of every future claim while the user
    thought they were ticking a box.

    Bands are deliberately not editable here. Renegotiating them is a new model,
    so that claims priced under the old one keep something to point at.
    """
    name: Optional[str] = None
    basis: Optional[str] = None
    vat_on_fee: Optional[bool] = None
    apply_mmap: Optional[bool] = None
    notes: Optional[str] = None
    active: Optional[bool] = None


@router.patch("/fee-models/{model_id}", response_model=schemas.FeeModelOut)
def update_fee_model(
    model_id: int, body: FeeModelPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _grant=Depends(require_step_up("scheme.edit")),
):
    """Change a fee model.

    There was no way to change one at all: POST creates and refuses a duplicate
    code, so `apply_mmap` — the switch that caps a scheme's charge at the
    published reference price — could only ever be set when the model was first
    created. The cap has been in pricing.py the whole time, reading a field that
    nothing populated and a flag nobody could turn on.

    Behind the same authority as a scheme's terms, because it is the same kind of
    change: it reprices every claim made afterwards, and nothing on a receipt
    says which model produced the figure.
    """
    model = db.get(FeeModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="That fee model no longer exists.")

    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing was sent to change.")

    before = {field: getattr(model, field) for field in changes}
    for field, value in changes.items():
        setattr(model, field, value)
    db.commit()
    db.refresh(model)
    log.info("fee_model.changed model=%s by=%s from=%s to=%s",
             model.code, user.username, before, changes)
    return model


@router.get("/fee-models/{model_id}/quote")
def quote_fee(model_id: int, base: float, db: Session = Depends(get_db)):
    """What this model charges on a given base price, used to sanity-check bands."""
    model = db.get(FeeModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Fee model not found")
    fee = pricing.professional_fee(model, base)
    return {"base": base, "fee": fee, "total": round(base + fee, 2),
            "model": model.code, "basis": model.basis}


# ---------- pricing ----------
@router.post("/price", response_model=schemas.PricedBasket)
def price(body: schemas.PriceRequest, db: Session = Depends(get_db)):
    """Price a basket for a scheme. The derived price a claim will carry."""
    scheme = db.get(MedicalAid, body.medical_aid_id) if body.medical_aid_id else None
    if body.medical_aid_id and not scheme:
        raise HTTPException(status_code=404, detail="Medical aid not found")
    lines = []
    for item in body.items:
        product = db.get(Product, item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        lines.append((product, item.quantity))
    if not lines:
        raise HTTPException(status_code=400, detail="Nothing to price")
    return pricing.price_basket(db, lines, scheme)


# ---------- formulary ----------
@router.get("/formularies", response_model=list[schemas.FormularyOut])
def list_formularies(db: Session = Depends(get_db)):
    return db.query(Formulary).order_by(Formulary.name).all()


@router.post("/formularies", response_model=schemas.FormularyOut)
def create_formulary(body: schemas.FormularyCreate, db: Session = Depends(get_db)):
    if db.query(Formulary).filter(Formulary.code == body.code.upper()).first():
        raise HTTPException(status_code=400, detail=f"Formulary {body.code} already exists")
    if body.default_rule not in ("covered", "excluded"):
        raise HTTPException(status_code=400,
                            detail="default_rule must be 'covered' (open) or 'excluded' (closed)")
    formulary = Formulary(**{**body.model_dump(), "code": body.code.upper()})
    db.add(formulary)
    db.commit()
    db.refresh(formulary)
    return formulary


@router.get("/formularies/{formulary_id}/entries", response_model=list[schemas.FormularyEntryOut])
def list_entries(formulary_id: int, status_filter: str = "", limit: int = 500,
                 db: Session = Depends(get_db)):
    query = db.query(FormularyEntry).filter(FormularyEntry.formulary_id == formulary_id)
    if status_filter:
        query = query.filter(FormularyEntry.status == status_filter)
    return query.limit(limit).all()


@router.post("/formularies/{formulary_id}/entries", response_model=schemas.FormularyEntryOut)
def upsert_entry(formulary_id: int, body: schemas.FormularyEntryIn,
                 db: Session = Depends(get_db)):
    if not db.get(Formulary, formulary_id):
        raise HTTPException(status_code=404, detail="Formulary not found")
    if not db.get(Product, body.product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    if body.status not in ("covered", "reference", "authorisation", "excluded"):
        raise HTTPException(
            status_code=400,
            detail="status must be covered, reference, authorisation or excluded",
        )
    entry = (
        db.query(FormularyEntry)
        .filter(FormularyEntry.formulary_id == formulary_id,
                FormularyEntry.product_id == body.product_id)
        .first()
    )
    if entry:
        for key, value in body.model_dump().items():
            setattr(entry, key, value)
    else:
        entry = FormularyEntry(formulary_id=formulary_id, **body.model_dump())
        db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/coverage", response_model=schemas.CoverageReport)
def coverage(body: schemas.PriceRequest, db: Session = Depends(get_db)):
    """Check a basket against the scheme's formulary before dispensing it."""
    scheme = db.get(MedicalAid, body.medical_aid_id) if body.medical_aid_id else None
    if body.medical_aid_id and not scheme:
        raise HTTPException(status_code=404, detail="Medical aid not found")
    lines = []
    for item in body.items:
        product = db.get(Product, item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        lines.append((product, item.quantity))
    if not lines:
        raise HTTPException(status_code=400, detail="Nothing to check")
    return formulary_service.check_basket(db, scheme, lines)


# ---------- claim batches ----------
@router.get("/batches", response_model=list[schemas.ClaimBatchOut])
def list_batches(status: str = "", limit: int = 50, db: Session = Depends(get_db)):
    query = db.query(ClaimBatch)
    if status:
        query = query.filter(ClaimBatch.status == status)
    return query.order_by(desc(ClaimBatch.created_at)).limit(limit).all()


@router.post("/batches", response_model=schemas.ClaimBatchOut)
def create_batch(body: schemas.ClaimBatchCreate, db: Session = Depends(get_db),
                 _: User = Depends(get_current_user)):
    """Gather every unbatched claim for a pay office into one submission.

    Realtime schemes settle line by line and are deliberately left out — batching
    them would double-claim.
    """
    office = db.get(PayOffice, body.pay_office_id)
    if not office:
        raise HTTPException(status_code=404, detail="Pay office not found")

    scheme_ids = [s.id for s in office.schemes if not s.realtime]
    if not scheme_ids:
        raise HTTPException(
            status_code=400,
            detail=f"{office.name} has no schemes that claim by batch",
        )

    query = (
        db.query(Claim)
        .filter(Claim.batch_id.is_(None),
                Claim.medical_aid_id.in_(scheme_ids),
                Claim.status.in_(["submitted", "approved", "partial"]))
    )
    if body.date_from:
        query = query.filter(Claim.created_at >= datetime.combine(body.date_from, datetime.min.time()))
    if body.date_to:
        query = query.filter(Claim.created_at <= datetime.combine(body.date_to, datetime.max.time()))
    claims = query.order_by(Claim.created_at).all()
    if not claims:
        raise HTTPException(status_code=400, detail="No unbatched claims for this pay office")

    batch = ClaimBatch(
        batch_number=helpers.next_number(db, ClaimBatch, "BAT", "batch_number"),
        pay_office_id=office.id,
        period_from=claims[0].created_at,
        period_to=claims[-1].created_at,
        claim_count=len(claims),
        total_gross=round(sum(c.gross or c.amount_claimed for c in claims), 2),
        total_discount=round(sum(c.discount for c in claims), 2),
        total_levy=round(sum(c.levy for c in claims), 2),
        total_claimed=round(sum(c.amount_approved for c in claims), 2),
        notes=body.notes,
    )
    db.add(batch)
    db.flush()
    for claim in claims:
        claim.batch_id = batch.id
    db.commit()
    db.refresh(batch)
    return batch


@router.post("/batches/{batch_id}/submit", response_model=schemas.ClaimBatchOut)
def submit_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.get(ClaimBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.status != "open":
        raise HTTPException(status_code=400, detail=f"Batch is already {batch.status}")
    batch.status = "submitted"
    batch.submitted_at = datetime.utcnow()
    db.commit()
    db.refresh(batch)
    return batch


@router.post("/batches/{batch_id}/settle", response_model=schemas.ClaimBatchOut)
def settle_batch(batch_id: int, body: schemas.BatchSettlement, db: Session = Depends(get_db)):
    """Record a remittance against a batch.

    Short payment is the normal case, so the shortfall is reported rather than
    silently absorbed — that difference is what gets queried with the scheme.
    """
    batch = db.get(ClaimBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.status not in ("submitted", "settled"):
        raise HTTPException(status_code=400,
                            detail="Only a submitted batch can be settled")
    batch.total_settled = round(body.amount, 2)
    batch.reference = body.reference
    batch.settled_at = datetime.utcnow()
    batch.status = "settled"
    db.commit()
    db.refresh(batch)
    return batch


@router.get("/batches/{batch_id}", response_model=schemas.ClaimBatchDetail)
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.get(ClaimBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    shortfall = round(batch.total_claimed - batch.total_settled, 2) if batch.settled_at else 0.0
    return {
        "batch": batch,
        "shortfall": shortfall,
        "claims": batch.claims,
    }


@router.get("/unbatched")
def unbatched_summary(db: Session = Depends(get_db)):
    """What is waiting to be claimed, by pay office, the work list."""
    rows = (
        db.query(
            PayOffice.id, PayOffice.name, PayOffice.code,
            func.count(Claim.id), func.coalesce(func.sum(Claim.amount_approved), 0.0),
        )
        .join(MedicalAid, MedicalAid.pay_office_id == PayOffice.id)
        .join(Claim, Claim.medical_aid_id == MedicalAid.id)
        .filter(Claim.batch_id.is_(None), MedicalAid.realtime.is_(False))
        .group_by(PayOffice.id, PayOffice.name, PayOffice.code)
        .all()
    )
    return [
        {"pay_office_id": pid, "pay_office": name, "code": code,
         "claims": count, "value": round(value, 2)}
        for pid, name, code, count, value in rows
    ]
