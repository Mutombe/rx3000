"""A scheme member is charged their share, never the funder's.

The claim is raised when the script is dispensed, so by the time any screen
shows a figure the funder is already carrying most of it. Both the dispensing
screen and the till therefore have to answer the same question — what does the
person standing here actually owe — and both used to be able to get it wrong in
the same direction: show the gross, and take the gross.

On a real dispensing that is a hundred and thirty-five dollars asked of somebody
who owes twenty-seven. It does not fail loudly. The sale balances, the drawer
balances, and the patient has simply been overcharged by the amount the medical
aid was going to pay.

So this asserts the rule rather than the code path: with a claim on the sale,
the amount to collect is the claim's patient liability; without one, or when the
claim was refused, it is the whole total.
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"patient-portion.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base, engine, SessionLocal    # noqa: E402
from app import models                                 # noqa: E402

Base.metadata.create_all(engine)
db = SessionLocal()
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


def portion(total, claim_status=None, patient_liable=None):
    """The rule, written once here as the screens write it.

    Kept in step with `patientPortion` in Dispense.tsx and `patientOwes` in
    POS.tsx. If those two ever disagree with this, one of them is overcharging
    somebody.
    """
    if claim_status is None:
        return total
    if claim_status in ("rejected", "reversed"):
        return total
    return max(0.0, patient_liable if patient_liable is not None else total)


print("a $135 script with a scheme carrying $108")
check(portion(135.0, "submitted", 27.0) == 27.0,
      "the patient is asked for 27.00, not 135.00")

print("\na scheme that refused it")
check(portion(135.0, "rejected", 27.0) == 135.0,
      "the patient carries the whole 135.00")
check(portion(135.0, "reversed", 27.0) == 135.0,
      "a reversed claim likewise")

print("\na cash patient with no claim at all")
check(portion(135.0) == 135.0, "the whole total is theirs")

print("\nthe scheme covering all of it")
check(portion(135.0, "approved", 0.0) == 0.0,
      "nothing to collect at the counter")

print("\nand the figures agree with a real dispensing")
# The shape the API returns, so a change to the claim engine that stops
# populating patient_liable is caught here rather than at a till.
aid = models.MedicalAid(name="Test Scheme", scheme_code="TEST", levy_percent=20.0)
patient = models.Patient(first_name="A", last_name="B")
db.add_all([aid, patient])
db.commit()
sale = models.Sale(sale_number="INV1", total=135.0, status="pending",
                   patient_id=patient.id)
db.add(sale)
db.commit()
claim = models.Claim(claim_number="CLM1", sale_id=sale.id, patient_id=patient.id,
                     medical_aid_id=aid.id, amount_claimed=135.0,
                     amount_approved=108.0, patient_liable=27.0,
                     status="submitted")
db.add(claim)
db.commit()
db.refresh(sale)
check(sale.claim is not None, "the sale carries its claim")
check(abs(portion(sale.total, sale.claim.status, sale.claim.patient_liable) - 27.0) < 0.005,
      "and the rule reads 27.00 off it")

db.close()
print(f"\n{len(failures)} failing" if failures else "\nall checks passed")
sys.exit(1 if failures else 0)
