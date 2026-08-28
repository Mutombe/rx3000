"""Prove a recorded allergy actually stops the dispensing it should.

This is the check the whole allergy picker exists for. The field is not
decoration: it raises a blocking warning at dispensing by matching what was
recorded against product names and active ingredients.

Two ways it silently fails, both found by running it rather than reading it:

  * A misspelling. "Penicilin" matches nothing, so the check never fires and
    the record looks perfectly correct while doing nothing. That is what the
    vocabulary is for.
  * A class. "Penicillin" spelt perfectly still did not warn on Amoxicillin,
    Augmentin or Co-amoxiclav, because it is not a substring of any of them —
    which is most of the penicillins a Zimbabwean pharmacy actually dispenses.

So the assertion is not "the matcher runs". It is "this patient cannot be given
this drug without somebody being stopped".
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"allergy-safety.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base, engine, SessionLocal          # noqa: E402
from app import models                                       # noqa: E402
from app.routers.clinical_terms_router import seed_if_empty  # noqa: E402
from app.services import messages                            # noqa: E402

Base.metadata.create_all(engine)
db = SessionLocal()
seed_if_empty(db)
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


patient = models.Patient(first_name="Test", last_name="Patient",
                         allergies="Penicillin, Sulphonamides")
db.add(patient)

# Named the way a Zimbabwean shelf actually names them.
STOCK = [
    ("Amoxicillin 500mg", "amoxicillin"),
    ("Augmentin 625mg", "amoxicillin, clavulanate"),
    ("Flucloxacillin 500mg", "flucloxacillin"),
    ("Cotrimoxazole 480mg", "sulfamethoxazole, trimethoprim"),
    ("Paracetamol 500mg", "paracetamol"),
    ("Metformin 500mg", "metformin"),
    ("Amlodipine 5mg", "amlodipine"),
]
products = []
for name, ingredient in STOCK:
    p = models.Product(name=name, active_ingredient=ingredient)
    db.add(p)
    products.append(p)
db.commit()

by_name = {p.name: p for p in products}

print("a patient recorded as allergic to penicillin and sulphonamides")
must_stop = ["Amoxicillin 500mg", "Augmentin 625mg", "Flucloxacillin 500mg",
             "Cotrimoxazole 480mg"]
for name in must_stop:
    rows = messages._allergy_rows(db, patient, [by_name[name]])
    check(bool(rows) and rows[0]["blocking"],
          f"{name} is stopped")

print("\nand nothing else is")
for name in ["Paracetamol 500mg", "Metformin 500mg", "Amlodipine 5mg"]:
    rows = messages._allergy_rows(db, patient, [by_name[name]])
    check(not rows, f"{name} raises no warning")

print("\nthe warning explains the connection")
rows = messages._allergy_rows(db, patient, [by_name["Augmentin 625mg"]])
body = rows[0]["body"] if rows else ""
check("Penicillin" in body and "amoxicillin" in body,
      "it names both the recorded allergy and what matched")

print("\na short synonym cannot fire inside an unrelated word")
# "asa" is a synonym of aspirin. Matched as a bare substring it would hit
# anything containing those three letters, and a warning that cries wolf is one
# a dispenser learns to click through — including the real one.
aspirin_patient = models.Patient(first_name="A", last_name="B", allergies="Aspirin")
db.add(aspirin_patient)
noise = models.Product(name="Lansoprazole 30mg", active_ingredient="lansoprazole")
db.add(noise)
db.commit()
check(not messages._allergy_rows(db, aspirin_patient, [noise]),
      "Lansoprazole does not trip the aspirin record")

db.close()
print(f"\n{len(failures)} failing" if failures else "\nall checks passed")
sys.exit(1 if failures else 0)
