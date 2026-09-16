from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import helpers, schedule_policy, schemas

#: Which capability each dispensing route needs.
#:
#: Routes are stable across jurisdiction packs — otc, prescription, controlled,
#: prohibited — while the schedules behind them are not, which is why this keys
#: on the route rather than on a schedule number.
#:
#: `prohibited` is absent on purpose: it is refused above this check for
#: everybody, including an administrator, and giving it a capability would imply
#: somewhere a pharmacy could switch it on.
ROUTE_CAPABILITY = {
    "otc": "dispense.otc",
    "prescription": "dispense.prescription",
    "controlled": "dispense.controlled",
}
from ..auth import get_current_user
from ..config import settings
from ..database import get_db

import logging

log = logging.getLogger("rx5000.dispensing")
from ..models import (
    Branch, Dispensing, Patient, Pharmacy, Prescription, PrescriptionItem,
    PriceOverride, Product, Sale, SaleItem, User,
)
# `sig` is imported here, at module level, and not inside one function.
# It was imported inside the shorthand-expansion endpoint only, while three
# other places in this file called `sig.expand(...)` — including
# `create_prescription`, which is the first step of every dispensing. Every
# attempt to create a prescription raised NameError and returned 500. A local
# import satisfies the function it sits in and quietly leaves the rest of the
# module referring to a name that does not exist.
from ..services import (branches, claims_engine, counselling, holds, messages, paging,
                        permissions, proppharm,
                        sig, to_follows)

router = APIRouter(prefix="/api", tags=["prescriptions"])


def _hand_set_price(db: Session, user: User, override_id, product_id: int,
                    rx_id: int | None = None):
    """Turn "this line was authorised at another price" into the price itself.

    The browser quotes a record id, never a figure. The figure is read off the
    row that was written when somebody's code was accepted, which is the whole
    reason the code was asked for: a client free to name its own price has
    walked round the password rather than through it.

    Refuses somebody else's authorisation, an authorisation for a different
    medicine, and one already spent on somebody else's line — the three ways a
    single approval could otherwise be turned into a standing discount.

    It does *not* refuse the line it is already on. A draft is saved by
    replacing every item, and the same script is temp-saved and then finished, so
    a strictly single-use rule would have made Temp Save destroy the price it had
    just been given a password for.
    """
    if not override_id:
        return None, None
    row = db.get(PriceOverride, int(override_id))
    if row is None:
        raise HTTPException(status_code=404,
                            detail="That price authorisation could not be found.")
    if row.requested_by_id != user.id:
        raise HTTPException(status_code=403,
                            detail="That price authorisation was issued to somebody else.")
    if row.product_id != product_id:
        raise HTTPException(
            status_code=400,
            detail="That price authorisation was given for a different medicine.")
    if row.prescription_item_id:
        held = db.get(PrescriptionItem, row.prescription_item_id)
        # Gone, or on this very script: this is the same line being rewritten,
        # not a second line helping itself to one approval.
        if held is not None and (rx_id is None or held.prescription_id != rx_id):
            raise HTTPException(status_code=409,
                                detail="That price authorisation has already been used.")
    return row, float(row.now)


@router.post("/prescriptions/{rx_id}/items/{item_id}/price")
def set_a_line_price(rx_id: int, item_id: int,
                     price_override_id: int = Body(..., embed=True),
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Put an authorised price onto a line that is already on the server.

    A script waiting on the worklist is dispensed *as itself* — the screen does
    not re-create it, it fetches it — so a price set on one of its lines had
    nowhere to go and was silently dropped at Finish. The patient was quoted one
    figure on screen and charged another at the till, which is the worst
    possible way for this to fail.

    The authorisation is checked here exactly as it is on capture. Nothing about
    a line already existing makes it cheaper to change its price.
    """
    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    line = db.get(PrescriptionItem, item_id)
    if not line or line.prescription_id != rx.id:
        raise HTTPException(status_code=404, detail="That line is not on this script.")
    if rx.status in ("cancelled", "dispensed"):
        raise HTTPException(
            status_code=400,
            detail=f"This script is {rx.status}. Its prices are what it was dispensed at.")

    authorised, hand_set = _hand_set_price(db, user, price_override_id,
                                           line.product_id, rx_id=rx.id)
    line.unit_price_override = hand_set
    if authorised:
        authorised.prescription_item_id = line.id
        authorised.used_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "item_id": line.id, "unit_price": hand_set}


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



@router.post("/claim-estimate")
def claim_estimate(patient_id: int | None = Body(default=None),
                   items: list[dict] = Body(default=[]),
                   medical_aid_id: int | None = Body(default=None),
                   member_number: str = Body(default=""),
                   db: Session = Depends(get_db),
                   _: User = Depends(get_current_user)):
    """What the scheme will carry and what the patient will owe, before dispensing.

    Asked while the script is being built, so the dispenser can hand over the
    bag and say "that is four dollars at the till" instead of the till operator
    discovering it in front of a queue.

    It calls the same rule the adjudication calls. Two implementations of "what
    does the scheme cover" would disagree eventually, and the day they disagreed
    somebody would be asked for the wrong amount.
    """
    patient = db.get(Patient, patient_id) if patient_id else None
    rows = []
    for line in items:
        product = db.get(Product, int(line.get("product_id") or 0))
        if product:
            rows.append((product, int(line.get("quantity") or 1)))
    # The scheme and member number chosen in Finish, where they are not (yet) on
    # the patient's record: a card shown at the counter. Estimated against them
    # without saving anything — the record is only changed when the script is
    # actually dispensed on that claim.
    if medical_aid_id:
        from types import SimpleNamespace

        from ..models import MedicalAid
        scheme = db.get(MedicalAid, medical_aid_id)
        if scheme:
            patient = SimpleNamespace(medical_aid_id=scheme.id, medical_aid=scheme,
                                      medical_aid_number=(member_number or "").strip())
    return claims_engine.estimate(db, patient, rows)


# ---------------------------------------------------------------------------
# The script table
#
# Every script the pharmacy holds, searchable by the number on it. See
# services/scripts.py for why there was no such screen and what a script ID is.
# ---------------------------------------------------------------------------

# Registered above /prescriptions/{rx_id}, which would otherwise match "table"
# as an id and answer 422 to a perfectly good request.
@router.get("/prescriptions/table")
def script_table(q: str = "", status: str = "", patient_id: int = 0,
                 doctor_id: int = 0, days: int = 0, altered_only: bool = False,
                 page: int = 1, per_page: int = paging.DEFAULT_PER_PAGE,
                 db: Session = Depends(get_db),
                 _: User = Depends(get_current_user)):
    """Scripts, newest first, searched by number, patient, ID or prescriber."""
    from ..services import scripts

    query = scripts.search(db, q=q, status=status, patient_id=patient_id,
                           doctor_id=doctor_id, days=days,
                           altered_only=altered_only)
    result = paging.page(query, page=page, per_page=per_page)
    return {**result.envelope(), "items": scripts.rows(db, result.items)}


# ---- holds (services/holds.py) ----------------------------------------------
# The clearing route is registered here, above every /prescriptions/{rx_id}
# route, so "holds" is never read as a script id.
@router.post("/prescriptions/holds/{hold_id}/clear")
def clear_hold(hold_id: int, note: str = Body(default="", embed=True),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Release a held script. A pharmacist or a manager."""
    from ..models import PrescriptionHold

    hold = db.get(PrescriptionHold, hold_id)
    if not hold:
        raise HTTPException(status_code=404, detail="That hold was not found.")
    try:
        holds.clear(db, hold=hold, note=note, user=user)
    except holds.HoldError as exc:
        status = 403 if user.role not in holds.CLEARERS else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    db.commit()
    return holds.summarise(db, hold)


@router.get("/prescriptions/holds/reasons")
def hold_reasons():
    """The reason codes, in the order they are offered."""
    return [{"code": code, "label": label} for code, label in holds.REASONS.items()]


# Registered above /prescriptions/{rx_id} for the same reason as the one above:
# it would otherwise match "next-number" as an id and answer 422.
@router.get("/prescriptions/next-number")
def next_script_number(db: Session = Depends(get_db),
                       _: User = Depends(get_current_user)):
    """The number the next script will take, so the screen can show it on open.

    A prediction, not a reservation. Nothing is written and nothing is held:
    this reads the highest number issued this month and walks to the first free
    one, which is exactly what the capture does when it writes. Two tills
    asking at the same moment are told the same number, and whichever dispenses
    first takes it — so the screen presents it as the number this script will
    be given, not one it already owns.

    Reserving would be the alternative and it is worse: every script started
    and abandoned would burn a number, and a hole in a numbered register is
    precisely what an inspector asks about. See `helpers.next_number` for why
    counting rows is wrong.
    """
    return {"number": helpers.next_number(db, Prescription, "RX", "rx_number")}


@router.get("/prescriptions/{rx_id}/full")
def script_detail(rx_id: int, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    """One script: its lines, what has been dispensed, and every alteration.

    A separate path from `/prescriptions/{rx_id}`, which answers the capture
    shape the dispensing screen expects. Changing that one to carry the trail
    would put an alteration history on every keystroke of a script being built.
    """
    from ..services import scripts

    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Script not found")
    return scripts.detail(db, rx)


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
    # The whole script's products in one query.
    on_script = {p.id: p for p in db.query(Product)
                 .filter(Product.id.in_([i.product_id for i in body.items])).all()}
    for item in body.items:
        product = on_script.get(item.product_id)
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
        authorised, hand_set = _hand_set_price(db, user, item.price_override_id,
                                               item.product_id)
        line = PrescriptionItem(
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
            unit_price_override=hand_set,
        )
        db.add(line)
        if authorised:
            # Flushed so the override can point at the line it paid for. Without
            # the id the trail says a price was approved and not which line it
            # reached, which is the question that gets asked.
            db.flush()
            authorised.prescription_item_id = line.id
            authorised.used_at = datetime.utcnow()
    db.commit()
    db.refresh(rx)
    return rx


@router.get("/prescriptions/{rx_id}", response_model=schemas.PrescriptionOut)
def get_prescription(rx_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    return rx


@router.get("/prescriptions/{rx_id}/holds")
def list_holds(rx_id: int, db: Session = Depends(get_db),
               _: User = Depends(get_current_user)):
    """Every hold this script has had, newest first. The open one, if any, first."""
    from ..models import PrescriptionHold

    if not db.get(Prescription, rx_id):
        raise HTTPException(status_code=404, detail="Prescription not found")
    rows = (db.query(PrescriptionHold)
            .filter(PrescriptionHold.prescription_id == rx_id)
            .order_by(PrescriptionHold.placed_at.desc()).all())
    return [holds.summarise(db, h) for h in rows]


@router.post("/prescriptions/{rx_id}/holds")
def place_hold(rx_id: int, reason_code: str = Body(...), note: str = Body(default=""),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Put a script down, with the reason, until somebody releases it."""
    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if rx.status == "draft":
        raise HTTPException(status_code=400, detail=(
            f"{rx.draft_ref or 'This script'} is still being captured. Save it for later "
            "instead. A hold is for a script that could otherwise be dispensed."))
    try:
        hold = holds.place(db, prescription=rx, reason_code=reason_code, note=note, user=user)
    except holds.HoldError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return holds.summarise(db, hold)


@router.post("/prescriptions/{rx_id}/cancel")
def cancel_script(rx_id: int, reason: str = Body(..., embed=True),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Take a script that was never dispensed off the worklist, with the reason."""
    from ..services import script_cancel

    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    try:
        script_cancel.cancel(db, rx=rx, reason=reason, user=user)
    except script_cancel.CancelError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    db.commit()
    return {"id": rx.id, "rx_number": rx.rx_number, "status": rx.status}


@router.post("/prescriptions/{rx_id}/dispense", response_model=schemas.SaleOut)
def dispense(
    rx_id: int,
    body: schemas.DispenseRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Dispense selected script items: stock out, register entries for S5/S6,
    repeat tracking, and a pending sale handed over to the POS for payment."""
    # One dispensing of a script at a time. Pressed from two terminals at once,
    # both requests found no dispensing yet and both went out. Taken before the
    # script is read, so what is read below is what the other request committed.
    from .. import concurrency
    concurrency.serialise(db, f"dispense:{rx_id}")
    rx = db.get(Prescription, rx_id)
    if rx and rx.status == "draft":
        raise HTTPException(
            status_code=400,
            detail=f"{rx.draft_ref} is an N-Repeat. Finish capturing it "
                   "before dispensing. It has no Rx number yet and cannot be "
                   "entered in the register.")
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    # Cancelled means it does not go out — reached by a link, an old tab, or a
    # screen opened before somebody cancelled it.
    if rx.status == "cancelled":
        raise HTTPException(status_code=400, detail=(
            f"{rx.rx_number or 'This script'} was cancelled and cannot be dispensed. "
            "Capture a new script if it is needed after all."))

    # A held script does not go out, whatever the screen that sent this thinks.
    # Somebody stopped it for a reason, and releasing it is a decision about
    # that reason, not a side effect of pressing Dispense.
    held = holds.open_hold(db, rx.id)
    if held:
        summary = holds.summarise(db, held)
        raise HTTPException(status_code=409, detail=(
            f"{rx.rx_number or 'This script'} is on hold. {summary['reason'].lower()}"
            + (f", placed by {summary['placed_by']}" if summary["placed_by"] else "")
            + ". A pharmacist or a manager clears the hold before it can be dispensed."))

    items = [i for i in rx.items if i.id in body.item_ids]
    if not items:
        raise HTTPException(status_code=400, detail="No valid items selected")

    # ---- schedule policy enforcement (dangerous drugs vs ordinary medicine) ----
    # A blocking counter message stops the dispense until somebody takes
    # responsibility for it by name. This is the point where it has to bite —
    # a warning shown after the medicine is handed over is not a warning.
    # Acknowledged at the counter, before this script existed. A new script is
    # created and dispensed in one act, so there was never an id to record the
    # acknowledgement against until now — and without this, a patient with an
    # allergy match could not be dispensed that medicine from the dispensary at
    # all. Recorded in the dispensing user's name; only what is actually
    # blocking this dispensing is taken, so an id sent here cannot be used to
    # wave through something else.
    if body.acknowledged_message_ids:
        found = messages.for_dispensing(
            db, patient_id=rx.patient_id,
            product_ids=[i.product_id for i in items],
            medical_aid_id=(rx.patient.medical_aid_id if rx.patient else None))
        blocking_ids = {m["id"] for m in found["blocking"]}
        already = messages.acknowledged_ids(db, rx.id)
        for message_id in sorted(set(body.acknowledged_message_ids) & (blocking_ids - already)):
            messages.acknowledge(
                db, message_id=message_id, prescription_id=rx.id, user_id=user.id,
                note="Acknowledged at the counter; recorded on dispensing.")

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
    # Two separate questions, and the stricter one wins.
    #
    # First: does this person hold the capability for this route? That is the
    # pharmacy's own rule, it lives on the role matrix, and it can be granted to
    # a named person for a reason with an end date. It is the question the three
    # tabs on the dispensary ask, asked again here — the tab is a courtesy, this
    # is the rule, and they read the same capability so they cannot drift.
    #
    # The schedule chooses the capability through the jurisdiction's own route,
    # so a pack that reclassifies a substance moves the permission with it.
    needed = ROUTE_CAPABILITY.get(policy.route)
    if needed:
        decision = permissions.check(db, user, needed)
        if not decision["allowed"]:
            raise HTTPException(status_code=403, detail=decision["why"])

    # Second: the law. `requires_pharmacist` is about somebody's registration,
    # not about what this pharmacy has chosen to allow, so it is checked
    # separately and cannot be ticked away on the matrix. A capability that
    # became a route around the Medicines Act would be worse than no capability.
    if policy.requires_pharmacist and user.role not in ("pharmacist", "admin"):
        raise HTTPException(
            status_code=403,
            detail=f"{policy.label} must be dispensed by a pharmacist.",
        )

    # The setting has existed and been true by default while nothing read it, so
    # a dispensing could complete with no record of who checked it, which is the
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

    # What the patient was told. Required when the pharmacy says so for this
    # script (CareXpress blueprint §5; when is §13's open decision, so it is a
    # setting). Unknown points are dropped rather than refused: the list is the
    # server's, and a stale client should not stop a dispensing over a label.
    counselled_points = counselling.clean(body.counselling_points)
    counselled_notes = (body.counselling_notes or "").strip()
    if counselling.required(db, controlled=policy.route == "controlled") and not counselled_points:
        raise HTTPException(status_code=400, detail=(
            "Record the counselling given before dispensing. Tick the points the "
            "patient was told. This pharmacy requires it"
            + (" for controlled medicines." if counselling.rule(db) == "controlled" else ".")))

    # The packs, scanned against the script (blueprint §5, §8). Every code sent
    # is resolved again here and must be that line's medicine: the screen's word
    # that a pack matched is not taken, because a check that can be claimed is
    # not a check. Done before anything is built, so a wrong pack refuses the
    # dispensing cleanly.
    from .scan_router import _match as match_scanned
    from ..services import barcodes as bc

    scanned: dict[int, str] = {}
    for item in items:
        code = (body.scanned_codes.get(item.id) or "").strip()
        if not code:
            continue
        found, _mult, _on = match_scanned(db, bc.read(code).keys)
        if not found or found.id != item.product_id:
            raise HTTPException(status_code=400, detail=(
                f"The pack scanned for {item.product.name} is "
                + (f"{found.name}" if found else "not a medicine this pharmacy stocks")
                + ". Scan the right pack, or clear the scan."))
        scanned[item.id] = code[:64]
    from .settings_router import get_value as setting

    if setting(db, "dispensing.require_scan_check"):
        unscanned = [i.product.name for i in items if i.id not in scanned]
        if unscanned:
            raise HTTPException(status_code=400, detail=(
                "Scan each pack against the script before dispensing. Not yet scanned: "
                + ", ".join(unscanned) + "."))

    # Paid by medical aid, chosen at Finish: checked before anything is built, so
    # a missing member number refuses the dispensing cleanly rather than leaving
    # a sale with a claim that cannot be raised.
    chosen_scheme = None
    if body.claim:
        from ..models import MedicalAid

        chosen_scheme = db.get(MedicalAid, body.claim.medical_aid_id)
        if not chosen_scheme:
            raise HTTPException(status_code=400, detail="Choose the medical aid scheme to claim from.")
        if not body.claim.member_number.strip():
            raise HTTPException(status_code=400, detail=(
                f"Enter the {chosen_scheme.name} member number from the patient's card."))
        if body.claim.hold and len(body.claim.hold_reason.strip()) < 3:
            raise HTTPException(status_code=400, detail="Say why the claim is being held.")

    # The expiry read off the pack, for stock that arrived without one. Written
    # onto the undated stock before anything is drawn, inside this transaction —
    # so a dispensing that fails later leaves the batch as it was. A pack already
    # out of date is refused here, by name: the date was asked for to stop
    # exactly that pack going out.
    for item in items:
        expiry = body.pack_expiries.get(item.product_id)
        if not expiry:
            continue
        if expiry < date.today():
            raise HTTPException(status_code=400, detail=(
                f"The pack of {item.product.name} expired on {expiry:%d %b %Y}. "
                "Take another pack from the shelf."))
        helpers.date_undated_stock(db, item.product, expiry, user.id)

    sale = Sale(
        sale_number=helpers.next_number(db, Sale, "INV", "sale_number"),
        patient_id=rx.patient_id,
        cashier_id=user.id,
        payment_method=body.payment_method,
        status="pending",
        # Carried on the sale, not on the moment: the billing often goes to the
        # till and is printed by somebody who never met the patient.
        receipt_private=bool(getattr(body, "receipt_private", False)),
    )
    db.add(sale)
    db.flush()

    subtotal = vat_total = 0.0
    for position, item in enumerate(items, start=1):
        product = item.product
        is_repeat = item.repeats_used > 0 or bool(item.dispensings)
        # The count is the authority, with or without local history.
        #
        # This also required `item.dispensings`, so a line carrying
        # `5 used of 5` but no dispensing rows of ours sailed past and was
        # dispensed a sixth time. That is precisely the shape of an imported or
        # migrated script: the counter came across, the history did not. The
        # check that exists to stop a script going out more often than the
        # prescriber allowed was disabled for exactly the scripts whose history
        # this pharmacy cannot see.
        #
        # The schedule check twenty lines above already uses `or` for the same
        # pair. This one used `and`, and one row in this database reached
        # six of five because of it.
        if is_repeat and item.repeats_used >= item.repeats_allowed:
            raise HTTPException(
                status_code=400,
                detail=f"{product.name}: no repeats remaining "
                       f"({item.repeats_used}/{item.repeats_allowed}). "
                       f"A fresh prescription is required.",
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

        # Priced per UNIT, because `item.quantity` is a count of tablets.
        #
        # `product.unit_price` is what a PACK sells for despite its name, so
        # multiplying it by thirty charged a patient for thirty tubs. Nine
        # capsules of amoxicillin came to $274.50 on a $50 tub.
        #
        # The cost follows the same divisor, and it has to be the same divisor:
        # a price per unit against a cost per pack would report a margin of
        # minus several thousand percent and look like a pricing error rather
        # than an arithmetic one.
        #
        # A price set by hand at capture stands instead of the shelf price, and
        # only because a `PriceOverride` row says somebody authorised it. Read
        # off the line, not off the request: by the time it gets here the figure
        # has been through a password, and the browser is not asked again.
        per_unit = item.billed_per_unit()
        line_total = round(per_unit * item.quantity, 2)
        line_ex_vat = round(line_total / (1 + product.vat_rate), 2)
        subtotal += line_ex_vat
        vat_total += line_total - line_ex_vat
        sale_item = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            description=f"{product.name} {product.strength}".strip(),
            quantity=item.quantity,
            # Stored per unit, so a line re-read later reprices to what was
            # actually charged rather than to what the pack costs today.
            unit_price=per_unit,
            unit_cost=product.unit_cost(),
            vat_rate=product.vat_rate,
            line_total=line_total,
            prescription_item_id=item.id,
        )
        db.add(sale_item)
        db.flush()

        # The authorisation follows the money. Asked in six weeks' time who
        # discounted this sale, the answer is one join rather than a search
        # through scripts for a line that happens to match.
        if item.unit_price_override is not None:
            (db.query(PriceOverride)
             .filter(PriceOverride.prescription_item_id == item.id,
                     PriceOverride.sale_item_id.is_(None))
             .update({"sale_item_id": sale_item.id}, synchronize_session=False))

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
            counselling_points=",".join(counselled_points),
            counselling_notes=counselled_notes,
            counselled_by_id=user.id if (counselled_points or counselled_notes) else None,
            scan_code=scanned.get(item.id, ""),
            scan_verified=item.id in scanned,
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

    # Bill the scheme here, while the patient is still at the dispensary.
    #
    # The claim used to be raised at the till, which meant the pending sale
    # carried one gross figure and nobody could tell the patient what they
    # owed until they had walked to the counter and queued. Adjudicating now
    # means the dispenser says "that is four dollars at the till" while
    # handing the bag over, and the till collects a figure that is already
    # known rather than discovering it in front of the customer.
    #
    # Deliberately non-fatal. The medicine has left the shelf and the register
    # entry is written; a scheme that cannot be reached must not undo that. A
    # claim that could not be raised is held, which is the state the claiming
    # screens exist to work through.
    patient = rx.patient
    if patient is not None and body.claim and chosen_scheme is not None:
        # Paid by medical aid, chosen at Finish. The card at the counter is the
        # authority: the patient's record takes its scheme and number, so the
        # claim, the next dispensing and the patient's page all agree with it.
        changed = (patient.medical_aid_id != chosen_scheme.id
                   or (patient.medical_aid_number or "") != body.claim.member_number.strip()
                   or (patient.dependent_code or "00") != (body.claim.dependent_code or "00"))
        patient.medical_aid_id = chosen_scheme.id
        patient.medical_aid_number = body.claim.member_number.strip()
        patient.dependent_code = (body.claim.dependent_code or "00").strip() or "00"
        if changed:
            log.info("Medical aid on patient %s set from the card at dispensing: %s %s",
                     patient.id, chosen_scheme.name, patient.medical_aid_number)
        db.flush()
        if body.claim.hold:
            claims_engine.defer_claim(db, sale, patient, body.claim.hold_reason.strip())
        else:
            try:
                claims_engine.submit_claim(db, sale, patient)
            except Exception as exc:                   # noqa: BLE001
                log.warning("claim for %s could not be raised: %s", rx.rx_number, exc)
                claims_engine.defer_claim(
                    db, sale, patient,
                    "Could not be adjudicated when dispensed; held at the counter.")
    elif patient is not None and patient.medical_aid_id:
        try:
            claims_engine.submit_claim(db, sale, patient)
        except Exception as exc:                       # noqa: BLE001
            log.warning("claim for %s could not be raised: %s", rx.rx_number, exc)
            try:
                claims_engine.defer_claim(
                    db, sale, patient,
                    "Could not be adjudicated when dispensed; held at the counter.")
            except Exception:                          # noqa: BLE001
                pass

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
    other than the logged-in user, which the shared-till case makes possible —
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
    makes people abbreviate the label itself, and the label is where a patient
    reads what to do. The shorthand belongs in the input; the words belong on
    the box.
    """
    sig.seed_if_empty(db)
    # The label is expanded from whatever is in the book, and the Proppharm
    # vocabulary is half of it now. Short-circuits on one indexed lookup once
    # the import has run, so this is not a cost per label.
    proppharm.seed(db)
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
        Avenue, Harare", and appending the city column to that gives
        "…Harare, Harare" on every sticker printed.
        """
        street = (b.address or "").strip().rstrip(",")
        city = (b.city or "").strip()
        if not city or street.lower().endswith(city.lower()):
            return street
        return f"{street}, {city}" if street else city

    branch_address = _address(branch) if branch else ""
    # Whose pharmacy this is: their own record, not the server's defaults.
    from ..services import pharmacy_identity
    identity = pharmacy_identity.of(db)

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

        # A medicine label names the batch it came from and when that batch
        # expires, or it does not print. It used to print regardless, with the
        # batch and expiry lines simply left off — so a box could leave the
        # counter carrying nothing a recall could be traced by, and nobody would
        # know until the recall. Refused here, with the reason a dispenser can
        # act on, and refused again in the browser in case this is an older
        # server that sends no verdict.
        if dispensing is None:
            blocked_reason = ("Not dispensed yet. A label names the batch it was "
                              "dispensed from, so it prints once this line has gone out.")
        elif not batch_number:
            blocked_reason = ("No batch was recorded when this line was dispensed, "
                              "and a medicine label must name its batch.")
        elif expiry is None:
            blocked_reason = (f"Batch {batch_number} has no expiry date on file. "
                              "Add it to the batch, then print.")
        else:
            blocked_reason = ""

        labels.append(schemas.LabelOut(
            printable=not blocked_reason,
            blocked_reason=blocked_reason,
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
            pharmacy_name=identity["name"],
            pharmacy_reg_no=identity["reg_no"],
            pharmacy_address=identity["address"],
            pharmacy_phone=identity["phone"],
            manufacturer=(product.manufacturer or ""),
            item_number=position,
            item_count=len(items),
            doctor_practice_no=(rx.doctor.practice_number or "") if rx.doctor else "",
            # Per unit, matching what the sale actually charged. This read the
            # pack price, so a label for twenty-one capsules said $1,050.
            unit_price=round(item.billed_per_unit(), 2),
            line_total=round(item.billed_per_unit() * (item.quantity or 0), 2),
            branch_code=(branch.code or "") if branch else "",
            # The branch's own name and number where it has them, the company's
            # where it does not — an empty line on a sticker is worse than a
            # slightly less specific one.
            branch_name=((branch.name or "") if branch else "") or identity["name"],
            branch_address=branch_address or identity["address"],
            branch_phone=((branch.phone or "") if branch else "") or identity["phone"],
            branch_reg_no=((branch.registration_no or "") if branch else "") or identity["reg_no"],
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
# N-Repeats — scripts captured but not finished, so holding no Rx number
#
# Called "unfinished" until the dispensary asked for the trade's own name. The
# route keeps its path: an endpoint is not a label, and renaming a URL breaks
# every bookmark, integration and cached client for a word nobody sees.
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
        authorised, hand_set = _hand_set_price(db, user, item.price_override_id,
                                               item.product_id, rx_id=rx.id)
        line = PrescriptionItem(
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
            unit_price_override=hand_set,
        )
        db.add(line)
        if authorised:
            db.flush()
            authorised.prescription_item_id = line.id
            authorised.used_at = datetime.utcnow()
    db.commit()
    db.refresh(rx)
    return rx


@router.get("/prescriptions/{rx_id}/claim-copy.pdf")
def claim_copy(rx_id: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """The A4 copy of a dispensing — for the funder, the inspector, the file.

    Reads the SALE lines rather than the script, because the script says what
    was asked for and the sale says what went out and at what price. A copy
    built from the script would reprice itself every time the shelf price moved
    and could never settle an argument about what was charged in March.
    """
    from fastapi.responses import Response

    from ..services import claim_copy as copy_service

    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")

    sale = (db.query(Sale).filter(Sale.id.in_(
        db.query(SaleItem.sale_id).join(
            PrescriptionItem, SaleItem.prescription_item_id == PrescriptionItem.id)
        .filter(PrescriptionItem.prescription_id == rx.id)))
        .order_by(Sale.id.desc()).first())
    if sale is None:
        raise HTTPException(
            status_code=400,
            detail="Nothing has been dispensed on this script yet, so there is "
                   "no claim copy to produce.")

    directions = {i.id: (i.dosage_instructions or "") for i in rx.items}
    lines = [{
        "description": si.description,
        "quantity": si.quantity,
        "unit_price": si.unit_price or 0.0,
        "line_total": si.line_total or 0.0,
        "directions": sig.expand(db, directions.get(si.prescription_item_id, "")),
    } for si in sale.items]

    pharmacy = db.get(Pharmacy, user.pharmacy_id)
    branch = branches.default_branch(db)
    patient = rx.patient
    pdf = copy_service.build(
        pharmacy=(pharmacy.name if pharmacy else settings.PHARMACY_NAME),
        pharmacy_reg=settings.PHARMACY_REG_NO,
        pharmacy_address=settings.PHARMACY_ADDRESS,
        rx_number=rx.rx_number or f"#{rx.id}",
        dispensed_at=sale.created_at,
        patient_name=(f"{patient.first_name} {patient.last_name}".strip()
                      if patient else ""),
        patient_id=(patient.id_number or "") if patient else "",
        medical_aid=(patient.medical_aid.name
                     if patient and patient.medical_aid else ""),
        membership_no=(patient.medical_aid_number or "") if patient else "",
        doctor_name=(rx.doctor.name or "") if rx.doctor else "",
        doctor_practice=(rx.doctor.practice_number or "") if rx.doctor else "",
        doctor_ahfoz=(getattr(rx.doctor, "ahfoz_number", "") or "") if rx.doctor else "",
        branch=(branch.name if branch else ""),
        dispensed_by=(user.full_name or user.username),
        lines=lines,
        total=sale.total or 0.0,
    )
    stamp = (rx.rx_number or str(rx.id)).replace("/", "-")
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="claim-copy-{stamp}.pdf"'})


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
