import logging
from datetime import datetime, timedelta

from fastapi import (APIRouter, Body, Depends, File, Form, HTTPException,
                     UploadFile)
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..services import insurance_standing
from ..services import patient_duplicates
from ..services import paging
from ..models import (BatchAllocation, Dispensing, Doctor, MedicalAid, Patient,
                      Prescription, PrescriptionItem, Sale, SaleItem, User)
from .periods_router import require_step_up

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["patients"], dependencies=[Depends(get_current_user)])


#: The questions a pharmacy actually asks of its patient list.
#:
#: Not a general query builder. Each of these is a question somebody walks up
#: to the screen already holding: who is on a scheme, who pays cash, who have
#: we just registered, and who has stopped coming. A filter nobody can name in
#: a sentence is a filter nobody uses.
#:
#: "Lapsed" is the one worth arguing about. Six months without a dispensing is
#: not proof that somebody has gone elsewhere, and it is the only signal a
#: pharmacy has: a patient who used to come monthly and has not been in since
#: March is a conversation worth having, whether or not the reason turns out to
#: be a move, a new doctor or a death. It is named for what is measured rather
#: than for what it is taken to mean.
PATIENT_FILTERS = ("aid", "private", "recent", "lapsed", "chronic", "caregiver")

#: What "recently added" and "lapsed" mean, in days. Stated once here rather
#: than spelled into three queries that can drift apart.
RECENT_DAYS = 30
LAPSED_DAYS = 180


def _patient_search(db: Session, q: str, view: str = ""):
    query = db.query(Patient)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Patient.first_name.ilike(like),
            Patient.last_name.ilike(like),
            Patient.id_number.ilike(like),
            Patient.phone.ilike(like),
            Patient.medical_aid_number.ilike(like),
            # A number read off a label or a card finds the patient.
            Patient.profile_number.ilike(like),
        ))

    view = (view or "").strip().lower()
    if view == "aid":
        query = query.filter(Patient.medical_aid_id.isnot(None))
    elif view == "private":
        query = query.filter(Patient.medical_aid_id.is_(None))
    elif view == "recent":
        query = query.filter(
            Patient.created_at >= datetime.utcnow() - timedelta(days=RECENT_DAYS))
    elif view == "chronic":
        query = query.filter(
            func.coalesce(Patient.chronic_conditions, "") != "")
    elif view == "caregiver":
        query = query.filter(func.coalesce(Patient.caregiver_name, "") != "")
    elif view == "lapsed":
        # Nothing dispensed to them in the window. Expressed as "no dispensing
        # since" rather than "last seen before", so a patient who has never
        # been dispensed to is included: never having come back is the strongest
        # version of having stopped.
        seen = (
            db.query(Prescription.patient_id)
            .join(PrescriptionItem,
                  PrescriptionItem.prescription_id == Prescription.id)
            .join(Dispensing,
                  Dispensing.prescription_item_id == PrescriptionItem.id)
            .filter(Dispensing.dispensed_at
                    >= datetime.utcnow() - timedelta(days=LAPSED_DAYS))
        )
        query = query.filter(Patient.id.notin_(seen))

    # Newest first where the question is about recency, alphabetical otherwise:
    # "recently added" sorted by surname answers a different question than the
    # one that was asked.
    if view == "recent":
        return query.order_by(Patient.created_at.desc())
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
    view: str = "",
    page: int = 1,
    per_page: int = paging.DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
):
    """The browse list, which always reports how many patients there are.

    A list that has been cut short must say so. Returning 100 of 159 with no
    total is not a smaller answer, it is a wrong one.

    `view` narrows it to one of PATIENT_FILTERS. An unknown value is ignored
    rather than refused: a stale bookmark should show the patient list, not an
    error page.
    """
    result = paging.page(_patient_search(db, q, view), page=page, per_page=per_page)
    return result.envelope(
        lambda p: schemas.PatientOut.model_validate(p, from_attributes=True).model_dump()
    )


@router.get("/patients/counts")
def patient_counts(q: str = "", db: Session = Depends(get_db)):
    """How many patients each filter would show, for the buttons themselves.

    A filter button that might show nothing is a button nobody presses twice.
    Counted against the same search text the list is using, so the numbers
    describe what pressing it would actually do.
    """
    return {
        "all": _patient_search(db, q).count(),
        **{name: _patient_search(db, q, name).count() for name in PATIENT_FILTERS},
    }


@router.post("/patients/duplicates")
def possible_duplicates(body: schemas.PatientCreate, db: Session = Depends(get_db)):
    """Who on file may already be this person — asked before registering.

    The registration form calls this first and shows the matches, because the
    client flattens an error body to a sentence and could not show a list from
    a refusal. The registration endpoint enforces the same rule regardless.
    """
    return patient_duplicates.find(
        db, first_name=body.first_name, last_name=body.last_name,
        id_number=body.id_number, date_of_birth=body.date_of_birth, phone=body.phone)


@router.post("/patients", response_model=schemas.PatientOut)
def create_patient(body: schemas.PatientRegistration, db: Session = Depends(get_db)):
    # Checked here as well as by the form, so a client that skips the review —
    # another integration, a second tab — cannot quietly make a second record.
    if not body.confirmed_distinct:
        matches = patient_duplicates.find(
            db, first_name=body.first_name, last_name=body.last_name,
            id_number=body.id_number, date_of_birth=body.date_of_birth, phone=body.phone)
        if matches:
            m = matches[0]
            more = f" and {len(matches) - 1} more" if len(matches) > 1 else ""
            raise HTTPException(status_code=409, detail=(
                f"{m['first_name']} {m['last_name']} ({m['profile_number'] or 'no profile number'}) "
                f"is already on file. {m['reasons'][0].lower()}{more}. Open that record, or "
                "confirm this is a different person to register them."))
    data = body.model_dump(exclude={"confirmed_distinct"})
    patient = Patient(**data)
    db.add(patient)
    db.commit()
    db.refresh(patient)
    if body.confirmed_distinct and body.possible_duplicate_of_id:
        log.info("Patient %s registered as distinct from possible duplicate %s",
                 patient.id, body.possible_duplicate_of_id)
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
def list_doctors(include_retired: bool = False, db: Session = Depends(get_db)):
    """The prescribers a script can be captured against.

    Retired ones are left out, which is what retiring is *for* and what this
    did not do. `DELETE /doctors/{id}` has always set `active` to false rather
    than deleting — the model says "Retired, never deleted", because every
    script a prescriber wrote must go on naming them — but the picker read the
    whole table, so retiring somebody changed nothing anybody could see. A
    pharmacy with 539 prescribers it cannot identify to a funder had no way to
    get them out of the list it types into forty times a morning.

    `include_retired` is for the screens that maintain the list, where the
    point is to see the ones that have been put away.
    """
    query = db.query(Doctor)
    if not include_retired:
        query = query.filter(Doctor.active.is_(True))
    return query.order_by(Doctor.name).all()


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
    for field, width in (("practice_number", 40), ("ahfoz_number", 40),
                         ("phone", 30),
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


# ---------------------------------------------------------------- bringing a
# ---------------------------------------------------------------- list in
#
# A pharmacy arriving on this system has its patients somewhere already: the
# system it is leaving, a spreadsheet a receptionist has kept for nine years,
# or a scheme's membership file. Typing four thousand of them in is not a
# migration plan, it is a reason to stay where they are.
#
# TWO PHASES, THE SAME AS STOCK.
#
# `apply=false` reads the file and says what WOULD happen, row by row, and
# writes nothing. `apply=true` does it. A bulk write nobody can preview is one
# nobody dares run, and the preview is most of the value: it is where somebody
# discovers that column D is a date in American order.

def _rows_from(raw: bytes, filename: str) -> list[dict]:
    """The uploaded file as dictionaries, whatever shape it arrived in."""
    import csv as _csv
    import io as _io

    from ..services import spreadsheet

    text, _sheet, _n = spreadsheet.read_any(raw, filename or "")
    reader = _csv.DictReader(_io.StringIO(text))
    return [{(k or "").strip().lower().replace(" ", "_"): (v or "").strip()
             for k, v in row.items()} for row in reader]


#: What a column may be called in somebody else's system. The left is ours.
ALIASES = {
    "last_name": ("last_name", "surname", "lastname", "family_name"),
    "first_name": ("first_name", "firstname", "given_name", "name", "forename"),
    "id_number": ("id_number", "id", "national_id", "identity_number"),
    "date_of_birth": ("date_of_birth", "dob", "birthday", "birth_date"),
    "phone": ("phone", "mobile", "cell", "telephone", "contact"),
    "email": ("email", "e_mail", "email_address"),
    "address": ("address", "street", "residential_address"),
    "medical_aid": ("medical_aid", "scheme", "funder", "medical_scheme"),
    "medical_aid_number": ("medical_aid_number", "member_number", "membership_number"),
    "dependent_code": ("dependent_code", "dependant_code", "suffix"),
    "allergies": ("allergies", "allergy"),
    "chronic_conditions": ("chronic_conditions", "chronic", "conditions"),
}


def _pick(row: dict, field: str) -> str:
    for name in ALIASES[field]:
        if row.get(name):
            return row[name]
    return ""


@router.post("/patients/import")
async def import_patients(
    file: UploadFile = File(...),
    apply: bool = Form(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Read a list of patients, say what would happen, and on request do it."""
    raw = await file.read()
    try:
        rows = _rows_from(raw, file.filename or "")
    except Exception as exc:
        raise HTTPException(400, f"That file could not be read: {exc}") from exc
    if not rows:
        raise HTTPException(400, "That file has no rows in it.")

    aids = {a.name.strip().lower(): a for a in db.query(MedicalAid).all()}
    plan: list[dict] = []
    made = 0

    for n, row in enumerate(rows, start=2):   # 2: row 1 is the header
        last = _pick(row, "last_name")
        first = _pick(row, "first_name")
        ident = _pick(row, "id_number")

        if not last and not first:
            plan.append({"row": n, "what": "skipped", "who": "",
                         "why": "No name in this row."})
            continue

        # The identity number is the only thing in a pharmacy's data that is
        # meant to be unique to a person, so it is what a second import is
        # matched on. Without one, a row is taken at face value: guessing that
        # two Tendai Moyos are the same person is a worse mistake than two
        # records somebody can merge.
        existing = (db.query(Patient).filter(Patient.id_number == ident).first()
                    if ident else None)
        who = f"{first} {last}".strip()
        if existing:
            plan.append({"row": n, "what": "already on file", "who": who,
                         "why": f"{ident} is {existing.first_name} "
                                f"{existing.last_name} already."})
            continue

        # A row with no identity number cannot be checked against what is
        # already here, so importing the same file twice would make a second
        # copy of this person. Said in the preview, where somebody can still
        # do something about it, rather than discovered afterwards in a list
        # with two of everybody.
        plan.append({"row": n, "what": "new patient", "who": who,
                     "why": "" if ident else
                            "No identity number, so this one cannot be checked "
                            "against the list. Importing this file again would "
                            "add them a second time."})
        if apply:
            aid = aids.get(_pick(row, "medical_aid").strip().lower())
            born = _pick(row, "date_of_birth")
            db.add(Patient(
                first_name=first, last_name=last, id_number=ident,
                date_of_birth=_a_date(born), phone=_pick(row, "phone"),
                email=_pick(row, "email"), address=_pick(row, "address"),
                allergies=_pick(row, "allergies"),
                chronic_conditions=_pick(row, "chronic_conditions"),
                medical_aid_id=aid.id if aid else None,
                medical_aid_number=_pick(row, "medical_aid_number"),
                dependent_code=_pick(row, "dependent_code") or "00",
            ))
            made += 1

    if apply:
        db.commit()
        log.info("Imported %s patient(s) from %s", made, file.filename)

    return {
        "applied": apply,
        "rows": len(rows),
        "new": sum(1 for p in plan if p["what"] == "new patient"),
        "already": sum(1 for p in plan if p["what"] == "already on file"),
        "skipped": sum(1 for p in plan if p["what"] == "skipped"),
        "unchecked": sum(1 for p in plan
                         if p["what"] == "new patient" and p["why"]),
        # The whole plan, not a sample. Somebody about to write four thousand
        # records is entitled to read all four thousand lines first.
        "plan": plan,
    }


def _a_date(said: str):
    """A date written however the other system wrote it, or nothing.

    Deliberately refuses rather than guesses between 03/04 and 04/03: a date of
    birth six months out is worse than a blank one, because a blank is asked
    about and a wrong one is trusted.
    """
    from datetime import date as _date

    said = (said or "").strip()
    if not said:
        return None
    for shape in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(said, shape).date()
        except ValueError:
            continue
    return None
