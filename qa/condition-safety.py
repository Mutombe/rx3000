"""Does the counter warn on what the patient is recorded as living with?

"Chronic conditions" is a first-class field on every patient. The picker offers
Pregnancy and Breastfeeding as their own entries. A pharmacist fills it in for
exactly one reason: it changes what may be handed over.

Nothing on the dispensing path read it. The field was used by the worklist to
decide whose repeat was urgent, by the AI prompt, and by marketing to pick a
campaign audience — and not by the screen that hands over the medicine. So a
pharmacy could hold the single most important fact about a patient, typed in by
somebody who knew why it mattered, and the counter would not mention it.

Recorded and ignored is the worst shape a safety gap takes. The hard part —
asking the patient, and writing it down — had already been done.

Each case below is one somebody actually stands at a counter with. They are
built directly and rolled back, so this runs against any database.

    python qa/condition-safety.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal              # noqa: E402
from app import tenancy                            # noqa: E402
from app.models import Patient, Product            # noqa: E402
from app.services import conditions, messages      # noqa: E402

#: (what the record says, the medicine, must it warn, why it matters)
CASES = [
    ("Breastfeeding", "Codeine Phosphate", True,
     "codeine in a rapid metaboliser has killed breastfed infants"),
    ("Pregnancy", "Warfarin", True,
     "warfarin crosses the placenta and is teratogenic"),
    ("Pregnancy", "Doxycycline", True,
     "tetracyclines affect foetal teeth and bone"),
    ("Pregnancy", "Enalapril", True,
     "ACE inhibitors cause foetal injury"),
    ("Asthma", "Propranolol", True,
     "beta-blockers cause bronchospasm in asthma"),
    ("Renal disease", "Ibuprofen", True,
     "NSAIDs precipitate acute kidney injury in renal disease"),
    ("Renal disease", "Metformin", True,
     "metformin accumulates and risks lactic acidosis"),
    ("Diabetes", "Prednisolone", True,
     "steroids raise blood glucose"),
    ("Glaucoma", "Amitriptyline", True,
     "anticholinergics can close the angle"),
    ("Epilepsy", "Tramadol", True,
     "lowers the seizure threshold"),
    # And the other half of a checker being worth anything: it has to be quiet
    # when there is nothing to say. A warning that fires on everything is read
    # as noise, and then the real one is read as noise too.
    ("Asthma", "Amoxicillin", False, "no reason to warn — an ordinary antibiotic"),
    ("Pregnancy", "Paracetamol", False, "paracetamol is the safe choice here"),
    ("Diabetes", "Amoxicillin", False, "unrelated"),
]


def main() -> int:
    tenancy.set_current_pharmacy(1)
    db = SessionLocal()
    tenancy.stamp(db)
    failures: list[str] = []

    cover = conditions.coverage()
    print(f"  the table holds {cover['pairs']} medicine-and-condition pairs "
          f"across {cover['conditions']} conditions\n")

    try:
        patient = db.query(Patient).first()
        if patient is None:
            print("FAIL: no patient on this database to test with")
            return 2
        original = patient.chronic_conditions

        for recorded, medicine, should_warn, why in CASES:
            product = (db.query(Product)
                       .filter(Product.name.ilike(f"%{medicine}%")).first())
            if product is None:
                # Said, not skipped silently. A case that never ran is not a
                # case that passed, and a quiet skip is how coverage rots.
                print(f"  ––   {recorded:<16} + {medicine:<20} "
                      f"not stocked here, not checked")
                continue

            patient.chronic_conditions = recorded
            db.flush()
            found = conditions.check(db, patient, [product])
            warned = len(found) > 0

            ok = warned == should_warn
            mark = "ok  " if ok else "FAIL"
            if warned:
                sev = found[0]["severity"]
                print(f"  {mark} {recorded:<16} + {medicine:<20} "
                      f"{sev:<5} — {why}")
            else:
                print(f"  {mark} {recorded:<16} + {medicine:<20} "
                      f"quiet — {why}")
            if not ok:
                failures.append(
                    f"{recorded} + {medicine}: "
                    + ("nothing was said, and " + why
                       if should_warn else
                       "it warned when there is nothing to warn about, which is "
                       "how a pharmacist learns to dismiss them"))

        # The warning has to be readable by somebody moving fast: it must name
        # the condition on the record AND what in the medicine matched it.
        breast = (db.query(Product)
                  .filter(Product.name.ilike("%Codeine%")).first())
        if breast is not None:
            patient.chronic_conditions = "Breastfeeding"
            db.flush()
            body = conditions.check(db, patient, [breast])[0]["body"].lower()
            named_both = "breastfeeding" in body and "codeine" in body
            print()
            print(f"  {'ok  ' if named_both else 'FAIL'} the warning names both "
                  f"the record and what matched it")
            if not named_both:
                failures.append(
                    "the warning does not name both the recorded condition and "
                    "the ingredient — a pharmacist has to make the connection "
                    "themselves, at speed")

        # And it must arrive through the same call the counter already makes,
        # or it is a feature nothing reaches.
        if breast is not None:
            bundle = messages.for_dispensing(
                db, patient_id=patient.id, product_ids=[breast.id])
            reached = any(m.get("category") == "condition"
                          for m in bundle.get("messages", bundle.get("items", [])))
            print(f"  {'ok  ' if reached else 'FAIL'} it reaches the counter "
                  f"through the call the dispensing screen already makes")
            if not reached:
                failures.append(
                    "the check works but nothing calls it — the dispensing "
                    "screen would never show it")

        patient.chronic_conditions = original
    finally:
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("what the pharmacy wrote down is read at the moment it matters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
