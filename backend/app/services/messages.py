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
import re
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import (
    CounterMessage as Message, MessageAcknowledgement, Patient, Product,
)
from . import conditions, refill_timing

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


def _match_words(db: Session, terms: list[str]) -> list[tuple[str, list[str]]]:
    """Expand each recorded allergy into every word that should trigger on it.

    A patient recorded as allergic to "Penicillin" was getting no warning at all
    for Amoxicillin, Augmentin or Co-amoxiclav. The check matched the recorded
    text against the product, and "penicillin" is simply not a substring of
    "amoxicillin" — so the one record whose entire purpose is to stop that
    dispensing sat there looking correct and did nothing. It only came to light
    by running a real patient against real products rather than reading the
    matcher.

    The vocabulary already holds the answer: each catalogued allergen carries
    the names it is met under. Recording "Penicillin" therefore now also watches
    for amoxicillin, ampicillin, flucloxacillin and the rest. A term that is not
    in the catalogue still matches on itself, so a free-text allergy typed
    before any of this existed is no worse off than it was.
    """
    from ..models import ClinicalTerm

    catalogue = db.query(ClinicalTerm).filter(ClinicalTerm.kind == "allergy",
                                              ClinicalTerm.active.is_(True)).all()
    out = []
    for term in terms:
        low = term.lower()
        words = {low}
        for row in catalogue:
            names = {(row.name or "").lower()}
            syns = {w.strip().lower() for w in (row.synonyms or "").split(",") if w.strip()}
            # Matched either way round: the record may hold the catalogue's name
            # or one of the words it is met under.
            if low in names or low in syns:
                words |= names | syns
        out.append((term, sorted(w for w in words if len(w) >= 4)))
    return out


def _hits(haystack: str, words: list[str]) -> str | None:
    """The first word that appears in the product, matched whole.

    Whole words, not substrings. The synonym lists contain short forms — "asa"
    for aspirin, "tb", "bp" — and a bare substring test lets those fire inside
    unrelated names, which trains a dispenser to click past allergy warnings.
    A warning nobody believes is worse than none, because it is the same
    indifference applied to the real one.
    """
    for word in words:
        if re.search(r"\b" + re.escape(word) + r"\b", haystack):
            return word
    return None


def _allergy_rows(db: Session, patient: Patient, products: list[Product]) -> list[dict]:
    """Turn the patient's recorded allergies into warnings against these products.

    Matched on the active ingredient and the product name, through the allergen
    vocabulary, so "penicillin" catches the whole class rather than only a
    product that spells it out. This is still a name match and it is not a
    clinical interaction check — it is deliberately conservative and says so,
    because a pharmacist who mistakes one for the other is the failure mode that
    matters.
    """
    text = (patient.allergies or "").strip()
    if not text:
        return []
    terms = [t.strip() for t in text.replace(";", ",").split(",") if t.strip()]
    expanded = _match_words(db, terms)

    hits = []
    for product in products:
        haystack = f"{product.name} {product.active_ingredient or ''}".lower()
        for recorded, words in expanded:
            word = _hits(haystack, words)
            if not word:
                continue
            # Say both: what the record holds, and what actually matched. A
            # pharmacist told only "allergic to penicillin" while holding a box
            # of Augmentin has to make the connection themselves, at speed.
            because = ("" if word == recorded.lower()
                       else f" {product.name} contains {word}, which is a {recorded.lower()}.")
            hits.append({
                # A derived warning still needs a stable identifier, or it
                # can never be acknowledged and the script can never be
                # dispensed at all. Negative ids cannot collide with a
                # stored message and say plainly that this one is derived.
                "id": -product.id, "scope": "patient", "target_id": patient.id,
                "derived": True,
                "severity": "stop", "category": "allergy",
                "body": (f"{patient.first_name} {patient.last_name} is recorded as "
                         f"allergic to {recorded}.{because} {product.name} matches that "
                         "on name or active ingredient. Confirm with the patient before "
                         "dispensing. This is a name match against the allergy "
                         "record, not a clinical interaction check."),
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
        out += _allergy_rows(db, patient, products)
        # What the patient is recorded as living with, against what is being
        # handed over. The field existed, the picker offered Pregnancy and
        # Breastfeeding as its own entries, a pharmacist filled it in because
        # they knew it mattered — and nothing on the dispensing path read it.
        # Recorded and ignored is the worst shape a safety gap takes: the hard
        # part was already done.
        out += conditions.check(db, patient, products)
        # Collected materially before it is due. Every fact needed to ask was
        # already on file — when it last went out, how long that was meant to
        # last — and nothing asked. On a schedule 5 that question is the whole
        # reason a controlled register is kept.
        out += refill_timing.check(db, patient, products)
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
