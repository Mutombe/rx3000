"""Turning a scanned string back into the prescription it was printed from.

This product has printed a Code 128 of the script number along the bottom of
every dispensing label for a long time, and on a standalone sticker besides.
It could not read one. Scanning a label the pharmacy itself produced answered

    Nothing is stocked under that code.

because every path through the scanner resolved to a *product*, and a script
number is not a product. The barcode was compliance decoration: printed
because it was asked for, and connected to nothing.

WHAT A SCAN OF A SCRIPT IS FOR

Finding it, and checking it. A dispenser holding a printed script should not
be searching by surname among the four Moyos on the worklist. And the moment
it opens, the screen can answer the questions that actually prevent the wrong
hand-over: is this the patient in front of me, has this already been
dispensed, how many repeats are left, and is it still in date.

WHY THE SCRIPT NUMBER RATHER THAN A NEW TOKEN

Because the labels already in circulation carry the script number, and a new
identifier would mean either a second barcode on the sticker or a drawer full
of scripts that no longer scan. The number is already unique within a pharmacy
and already indexed, and a scan is authenticated and tenant scoped, so it
reveals nothing to somebody who could not already list it.

WHY A MISS IS NOT AN ERROR

The same reason the product path says so in its own docstring: a dead end
makes the operator start again somewhere else. A script number that is not on
file, or belongs to another pharmacy, comes back as "not found" with the
reason, and the dispenser types a surname like they did before.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ..models import Prescription, ScriptChange, User

#: What a scan of a script is worth saying about its standing. Keyed on the
#: status the prescription carries, so a state added later shows up as itself
#: rather than as silence.
SAYS = {
    "draft": "Still being captured. It has not been finished yet.",
    "active": "",
    "partially_dispensed": "Partly dispensed. Some of it is still owed.",
    "dispensed": "Already dispensed in full.",
    "cancelled": "Cancelled. It must not be dispensed.",
    "expired": "Past its validity date.",
}


def find(db: Session, code: str) -> Prescription | None:
    """The prescription a scanned string names, or None.

    Tenant scoped by the ordinary mechanism: `Prescription` carries the tenant
    mixin, so this can only ever return a script belonging to the pharmacy the
    request is signed in to. There is no second rule to get wrong.
    """
    wanted = (code or "").strip()
    if not wanted:
        return None
    # The number as printed, and the same number in upper case. A scanner
    # reproduces what was encoded exactly, but a code typed into the fallback
    # box by hand does not.
    found = (db.query(Prescription)
             .filter(Prescription.rx_number == wanted).first())
    if found is None:
        found = (db.query(Prescription)
                 .filter(Prescription.rx_number == wanted.upper()).first())
    if found is None:
        # A draft carries its own reference and can be printed, so a sticker
        # from one has to find its way home as well.
        found = (db.query(Prescription)
                 .filter(Prescription.draft_ref == wanted.upper()).first())
    return found


def dispensable(rx: Prescription) -> tuple[bool, str]:
    """Whether this script may be dispensed against now, and why not.

    Said by the scanner rather than discovered at the Finish button, because
    the point of scanning it is to learn this while the patient is still at
    the counter and something can be done about it.

    Only the states this system actually records. A prescription here has no
    validity window — there is no column for one and no setting behind it — so
    this does not pretend to check one. Inventing an expiry rule in the one
    place that reports it, while nothing else in the product enforces it,
    would produce a refusal no other screen agrees with.
    """
    status = (rx.status or "").lower()
    if status == "cancelled":
        return False, "This script was cancelled. It must not be dispensed."
    if status == "dispensed":
        return False, ("This script has already been dispensed in full. "
                       "Check whether the patient is collecting something "
                       "else before dispensing it again.")
    if status == "draft":
        return False, ("This script is still being captured. Finish it before "
                       "dispensing against it.")
    return True, ""


def note_scan(db: Session, rx: Prescription, *, user: User, where: str) -> None:
    """Record that somebody scanned it, on the script's own trail.

    On `ScriptChange` rather than a table of its own. That trail is already
    append-only, already indexed by prescription, and already carries who and
    when, which is the whole of what a scan needs to say. A second table
    holding the same four columns would mean every screen that wants the
    history of one script reads two.

    The API audit log records the request as well, but it is keyed by user and
    path: it can answer "what did this person do today" and not "what happened
    to this script", and the second question is the one asked in an
    investigation.
    """
    db.add(ScriptChange(
        prescription_id=rx.id,
        field="scanned",
        old_value="",
        new_value=(where or "")[:240],
        reason="",
        changed_by_id=getattr(user, "id", None),
        pharmacy_id=rx.pharmacy_id,
    ))


def shape(db: Session, rx: Prescription) -> dict:
    """One script, as a scanner needs it: who, what, and may it go out.

    Deliberately not the full detail payload. This is what somebody reads in
    the second after a beep, standing at a counter, deciding whether to carry
    on — so it is the patient's name, the medicines, what is left to dispense,
    and anything that should stop them.
    """
    may, refuse = dispensable(rx)
    patient = rx.patient
    lines = []
    for item in (rx.items or []):
        product = item.product
        wanted = int(item.quantity or 0)
        # What actually went out, summed off the dispensings themselves. There
        # is no "quantity dispensed" column on a line: a line can be dispensed
        # more than once, in parts, and the rows are the record. `detail()` in
        # services/scripts adds them up the same way, and the two must not
        # drift into two different answers to one question.
        given = sum(d.quantity or 0 for d in (item.dispensings or []))
        lines.append({
            "item_id": item.id,
            "product_id": item.product_id,
            "medicine": (f"{product.name} {product.strength or ''}".strip()
                         if product else ""),
            "quantity": wanted,
            "dispensed": given,
            "outstanding": max(0, wanted - given),
            "directions": item.dosage_instructions or "",
            # Repeats are held per LINE, not per script: a prescriber can
            # allow six of one and none of another on the same piece of paper,
            # and this system records that faithfully.
            "repeats_allowed": int(item.repeats_allowed or 0),
            "repeats_used": int(item.repeats_used or 0),
            "not_dispensed": bool(item.not_dispensed),
            "schedule": int(getattr(product, "schedule", 0) or 0) if product else 0,
        })
    return {
        "id": rx.id,
        "rx_number": rx.rx_number or rx.draft_ref or "",
        "status": rx.status or "",
        "says": SAYS.get((rx.status or "").lower(), ""),
        "may_dispense": may,
        "refuse": refuse,
        "patient_id": rx.patient_id,
        "patient": (f"{patient.first_name} {patient.last_name}".strip()
                    if patient else ""),
        "prescriber": rx.doctor.name if getattr(rx, "doctor", None) else "",
        # The highest schedule anything on it carries. The screen opens on the
        # route that governs the strictest line: a script holding one S5 among
        # four ordinary lines is a controlled dispensing, and opening it on the
        # ordinary tab would present it as something it is not.
        "schedule": max([l["schedule"] for l in lines] or [0]),
        "written_on": (rx.date_prescribed.isoformat()
                       if getattr(rx, "date_prescribed", None) else ""),
        "lines": lines,
    }
