"""Outside-facing portals: one for patients, one for prescribers.

The two are built differently on purpose, and the dividing line is reading
versus writing.

**Patients only ever read.** Is my repeat ready, what do I owe, what did I get
last time. There is no account worth creating for four facts, so the signed link
is the credential and it arrives on the phone number already on file.

**Doctors read the same way and write differently.** A signed link is fine for
"did my patient collect". It is not fine for sending a prescription in: a link
that can prescribe is a prescription pad held by everyone it was ever forwarded
to. Prescribing therefore requires a real account tied to a practice number, and
every submitted script carries that prescriber's identity.

One further rule on the writing side: a doctor cannot put a dispensable script
into this pharmacy. Submissions land as `submitted` and a pharmacist accepts
them, at which point they become `active`. The pharmacy stays in control of what
it is willing to dispense, which is both the legal position and the practical
one — the prescriber cannot see the stock, the funder rules, or the patient
standing in front of the counter.
"""
from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import auth
from ..database import get_db
from ..models import Doctor, Patient, Prescription, PrescriptionItem, Product, Sale, User
from ..services import portal_tokens

# Unauthenticated by design — the link or the prescriber login is the credential.
router = APIRouter(prefix="/api/portal", tags=["portals"])

# Issuing links is a staff action, so it sits behind the normal session.
admin = APIRouter(prefix="/api/portal-admin", tags=["portals"],
                  dependencies=[Depends(auth.get_current_user)])


# ---------------------------------------------------------------- link issuing
@admin.post("/links/patient/{patient_id}")
def issue_patient_link(patient_id: int, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    if not patient.phone:
        raise HTTPException(
            400,
            "This patient has no phone number on file, so there is nowhere to "
            "send the link. Add one first.")
    token = portal_tokens.issue(kind="patient", subject_id=patient.id)
    return {
        "token": token,
        "path": f"/portal/patient/{token}",
        "send_to": patient.phone,
        "expires_in_days": portal_tokens.DEFAULT_TTL // 86400,
        "message": "Link created. Send it to the patient's own number, not a "
                   "shared one, it opens their record.",
    }


@admin.post("/links/doctor/{doctor_id}")
def issue_doctor_link(doctor_id: int, db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(404, "Doctor not found")
    token = portal_tokens.issue(kind="doctor", subject_id=doctor.id)
    return {
        "token": token,
        "path": f"/portal/doctor/{token}",
        "send_to": doctor.phone or doctor.email or "",
        "note": "This link shows dispensing status only. Sending a prescription "
                "in requires the prescriber's own sign-in.",
    }


def _patient_from(token: str, db: Session) -> Patient:
    try:
        pid = portal_tokens.read(token, expect="patient")
    except portal_tokens.TokenError as e:
        raise HTTPException(401, str(e))
    patient = db.get(Patient, pid)
    if not patient:
        raise HTTPException(404, "This record is no longer available.")
    return patient


# ------------------------------------------------------------- patient portal
@router.get("/patient/{token}")
def patient_overview(token: str, db: Session = Depends(get_db)):
    """What a patient sees on opening the link, before proving anything.

    Deliberately thin. A collection status and a balance are the two things they
    opened the link for, and neither says what the medicine is — so a link that
    reaches the wrong phone has not disclosed a diagnosis.
    """
    patient = _patient_from(token, db)
    scripts = (db.query(Prescription)
               .filter(Prescription.patient_id == patient.id,
                       Prescription.status == "active")
               .order_by(Prescription.date_prescribed.desc()).limit(5).all())
    return {
        "greeting": patient.first_name,
        "pharmacy_ready": sum(1 for s in scripts if s.status == "active"),
        "active_scripts": len(scripts),
        "requires_confirmation": True,
        "note": "To see what was dispensed, confirm your date of birth.",
    }


@router.post("/patient/{token}/confirm")
def patient_confirm(token: str, date_of_birth: str = Body(embed=True),
                    db: Session = Depends(get_db)):
    """The second factor for anything clinical.

    A WhatsApp link gets forwarded. Collection status surviving that is a
    nuisance; a chronic medication list surviving it is a disclosure. One date
    the patient knows and a forwarder generally does not is proportionate — this
    is not protecting a bank account.
    """
    patient = _patient_from(token, db)
    if not patient.date_of_birth:
        raise HTTPException(
            400,
            "We cannot confirm your identity from the details we hold. Please "
            "contact the pharmacy.")
    try:
        given = date.fromisoformat(date_of_birth)
    except ValueError:
        raise HTTPException(400, "Enter the date as YYYY-MM-DD.")
    if given != patient.date_of_birth:
        raise HTTPException(401, "That date does not match our records.")

    scripts = (db.query(Prescription)
               .filter(Prescription.patient_id == patient.id)
               .order_by(Prescription.date_prescribed.desc()).limit(10).all())
    return {
        "patient": f"{patient.first_name} {patient.last_name}",
        "allergies": patient.allergies or "",
        "loyalty_points": patient.loyalty_points or 0,
        "scripts": [{
            "rx_number": s.rx_number,
            "date": s.date_prescribed,
            "status": s.status,
            "doctor": s.doctor.name if s.doctor else "",
            "items": [{
                "product": i.product.name if i.product else "",
                "instructions": i.dosage_instructions,
                "quantity": i.quantity,
                "repeats_left": max(0, (i.repeats_allowed or 0) - (i.repeats_used or 0)),
                "next_repeat": i.next_repeat_date,
            } for i in s.items],
        } for s in scripts],
    }


# -------------------------------------------------------------- doctor portal
@router.get("/doctor/{token}")
def doctor_overview(token: str, db: Session = Depends(get_db)):
    """Read-only visibility for a prescriber, from a link.

    Answers the one question a prescriber actually rings the pharmacy about:
    did my patient collect. It shows no clinical detail beyond the prescriber's
    own scripts, because that is all they are entitled to see here.
    """
    try:
        did = portal_tokens.read(token, expect="doctor")
    except portal_tokens.TokenError as e:
        raise HTTPException(401, str(e))
    doctor = db.get(Doctor, did)
    if not doctor:
        raise HTTPException(404, "This link is no longer available.")

    scripts = (db.query(Prescription)
               .filter(Prescription.doctor_id == doctor.id)
               .order_by(Prescription.date_prescribed.desc()).limit(25).all())
    return {
        "doctor": doctor.name,
        "practice_number": doctor.practice_number,
        "can_prescribe_here": False,
        "note": "Sending a prescription in requires your own sign-in. Ask the "
                "pharmacy to enable it for this practice number.",
        "scripts": [{
            "rx_number": s.rx_number,
            "date": s.date_prescribed,
            "status": s.status,
            "patient": f"{s.patient.first_name} {s.patient.last_name}" if s.patient else "",
            "collected": s.status == "active",
        } for s in scripts],
    }


class PrescriberLogin(BaseModel):
    practice_number: str
    password: str


class NewItem(BaseModel):
    product_id: int
    dosage_instructions: str = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0)
    repeats_allowed: int = Field(default=0, ge=0, le=12)
    icd10_code: str = ""


class NewScript(BaseModel):
    patient_id: int
    notes: str = ""
    items: list[NewItem] = Field(min_length=1)


@router.post("/doctor/login")
def prescriber_login(body: PrescriberLogin, db: Session = Depends(get_db)):
    """Sign-in for a prescriber who is allowed to send scripts to this pharmacy.

    Enabled per practice number by the pharmacy, not self-service. A pharmacy
    should know which prescribers can write into its system, and a self-service
    signup form is an open door to exactly the thing the controlled register
    exists to prevent.
    """
    doctor = (db.query(Doctor)
              .filter(Doctor.practice_number == body.practice_number.strip()).first())
    if not doctor or not doctor.portal_password_hash:
        raise HTTPException(
            401,
            "No prescriber sign-in exists for that practice number. Ask the "
            "pharmacy to enable it.")
    if not doctor.portal_active:
        raise HTTPException(403, "This prescriber sign-in has been disabled.")
    if not auth.verify_password(body.password, doctor.portal_password_hash):
        raise HTTPException(401, "Practice number or password is not correct.")
    # A short session: a prescriber writes a script and leaves.
    return {
        "token": portal_tokens.issue(kind="prescriber", subject_id=doctor.id, ttl=8 * 3600),
        "doctor": doctor.name,
        "practice_number": doctor.practice_number,
    }


def _prescriber_from(token: str, db: Session) -> Doctor:
    try:
        did = portal_tokens.read(token, expect="prescriber")
    except portal_tokens.TokenError as e:
        raise HTTPException(401, str(e))
    doctor = db.get(Doctor, did)
    if not doctor or not doctor.portal_active:
        raise HTTPException(403, "This prescriber sign-in has been disabled.")
    return doctor


@router.post("/doctor/prescriptions")
def submit_prescription(body: NewScript,
                        authorization: str = Header(default=""),
                        db: Session = Depends(get_db)):
    """A prescriber sends a script to this pharmacy.

    It lands as `submitted`, never `active`. A pharmacist accepts it before it
    can be dispensed, because the prescriber cannot see the stock, the funder
    rules, or the person standing at the counter — and because what a pharmacy
    is willing to dispense is the pharmacy's decision to make.
    """
    # The session rides in the header, not the body. Mixing a bearer token into
    # a JSON body makes it something a browser will happily log, cache and put
    # in a referrer.
    doctor = _prescriber_from(authorization.removeprefix("Bearer ").strip(), db)
    patient = db.get(Patient, body.patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")

    products = {p.id: p for p in db.query(Product)
                .filter(Product.id.in_([i.product_id for i in body.items])).all()}
    missing = sorted(set(i.product_id for i in body.items) - set(products))
    if missing:
        raise HTTPException(
            400, f"This pharmacy does not stock product(s): {missing}. "
                 "The pharmacist can substitute on acceptance.")

    rx = Prescription(
        rx_number=f"DR-{datetime.utcnow():%Y%m%d%H%M%S}",
        patient_id=patient.id,
        doctor_id=doctor.id,
        date_prescribed=date.today(),
        notes=body.notes,
        status="submitted",
    )
    db.add(rx)
    db.flush()
    for item in body.items:
        db.add(PrescriptionItem(
            prescription_id=rx.id,
            product_id=item.product_id,
            dosage_instructions=item.dosage_instructions,
            quantity=item.quantity,
            repeats_allowed=item.repeats_allowed,
            icd10_code=item.icd10_code or None,
        ))
    db.commit()
    return {
        "rx_number": rx.rx_number,
        "status": rx.status,
        "message": "Sent to the pharmacy. A pharmacist will review it before it "
                   "can be dispensed.",
    }


@admin.post("/prescribers/{doctor_id}/enable")
def enable_prescriber(doctor_id: int, password: str = Body(embed=True),
                      db: Session = Depends(get_db)):
    """Turn on prescriber sign-in for one practice number."""
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(404, "Doctor not found")
    if not doctor.practice_number:
        raise HTTPException(
            400,
            "This prescriber has no practice number recorded. That is what a "
            "submitted script is attributed to, so it must be set first.")
    if len(password) < 8:
        raise HTTPException(400, "The password must be at least 8 characters.")
    doctor.portal_password_hash = auth.hash_password(password)
    doctor.portal_active = True
    db.commit()
    return {"message": f"{doctor.name} can now send prescriptions to this pharmacy."}


@admin.get("/submitted")
def submitted_scripts(db: Session = Depends(get_db)):
    """What prescribers have sent in and nobody has accepted yet."""
    rows = (db.query(Prescription).filter(Prescription.status == "submitted")
            .order_by(Prescription.created_at.desc()).all())
    return [{
        "id": s.id, "rx_number": s.rx_number, "date": s.date_prescribed,
        "doctor": s.doctor.name if s.doctor else "",
        "practice_number": s.doctor.practice_number if s.doctor else "",
        "patient": f"{s.patient.first_name} {s.patient.last_name}" if s.patient else "",
        "patient_id": s.patient_id,
        "items": [{"product": i.product.name if i.product else "",
                   "instructions": i.dosage_instructions,
                   "quantity": i.quantity} for i in s.items],
    } for s in rows]


@admin.post("/submitted/{rx_id}/accept")
def accept_script(rx_id: int, db: Session = Depends(get_db),
                  user: User = Depends(auth.get_current_user)):
    """A pharmacist takes responsibility for a submitted script."""
    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(404, "Prescription not found")
    if rx.status != "submitted":
        raise HTTPException(
            400,
            f"This script is already '{rx.status}'. Only a submitted script can "
            "be accepted.")
    rx.status = "active"
    rx.started_by_id = user.id
    rx.updated_at = datetime.utcnow()
    db.commit()
    return {"rx_number": rx.rx_number, "status": rx.status,
            "message": "Accepted. It can now be dispensed."}
