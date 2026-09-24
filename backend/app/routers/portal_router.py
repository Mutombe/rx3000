"""Outside-facing portals: patients, prescribers and wholesalers.

They are built differently on purpose, and the dividing line is reading
versus writing.

**Patients only ever read.** Is my repeat ready, what do I owe, what did I get
last time. There is no account worth creating for four facts, so the signed link
is the credential and it arrives on the phone number already on file.

**Doctors read the same way and write differently.** A signed link is fine for
"did my patient collect". It is not fine for sending a prescription in: a link
that can prescribe is a prescription pad held by everyone it was ever forwarded
to. Prescribing therefore requires a real account tied to a practice number, and
every submitted script carries that prescriber's identity.

**Wholesalers read and write a narrow thing.** Two links: one for a single
request for quotation, where they type their own prices, and a standing one
for the orders this pharmacy has sent them, where they say what they are
sending and when. Both are signed links for the same reason the patient's is:
nobody at a wholesaler will create an account to quote for eight boxes of
amoxicillin, and a portal nobody signs into is a portal nobody uses.

What a supplier cannot do is change the transaction. Not a price, not a
quantity ordered, not anything the pharmacy decided. What they say is
recorded as what THEY said, beside what the pharmacy ordered, and the two are
compared rather than merged: a portal where the other side can edit the deal
is a shared document with no owner, and the first dispute about what was
agreed ends it.

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
from ..models import (Doctor, Patient, Pharmacy, Prescription, PrescriptionItem,
                      Product, PurchaseOrder, RfqSupplier, Sale, Supplier, User)
from ..services import (config, patient_portal, portal_pins, portal_tokens,
                        supplier_portal)
from ..services import rfq as rfq_svc

# Unauthenticated by design: the link or the prescriber login is the credential.
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

    # A code goes with the link. It cannot be "the one they already have" any
    # more, because nothing can read that back — it is a hash. So re-sending a
    # link issues fresh digits and the message carries them, which is the
    # honest version of what this always meant: the patient reads the code out
    # of the message they were just sent.
    code = patient_portal.set_code(db, patient)

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
            f"{{link}}\n\nYour code is {code}. Please keep it to yourself. "
            f"it opens your prescriptions."),
        "message": ("Link and code created. Send them to the patient's own "
                    "number, not a shared one. Together they open their "
                    "record."),
    }


@admin.post("/links/patient/{patient_id}/new-code")
def reset_patient_code(patient_id: int, code: str = Body(default="", embed=True),
                       db: Session = Depends(get_db)):
    """Give a patient a new code: a lost phone, or one they cannot remember.

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
    deliberately, and only here, and their pharmacy is then set, so everything
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
    a spouse, a child, a colleague, so it protected against almost nobody who
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
        # No code. It is a hash now, so nobody — staff included — can read a
        # patient's four digits off a screen. Where they have forgotten them,
        # "Give them a new code" issues fresh ones and shows them once.
        "has_code": portal_pins.has_pin(patient),
        "note": ("This is what the patient sees. Nothing here is a live "
                 "portal session. It is their record, read through your own."),
    }


# ------------------------------------------------------------ supplier portal
def _invited_from(token: str, db: Session) -> RfqSupplier:
    """The wholesaler a signed link names, and their pharmacy put in force.

    Same shape as `_patient_from`, and for the same reason: a portal request
    carries no session, so no pharmacy is in force, so the ordinary tenant
    filter matches nothing and every link would answer "no longer available".
    The token is the authority — signed, naming one supplier on one request,
    and expiring — so the row is read unscoped, deliberately and only here,
    and the pharmacy is then set so everything read afterwards belongs to the
    shop that sent the request and cannot reach another tenant's data.
    """
    try:
        rid = portal_tokens.read(token, expect="rfq")
    except portal_tokens.TokenError as e:
        raise HTTPException(401, str(e))

    with tenancy.unscoped():
        invited = db.get(RfqSupplier, rid)
    if not invited:
        raise HTTPException(404, "This request is no longer available.")
    if invited.pharmacy_id:
        tenancy.set_current_pharmacy(invited.pharmacy_id)
        tenancy.stamp(db)
    return invited


def _asking_pharmacy(db: Session) -> str:
    pid = tenancy.current_pharmacy_id()
    row = db.get(Pharmacy, pid) if pid else None
    return (row.trading_name or row.name) if row else ""


# --------------------------------------------------------------- the brand
#
# WHOSE SHOPFRONT THIS IS.
#
# Three of the four portals put "RX5000" at the top, which is the software
# vendor's name on a page the pharmacy's own customer is reading. The printed
# documents settled this argument already: the wordmark on a statement is the
# PHARMACY'S, not ours. The portals never got the memo, so a patient opening
# their prescriptions from an SMS sees a product they have never bought from
# and not the shop they collect at.
#
# Served here rather than folded into each portal's own payload because all
# five want the same answer, and a second copy of it is a second thing to keep
# true. The same shape the letterhead serves, so print and portal cannot
# disagree about what this pharmacy is called.

@router.get("/brand/{kind}/{token}")
def portal_brand(kind: str, token: str, db: Session = Depends(get_db)):
    """The pharmacy behind this link: what it is called, and what it looks like.

    Public, and narrow on purpose. It carries what goes on a shopfront and
    nothing a competitor could not read off the door: the trading name, the
    logo, a telephone number and an address. No figures, no patients, no
    stock, and nothing at all until the token proves which pharmacy is being
    asked about.
    """
    # Looked up at call time rather than in a module-level map: the supplier
    # resolver is defined below this point, and a map built at import would
    # bind the name before it exists.
    #
    # Each resolver proves the token AND sets the tenant as a side effect,
    # which is what makes the settings lookup below return anything at all. A
    # caller cannot therefore ask for one pharmacy's brand holding another's
    # link.
    resolve = {
        "patient": _patient_from,
        "rfq": _invited_from,
        # The quote portal's own route is /portal/quote/{token}, so it asks
        # under the name it is read at rather than the name of the row.
        "quote": _invited_from,
        "doctor": _doctor_from,
        "supplier": _supplier_from,
    }.get(kind)
    if resolve is None:
        raise HTTPException(404, "No such link.")
    # Sets the tenant as it goes, and raises if the link is spent. Everything
    # below reads settings, which return nothing without a pharmacy in force.
    resolve(token, db)

    from ..routers.profile_router import LOGO_KEY, _many

    stored = _many(db, ["company.trading_name", "company.legal_name",
                        "company.phone", "company.email",
                        "company.address_line1", "company.address_line2",
                        "company.city", "company.registration_no", LOGO_KEY])
    pid = tenancy.current_pharmacy_id()
    row = db.get(Pharmacy, pid) if pid else None

    # The settings first, the pharmacy row behind them. A shop that has filled
    # in its company profile has said how it wants to be seen; one that has
    # not still has a name on its record, and a blank header is worse than an
    # unstyled one.
    name = (stored["company.trading_name"] or stored["company.legal_name"]
            or (row.trading_name or row.name if row else ""))
    # Every field a string, never a null. A header that renders "null" under
    # the pharmacy's name is worse than one that renders nothing, and the
    # pharmacy row carries nulls for anything nobody filled in.
    return {
        "name": name or "",
        "logo": stored[LOGO_KEY] or "",
        "phone": stored["company.phone"] or (row.phone if row else "") or "",
        "email": stored["company.email"] or (row.email if row else "") or "",
        "registration_no": (stored["company.registration_no"]
                            or (row.registration_no if row else "") or ""),
        "address": _address_lines(
            stored["company.address_line1"] or (row.address if row else ""),
            stored["company.address_line2"],
            stored["company.city"] or (row.city if row else ""),
        ),
    }


def _address_lines(*lines: str | None) -> list[str]:
    """The address, with nothing said twice.

    A shop that types "114 Samora Machel Avenue, Harare" on the first line and
    "Harare" in the city box is not making a mistake — both boxes want
    filling — but printing both gives the patient "114 Samora Machel Avenue,
    Harare, Harare", which reads as a fault in the software rather than in
    the form. So a line already spelt out inside an earlier one is dropped.
    """
    kept: list[str] = []
    for line in lines:
        said = (line or "").strip()
        if not said:
            continue
        if any(said.casefold() in already.casefold() for already in kept):
            continue
        kept.append(said)
    return kept


@router.get("/quote/{token}")
def quote_form(token: str, db: Session = Depends(get_db)):
    """What a wholesaler sees when they open the link in the email.

    No sign-in, because nobody at a wholesaler will create an account to quote
    a pharmacy for eight boxes of amoxicillin, and asking them to is how a
    supplier portal ends up unused and the prices go on being read down a
    telephone.
    """
    invited = _invited_from(token, db)
    # Opened is not answered, and the difference is worth keeping: a
    # wholesaler who never saw the request needs it re-sending, one who read
    # it and went quiet needs ringing. Those are different phone calls.
    if invited.opened_at is None:
        invited.opened_at = datetime.utcnow()
        db.commit()
    return rfq_svc.portal_view(db, invited,
                               pharmacy_name=_asking_pharmacy(db))


@router.post("/quote/{token}")
def submit_quote(token: str, body: dict = Body(default={}),
                 db: Session = Depends(get_db)):
    """The wholesaler's own prices, typed by the wholesaler.

    This is the whole point of the portal: a price entered by the person
    selling it needs nobody here to write it down afterwards, so "who recorded
    this" stops being a question anybody has to ask.

    It stays editable until the request is decided. A supplier who spots a
    mistyped price an hour later can correct it, and the alternative is a
    telephone call that puts a transcription step back in.
    """
    invited = _invited_from(token, db)
    view = rfq_svc.portal_view(db, invited)
    if view["closed"]:
        raise HTTPException(409, view["closed_because"])

    said = rfq_svc.record(
        db, invited,
        answers=body.get("answers") or [],
        declined=bool(body.get("declined")),
        note=str(body.get("note") or ""),
        by_supplier=True)
    db.commit()
    return {
        **said,
        "answered_at": invited.responded_at,
        "message": (
            "Thank you. The pharmacy has been told you cannot supply this one."
            if invited.declined else
            f"Thank you. Your prices for {invited.rfq.reference} have "
            "reached the pharmacy."),
    }


def _supplier_from(token: str, db: Session) -> Supplier:
    """The wholesaler a standing link names, and their pharmacy in force.

    Same shape and same reasoning as `_patient_from`: a portal request
    carries no session, so the ordinary tenant filter matches nothing and
    every link would answer "no longer available". The token is the
    authority, so the supplier is read unscoped, deliberately and only here,
    and their pharmacy is then set.
    """
    try:
        sid = portal_tokens.read(token, expect="supplier")
    except portal_tokens.TokenError as e:
        raise HTTPException(401, str(e))

    with tenancy.unscoped():
        supplier = db.get(Supplier, sid)
    if not supplier:
        raise HTTPException(404, "This link is no longer available.")
    if supplier.active is False:
        raise HTTPException(
            403, "This account is closed. Please ring the pharmacy.")
    if supplier.pharmacy_id:
        tenancy.set_current_pharmacy(supplier.pharmacy_id)
        tenancy.stamp(db)
    return supplier


@router.get("/supplier/{token}")
def supplier_orders(token: str, db: Session = Depends(get_db)):
    """What a wholesaler sees: the orders this pharmacy has sent them."""
    supplier = _supplier_from(token, db)
    return supplier_portal.view(db, supplier,
                                pharmacy_name=_asking_pharmacy(db))


@router.post("/supplier/{token}/orders/{order_id}")
def acknowledge_order(token: str, order_id: int, body: dict = Body(default={}),
                      db: Session = Depends(get_db)):
    """The wholesaler confirms what they are sending, and when.

    This is the answer to the telephone call a pharmacy would otherwise make,
    given once and in writing by the person who actually knows.
    """
    supplier = _supplier_from(token, db)
    order = db.get(PurchaseOrder, order_id)
    if order is None:
        raise HTTPException(404, "That order is not on file.")
    try:
        said = supplier_portal.acknowledge(
            db, supplier, order,
            promised=str(body.get("promised_date") or ""),
            note=str(body.get("note") or ""),
            lines=body.get("lines") or [])
    except supplier_portal.PortalError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return said


@admin.post("/links/supplier/{supplier_id}")
def issue_supplier_link(supplier_id: int, db: Session = Depends(get_db)):
    """A standing link for a wholesaler, to send by email or WhatsApp."""
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    token = portal_tokens.issue(kind="supplier", subject_id=supplier.id,
                                ttl=supplier_portal.TTL)
    base = config.text(db, "portal.base_url",
                       rfq_svc.DEFAULT_PORTAL_BASE).rstrip("/")
    link = f"{base}/supplier/{token}"
    pharmacy = _asking_pharmacy(db)
    return {
        "token": token,
        "link": link,
        "path": f"/supplier/{token}",
        "supplier": supplier.name,
        "send_to": (supplier.email or "").strip(),
        "expires_in_days": supplier_portal.TTL // 86400,
        # Written to be sent as it stands.
        "share_text": (
            f"Good day. {pharmacy or 'We'} can now show you our orders with "
            "you online. You can confirm what you are sending and when, "
            f"which saves us ringing: {link}"),
        "message": (f"Link for {supplier.name} created. It lasts "
                    f"{supplier_portal.TTL // 86400} days and shows them "
                    "their own orders only."),
    }


# -------------------------------------------------------------- doctor portal
def _doctor_from(token: str, db: Session) -> Doctor:
    """The prescriber a signed link names, and their pharmacy put in force.

    Same reasoning as `_patient_from`, and the same defect it was written to
    fix: a portal request carries no session, so no pharmacy was in force, so
    every script the prescriber asked about was filtered away and the page
    came back empty for a prescriber whose patients had collected that
    morning. The token is the authority; the row is read unscoped once, and
    the prescriber's own pharmacy is in force for everything read after it.
    """
    try:
        did = portal_tokens.read(token, expect="doctor")
    except portal_tokens.TokenError as e:
        raise HTTPException(401, str(e))

    with tenancy.unscoped():
        doctor = db.get(Doctor, did)
    if not doctor:
        raise HTTPException(404, "This link is no longer available.")

    if doctor.pharmacy_id:
        tenancy.set_current_pharmacy(doctor.pharmacy_id)
        tenancy.stamp(db)
    return doctor


@router.get("/doctor/{token}")
def doctor_overview(token: str, db: Session = Depends(get_db)):
    """Read-only visibility for a prescriber, from a link.

    Answers the one question a prescriber actually rings the pharmacy about:
    did my patient collect. It shows no clinical detail beyond the prescriber's
    own scripts, because that is all they are entitled to see here.
    """
    doctor = _doctor_from(token, db)

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
    rules, or the person standing at the counter, and because what a pharmacy
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
