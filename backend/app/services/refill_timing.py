"""Is this being collected too soon?

A patient collecting a thirty-day supply twenty days after the last one is
saying something, and it is one of four things: they lost the tablets, they are
taking more than the label says, they are stockpiling before travel, or they
are collecting from more than one pharmacy and selling them. On a schedule 5
the last of those is the one the law cares about, and it is the reason a
controlled register exists at all.

The pharmacy had every fact needed to ask the question — when it was last
dispensed, how many days that quantity was meant to last, and never asked it.
There is no early-refill check anywhere in this system. Every incumbent has
one, and in a market where codeine and benzodiazepines move freely it is not a
nicety.

It is equally a money and adherence signal in the other direction. A repeat
collected consistently late is a patient with untreated stretches every month,
which the repeat detail page now shows per line — this is the same fact caught
at the counter, while the person is standing there and can be asked.

HOW EARLY IS TOO EARLY

Not "before the day it is due". Real collection is lumpy: somebody comes on
Saturday because they work weekdays, or picks up two days early before
travelling, and a system that queries every one of those is a system whose
warnings are dismissed unread — including the one that mattered.

The tolerance below is a proportion of the supply rather than a fixed number of
days, because five days early on a seven-day course is a different event from
five days early on a ninety-day one.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Dispensing, Patient, Prescription, PrescriptionItem,
                      Product)

#: Collect with this much of the last supply still unused and it is queried.
#: A quarter is deliberately generous — see the module docstring.
TOLERANCE = 0.25

#: A supply of a week or less is not measured. A short course is not collected
#: again — somebody finishing a week of antibiotics does not come back for more
#:, so querying it produces noise on a case that does not arise, and noise is
#: what teaches a pharmacist to dismiss the warning that matters.
MIN_SUPPLY_DAYS = 7

#: Assumed days of supply where the line never recorded one. Stated rather than
#: silently defaulted, and reported as an assumption in the warning, because a
#: number the pharmacy did not choose should not be presented as one it did.
ASSUMED_SUPPLY_DAYS = 30


def check(db: Session, patient: Patient | None,
          products: list[Product]) -> list[dict]:
    """Warn where a medicine is being collected materially before it is due.

    Shaped like the allergy and condition warnings beside it, so the counter
    renders all three without knowing there are three sources.
    """
    if patient is None or not products:
        return []

    ids = [p.id for p in products]
    # The last time each of these went out to this patient, and what the line
    # said it should last. One query for the basket rather than one per line:
    # this runs on every keystroke of the dispensing screen.
    rows = (
        db.query(Product.id,
                 func.max(Dispensing.dispensed_at),
                 func.max(PrescriptionItem.supply_days),
                 func.max(PrescriptionItem.quantity))
        .join(PrescriptionItem, PrescriptionItem.product_id == Product.id)
        .join(Dispensing, Dispensing.prescription_item_id == PrescriptionItem.id)
        .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
        .filter(Prescription.patient_id == patient.id,
                Product.id.in_(ids))
        .group_by(Product.id)
        .all())

    by_product = {p.id: p for p in products}
    now = datetime.utcnow()
    out: list[dict] = []

    for product_id, last, supply_days, quantity in rows:
        if last is None:
            continue
        product = by_product.get(product_id)
        if product is None:
            continue

        assumed = not supply_days or supply_days <= 0
        days_of_supply = ASSUMED_SUPPLY_DAYS if assumed else int(supply_days)
        if days_of_supply <= MIN_SUPPLY_DAYS:
            continue

        elapsed = (now - last).days
        if elapsed < 0:
            continue
        early = days_of_supply - elapsed
        if early <= days_of_supply * TOLERANCE:
            continue

        # A scheduled medicine collected early is a different event from a
        # blood-pressure tablet collected early. The first is the one the
        # register exists for.
        schedule = product.schedule or 0
        controlled = schedule >= 5
        severity = "stop" if controlled else "warn"

        because = (
            f"{product.name} was last dispensed to "
            f"{patient.first_name} {patient.last_name} {elapsed} day"
            f"{'' if elapsed == 1 else 's'} ago"
            + (f" as a {days_of_supply}-day supply" if not assumed
               else f", and the line recorded no days of supply — read against "
                    f"an assumed {days_of_supply} days")
            + f". That leaves {early} day{'' if early == 1 else 's'} of the "
              f"last supply unaccounted for."
        )
        advice = (
            "This is a schedule {s} medicine. Ask what happened to the last "
            "supply and record the answer before dispensing — an early "
            "collection on a controlled item is the pattern a register is kept "
            "to catch.".format(s=schedule)
            if controlled else
            "Ask whether they lost them, are taking more than the label says, "
            "or are going away. Any of those is fine once it is known."
        )

        out.append({
            "id": -(900000 + product_id),
            "scope": "patient", "target_id": patient.id,
            "derived": True,
            "severity": severity,
            "category": "early refill",
            "body": f"{because} {advice}",
            "source": "dispensing history",
            # Never refuses. A patient going away for a month needs their
            # tablets, and software that will not let a pharmacist use their
            # judgement is software they route around — after which it catches
            # nothing at all.
            "blocking": False,
            "created_at": None, "created_by": "",
            # The figures on their own, for a screen that wants to show the
            # arithmetic rather than the sentence.
            "detail": {
                "days_since": elapsed,
                "days_of_supply": days_of_supply,
                "days_early": early,
                "assumed_supply": assumed,
                "schedule": schedule,
            },
        })
    return out
