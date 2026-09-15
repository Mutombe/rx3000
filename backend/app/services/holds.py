"""A script put down on purpose, with the reason, until somebody picks it up.

CareXpress To-Be blueprint §8 (Dispensing Holds): a prescription is placed on
hold with a reason code, cleared by a pharmacist or supervisor, and the hold's
duration is tracked and reported. RX5000 had no such state — a prescription was
draft, active or cancelled — so a script waiting on a prescriber's call looked
exactly like one waiting to be dispensed, and the only record that it was
waiting was whoever remembered.

A hold is a row, not a status. A script can be held and released more than
once, and "how long did it wait" is only answerable if each hold keeps when it
was placed and when it was cleared. One open hold at a time per script.

While a hold is open the script cannot be dispensed: the server refuses, the
worklist marks it, and the dispensary says why. Anyone who dispenses may place
one — the person who finds the problem is at the counter. Clearing it takes a
pharmacist or a manager, RX5000's nearest role to the blueprint's supervisor:
releasing a script somebody stopped for a reason is a decision about that
reason.
"""
from datetime import datetime

from sqlalchemy.orm import Session

# Order is the order they are offered in: the commonest first.
REASONS: dict[str, str] = {
    "awaiting_stock": "Waiting for stock",
    "prescriber_query": "Querying the prescriber",
    "pharmacist_review": "Pharmacist to review",
    "awaiting_authorisation": "Waiting for medical aid authorisation",
    "patient_request": "Patient asked to wait",
    "payment": "Payment to be arranged",
}

CLEARERS = ("pharmacist", "manager", "admin")


class HoldError(Exception):
    pass


def open_hold(db: Session, prescription_id: int):
    from ..models import PrescriptionHold

    return (db.query(PrescriptionHold)
            .filter(PrescriptionHold.prescription_id == prescription_id,
                    PrescriptionHold.cleared_at.is_(None))
            .order_by(PrescriptionHold.placed_at.desc())
            .first())


def place(db: Session, *, prescription, reason_code: str, note: str, user):
    from ..models import PrescriptionHold

    if reason_code not in REASONS:
        raise HoldError("Choose why the script is being held.")
    if prescription.status == "cancelled":
        raise HoldError(f"{prescription.rx_number or 'This script'} is cancelled; there is nothing to hold.")
    existing = open_hold(db, prescription.id)
    if existing:
        raise HoldError(f"{prescription.rx_number or 'This script'} is already on hold: "
                        f"{REASONS.get(existing.reason_code, existing.reason_code).lower()}.")
    hold = PrescriptionHold(prescription_id=prescription.id, reason_code=reason_code,
                            note=(note or "").strip(), placed_by_id=user.id,
                            placed_at=datetime.utcnow())
    db.add(hold)
    db.flush()
    return hold


def clear(db: Session, *, hold, note: str, user):
    if user.role not in CLEARERS:
        raise HoldError("A pharmacist or a manager clears a hold. Ask one to release this script.")
    if hold.cleared_at is not None:
        raise HoldError("That hold has already been cleared.")
    hold.cleared_at = datetime.utcnow()
    hold.cleared_by_id = user.id
    hold.clear_note = (note or "").strip()
    db.flush()
    return hold


def hours_held(hold, now: datetime | None = None) -> float:
    end = hold.cleared_at or now or datetime.utcnow()
    return round(max(0.0, (end - hold.placed_at).total_seconds() / 3600), 1)


def summarise(db: Session, hold) -> dict:
    from ..models import User

    def name(uid):
        u = db.get(User, uid) if uid else None
        return (u.full_name or u.username) if u else ""

    return {
        "id": hold.id,
        "prescription_id": hold.prescription_id,
        "reason_code": hold.reason_code,
        "reason": REASONS.get(hold.reason_code, hold.reason_code),
        "note": hold.note or "",
        "placed_by": name(hold.placed_by_id),
        "placed_at": hold.placed_at,
        "cleared_by": name(hold.cleared_by_id),
        "cleared_at": hold.cleared_at,
        "clear_note": hold.clear_note or "",
        "open": hold.cleared_at is None,
        "hours_held": hours_held(hold),
    }
