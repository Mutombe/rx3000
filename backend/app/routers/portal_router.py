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

from .. import auth, tenancy
from ..database import get_db
from ..models import Doctor, Patient, Prescription, PrescriptionItem, Product, Sale, User
from ..services import patient_portal, portal_tokens

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

    # A code goes with the link, and is kept if one already exists — a patient
    # who has learned their four digits should not be given new ones every time
    # somebody re-sends the link.
    code = patient.portal_code or patient_portal.set_code(db, patient)
    db.commit()

    return {
        "token": token,
        "path": f"/portal/patient/{token}",
        "code": code,
        "send_to": patient.phone,
        "patient": f"{patient.first_name} {patient.last_name}".strip(),
        "expires_in_days": portal_tokens.DEFAULT_TTL // 86400,
        # Written to be sent as it stands. A pharmacy that has to compose the
        # message itself sends a bare URL with no explanation, and the patient
        # does not open it.
        "share_text": (
            f"Hello {patient.first_name}, here is your {{pharmacy}} record: "
            f"{{link}}\n\nYour code is {code}. Please keep it to yourself — "
            f"it opens your prescriptions."),
        "message": ("Link and code created. Send them to the patient's own "
                    "number, not a shared one — together they open their "
                    "record."),
    }


@admin.post("/links/patient/{patient_id}/new-code")
def reset_patient_code(patient_id: int, code: str = Body(default="", embed=True),
                       db: Session = Depends(get_db)):
    """Give a patient a new code — a lost phone, or one they cannot remember.

    The old one stops working the moment this is called, which is the point.
    """
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    try:
        fresh = patient_portal.set_code(db, patient, code)
    except patient_portal.PortalError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return {"code": fresh,
            "message": (f"{patient.first_name}'s code is now {fresh}. The old "
                        f"one has stopped working.")}


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
    """The patient a signed link names, and their pharmacy put in force.

    This read the patient through the ordinary tenant-scoped session, and a
    portal request carries no session — nobody is signed in, so no pharmacy is
    in force, so the filter matched nothing and every link answered "this
    record is no longer available". The portal was returning that to every
    patient who opened it.

    The token is the authority here, exactly as a staff token is: it is signed,
    it names one patient, and it expires. So the patient is read unscoped —
    deliberately, and only here — and their pharmacy is then set, so everything
    the portal reads afterwards is scoped to the shop that issued the link and
    cannot reach another tenant's data.
    """
    try:
        pid = portal_tokens.read(token, expect="patient")
    except portal_tokens.TokenError as e:
        raise HTTPException(401, str(e))

    with tenancy.unscoped():
        patient = db.get(Patient, pid)
    if not patient:
        raise HTTPException(404, "This record is no longer available.")

    # From here on the session is the patient's own pharmacy, so a script, a
    # dispensing or a delivery read below belongs to the shop that sent the
    # link and to nobody else.
    if patient.pharmacy_id:
        tenancy.set_current_pharmacy(patient.pharmacy_id)
        tenancy.stamp(db)
    return patient


# ------------------------------------------------------------- patient portal
@router.get("/patient/{token}")
def patient_overview(token: str, db: Session = Depends(get_db)):
    """What shows on opening the link, before the code is entered.

    Deliberately thin, and the thinness is the design: whether something is
    waiting is what they opened it for, and it says nothing about what the
    medicine is. A link that reaches the wrong phone has disclosed that
    somebody uses this pharmacy, which the message itself already did.
    """
    patient = _patient_from(token, db)
    return patient_portal.teaser(db, patient)


@router.post("/patient/{token}/confirm")
def patient_confirm(token: str, code: str = Body(default="", embed=True),
                    date_of_birth: str = Body(default="", embed=True),
                    db: Session = Depends(get_db)):
    """The second factor, and then their whole record.

    A four-digit code the pharmacy handed over, not a date of birth. A
    forwarded message usually reaches somebody who already knows the birthday —
    a spouse, a child, a colleague — so it protected against almost nobody who
    would actually receive it, and a patient who mistyped it was told their own
    date of birth was wrong.

    The date is still accepted where a record has no code yet, so a link sent
    last week does not stop working today.
    """
    patient = _patient_from(token, db)

    if code:
        try:
            patient_portal.verify(db, patient, code)
        except patient_portal.PortalError as exc:
            db.commit()   # the failure count is part of the protection
            raise HTTPException(401, str(exc)) from exc
    elif date_of_birth:
        if not patient.date_of_birth:
            raise HTTPException(
                400,
                "We cannot confirm your identity from what we hold. Please "
                "ring the pharmacy.")
        try:
            given = date.fromisoformat(date_of_birth)
        except ValueError:
            raise HTTPException(400, "Enter the date as YYYY-MM-DD.") from None
        if given != patient.date_of_birth:
            raise HTTPException(401, "That date does not match our records.")
        patient.portal_last_seen = datetime.utcnow()
    else:
        raise HTTPException(400, "Enter the code the pharmacy gave you.")

    db.commit()
    return patient_portal.record(db, patient)


@admin.get("/patient/{patient_id}/preview")
def preview_as_patient(patient_id: int, db: Session = Depends(get_db)):
    """See the portal exactly as this patient sees it.

    Staff answering "it does not show my tablets" cannot do so from a
    description, and asking the patient to read their code down the telephone
    teaches them to give it away. This is the same record the portal builds,
    through a staff session that is already authenticated and already audited.
    """
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    return {
        **patient_portal.record(db, patient),
        "impersonated": True,
        "code": patient.portal_code or "",
        "note": ("This is what the patient sees. Nothing here is a live "
                 "portal session — it is their record, read through your own."),
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
