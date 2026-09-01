"""Every script the pharmacy holds, as a table somebody can search.

WHY THERE WAS NO SUCH SCREEN

A script could be reached three ways and none of them was "look it up". Through
a patient, which needs the patient's name. Through the dispensing history —
which lists *dispensings*, the individual events, so a script dispensed in four
visits appears four times and a script dispensed never appears not at all.
Through the N-Repeat queue, which holds only the drafts.

So the question a dispensary asks constantly, "bring me script RX-0412", had no
answer except through the alter dialogue, which asks for the number, finds the
script, and then only lets you change a quantity. The record existed and the
door did not.

THE SCRIPT ID

Every script already carries one; it was simply never surfaced as an identifier
people could use. There are two, and which one applies is the script's state:

  `rx_number` is the register number, taken from a numbered sequence at the
    moment the script is finalised, and is the identity the register, the
    claim, the label and the inspector all use;
  `draft_ref` is what an N-Repeat carries instead, because a number burnt on a
    capture somebody abandons leaves a gap in a numbered register that a human
    then has to explain.

`script_id` below is whichever the script actually has, so a row always has an
identity a person can read out over a telephone. `id` remains the database key
and is what links point at, because a draft's reference becomes an Rx number
when it is finalised and a link that changed under somebody would be worse than
no link.

WHAT AN ALTERATION LOOKS LIKE HERE

`ScriptChange` has recorded every correction, per field, with the old value, the
new value, a reason and a name, since the alter endpoint was written. Nothing
read it back except a report nobody opens on the day it matters. It is on the
script now, in the order it happened, because "what did this used to say" is
asked about one script at a time and usually while somebody is on the phone.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from ..models import (Dispensing, Doctor, Patient, Prescription,
                      PrescriptionItem, Product, ScriptChange, User)


def script_id(rx: Prescription) -> str:
    """What to call this script out loud.

    The register number where it has one, the draft reference where it does
    not. Never the database key: a dispenser reading a number to a doctor's
    rooms is reading the one on the script, not ours.
    """
    return (rx.rx_number or rx.draft_ref or f"#{rx.id}").strip()


def _loaded(query):
    return query.options(
        joinedload(Prescription.patient),
        joinedload(Prescription.doctor),
        joinedload(Prescription.items).joinedload(PrescriptionItem.product),
    )


def search(db: Session, *, q: str = "", status: str = "", patient_id: int = 0,
           doctor_id: int = 0, days: int = 0, altered_only: bool = False):
    """The list query, filters applied. Paging is the caller's."""
    query = _loaded(db.query(Prescription))

    if q.strip():
        like = f"%{q.strip()}%"
        # The number first, because that is what somebody types nine times in
        # ten, and both kinds of number are searched — a dispenser holding an
        # N-Repeat has a draft reference in their hand and no way to know this
        # system files it in a different column.
        query = (query
                 .outerjoin(Patient, Prescription.patient_id == Patient.id)
                 .outerjoin(Doctor, Prescription.doctor_id == Doctor.id)
                 .filter(or_(
                     Prescription.rx_number.ilike(like),
                     Prescription.draft_ref.ilike(like),
                     Patient.first_name.ilike(like),
                     Patient.last_name.ilike(like),
                     Patient.id_number.ilike(like),
                     Doctor.name.ilike(like),
                 )))
    if status:
        query = query.filter(Prescription.status == status)
    if patient_id:
        query = query.filter(Prescription.patient_id == patient_id)
    if doctor_id:
        query = query.filter(Prescription.doctor_id == doctor_id)
    if days > 0:
        query = query.filter(
            Prescription.created_at >= datetime.utcnow() - timedelta(days=days))
    if altered_only:
        # A script that has been corrected since capture. Asked for by name at
        # an inspection, and previously answerable only by reading a report.
        query = query.filter(Prescription.id.in_(
            db.query(ScriptChange.prescription_id).distinct()))
    return query.order_by(Prescription.created_at.desc())


def rows(db: Session, prescriptions: list[Prescription]) -> list[dict]:
    """One row each, with the counts a list is read for.

    The dispensed and altered counts come from two queries for the whole page
    rather than two per row. A list screen that issues a query per row is the
    one that gets slower every month a pharmacy trades.
    """
    ids = [rx.id for rx in prescriptions] or [0]

    dispensed = dict(
        db.query(PrescriptionItem.prescription_id, func.count(Dispensing.id))
        .join(Dispensing, Dispensing.prescription_item_id == PrescriptionItem.id)
        .filter(PrescriptionItem.prescription_id.in_(ids))
        .group_by(PrescriptionItem.prescription_id).all())

    altered = dict(
        db.query(ScriptChange.prescription_id, func.count(ScriptChange.id))
        .filter(ScriptChange.prescription_id.in_(ids))
        .group_by(ScriptChange.prescription_id).all())

    out = []
    for rx in prescriptions:
        patient = rx.patient
        items = rx.items or []
        repeats_left = sum(max(0, (i.repeats_allowed or 0) - (i.repeats_used or 0))
                           for i in items)
        out.append({
            "id": rx.id,
            "script_id": script_id(rx),
            # Stated separately so a screen can tell a register number from a
            # draft reference without parsing the string for a prefix.
            "rx_number": rx.rx_number or "",
            "draft_ref": rx.draft_ref or "",
            "status": rx.status,
            "date_prescribed": rx.date_prescribed,
            "created_at": rx.created_at,
            "patient_id": rx.patient_id,
            "patient": (f"{patient.first_name} {patient.last_name}".strip()
                        if patient else ""),
            "doctor_id": rx.doctor_id,
            "doctor": rx.doctor.name if rx.doctor else "",
            "items": len(items),
            "repeats_left": repeats_left,
            "dispensed_count": dispensed.get(rx.id, 0),
            # The reason this list exists in the form it does: a script that has
            # been corrected is the one somebody comes looking for.
            "alterations": altered.get(rx.id, 0),
        })
    return out


def detail(db: Session, rx: Prescription) -> dict:
    """One script in full: its lines, what has gone out, and what changed."""
    items = []
    for item in rx.items or []:
        product = item.product
        went_out = sum(d.quantity or 0 for d in (item.dispensings or []))
        items.append({
            "id": item.id,
            "product_id": item.product_id,
            "product": (f"{product.name} {product.strength or ''}".strip()
                        if product else ""),
            "schedule": product.schedule if product else 0,
            "quantity": item.quantity,
            "dispensed_quantity": went_out,
            "dosage_instructions": item.dosage_instructions or "",
            "icd10_code": item.icd10_code or "",
            "supply_days": item.supply_days or 0,
            "repeats_allowed": item.repeats_allowed or 0,
            "repeats_used": item.repeats_used or 0,
            "next_repeat_date": item.next_repeat_date,
            # Whether this line can still be corrected, worked out here rather
            # than left for a screen to guess. It is the same rule the alter
            # endpoint enforces: what has left the shelf records something that
            # physically happened, and editing it would make the register
            # disagree with the medicine.
            "alterable": not item.dispensings,
        })

    changes = (db.query(ScriptChange)
               .filter(ScriptChange.prescription_id == rx.id)
               .order_by(ScriptChange.changed_at.desc()).all())
    who = {u.id: u.full_name for u in db.query(User).filter(
        User.id.in_([c.changed_by_id for c in changes] or [0])).all()}

    dispensings = (db.query(Dispensing)
                   .join(PrescriptionItem,
                         Dispensing.prescription_item_id == PrescriptionItem.id)
                   .filter(PrescriptionItem.prescription_id == rx.id)
                   .options(joinedload(Dispensing.dispensed_by),
                            joinedload(Dispensing.prescription_item)
                            .joinedload(PrescriptionItem.product))
                   .order_by(Dispensing.dispensed_at.desc()).all())

    patient = rx.patient
    return {
        "id": rx.id,
        "script_id": script_id(rx),
        "rx_number": rx.rx_number or "",
        "draft_ref": rx.draft_ref or "",
        "status": rx.status,
        "date_prescribed": rx.date_prescribed,
        "created_at": rx.created_at,
        "finalised_at": rx.finalised_at,
        "notes": rx.notes or "",
        "patient_id": rx.patient_id,
        "patient": (f"{patient.first_name} {patient.last_name}".strip()
                    if patient else ""),
        "patient_id_number": patient.id_number if patient else "",
        "doctor_id": rx.doctor_id,
        "doctor": rx.doctor.name if rx.doctor else "",
        "practice_number": rx.doctor.practice_number if rx.doctor else "",
        "items": items,
        "alterations": [{
            "id": c.id,
            "item_id": c.prescription_item_id,
            "field": c.field,
            "old_value": c.old_value or "",
            "new_value": c.new_value or "",
            "reason": c.reason or "",
            "changed_at": c.changed_at,
            "changed_by": who.get(c.changed_by_id, ""),
        } for c in changes],
        "dispensings": [{
            "id": d.id,
            "dispensed_at": d.dispensed_at,
            "quantity": d.quantity,
            "product": (f"{d.prescription_item.product.name} "
                        f"{d.prescription_item.product.strength or ''}".strip()
                        if d.prescription_item and d.prescription_item.product
                        else ""),
            "is_repeat": bool(d.is_repeat),
            "dispensed_by": d.dispensed_by.full_name if d.dispensed_by else "",
            "sale_id": d.sale_id,
        } for d in dispensings],
    }
