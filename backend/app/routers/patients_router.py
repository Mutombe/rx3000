import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..services import insurance_standing
from ..services import paging
from ..models import (BatchAllocation, Doctor, MedicalAid, Patient, Sale,
                      SaleItem, User)
from .periods_router import require_step_up

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["patients"], dependencies=[Depends(get_current_user)])


def _patient_search(db: Session, q: str):
    query = db.query(Patient)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Patient.first_name.ilike(like),
            Patient.last_name.ilike(like),
            Patient.id_number.ilike(like),
            Patient.phone.ilike(like),
            Patient.medical_aid_number.ilike(like),
        ))
    return query.order_by(Patient.last_name, Patient.first_name)


@router.get("/patients", response_model=list[schemas.PatientOut])
def list_patients(q: str = "", limit: int = 100, db: Session = Depends(get_db)):
    """The unpaged list, kept for the pickers that need a short shortlist.

    Deliberately left alone rather than "fixed": a search box that offers ten
    matches wants a cheap capped query, not a page envelope. What was wrong was
    using this shape for the *browse* screen, where the cap silently hid rows.
    That screen now calls /patients/paged below.
    """
    return _patient_search(db, q).limit(limit).all()


@router.get("/patients/paged")
def list_patients_paged(
    q: str = "",
    page: int = 1,
    per_page: int = paging.DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
):
    """The browse list, which always reports how many patients there are.

    A list that has been cut short must say so. Returning 100 of 159 with no
    total is not a smaller answer, it is a wrong one.
    """
    result = paging.page(_patient_search(db, q), page=page, per_page=per_page)
    return result.envelope(
        lambda p: schemas.PatientOut.model_validate(p, from_attributes=True).model_dump()
    )


@router.post("/patients", response_model=schemas.PatientOut)
def create_patient(body: schemas.PatientCreate, db: Session = Depends(get_db)):
    patient = Patient(**body.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/patients/{patient_id}", response_model=schemas.PatientOut)
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.put("/patients/{patient_id}", response_model=schemas.PatientOut)
def update_patient(patient_id: int, body: schemas.PatientCreate, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    for key, value in body.model_dump().items():
        setattr(patient, key, value)
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/patients/{patient_id}/insurance")
def patient_insurance(patient_id: int, db: Session = Depends(get_db)):
    """Whether this member has cover, and whether their scheme is paying us.

    Read at the two moments it can change a decision: dispensing, and taking
    the money. Advisory on purpose — a slow funder is a commercial problem and
    the person at the counter is not the one who can resolve it. What this does
    is make sure the medicine is handed over knowingly.
    """
    standing = insurance_standing.patient_standing(db, patient_id)
    if not standing:
        raise HTTPException(status_code=404, detail="Patient not found")
    return standing


@router.get("/medical-aids/{medical_aid_id}/standing")
def scheme_insurance(medical_aid_id: int, db: Session = Depends(get_db)):
    """How a funder has behaved, for a patient who is not on file yet."""
    standing = insurance_standing.scheme_standing(db, medical_aid_id)
    if not standing:
        raise HTTPException(status_code=404, detail="Scheme not found")
    return standing


@router.get("/patients/{patient_id}/sales", response_model=list[schemas.SaleOut])
def patient_sales(patient_id: int, db: Session = Depends(get_db)):
    # Same shape as the till's list, and the same reason: SaleOut renders the
    # lines, the tenders and the claim, and a hundred purchases fetched one
    # relation at a time is four hundred round trips on the patient record.
    return (
        db.query(Sale)
        .options(selectinload(Sale.items)
                 .selectinload(SaleItem.allocations)
                 .joinedload(BatchAllocation.batch),
                 selectinload(Sale.tenders),
                 joinedload(Sale.claim),
                 joinedload(Sale.patient).joinedload(Patient.medical_aid))
        .filter(Sale.patient_id == patient_id)
        .order_by(Sale.created_at.desc())
        .limit(100)
        .all()
    )


# ---------- reference data ----------
@router.get("/medical-aids", response_model=list[schemas.MedicalAidOut])
def list_medical_aids(db: Session = Depends(get_db)):
    return db.query(MedicalAid).order_by(MedicalAid.name).all()


@router.put("/medical-aids/{aid_id}", response_model=schemas.MedicalAidOut)
def update_medical_aid_terms(
    aid_id: int, body: schemas.MedicalAidTerms,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _grant=Depends(require_step_up("scheme.edit")),
):
    """Change a scheme's terms.

    Behind `scheme.edit`, which had been declared as a protected action since the
    step-up work went in and guarded nothing, because no endpoint existed to
    change a scheme at all. A declared control with no code behind it is worse
    than no control: it appears in the list of protected actions and in the audit
    configuration, so it reads as covered.

    Levies and discounts reprice every future claim, and the credit limit decides
    when the pharmacy stops lending to a scheme. Both are the kind of figure that
    is changed once, by one person, after a phone call, and then argued about
    months later, which is why the change is attributable.
    """
    aid = db.get(MedicalAid, aid_id)
    if not aid:
        raise HTTPException(status_code=404, detail="That scheme no longer exists.")

    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing was sent to change.")

    for field in ("levy_percent", "discount_percent", "extra_markup_percent"):
        value = changes.get(field)
        # A percentage outside 0–100 is a typo every time, and one that would
        # reprice every claim afterwards without anything looking wrong.
        if value is not None and not 0 <= value <= 100:
            raise HTTPException(
                status_code=400,
                detail=f"{field.replace('_', ' ').capitalize()} must be between 0 and 100.",
            )
    if changes.get("credit_limit") is not None and changes["credit_limit"] < 0:
        raise HTTPException(
            status_code=400,
            detail="A credit limit cannot be negative. Zero means no limit is set.",
        )

    before = {f: getattr(aid, f) for f in changes}
    for field, value in changes.items():
        setattr(aid, field, value)
    db.commit()
    db.refresh(aid)
    log.info(
        "scheme.terms_changed scheme=%s by=%s from=%s to=%s",
        aid.name, user.username, before, changes,
    )
    return aid


@router.get("/doctors", response_model=list[schemas.DoctorOut])
def list_doctors(db: Session = Depends(get_db)):
    return db.query(Doctor).order_by(Doctor.name).all()


@router.post("/doctors", response_model=schemas.DoctorOut)
def create_doctor(body: schemas.DoctorBase, db: Session = Depends(get_db)):
    doctor = Doctor(**body.model_dump())
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return doctor


@router.put("/doctors/{doctor_id}", response_model=schemas.DoctorOut)
def update_doctor(doctor_id: int, body: dict = Body(...),
                  db: Session = Depends(get_db)):
    """Correct a prescriber.

    Prescribers could be created and listed and never changed. A practice
    number typed wrong was permanent, and a practice number is what a funder
    adjudicates on, so every claim carrying that prescriber was rejected for
    as long as the record stood, and the only way out was a second prescriber
    record with the same name.
    """
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Prescriber not found")

    if "name" in body:
        name = str(body["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400,
                                detail="A prescriber needs a name.")
        doctor.name = name[:120]
    for field, width in (("practice_number", 40), ("phone", 30),
                         ("email", 120), ("speciality", 80), ("address", 300),
                         ("hpa_number", 40), ("notes", 400)):
        if field in body and hasattr(doctor, field):
            setattr(doctor, field, str(body[field] or "").strip()[:width])
    if "active" in body and hasattr(doctor, "active"):
        doctor.active = bool(body["active"])
    db.commit()
    db.refresh(doctor)
    return doctor


@router.delete("/doctors/{doctor_id}")
def retire_doctor(doctor_id: int, db: Session = Depends(get_db)):
    """Retire a prescriber. Never deleted. Their name is on every script.

    A prescriber who has retired, moved abroad or been struck off should stop
    appearing in the picker, and every script they ever wrote must still say
    who wrote it. Those are not in tension; deleting the row breaks the second
    to achieve the first.
    """
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Prescriber not found")
    if not hasattr(doctor, "active"):
        raise HTTPException(
            status_code=400,
            detail="Prescribers on this database cannot be retired.")
    doctor.active = False
    db.commit()
    return {"ok": True,
            "message": (f"{doctor.name} will not appear when capturing a "
                        f"script. Their name stays on the ones they wrote.")}
