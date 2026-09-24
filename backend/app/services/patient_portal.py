"""What a patient can see of their own record, and how they prove it is theirs.

WHY A CODE AND NOT A DATE OF BIRTH

The link used to be secured by date of birth, which is the wrong second factor
twice over. A forwarded WhatsApp message usually reaches somebody who already
knows the patient's birthday, a spouse, a child, a colleague, so it protects
against almost nobody who would actually receive it. And a patient who mistypes
it is told their own date of birth is wrong, which is close to the most
insulting thing software can say to someone.

A four-digit code handed over at the counter is known by exactly the people who
should know it, can be read out over the telephone, can be changed the moment a
phone is lost, and belongs to nobody's identity if it leaks.

It is four digits because it is protecting a medication list from a family
member, not a bank account from an attacker, and a code long enough to be
secure against a determined stranger is a code the patient telephones the
pharmacy about instead of using. The rate limit does the work that length
would: five wrong tries and the link stops answering for a while.

WHAT THEY SEE, AND WHY IT IS MORE THAN IT WAS

Before proving anything: whether something is ready, and nothing else. A link
on the wrong phone must not disclose a diagnosis.

After: everything about their own care that they would otherwise ring up to
ask — what is waiting, what is due, the whole prescription history, what they
have collected, what they owe, and what is out for delivery. A portal that
shows less than a telephone call is a portal nobody opens twice.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import (Dispensing, Patient, Prescription, PrescriptionItem,
                      Product, Sale, Waybill)
from . import portal_pins

#: Wrong tries before the link stops answering. Kept here as the names this
#: module has always published; the counting itself is `portal_pins`'s.
MAX_TRIES = portal_pins.MAX_TRIES
LOCK_MINUTES = portal_pins.LOCK_MINUTES


class PortalError(RuntimeError):
    """Raised when the portal refuses, with the sentence to show."""


def set_code(db: Session, patient: Patient, code: str = "") -> str:
    """Give this patient a code, or the one the pharmacy chose, and hand it
    back once.

    The returned string is the only time the code exists outside the patient's
    head. It is read to them at the counter or put in the message the link is
    sent with, and then it is a hash: `patients.portal_code` used to hold the
    working code to every patient portal in the shop, in clear text, in every
    backup.
    """
    try:
        return portal_pins.issue(db, patient, code)
    except portal_pins.PortalPinError as e:
        # One exception type crosses this module's own boundary, because every
        # caller already catches PortalError and says what it says.
        raise PortalError(str(e)) from e


def verify(db: Session, patient: Patient, code: str) -> None:
    """Check the code, counting failures. Raises with what to show.

    A patient whose code predates the hashing still verifies: the migration
    moved theirs across unchanged, so nobody is asked for a new one.
    """
    try:
        portal_pins.check(db, patient, code)
    except portal_pins.PortalPinError as e:
        raise PortalError(str(e)) from e


def teaser(db: Session, patient: Patient) -> dict:
    """What shows before the code is entered.

    Deliberately thin, and the thinness is the design: whether something is
    waiting is what they opened the link for, and it says nothing about what
    the medicine is. A link that reaches the wrong phone has disclosed that
    somebody uses this pharmacy, which they could see from the message anyway.
    """
    waiting = (db.query(func.count(Dispensing.id))
               .join(PrescriptionItem,
                     PrescriptionItem.id == Dispensing.prescription_item_id)
               .join(Prescription,
                     Prescription.id == PrescriptionItem.prescription_id)
               .filter(Prescription.patient_id == patient.id,
                       Dispensing.collected_at.is_(None)).scalar() or 0)
    return {
        "greeting": patient.first_name,
        "waiting": int(waiting),
        "has_code": portal_pins.has_pin(patient),
        "note": ("Enter the four-digit code the pharmacy gave you to see your "
                 "prescriptions."),
    }


def record(db: Session, patient: Patient) -> dict:
    """Everything about their own care, once they have proved it is theirs."""
    today = date.today()

    scripts = (db.query(Prescription)
               .options(joinedload(Prescription.doctor),
                        joinedload(Prescription.items)
                        .joinedload(PrescriptionItem.product))
               .filter(Prescription.patient_id == patient.id,
                       Prescription.status != "draft")
               .order_by(Prescription.date_prescribed.desc()).limit(40).all())

    fills = (db.query(Dispensing)
             .options(joinedload(Dispensing.prescription_item)
                      .joinedload(PrescriptionItem.product))
             .join(PrescriptionItem,
                   PrescriptionItem.id == Dispensing.prescription_item_id)
             .join(Prescription,
                   Prescription.id == PrescriptionItem.prescription_id)
             .filter(Prescription.patient_id == patient.id)
             .order_by(Dispensing.dispensed_at.desc()).limit(60).all())

    waiting = [f for f in fills if not f.collected_at]

    # What is due, and when. The single most useful thing a patient can be
    # shown — most of them do not know, and the pharmacy loses the repeat
    # because nobody remembered rather than because they went elsewhere.
    due = []
    for script in scripts:
        for item in script.items:
            left = max(0, (item.repeats_allowed or 0) - (item.repeats_used or 0))
            if not left or not item.next_repeat_date:
                continue
            days = (item.next_repeat_date - today).days
            due.append({
                "product": item.product.name if item.product else "",
                "on": item.next_repeat_date,
                "days": days,
                "overdue": days < 0,
                "left": left,
            })
    due.sort(key=lambda d: d["days"])

    owed = float(
        db.query(func.coalesce(func.sum(Sale.total), 0.0))
        .filter(Sale.patient_id == patient.id,
                Sale.status.in_(("pending", "part_paid"))).scalar() or 0.0)

    deliveries = (db.query(Waybill)
                  .filter(Waybill.patient_id == patient.id,
                          Waybill.status.in_(("pending", "out")))
                  .order_by(Waybill.created_at.desc()).limit(5).all())

    return {
        "patient": f"{patient.first_name} {patient.last_name}".strip(),
        "first_name": patient.first_name,
        "allergies": patient.allergies or "",
        "conditions": patient.chronic_conditions or "",
        "loyalty_points": patient.loyalty_points or 0,
        "medical_aid": (patient.medical_aid.name
                        if patient.medical_aid else ""),
        "member_number": patient.medical_aid_number or "",
        "owed": round(owed, 2),
        "waiting": [{
            "product": (f.prescription_item.product.name
                        if f.prescription_item and f.prescription_item.product
                        else ""),
            "quantity": f.quantity,
            "since": f.dispensed_at,
            "days": ((datetime.utcnow() - f.dispensed_at).days
                     if f.dispensed_at else None),
        } for f in waiting],
        "due": due[:12],
        "scripts": [{
            "rx_number": s.rx_number or "",
            "date": s.date_prescribed,
            "status": s.status,
            "doctor": s.doctor.name if s.doctor else "",
            "items": [{
                "product": (f"{i.product.name} {i.product.strength or ''}".strip()
                            if i.product else ""),
                "instructions": i.dosage_instructions or "",
                "quantity": i.quantity,
                "repeats_left": max(0, (i.repeats_allowed or 0)
                                    - (i.repeats_used or 0)),
                "repeats_allowed": i.repeats_allowed or 0,
                "next_repeat": i.next_repeat_date,
            } for i in s.items],
        } for s in scripts],
        "history": [{
            "product": (f.prescription_item.product.name
                        if f.prescription_item and f.prescription_item.product
                        else ""),
            "quantity": f.quantity,
            "on": f.dispensed_at,
            "collected": f.collected_at,
            "is_repeat": bool(f.is_repeat),
        } for f in fills],
        "deliveries": [{
            "number": w.waybill_number, "status": w.status,
            "address": w.address or "", "when": w.dispatched_at or w.created_at,
            "to_collect": round(w.cod_outstanding, 2),
        } for w in deliveries],
    }
