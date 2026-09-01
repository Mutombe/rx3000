"""Prescription churn: who stopped coming, and what it cost.

A takings report is the sum of the people who did come. It has no shape for
the people who did not, and that is the whole of the problem: a pharmacy losing
a patient a week sees a number that drifts slowly downward and blames the
economy, because the patients who left are not on any screen. They left no
record. The absence of a record IS the event.

So churn is measured the only way an absence can be: two windows, side by side.
Everyone who was a regular in the earlier one, and whether they came back in
the later one.

Three things this is careful about.

  **A patient who never came often is not a churned patient.** Somebody who
  bought a packet of paracetamol once in March and never returned did not
  churn — they were never retained. Only patients with at least
  `REGULAR_VISITS` visits in the base window count, because those are the ones
  whose absence means something changed.

  **A death, a move and a switch to a competitor look identical from here.**
  Every one of them is a patient who stopped coming. The screen must not claim
  to know which, so this reports what it can see and names what it cannot.

  **Value is what they were worth, not what they owe.** A churned patient costs
  the pharmacy their *rate* — what they spent per month while they were coming
  — projected forward. That is the figure that makes a retention call worth
  making, and it is the figure nobody ever has.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Dispensing, Patient, Prescription, PrescriptionItem,
                      Product, Sale)

#: How many visits in the base window make somebody a regular. Two rather than
#: one: a single visit is a passer-by, and counting passers-by as churned makes
#: the rate meaningless — every pharmacy would show 80% churn and nobody would
#: look at the number twice.
REGULAR_VISITS = 2

#: Below this, a chronic line was never really established. Somebody given a
#: month of an antihypertensive who did not come back may simply have been
#: given a different drug by their doctor.
CHRONIC_FILLS = 2


def _money(v) -> float:
    return round(float(v or 0.0), 2)


def _rate_tone(rate: float) -> str:
    """Red means somebody must do something. Low is amber, not red."""
    if rate >= 30:
        return "danger"
    if rate >= 15:
        return "warn"
    return "ok"


def churn(db: Session, *, days: int = 90) -> dict:
    """Who was coming, and who stopped.

    Two windows of `days` each: the base window, and the one that follows it up
    to today. A patient regular in the base window and absent from the recent
    one has churned.
    """
    days = max(14, min(days, 365))
    today = date.today()
    recent_from = today - timedelta(days=days)
    base_from = recent_from - timedelta(days=days)

    def visits(since: date, upto: date) -> dict[int, dict]:
        """Per patient: how many times they came, and what they spent."""
        rows = (
            db.query(Sale.patient_id,
                     func.count(Sale.id),
                     func.coalesce(func.sum(Sale.total), 0.0),
                     func.max(Sale.created_at))
            .filter(Sale.patient_id.isnot(None),
                    Sale.status.notin_(("void", "cancelled", "draft")),
                    Sale.created_at >= datetime.combine(since, datetime.min.time()),
                    Sale.created_at < datetime.combine(upto, datetime.min.time()))
            .group_by(Sale.patient_id).all())
        return {pid: {"visits": n, "value": _money(v), "last": last}
                for pid, n, v, last in rows}

    base = visits(base_from, recent_from)
    recent = visits(recent_from, today + timedelta(days=1))

    regulars = {pid: d for pid, d in base.items() if d["visits"] >= REGULAR_VISITS}
    churned_ids = [pid for pid in regulars if pid not in recent]
    retained_ids = [pid for pid in regulars if pid in recent]

    # What a churned patient was worth per month while they were coming. The
    # loss is that rate carried forward over the same window, because that is
    # the trade the pharmacy actually lost — not the historical total, which is
    # money it already banked.
    months = max(days / 30.4, 0.5)
    lost_monthly = _money(sum(regulars[pid]["value"] for pid in churned_ids) / months)
    lost_window = _money(lost_monthly * months)

    kept_monthly = _money(
        sum(regulars[pid]["value"] for pid in retained_ids) / months) if retained_ids else 0.0

    # Nought regulars is not nought churn.
    #
    # An empty base window makes the arithmetic say 0%, which reads as "nobody
    # left" — the most reassuring possible rendering of "there is nothing here
    # to measure". A pharmacy three months old, or one whose earlier window
    # predates the software, would be told its retention is perfect. So the
    # rate is None in that case and the screen says why.
    measurable = bool(regulars)
    rate = round(100.0 * len(churned_ids) / len(regulars), 1) if measurable else None

    # ---- who, by name ------------------------------------------------------
    #
    # A rate nobody can act on is a rate nobody reads. The list is the point:
    # these are the calls to make this week, most valuable first.
    names = {}
    if churned_ids:
        for p in db.query(Patient).filter(Patient.id.in_(churned_ids[:400])).all():
            names[p.id] = p
    leaving = []
    for pid in sorted(churned_ids, key=lambda i: -regulars[i]["value"])[:100]:
        p = names.get(pid)
        was = regulars[pid]
        leaving.append({
            "patient_id": pid,
            "patient": (f"{p.first_name} {p.last_name}".strip() if p else f"#{pid}"),
            "phone": (p.phone or "") if p else "",
            "visits_before": was["visits"],
            "spent_before": was["value"],
            "monthly_value": _money(was["value"] / months),
            "last_seen": (was["last"].date() if was["last"] else None),
            "days_away": ((today - was["last"].date()).days if was["last"] else None),
        })

    return {
        "days": days,
        "base_from": base_from,
        "base_to": recent_from,
        "recent_from": recent_from,
        "recent_to": today,
        "regulars": len(regulars),
        "churned": len(churned_ids),
        "retained": len(retained_ids),
        "rate": rate,
        "measurable": measurable,
        "retention_rate": round(100.0 - rate, 1) if measurable else None,
        "tone": _rate_tone(rate) if measurable else "muted",
        # Said in words when there is nothing to say in figures.
        "why_not": ("" if measurable else
                    f"Nobody came {REGULAR_VISITS} times or more between "
                    f"{base_from:%d %b %Y} and {recent_from:%d %b %Y}, so there "
                    f"is no earlier group to measure the recent one against. "
                    f"Either the pharmacy was not trading then, or that period "
                    f"predates this software. Try a shorter window."),
        "lost_value": lost_window,
        "lost_monthly": lost_monthly,
        "kept_monthly": kept_monthly,
        # What a percentage point is worth. The figure that turns "churn is up
        # three points" into a decision — three points of a two-hundred-patient
        # book at forty dollars a month is two hundred and forty dollars a month.
        "point_value": _money(lost_monthly / rate) if rate and rate > 0.05 else 0.0,
        "regular_visits": REGULAR_VISITS,
        "leaving": leaving,
        "new_patients": len([pid for pid in recent if pid not in base]),
        # Said in words, because a screen that shows a churn figure without it
        # invites somebody to conclude they lost those patients to a rival.
        "caveat": (
            "A patient who died, moved away, was admitted to hospital or simply "
            "got better looks exactly like one who went to another pharmacy. "
            "This counts everybody who stopped coming; the telephone is the only "
            "thing that can say which."),
    }


def chronic_churn(db: Session, *, days: int = 90) -> dict:
    """Therapies that stopped, medicine by medicine.

    Patient churn says somebody stopped coming. This says what they stopped
    taking, which is the clinically interesting half, and the actionable one:
    a patient who is still buying their diabetes medicine but stopped their
    statin has not left the pharmacy, they have stopped a treatment, and that is
    a call worth making today.
    """
    days = max(14, min(days, 365))
    today = date.today()
    recent_from = today - timedelta(days=days)
    base_from = recent_from - timedelta(days=days)

    rows = (
        db.query(Dispensing.dispensed_at, PrescriptionItem.product_id,
                 Prescription.patient_id, Product.name, Product.unit_price,
                 PrescriptionItem.quantity)
        .join(PrescriptionItem,
              Dispensing.prescription_item_id == PrescriptionItem.id)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .outerjoin(Product, PrescriptionItem.product_id == Product.id)
        .filter(Dispensing.dispensed_at
                >= datetime.combine(base_from, datetime.min.time()),
                Prescription.patient_id.isnot(None),
                PrescriptionItem.product_id.isnot(None))
        .all())

    # (patient, product) -> fills in each window
    base: dict[tuple[int, int], int] = defaultdict(int)
    recent: dict[tuple[int, int], int] = defaultdict(int)
    product_name: dict[int, str] = {}
    product_value: dict[int, float] = {}

    for when, product_id, patient_id, name, price, qty in rows:
        key = (patient_id, product_id)
        if when.date() < recent_from:
            base[key] += 1
        else:
            recent[key] += 1
        product_name[product_id] = name or f"#{product_id}"
        product_value[product_id] = _money((price or 0.0) * (qty or 0))

    per_product: dict[int, dict] = defaultdict(
        lambda: {"established": 0, "stopped": 0})
    for (patient_id, product_id), fills in base.items():
        if fills < CHRONIC_FILLS:
            continue
        entry = per_product[product_id]
        entry["established"] += 1
        if recent.get((patient_id, product_id), 0) == 0:
            entry["stopped"] += 1

    lines = []
    for product_id, entry in per_product.items():
        if entry["established"] < 3:
            # Three patients is the floor for a rate to mean anything. One
            # patient stopping a medicine two people take is 50% churn and
            # is noise dressed as a crisis.
            continue
        rate = round(100.0 * entry["stopped"] / entry["established"], 1)
        lines.append({
            "product_id": product_id,
            "product": product_name.get(product_id, f"#{product_id}"),
            "established": entry["established"],
            "stopped": entry["stopped"],
            "rate": rate,
            "tone": _rate_tone(rate),
            "value_at_risk": _money(entry["stopped"] * product_value.get(product_id, 0.0)),
        })
    lines.sort(key=lambda r: (-r["value_at_risk"], -r["rate"]))

    established = sum(l["established"] for l in lines)
    stopped = sum(l["stopped"] for l in lines)
    return {
        "days": days,
        "from": base_from,
        "to": today,
        "therapies": established,
        "stopped": stopped,
        "rate": round(100.0 * stopped / established, 1) if established else 0.0,
        "value_at_risk": _money(sum(l["value_at_risk"] for l in lines)),
        "minimum_fills": CHRONIC_FILLS,
        "lines": lines[:60],
    }
