"""What the dispensary has to do today, in the order it should be done.

Three questions a dispenser asks every morning, currently answered by opening
three screens and remembering:

* What is booked in and waiting?
* Which of it cannot wait?
* Who is due a repeat and has not come in?

Ordering is the whole value. A queue sorted by booking time treats a paediatric
antibiotic and a vitamin refill as equally urgent, and a queue sorted by severity
alone puts a schedule 4 booked for five o'clock ahead of one booked for nine.
Both matter, so both are used: severity first in bands, booking time within a
band. That is how a dispensary actually works — the urgent tray, then in order.

Severity here is not the drug schedule. A schedule is a legal classification and
this is a clinical urgency, and conflating them puts a controlled sleeping tablet
above a child's antibiotic.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Dispensing, Patient, Prescription, PrescriptionItem, Product

# Conditions where a missed dose matters within hours rather than days. Held
# here as a list rather than a column because it is clinical judgement that a
# pharmacy may want to adjust, and because inventing a per-product severity
# field would leave five hundred rows for somebody to fill in.
URGENT_CATEGORIES = {
    "antibiotic", "antiretroviral", "arv", "insulin", "anticoagulant",
    "antiepileptic", "anticonvulsant", "cardiac", "oncology", "tb",
}
URGENT_WORDS = (
    "insulin", "warfarin", "amoxicillin", "co-amoxiclav", "ceftriaxone",
    "phenytoin", "carbamazepine", "sodium valproate", "efavirenz",
    "tenofovir", "lamivudine", "rifampicin", "isoniazid", "salbutamol",
    "adrenaline", "epinephrine", "glyceryl trinitrate", "digoxin",
)

# Chronic markers. A chronic patient who misses a collection is a different
# problem from a walk-in who does: the medicine is holding something in check.
CHRONIC_WORDS = (
    "diabet", "hypertens", "asthma", "epilep", "hiv", "cardiac", "heart",
    "thyroid", "arthrit", "copd", "renal", "kidney", "cholesterol",
)


def _severity(product: Product, patient: Patient | None) -> tuple[int, str]:
    """Urgency band and why, so a dispenser can see the reason not just the rank.

    Bands rather than a score. A score invites false precision — nobody can say
    an antibiotic is 7.4 urgent — and a band is what a tray physically is.
    """
    name = (product.name or "").lower()
    ingredient = (product.active_ingredient or "").lower()
    category = (product.category or "").lower()

    if any(word in name or word in ingredient for word in URGENT_WORDS):
        return 1, "time-critical medicine"
    if category in URGENT_CATEGORIES:
        return 1, "time-critical category"

    conditions = ((patient.chronic_conditions or "") if patient else "").lower()
    if conditions and any(word in conditions for word in CHRONIC_WORDS):
        return 2, "chronic patient"
    if (product.schedule or 0) >= 5:
        # Controlled, so it needs care and a register entry — but that is
        # process urgency, not clinical, so it sits below a chronic patient.
        return 3, f"schedule {product.schedule}, register entry required"
    if (product.schedule or 0) >= 2:
        return 4, "prescription medicine"
    return 5, "routine"


BAND_LABELS = {
    1: "Time-critical",
    2: "Chronic",
    3: "Controlled",
    4: "Prescription",
    5: "Routine",
}


def pending(db: Session, *, limit: int = 200) -> tuple[list[dict], int, list[dict]]:
    """Everything captured and not yet dispensed, worst first then oldest first.

    Returns the visible rows *and* the true count. A queue is one of the few
    places a cap is genuinely right — nobody works a list of five thousand — but
    the count must not be the cap. Reporting the limit as the total is how a
    backlog of eight hundred reads as two hundred, and it is the same mistake
    this codebase has now made in five separate places.
    """
    rows = (
        db.query(PrescriptionItem, Prescription, Product)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .join(Product, PrescriptionItem.product_id == Product.id)
        .filter(Prescription.status.notin_(("draft", "cancelled")))
        .filter(PrescriptionItem.not_dispensed.is_(False))
        .all()
    )
    if not rows:
        return [], 0

    patients = {
        p.id: p for p in
        db.query(Patient).filter(
            Patient.id.in_({s.patient_id for _i, s, _p in rows if s.patient_id})).all()
    }
    out = []
    for item, script, product in rows:
        # Already gone out entirely? Then it is not pending.
        dispensed = sum(d.quantity or 0 for d in item.dispensings)
        outstanding = (item.quantity or 0) - dispensed
        if outstanding <= 0:
            continue
        patient = patients.get(script.patient_id)
        band, reason = _severity(product, patient)
        booked = script.date_prescribed or (
            script.created_at.date() if script.created_at else date.today())
        out.append({
            "item_id": item.id,
            "prescription_id": script.id,
            "rx_number": script.rx_number or f"#{script.id}",
            "patient_id": script.patient_id,
            # Truncated deliberately: this is a queue, read at a glance, and a
            # long name pushes the quantity and the reason off a narrow panel.
            "patient": _clip(
                f"{patient.first_name} {patient.last_name}".strip() if patient else "—", 22),
            "product": _clip(f"{product.name} {product.strength or ''}".strip(), 26),
            "quantity": outstanding,
            "band": band,
            "band_label": BAND_LABELS[band],
            "reason": reason,
            "booked_for": booked.isoformat(),
            "waiting_days": (date.today() - booked).days,
            "schedule": product.schedule or 0,
            "chronic": bool(patient and _is_chronic(patient)),
        })
    # Severity band first, then how long it has been waiting. Within a band the
    # oldest booking goes first, which is the only fair reading of a queue.
    out.sort(key=lambda r: (r["band"], -r["waiting_days"], r["patient"]))
    return out[:limit], len(out), out


def band_counts(rows: list[dict]) -> dict[str, int]:
    """How many in each band. Given the whole backlog, not the visible page.

    Counted from the full list on purpose: bands taken from the page would shrink
    as the queue grew, so a worsening backlog would report fewer time-critical
    items — the opposite of the truth, on the number a dispenser acts on first.
    """
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["band_label"]] = counts.get(row["band_label"], 0) + 1
    return counts


def _is_chronic(patient: Patient) -> bool:
    conditions = (patient.chronic_conditions or "").lower()
    return bool(conditions and any(w in conditions for w in CHRONIC_WORDS))


def _clip(text: str, width: int) -> str:
    """Shorten for a panel, with an ellipsis so nothing looks complete when it is not."""
    text = (text or "").strip()
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def chronic_patients(db: Session, *, limit: int = 50) -> list[dict]:
    """Chronic patients and where their repeat stands.

    Shown beside the queue because a chronic patient's next collection is the
    one thing a dispenser can act on before they arrive — the medicine is
    holding something in check, and a missed month is a clinical event.
    """
    today_ = date.today()
    rows = (
        db.query(Patient)
        .filter(Patient.chronic_conditions.isnot(None))
        .filter(Patient.chronic_conditions != "")
        .all()
    )
    people = [p for p in rows if _is_chronic(p)]
    if not people:
        return []

    due = {}
    for item, script in (
        db.query(PrescriptionItem, Prescription)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .filter(PrescriptionItem.next_repeat_date.isnot(None))
        .filter(PrescriptionItem.repeats_used < PrescriptionItem.repeats_allowed)
        .all()
    ):
        current = due.get(script.patient_id)
        if current is None or item.next_repeat_date < current:
            due[script.patient_id] = item.next_repeat_date

    out = []
    for patient in people:
        next_due = due.get(patient.id)
        days = (next_due - today_).days if next_due else None
        out.append({
            "patient_id": patient.id,
            "patient": _clip(f"{patient.first_name} {patient.last_name}".strip(), 22),
            "conditions": _clip(patient.chronic_conditions or "", 34),
            "next_due": next_due.isoformat() if next_due else "",
            "days_to_due": days,
            # The state a dispenser acts on, said in a word rather than left to
            # be worked out from a date.
            "state": ("overdue" if days is not None and days < 0
                      else "due" if days is not None and days <= 7
                      else "on track" if days is not None
                      else "no repeat set"),
            # Who to actually ring. For many chronic patients that is not them.
            "call": _clip(
                (patient.caregiver_name or "") if patient.contact_caregiver_first
                else f"{patient.first_name} {patient.last_name}".strip(), 22),
            "phone": ((patient.caregiver_phone or patient.phone or "")
                      if patient.contact_caregiver_first
                      else (patient.phone or patient.caregiver_phone or "")),
        })
    out.sort(key=lambda r: (r["days_to_due"] is None, r["days_to_due"] or 0))
    return out[:limit]


def due_reminders(db: Session, *, within_days: int = 7) -> list[dict]:
    """Repeats due soon or already past, with who to contact."""
    horizon = date.today() + timedelta(days=within_days)
    rows = (
        db.query(PrescriptionItem, Prescription, Product)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .join(Product, PrescriptionItem.product_id == Product.id)
        .filter(PrescriptionItem.next_repeat_date.isnot(None))
        .filter(PrescriptionItem.next_repeat_date <= horizon)
        .filter(PrescriptionItem.repeats_used < PrescriptionItem.repeats_allowed)
        .all()
    )
    if not rows:
        return []
    patients = {
        p.id: p for p in
        db.query(Patient).filter(
            Patient.id.in_({s.patient_id for _i, s, _p in rows if s.patient_id})).all()
    }
    today_ = date.today()
    out = []
    for item, script, product in rows:
        patient = patients.get(script.patient_id)
        days = (item.next_repeat_date - today_).days
        out.append({
            "patient_id": script.patient_id,
            "patient": _clip(
                f"{patient.first_name} {patient.last_name}".strip() if patient else "—", 22),
            "product": _clip(product.name, 24),
            "due": item.next_repeat_date.isoformat(),
            "days": days,
            "overdue": days < 0,
            "call": _clip(
                (patient.caregiver_name or "")
                if patient and patient.contact_caregiver_first and patient.caregiver_name
                else (f"{patient.first_name} {patient.last_name}".strip() if patient else "—"),
                22),
            "phone": ((patient.caregiver_phone or patient.phone or "")
                      if patient and patient.contact_caregiver_first
                      else ((patient.phone or patient.caregiver_phone or "") if patient else "")),
            "repeats_left": (item.repeats_allowed or 0) - (item.repeats_used or 0),
        })
    out.sort(key=lambda r: r["days"])
    return out
