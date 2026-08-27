from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import helpers, schedule_policy, schemas
from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import (
    Branch, Dispensing, Patient, Prescription, PrescriptionItem, Product, Sale,
    SaleItem, User,
)
# `sig` is imported here, at module level, and not inside one function.
# It was imported inside the shorthand-expansion endpoint only, while three
# other places in this file called `sig.expand(...)` — including
# `create_prescription`, which is the first step of every dispensing. Every
# attempt to create a prescription raised NameError and returned 500. A local
# import satisfies the function it sits in and quietly leaves the rest of the
# module referring to a name that does not exist.
from ..services import branches, messages, sig, to_follows

router = APIRouter(prefix="/api", tags=["prescriptions"])


def _rx_loaded(query):
    """Load everything `PrescriptionOut` serialises, in a fixed few queries.

    The schema reaches for the patient, the prescriber, every item and every
    item's product. Left lazy that is four round trips per script — a hundred
    scripts became a hundred and fifty-five queries, which on a laptop is
    milliseconds and against a hosted database is sixteen seconds.

    `selectinload` for the items rather than `joinedload`: items are a
    collection, and a joined load with LIMIT applies the limit to the joined
    rows, so a script with three items would eat three of the hundred.
    """
    return query.options(
        joinedload(Prescription.patient),
        joinedload(Prescription.doctor),
        selectinload(Prescription.items).joinedload(PrescriptionItem.product),
    )


@router.get("/prescriptions", response_model=list[schemas.PrescriptionOut])
def list_prescriptions(
    patient_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = _rx_loaded(db.query(Prescription))
    if patient_id:
        query = query.filter(Prescription.patient_id == patient_id)
    return query.order_by(Prescription.created_at.desc()).limit(limit).all()



def _default_icd10(db: Session) -> str:
    """The pharmacy's default diagnosis code, if it set one.

    Read per call rather than cached, because a setting that needs a restart to
    take effect is a setting people believe is broken.
    """
    try:
        from .settings_router import get_value

        return str(get_value(db, "dispensing.default_icd10") or "").strip().upper()
    except Exception:
        # A missing or unreadable setting must never stop a script being
        # captured. No default simply means the field stays blank.
        return ""


@router.post("/prescriptions", response_model=schemas.PrescriptionOut)
def create_prescription(
    body: schemas.PrescriptionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # A draft may legitimately be empty: a pharmacist often opens a script for a
    # patient before they have read the prescriber's handwriting. The check that
    # matters happens at finalise, when it becomes something that can be
    # dispensed.
    if not body.items and not getattr(body, "draft", False):
        raise HTTPException(status_code=400, detail="Prescription needs at least one item")
    if not db.get(Patient, body.patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")

    draft = bool(getattr(body, "draft", False))
    if not draft and not body.doctor_id:
        raise HTTPException(status_code=400,
                            detail="A finalised script needs a prescriber.")
    rx = Prescription(
        # A draft takes no Rx number: the register is a numbered sequence, and a
        # number burnt on an abandoned capture leaves a gap somebody has to
        # explain. It gets one when it becomes real.
        rx_number=None if draft else helpers.next_number(db, Prescription, "RX", "rx_number"),
        draft_ref=(f"DRAFT{datetime.utcnow():%y%m%d%H%M%S}" if draft else ""),
        status="draft" if draft else "active",
        started_by_id=user.id,
        finalised_at=None if draft else datetime.utcnow(),
        patient_id=body.patient_id,
        doctor_id=body.doctor_id,
        date_prescribed=body.date_prescribed or date.today(),
        notes=body.notes,
    )
    db.add(rx)
    db.flush()
    for item in body.items:
        product = db.get(Product, item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        policy = schedule_policy.policy_for(product.schedule)
        if policy.route == "prohibited":
            raise HTTPException(
                status_code=400,
                detail=f"{product.name} is Schedule {product.schedule} and cannot be prescribed here.",
            )
        # repeats are capped by what the schedule legally allows
        repeats = schedule_policy.effective_max_repeats(product.schedule, item.repeats_allowed)
        db.add(PrescriptionItem(
            prescription_id=rx.id,
            product_id=item.product_id,
            dosage_instructions=sig.expand(db, item.dosage_instructions),
            quantity=item.quantity,
            repeats_allowed=repeats,
            repeat_interval_days=item.repeat_interval_days,
            auto_refill=item.auto_refill and repeats > 0,
            # Falls back to the pharmacy's default where the line carries
            # none, so a dispenser corrects one field rather than typing
            # the same code all day. Blank by default: a pharmacy that
            # wants every diagnosis deliberate leaves the setting empty.
            icd10_code=((item.icd10_code or "").strip().upper()
                        or _default_icd10(db)),
            supply_days=item.supply_days,
            no_claim=item.no_claim,
            not_dispensed=item.not_dispensed,
        ))
    db.commit()
    db.refresh(rx)
    return rx


@router.get("/prescriptions/{rx_id}", response_model=schemas.PrescriptionOut)
def get_prescription(rx_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    return rx


@router.post("/prescriptions/{rx_id}/dispense", response_model=schemas.SaleOut)
def dispense(
    rx_id: int,
    body: schemas.DispenseRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Dispense selected script items: stock out, register entries for S5/S6,
    repeat tracking, and a pending sale handed over to the POS for payment."""
    rx = db.get(Prescription, rx_id)
    if rx and rx.status == "draft":
        raise HTTPException(
            status_code=400,
            detail=f"{rx.draft_ref} is an unfinished script. Finish capturing it "
                   "before dispensing. A draft has no Rx number and cannot be "
                   "entered in the register.")
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")

    items = [i for i in rx.items if i.id in body.item_ids]
    if not items:
        raise HTTPException(status_code=400, detail="No valid items selected")

    # ---- schedule policy enforcement (dangerous drugs vs ordinary medicine) ----
    # A blocking counter message stops the dispense until somebody takes
    # responsibility for it by name. This is the point where it has to bite —
    # a warning shown after the medicine is handed over is not a warning.
    try:
        messages.guard_dispense(
            db, prescription_id=rx.id, patient_id=rx.patient_id,
            product_ids=[i.product_id for i in items],
            medical_aid_id=(rx.patient.medical_aid_id if rx.patient else None))
    except messages.MessageError as exc:
        raise HTTPException(status_code=409, detail={
            "error_code": "MESSAGE_UNACKNOWLEDGED", "message": str(exc)}) from exc

    highest = max((i.product.schedule or 0) for i in items)
    policy = schedule_policy.policy_for(highest)

    if policy.route == "prohibited":
        raise HTTPException(
            status_code=400,
            detail=f"Schedule {highest} substances cannot be dispensed in a retail pharmacy "
                   "without a departmental permit.",
        )
    if policy.requires_pharmacist and user.role not in ("pharmacist", "admin"):
        raise HTTPException(
            status_code=403,
            detail=f"{policy.label} must be dispensed by a pharmacist.",
        )

    # The setting has existed and been true by default while nothing read it, so
    # a dispensing could complete with no record of who checked it — which is the
    # one thing the initial is for.
    from ..routers.settings_router import get_value

    if get_value(db, "dispensing.require_pharmacist_initial"):
        initial = body.pharmacist_initial.strip()
        if not initial:
            raise HTTPException(
                status_code=400,
                detail=("Enter the initials of the pharmacist who checked this "
                        "dispensing. This is the record that somebody checked it."),
            )
        if len(initial) > 8:
            raise HTTPException(
                status_code=400,
                detail="Initials should be a few letters, not a full name.",
            )
    if policy.route == "controlled":
        missing = []
        if policy.requires_id_verification and not body.id_verified:
            missing.append("patient identity verification")
        if policy.requires_script_sighted and not body.script_sighted:
            missing.append("original prescription sighted")
        if policy.requires_prescriber_verification and not body.prescriber_verified:
            missing.append("prescriber verification")
        # Where the jurisdiction pack asks for an independent witness, this asks
        # for the checking pharmacist's initials instead. A witness is a second
        # body in the room; an initial is a name against the check, which is what
        # the record is actually for.
        if policy.requires_witness and not body.pharmacist_initial.strip():
            missing.append("the checking pharmacist's initials")
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"{policy.label} requires: {', '.join(missing)}.",
            )
        for item in items:
            allowed = schedule_policy.policy_for(item.product.schedule).max_repeats
            if allowed == 0 and (item.repeats_used > 0 or item.dispensings):
                raise HTTPException(
                    status_code=400,
                    detail=f"{item.product.name} is Schedule {item.product.schedule}, no repeats are "
                           "permitted. A fresh prescription is required.",
                )

    sale = Sale(
        sale_number=helpers.next_number(db, Sale, "INV", "sale_number"),
        patient_id=rx.patient_id,
        cashier_id=user.id,
        payment_method=body.payment_method,
        status="pending",
    )
    db.add(sale)
    db.flush()

    subtotal = vat_total = 0.0
    for position, item in enumerate(items, start=1):
        product = item.product
        is_repeat = item.repeats_used > 0 or bool(item.dispensings)
        if is_repeat and item.repeats_used >= item.repeats_allowed and item.dispensings:
            raise HTTPException(
                status_code=400,
                detail=f"{product.name}: no repeats remaining ({item.repeats_used}/{item.repeats_allowed})",
            )

        # The patient is billed for what the script says; what is actually
        # handed over may be less, and the balance becomes a debt.
        supplied = body.supply.get(item.id, item.quantity)
        if supplied < 0 or supplied > item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"{product.name}: cannot supply {supplied} of {item.quantity}.")
        owed_qty = item.quantity - supplied
        if owed_qty and (product.quantity_on_hand or 0) < supplied:
            raise HTTPException(
                status_code=400,
                detail=f"{product.name}: only {product.quantity_on_hand} in stock.")

        line_total = round(product.unit_price * item.quantity, 2)
        line_ex_vat = round(line_total / (1 + product.vat_rate), 2)
        subtotal += line_ex_vat
        vat_total += line_total - line_ex_vat
        sale_item = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            description=f"{product.name} {product.strength}".strip(),
            quantity=item.quantity,
            unit_price=product.unit_price,
            unit_cost=product.cost_price or 0.0,
            vat_rate=product.vat_rate,
            line_total=line_total,
            prescription_item_id=item.id,
        )
        db.add(sale_item)
        db.flush()

        # FEFO batch consumption — blocks expired stock from being dispensed.
        # Only what actually left the shelf moves; the owed balance is not stock
        # the pharmacy has, so it must not be deducted from stock it does have.
        if supplied:
            helpers.consume_stock_fefo(
                db, product, supplied, "sale", user.id,
                reference=rx.rx_number, sale_item_id=sale_item.id,
            )
            helpers.record_register_entry(
                db, product, -supplied, "dispense", user.id,
                patient_id=rx.patient_id, doctor_id=rx.doctor_id,
                prescription_item_id=item.id, reference=rx.rx_number,
            )
        if owed_qty:
            to_follows.record(
                db, product=product, quantity_owed=owed_qty,
                patient_id=rx.patient_id, prescription_item_id=item.id,
                sale_id=sale.id, user_id=user.id, promised_for=body.promised_for,
                notes=f"Short supply on {rx.rx_number}: "
                      f"{supplied} of {item.quantity} handed over.",
            )

        item_policy = schedule_policy.policy_for(product.schedule)
        dispensing = Dispensing(
            prescription_item_id=item.id,
            quantity=item.quantity,
            dispensed_by_id=user.id,
            is_repeat=is_repeat,
            sale_id=sale.id,
            dispense_type=item_policy.route if item_policy.route == "controlled" else "prescription",
            schedule=product.schedule or 0,
            id_verified=body.id_verified,
            id_number_seen=body.id_number_seen,
            script_sighted=body.script_sighted,
            prescriber_verified=body.prescriber_verified,
            # Stored on every dispensing, not only the controlled ones. It is the
            # line the label prints as "checked by", and a patient asking who
            # checked their medicine is not asking only about schedule 5.
            pharmacist_initial=body.pharmacist_initial.strip().upper(),
            compliance_notes=body.compliance_notes,
        )
        db.add(dispensing)

        if is_repeat:
            item.repeats_used += 1
        if item.repeats_used < item.repeats_allowed:
            item.next_repeat_date = date.today() + timedelta(days=item.repeat_interval_days)
        else:
            item.next_repeat_date = None

    sale.subtotal = round(subtotal, 2)
    sale.vat_amount = round(vat_total, 2)
    sale.total = round(subtotal + vat_total, 2)
    db.commit()
    db.refresh(sale)
    return sale


CAUTION_LABELS = {
    "antibiotic": "Complete the full course even if you feel better.",
    "drowsy": "May cause drowsiness. Do not drive or operate machinery. Avoid alcohol.",
    "food": "Take with or just after food.",
    "inhaler": "Rinse mouth after use. Shake well before each dose.",
}
DROWSY_DRUGS = ("tramadol", "zolpidem", "morphine", "cetirizine", "codeine", "amitriptyline")
ANTIBIOTICS = ("amoxicillin", "penicillin", "azithromycin", "ciprofloxacin", "doxycycline")


def _warnings(product) -> str:
    name = (product.name or "").lower()
    notes = []
    if any(a in name for a in ANTIBIOTICS):
        notes.append(CAUTION_LABELS["antibiotic"])
    if any(d in name for d in DROWSY_DRUGS) or (product.schedule or 0) >= 5:
        notes.append(CAUTION_LABELS["drowsy"])
    if "inhaler" in (product.dosage_form or "").lower():
        notes.append(CAUTION_LABELS["inhaler"])
    if any(x in name for x in ("ibuprofen", "metformin", "diclofenac")):
        notes.append(CAUTION_LABELS["food"])
    return " ".join(notes)


def _initials_of(name: str) -> str:
    """The initials a person would sign with, from their full name.

    Tolerant of how staff are actually recorded: "T. Moyo (Pharmacist)" and
    "Tendai Moyo" both give TM, because the stops, the parenthetical and the
    case are decoration.
    """
    import re as _re

    cleaned = _re.sub(r"\([^)]*\)", " ", name or "")
    parts = [p for p in _re.split(r"[^A-Za-z]+", cleaned) if p]
    return "".join(p[0] for p in parts).upper()


def _dispenser(dispensing, user) -> str:
    """Who handed the medicine over, in words a patient can read.

    The label used to print the pharmacist's initials, because the initials are
    what the checking pharmacist signed for while the login is only whoever was
    at the till. True, and useless to the person holding the box: "TM" answers
    nobody's question.

    So the full name is printed. Where an initial was recorded for somebody
    other than the logged-in user — which the shared-till case makes possible —
    it is kept alongside, because that is the one case where the two really do
    name different people and the accountability belongs to the initial.
    """
    if dispensing is None:
        return user.full_name

    full = (dispensing.dispensed_by.full_name
            if dispensing.dispensed_by else "").strip()
    initial = (dispensing.pharmacist_initial or "").strip()

    if not full:
        return initial
    if not initial or initial.upper() == _initials_of(full):
        return full
    return f"{full} ({initial})"


@router.get("/prescriptions/{rx_id}/labels", response_model=list[schemas.LabelOut])
def prescription_labels(
    rx_id: int,
    item_ids: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Dispensing-label data for a script — patient, directions, cautions, batch.

    Directions are expanded from shorthand before they leave here. A dispenser
    types `1t tds pc` because typing the sentence forty times a day is what
    makes people abbreviate the label itself — and the label is where a patient
    reads what to do. The shorthand belongs in the input; the words belong on
    the box.
    """
    sig.seed_if_empty(db)
    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    wanted = {int(i) for i in item_ids.split(",") if i.strip().isdigit()}
    items = [i for i in rx.items if not wanted or i.id in wanted]

    # Which shop is handing this over.
    #
    # Resolved once for the script rather than per item: every item on one
    # script goes out over the same counter, and asking the database again for
    # each of five boxes is five round trips for an answer that cannot change.
    branch = None
    first_dispensing = next((i.dispensings[-1] for i in items if i.dispensings), None)
    if first_dispensing is not None and first_dispensing.sale_id:
        sale = db.get(Sale, first_dispensing.sale_id)
        if sale is not None and getattr(sale, "branch_id", None):
            branch = db.get(Branch, sale.branch_id)
    if branch is None:
        # A single-shop pharmacy has one branch and never chose it. Falling back
        # to the default is what makes the address on the sticker right for the
        # nine pharmacies in ten that will never open a second counter.
        branch = branches.default_branch(db)

    def _address(b) -> str:
        """Street and city, without saying the city twice.

        Pharmacies write the town into the address field — "114 Samora Machel
        Avenue, Harare" — and appending the city column to that gives
        "…Harare, Harare" on every sticker printed.
        """
        street = (b.address or "").strip().rstrip(",")
        city = (b.city or "").strip()
        if not city or street.lower().endswith(city.lower()):
            return street
        return f"{street}, {city}" if street else city

    branch_address = _address(branch) if branch else ""

    labels = []
    for position, item in enumerate(items, start=1):
        product = item.product
        dispensing = item.dispensings[-1] if item.dispensings else None
        batch_number = expiry = None
        if dispensing and dispensing.sale_id:
            sale_item = (
                db.query(SaleItem)
                .filter(SaleItem.sale_id == dispensing.sale_id, SaleItem.product_id == product.id)
                .first()
            )
            allocation = sale_item.allocations[0] if sale_item and sale_item.allocations else None
            if allocation and allocation.batch:
                batch_number = allocation.batch.batch_number
                expiry = allocation.batch.expiry_date

        labels.append(schemas.LabelOut(
            patient_name=f"{rx.patient.first_name} {rx.patient.last_name}",
            patient_id_number=rx.patient.id_number,
            rx_number=rx.rx_number,
            product_name=product.name,
            strength=product.strength,
            dosage_form=product.dosage_form,
            quantity=item.quantity,
            dosage_instructions=sig.expand(db, item.dosage_instructions) or "As directed by your doctor",
            warnings=_warnings(product),
            schedule=product.schedule or 0,
            batch_number=batch_number or "",
            expiry_date=expiry,
            repeats_remaining=max(0, item.repeats_allowed - item.repeats_used),
            next_repeat_date=item.next_repeat_date,
            doctor_name=rx.doctor.name if rx.doctor else "",
            dispensed_by=_dispenser(dispensing, user),
            dispensed_at=(dispensing.dispensed_at if dispensing else datetime.utcnow()),
            pharmacy_name=settings.PHARMACY_NAME,
            pharmacy_reg_no=settings.PHARMACY_REG_NO,
            pharmacy_address=settings.PHARMACY_ADDRESS,
            pharmacy_phone=settings.PHARMACY_PHONE,
            item_number=position,
            item_count=len(items),
            doctor_practice_no=(rx.doctor.practice_number or "") if rx.doctor else "",
            unit_price=round(product.unit_price or 0.0, 2),
            line_total=round((product.unit_price or 0.0) * (item.quantity or 0), 2),
            branch_code=(branch.code or "") if branch else "",
            # The branch's own name and number where it has them, the company's
            # where it does not — an empty line on a sticker is worse than a
            # slightly less specific one.
            branch_name=(branch.name or settings.PHARMACY_NAME) if branch else settings.PHARMACY_NAME,
            branch_address=branch_address or settings.PHARMACY_ADDRESS,
            branch_phone=((branch.phone or "") if branch else "") or settings.PHARMACY_PHONE,
            branch_reg_no=((branch.registration_no or "") if branch else "") or settings.PHARMACY_REG_NO,
            dispensing_id=dispensing.id if dispensing else None,
        ))
    return labels


@router.get("/repeats/due", response_model=list[schemas.PrescriptionItemOut])
def repeats_due(days: int = 7, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    horizon = date.today() + timedelta(days=days)
    # The row is a script line, and the screen shows the medicine and the
    # patient beside it. Both were fetched one at a time: two hundred and thirty
    # lines came to three hundred and eighty-four queries and thirty-five
    # seconds in production, for a list a pharmacist opens every morning.
    return (
        db.query(PrescriptionItem)
        .options(
            joinedload(PrescriptionItem.product),
            joinedload(PrescriptionItem.prescription)
            .joinedload(Prescription.patient),
        )
        .filter(
            PrescriptionItem.next_repeat_date.isnot(None),
            PrescriptionItem.next_repeat_date <= horizon,
            PrescriptionItem.repeats_used < PrescriptionItem.repeats_allowed,
        )
        .order_by(PrescriptionItem.next_repeat_date)
        .all()
    )


# ---------------------------------------------------------------------------
# Unfinished scripts
#
# A capture interrupted by the phone, a query, or a patient who has gone back to
# the car for their card. The alternative to resuming is re-keying, and re-keying
# is where dispensing errors come from.
# ---------------------------------------------------------------------------

# Two segments so it cannot be swallowed by /prescriptions/{rx_id}, which is
# registered earlier and would otherwise match "unfinished" as an id.
@router.get("/prescriptions/queue/unfinished",
            response_model=list[schemas.PrescriptionOut])
def unfinished(mine_only: bool = False, limit: int = 100,
               db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """Scripts started and not finished. Oldest first, the stalest is the risk."""
    query = _rx_loaded(db.query(Prescription)).filter(Prescription.status == "draft")
    if mine_only:
        query = query.filter(Prescription.started_by_id == user.id)
    return query.order_by(Prescription.updated_at).limit(limit).all()


@router.put("/prescriptions/{rx_id}/draft", response_model=schemas.PrescriptionOut)
def save_draft(rx_id: int, body: schemas.PrescriptionCreate,
               db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """Replace what a draft holds. This is what Temp Save writes.

    The item list is replaced wholesale rather than merged: a pharmacist editing
    a draft has the whole script in front of them, and a merge would silently
    keep a line they had just deleted.
    """
    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if rx.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"{rx.rx_number} is already a finished script. Use Alter Script "
                   "to change it, so the change is recorded rather than overwritten.")

    rx.patient_id = body.patient_id or rx.patient_id
    rx.doctor_id = body.doctor_id
    rx.notes = body.notes
    rx.date_prescribed = body.date_prescribed or rx.date_prescribed
    rx.updated_at = datetime.utcnow()

    for existing in list(rx.items):
        db.delete(existing)
    db.flush()
    for item in body.items:
        product = db.get(Product, item.product_id)
        if not product:
            raise HTTPException(status_code=404,
                                detail=f"Product {item.product_id} not found")
        repeats = schedule_policy.effective_max_repeats(product.schedule,
                                                        item.repeats_allowed)
        db.add(PrescriptionItem(
            prescription_id=rx.id, product_id=item.product_id,
            dosage_instructions=sig.expand(db, item.dosage_instructions), quantity=item.quantity,
            repeats_allowed=repeats, repeat_interval_days=item.repeat_interval_days,
            auto_refill=item.auto_refill and repeats > 0,
            # Falls back to the pharmacy's default where the line carries
            # none, so a dispenser corrects one field rather than typing
            # the same code all day. Blank by default: a pharmacy that
            # wants every diagnosis deliberate leaves the setting empty.
            icd10_code=((item.icd10_code or "").strip().upper()
                        or _default_icd10(db)),
            supply_days=item.supply_days, no_claim=item.no_claim,
            not_dispensed=item.not_dispensed,
        ))
    db.commit()
    db.refresh(rx)
    return rx


@router.post("/prescriptions/{rx_id}/finalise", response_model=schemas.PrescriptionOut)
def finalise(rx_id: int, db: Session = Depends(get_db),
             _user: User = Depends(get_current_user)):
    """Turn a draft into a real script, taking the next Rx number as it does.

    The checks that were skipped while it was a draft happen here, at the point
    the script becomes something that can be dispensed and entered in a register.
    """
    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if rx.status != "draft":
        raise HTTPException(status_code=400, detail=f"{rx.rx_number} is already finished.")
    if not rx.doctor_id:
        raise HTTPException(status_code=400,
                            detail="A script needs a prescriber before it can be finished.")
    if not rx.items:
        raise HTTPException(status_code=400,
                            detail="A script with no items cannot be finished.")
    for item in rx.items:
        policy = schedule_policy.policy_for(item.product.schedule)
        if policy.route == "prohibited":
            raise HTTPException(
                status_code=400,
                detail=f"{item.product.name} is {policy.code} and cannot be "
                       "dispensed here.")

    rx.rx_number = helpers.next_number(db, Prescription, "RX", "rx_number")
    rx.status = "active"
    rx.finalised_at = datetime.utcnow()
    rx.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(rx)
    return rx


@router.delete("/prescriptions/{rx_id}/draft")
def discard_draft(rx_id: int, db: Session = Depends(get_db)):
    """Throw a draft away. Only ever a draft. A real script is cancelled, not deleted."""
    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if rx.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"{rx.rx_number} is a finished script and cannot be deleted. "
                   "A dispensed script is a record.")
    ref = rx.draft_ref
    db.delete(rx)
    db.commit()
    return {"discarded": ref}
