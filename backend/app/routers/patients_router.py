from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..services import paging
from ..models import Doctor, MedicalAid, Patient, Sale, User

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


@router.get("/patients/{patient_id}/sales", response_model=list[schemas.SaleOut])
def patient_sales(patient_id: int, db: Session = Depends(get_db)):
    return (
        db.query(Sale)
        .filter(Sale.patient_id == patient_id)
        .order_by(Sale.created_at.desc())
        .limit(100)
        .all()
    )


# ---------- reference data ----------
@router.get("/medical-aids", response_model=list[schemas.MedicalAidOut])
def list_medical_aids(db: Session = Depends(get_db)):
    return db.query(MedicalAid).order_by(MedicalAid.name).all()


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
