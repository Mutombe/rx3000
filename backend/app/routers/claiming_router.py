import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session, joinedload

from .. import helpers, icd10, schemas
from ..auth import get_current_user, require_role
from .. import auth
from ..database import get_db
from ..models import (
    Claim, ClaimBatch, DiagnosisCode, FeeModel, FeeTier, Formulary, FormularyEntry, MedicalAid, PayOffice, Product, User,
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
    user already know the code, which is the difference between a searchable
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
# Pricing a basket for a scheme used to live here. /api/quick-price answers the
# same question and is the one the counter uses — it was written for the
# question a patient actually asks, which is what this cost them, and this was
# the same sum reached from the claim engine's side. Two routes returning one
# figure is how they come to disagree.

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
    if not body.items:
        raise HTTPException(status_code=400, detail="Nothing to check")

    # Every product in one query, not one query a line.
    #
    # This runs on every basket change while somebody is dispensing, so a query
    # per line is a round trip per line on the busiest screen in the product:
    # a ten-item script cost thirteen of them, which is about a second of
    # nothing happening on the hosted database, repeated on every keystroke
    # that changes the basket.
    wanted = [i.product_id for i in body.items]
    found = {p.id: p for p in
             db.query(Product).filter(Product.id.in_(wanted)).all()}
    missing = [i for i in wanted if i not in found]
    if missing:
        raise HTTPException(status_code=404,
                            detail=f"Product {missing[0]} not found")
    lines = [(found[i.product_id], i.quantity) for i in body.items]
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
def submit_batch(batch_id: int, db: Session = Depends(get_db),
                                _may=Depends(auth.requires("claims.submit"))):
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


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    """One batch, and every claim inside it — with who each one is for.

    A batch that came back four hundred dollars short is a number nobody can
    act on. The question is always which claims were cut and by how much, and
    answering it needs the patient's name beside the figure: a claim number on
    its own is a reference to something the pharmacist then has to go and look
    up one at a time.

    This returned bare ClaimOut rows, number, amount, status, and no screen
    called it, so a short-paid batch could be seen and never opened.
    """
    batch = db.get(ClaimBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Loaded, not walked. One query for the patients and one for the sales
    # rather than two per claim; a month's batch runs to hundreds of lines.
    claims = (db.query(Claim)
              .filter(Claim.batch_id == batch_id)
              .options(joinedload(Claim.patient), joinedload(Claim.sale))
              .order_by(Claim.id).all())

    settled = bool(batch.settled_at)
    lines = []
    for c in claims:
        # Per claim, the same arithmetic the batch does in total. Only once the
        # batch is settled: a claim that has not been paid yet is not short, it
        # is outstanding, and colouring it red teaches staff to ignore red.
        short = round(c.amount_claimed - c.settled_amount, 2) if settled else 0.0
        lines.append({
            "id": c.id,
            "claim_number": c.claim_number,
            "status": c.status,
            "patient": (f"{c.patient.first_name} {c.patient.last_name}".strip()
                        if c.patient else ""),
            "patient_id": c.patient_id,
            "sale_id": c.sale_id,
            "sale_number": c.sale.sale_number if c.sale else "",
            "gross": round(c.gross, 2),
            "levy": round(c.levy, 2),
            "amount_claimed": round(c.amount_claimed, 2),
            "amount_approved": round(c.amount_approved, 2),
            "settled_amount": round(c.settled_amount, 2),
            "shortfall": short if short > 0.005 else 0.0,
            "patient_liable": round(c.patient_liable, 2),
            "response_message": c.response_message or "",
            "created_at": c.created_at,
        })

    shortfall = round(batch.total_claimed - batch.total_settled, 2) if settled else 0.0
    short_lines = [l for l in lines if l["shortfall"] > 0.005]
    return {
        "batch": schemas.ClaimBatchOut.model_validate(batch),
        "settled": settled,
        "shortfall": shortfall,
        # The difference between what the batch is short overall and what the
        # named lines account for. It should be nought; when it is not, the
        # scheme has deducted something that is not attributable to any single
        # claim, a levy adjustment, an old recovery, and that is worth seeing
        # rather than absorbing into a rounding difference.
        "unattributed": round(shortfall - sum(l["shortfall"] for l in short_lines), 2),
        "short_count": len(short_lines),
        "rejected": len([l for l in lines if l["status"] == "rejected"]),
        # The batch keeps its own count. When it disagrees with the claims
        # actually attached, something detached them — a reversal, a migration
        # from another system, a partial import, and the totals on the batch
        # are then describing claims nobody can see. Reported rather than
        # papered over: a page that shows "5 claims" beside an empty table has
        # told the reader two things and left them to pick.
        "counted_on_batch": batch.claim_count or 0,
        "found": len(lines),
        "claims": lines,
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


def _next_on(day: int, today: date) -> date | None:
    """The next occurrence of a day-of-month, this month or next.

    Clamped to the length of the month, because a funder that settles on the
    31st still settles in February — on the 28th, or the 29th, and a diary that
    says "no such date" is a diary nobody trusts.
    """
    if not day:
        return None
    import calendar

    def clamp(year: int, month: int) -> date:
        return date(year, month, min(day, calendar.monthrange(year, month)[1]))

    this_month = clamp(today.year, today.month)
    if this_month >= today:
        return this_month
    year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return clamp(year, month)


@router.get("/schemes/calendar")
def scheme_calendar(db: Session = Depends(get_db)):
    """Every funder, its agreed dates, and what is riding on the next one.

    Claiming is not continuous. A pharmacy signs terms with each scheme saying
    when a month's claims must be in and when the money comes back, and missing
    a cut-off costs a whole cycle, which for a shop running on its float is the
    difference between paying staff this month and not.

    None of that was recorded anywhere, so "when does CIMAS pay" was answered
    from somebody's memory, and "what have we not sent yet" was a report nobody
    ran until the money was late.
    """
    today = date.today()
    schemes = (db.query(MedicalAid)
                 .filter(MedicalAid.active.is_(True))
                 .order_by(MedicalAid.name).all())

    # What is outstanding with each funder, in one grouped query.
    waiting = dict(
        db.query(Claim.medical_aid_id,
                 func.coalesce(func.sum(Claim.amount_claimed), 0.0))
          .filter(Claim.status.in_(("submitted", "partial")))
          .group_by(Claim.medical_aid_id).all())
    unsent = dict(
        db.query(Claim.medical_aid_id, func.count(Claim.id))
          .filter(Claim.status == "deferred")
          .group_by(Claim.medical_aid_id).all())
    counts = dict(
        db.query(Claim.medical_aid_id, func.count(Claim.id))
          .filter(Claim.status.in_(("submitted", "partial")))
          .group_by(Claim.medical_aid_id).all())

    rows = []
    for scheme in schemes:
        cutoff = _next_on(scheme.claim_cutoff_day or 0, today)
        pays = _next_on(scheme.settlement_day or 0, today)
        rows.append({
            "id": scheme.id,
            "name": scheme.name,
            "scheme_code": scheme.scheme_code or "",
            "currency_code": scheme.currency_code or "",
            "realtime": bool(scheme.realtime),
            "claim_cutoff_day": scheme.claim_cutoff_day or 0,
            "settlement_day": scheme.settlement_day or 0,
            "settlement_days": scheme.settlement_days or 0,
            "agreement_reference": scheme.agreement_reference or "",
            "agreement_note": scheme.agreement_note or "",
            # What the member pays and what the pharmacy gives away.
            #
            # These reprice every claim this scheme touches — the levy is the
            # patient's share at the counter, and there was an endpoint to
            # change them and no screen anywhere that could. So the calculation
            # ran on whatever the seeder happened to set, for ever.
            "levy_fixed": round(float(scheme.levy_fixed or 0), 2),
            "levy_percent": round(float(scheme.levy_percent or 0), 2),
            "discount_percent": round(float(scheme.discount_percent or 0), 2),
            "extra_markup_percent": round(float(scheme.extra_markup_percent or 0), 2),
            "credit_limit": round(float(scheme.credit_limit or 0), 2),
            "next_cutoff": cutoff,
            "days_to_cutoff": (cutoff - today).days if cutoff else None,
            "next_settlement": pays,
            "days_to_settlement": (pays - today).days if pays else None,
            "awaiting_payment": round(float(waiting.get(scheme.id) or 0.0), 2),
            "claims_awaiting": int(counts.get(scheme.id) or 0),
            # Claims held rather than sent. These are the ones that miss a
            # cut-off, because nothing about them is on anybody's list.
            "held": int(unsent.get(scheme.id) or 0),
        })

    # Soonest cut-off first: the one with a deadline is the one to act on.
    rows.sort(key=lambda r: (r["days_to_cutoff"] is None,
                             r["days_to_cutoff"] if r["days_to_cutoff"] is not None else 0))
    return {
        "as_at": today,
        "schemes": rows,
        "awaiting_payment": round(sum(r["awaiting_payment"] for r in rows), 2),
        "held": sum(r["held"] for r in rows),
        "without_agreement": [r["name"] for r in rows
                              if not r["claim_cutoff_day"] and not r["settlement_day"]
                              and not r["settlement_days"]],
    }


@router.put("/schemes/{scheme_id}/agreement")
def set_agreement(scheme_id: int,
                  claim_cutoff_day: int = Body(default=0),
                  settlement_day: int = Body(default=0),
                  settlement_days: int = Body(default=0),
                  agreement_reference: str = Body(default=""),
                  agreement_note: str = Body(default=""),
                  db: Session = Depends(get_db),
                  user: User = Depends(require_role("admin", "pharmacist"))):
    """Record what was agreed with a funder."""
    scheme = db.get(MedicalAid, scheme_id)
    if scheme is None:
        raise HTTPException(404, "No such scheme.")
    for day, label in ((claim_cutoff_day, "cut-off"), (settlement_day, "settlement")):
        if day and not 1 <= day <= 31:
            raise HTTPException(400, f"The {label} day has to be between 1 and 31.")
    scheme.claim_cutoff_day = claim_cutoff_day
    scheme.settlement_day = settlement_day
    scheme.settlement_days = settlement_days
    scheme.agreement_reference = agreement_reference.strip()[:60]
    scheme.agreement_note = agreement_note.strip()
    db.commit()
    return {"message": f"The agreement with {scheme.name} is recorded."}
