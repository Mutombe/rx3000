"""Does the counter ask when something is collected too soon?

A patient collecting a thirty-day supply twenty days after the last one is
saying something, and it is one of four things: they lost the tablets, they are
taking more than the label says, they are stockpiling before travel, or they
are collecting from several pharmacies and selling them. On a schedule 5 the
last of those is what the controlled register exists to catch.

The pharmacy held every fact needed to ask — when it last went out, how many
days that quantity was meant to last, and nothing asked. There was no
early-refill check anywhere.

The other half of the test matters as much. A checker that queries every
collection is one whose warnings are dismissed unread, including the one that
mattered, so the cases below include the ordinary ones it must stay quiet on: a
patient two days early before a weekend, and one collecting on time.

Built directly and rolled back, so it runs against any database.

    python qa/early-refill.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal                        # noqa: E402
from app import tenancy                                      # noqa: E402
from app.models import (Dispensing, Patient, Prescription,   # noqa: E402
                        PrescriptionItem, Product, User)
from app.services import refill_timing                       # noqa: E402

#: (days since the last one, days of supply, schedule, must it warn, the story)
CASES = [
    (28, 30, 0, False, "two days early on a monthly repeat — ordinary life"),
    (30, 30, 0, False, "collected on the day it is due"),
    (45, 30, 0, False, "late, not early — a different problem, not this one"),
    (20, 30, 0, True, "ten days of the last supply unaccounted for"),
    (8, 30, 0, True, "three weeks early — something has gone wrong"),
    (10, 30, 5, True, "three weeks early on a schedule 5, which is the case "
                      "the register is kept for"),
    (3, 7, 0, False, "a seven-day course; too short a supply to measure"),
    (60, 90, 0, True, "a quarterly script collected a month early"),
]


def main() -> int:
    tenancy.set_current_pharmacy(1)
    db = SessionLocal()
    tenancy.stamp(db)
    failures: list[str] = []

    print(f"  queried when more than {refill_timing.TOLERANCE:.0%} of the last "
          f"supply is unaccounted for\n")

    try:
        patient = db.query(Patient).first()
        user = db.query(User).first()
        product = db.query(Product).first()
        if not (patient and user and product):
            print("FAIL: no patient, user or product on this database")
            return 2

        original_schedule = product.schedule

        for since, supply, schedule, should_warn, story in CASES:
            product.schedule = schedule
            rx = Prescription(patient_id=patient.id, status="active",
                              pharmacy_id=1)
            db.add(rx)
            db.flush()
            item = PrescriptionItem(prescription_id=rx.id,
                                    product_id=product.id, quantity=30,
                                    supply_days=supply, pharmacy_id=1)
            db.add(item)
            db.flush()
            db.add(Dispensing(
                prescription_item_id=item.id, quantity=30,
                dispensed_by_id=user.id,
                dispensed_at=datetime.utcnow() - timedelta(days=since),
                pharmacy_id=1))
            db.flush()

            found = refill_timing.check(db, patient, [product])
            warned = len(found) > 0
            ok = warned == should_warn
            mark = "ok  " if ok else "FAIL"
            label = f"{since}d since a {supply}d supply"
            if schedule:
                label += f", S{schedule}"
            if warned:
                d = found[0]["detail"]
                print(f"  {mark} {label:<34} {found[0]['severity']:<5} "
                      f"{d['days_early']}d early — {story}")
            else:
                print(f"  {mark} {label:<34} quiet — {story}")
            if not ok:
                failures.append(
                    f"{label}: "
                    + ("nothing was said, and " + story if should_warn else
                       "it queried a collection nobody would query, which is "
                       "how a pharmacist learns to dismiss these"))

            # Each case on its own history.
            db.query(Dispensing).filter(
                Dispensing.prescription_item_id == item.id).delete()
            db.query(PrescriptionItem).filter(
                PrescriptionItem.id == item.id).delete()
            db.query(Prescription).filter(Prescription.id == rx.id).delete()
            db.flush()

        # A controlled item must be louder than a blood-pressure tablet, and
        # must say so in words rather than only in a severity code.
        product.schedule = 5
        rx = Prescription(patient_id=patient.id, status="active", pharmacy_id=1)
        db.add(rx); db.flush()
        item = PrescriptionItem(prescription_id=rx.id, product_id=product.id,
                                quantity=30, supply_days=30, pharmacy_id=1)
        db.add(item); db.flush()
        db.add(Dispensing(prescription_item_id=item.id, quantity=30,
                          dispensed_by_id=user.id,
                          dispensed_at=datetime.utcnow() - timedelta(days=10),
                          pharmacy_id=1))
        db.flush()
        found = refill_timing.check(db, patient, [product])
        print()
        loud = bool(found) and found[0]["severity"] == "stop"
        print(f"  {'ok  ' if loud else 'FAIL'} a schedule 5 collected early is "
              f"raised as a stop, not a note")
        if not loud:
            failures.append("an early collection on a controlled item is not "
                            "raised any louder than on a paracetamol")
        says_register = bool(found) and "register" in found[0]["body"].lower()
        print(f"  {'ok  ' if says_register else 'FAIL'} and it says what to do "
              f"— ask, and record the answer")
        if not says_register:
            failures.append("the controlled warning does not tell the "
                            "pharmacist to record the answer")

        never_blocks = all(not f["blocking"] for f in found)
        print(f"  {'ok  ' if never_blocks else 'FAIL'} it never refuses on its "
              f"own — a patient going away needs their tablets")
        if not never_blocks:
            failures.append("it blocks the dispensing, which is how a control "
                            "gets routed around and then catches nothing")

        product.schedule = original_schedule
    finally:
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("a collection that is too soon is queried, and an ordinary one is not")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
