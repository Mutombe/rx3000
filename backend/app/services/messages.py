"""Notes that surface at the moment of dispensing.

The information that stops a mistake is worthless if it lives on a record nobody
opens mid-transaction. So this service answers one question — *everything the
pharmacist needs to see about this patient and these products, right now* — and
answers it in one call, because a screen that needs five requests to assemble a
warning will render the warning late or not at all.

The blocking rule is the point. A `stop` message refuses the dispense until
somebody acknowledges it by name, and the acknowledgement is kept. A patient
with a documented anaphylactic allergy is not a case for a banner that a busy
assistant scrolls past; it is a case for the transaction not completing.

Allergies already recorded on the patient record are folded in here rather than
requiring a separate message to be written, because a system that only warns
about allergies somebody remembered to re-enter as a note is worse than useless
— it is reassuring and wrong.
"""
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import (
    CounterMessage as Message, MessageAcknowledgement, Patient, Product,
)

SEVERITIES = ("info", "warn", "stop")
_RANK = {"stop": 0, "warn": 1, "info": 2}


class MessageError(ValueError):
    """Raised when a dispense is blocked by an unacknowledged message."""


def _live(query):
    today = date.today()
    return query.filter(Message.active.is_(True),
                        or_(Message.expires_on.is_(None), Message.expires_on >= today))


def _row(message: Message, source: str = "") -> dict:
    return {
        "id": message.id,
        "scope": message.scope,
        "target_id": message.target_id,
        "severity": message.severity,
        "category": message.category,
        "body": message.body,
        "source": source or message.scope,
        "blocking": message.severity == "stop",
        "created_at": message.created_at,
        "created_by": message.created_by.full_name if message.created_by else "",
    }


def _allergy_rows(patient: Patient, products: list[Product]) -> list[dict]:
    """Turn the patient's recorded allergies into warnings against these products.

    Matched on the active ingredient and the product name, both ways round, so
    "penicillin" catches a product whose ingredient names it. This is a text
    match and it is not a clinical interaction check — it is deliberately
    conservative and says so, because a pharmacist who mistakes one for the
    other is the failure mode that matters.
    """
    text = (patient.allergies or "").strip()
    if not text:
        return []
    terms = [t.strip().lower() for t in text.replace(";", ",").split(",") if t.strip()]
    hits = []
    for product in products:
        haystack = f"{product.name} {product.active_ingredient or ''}".lower()
        for term in terms:
            if len(term) > 2 and term in haystack:
                hits.append({
                    # A derived warning still needs a stable identifier, or it
                    # can never be acknowledged and the script can never be
                    # dispensed at all. Negative ids cannot collide with a
                    # stored message and say plainly that this one is derived.
                    "id": -product.id, "scope": "patient", "target_id": patient.id,
                    "derived": True,
                    "severity": "stop", "category": "allergy",
                    "body": (f"{patient.first_name} {patient.last_name} is recorded as "
                             f"allergic to {term}. {product.name} matches that on name "
                             "or active ingredient. Confirm with the patient before "
                             "dispensing — this is a text match against the allergy "
                             "field, not a clinical interaction check."),
                    "source": "allergy record", "blocking": True,
                    "created_at": None, "created_by": "",
                })
                break
    return hits


def for_dispensing(db: Session, *, patient_id: int | None = None,
                   product_ids: list[int] | None = None,
                   medical_aid_id: int | None = None,
                   doctor_id: int | None = None) -> dict:
    """Everything to put in front of the pharmacist, in one call."""
    product_ids = product_ids or []
    out: list[dict] = []

    patient = db.get(Patient, patient_id) if patient_id else None
    products = (db.query(Product).filter(Product.id.in_(product_ids)).all()
                if product_ids else [])

    if patient:
        rows = _live(db.query(Message).filter(
            Message.scope == "patient",
            or_(Message.target_id == patient.id, Message.target_id.is_(None)))).all()
        out += [_row(m, "patient") for m in rows]
        out += _allergy_rows(patient, products)
        aid_id = medical_aid_id or patient.medical_aid_id
    else:
        aid_id = medical_aid_id

    if aid_id:
        rows = _live(db.query(Message).filter(
            Message.scope.in_(("scheme", "member")),
            or_(Message.target_id == aid_id, Message.target_id.is_(None)))).all()
        out += [_row(m, "scheme") for m in rows]

    if product_ids:
        rows = _live(db.query(Message).filter(
            Message.scope == "product", Message.target_id.in_(product_ids))).all()
        out += [_row(m, "product") for m in rows]

    if doctor_id:
        rows = _live(db.query(Message).filter(
            Message.scope == "doctor", Message.target_id == doctor_id)).all()
        out += [_row(m, "prescriber") for m in rows]

    out.sort(key=lambda m: (_RANK.get(m["severity"], 9), m["source"]))
    blocking = [m for m in out if m["blocking"]]
    return {
        "messages": out,
        "count": len(out),
        "blocking": blocking,
        "must_acknowledge": [m["id"] for m in blocking],
        "can_dispense": not blocking,
        "summary": ("" if not out else
                    f"{len(blocking)} blocking, {len(out) - len(blocking)} advisory"),
    }


def acknowledged_ids(db: Session, prescription_id: int) -> set:
    rows = (db.query(MessageAcknowledgement.message_id)
            .filter(MessageAcknowledgement.prescription_id == prescription_id).all())
    return {r[0] for r in rows}


def guard_dispense(db: Session, *, prescription_id: int, patient_id: int | None,
                   product_ids: list[int], medical_aid_id: int | None = None) -> None:
    """Refuse the dispense while a blocking message stands unacknowledged."""
    found = for_dispensing(db, patient_id=patient_id, product_ids=product_ids,
                           medical_aid_id=medical_aid_id)
    if not found["blocking"]:
        return
    seen = acknowledged_ids(db, prescription_id)
    outstanding = [m for m in found["blocking"] if m["id"] not in seen]
    if not outstanding:
        return
    raise MessageError(
        "; ".join(m["body"] for m in outstanding[:2])
        + (f" (and {len(outstanding) - 2} more)" if len(outstanding) > 2 else "")
    )


def acknowledge(db: Session, *, message_id: int, prescription_id: int,
                user_id: int, note: str = "") -> MessageAcknowledgement:
    record = MessageAcknowledgement(
        message_id=message_id, prescription_id=prescription_id,
        acknowledged_by_id=user_id, note=note[:200])
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
