"""Every label printed a second time leaves a record.

The model says why: labels jam, peel and end up on the wrong box, so reprinting
is a daily action rather than an exception, but a second label for a controlled
substance is also the easiest way to make one dispensing look like two.
Recording who reprinted what costs nothing and answers the question later.

It cost nothing and was never done. The endpoint existed from the day it was
written and no screen had ever called it, so every label reprinted in this
product so far is unrecorded, and the controlled register's balances had no
companion that could explain a discrepancy.

What is asserted: that the record is made, that it counts up so the dialog can
warn the second time, that a reason survives, and that an unfinished script has
nothing to reprint — the one case where printing a label would be inventing a
dispensing rather than repeating one.
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"reprint-trail.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient              # noqa: E402
from app.database import Base, engine, SessionLocal, get_db   # noqa: E402
from app import models                                 # noqa: E402
from app.main import app                               # noqa: E402
from app.auth import get_current_user                  # noqa: E402

Base.metadata.create_all(engine)
db = SessionLocal()
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


user = models.User(username="rose", full_name="Rose M", role="pharmacist",
                   password_hash="x")
patient = models.Patient(first_name="Tendai", last_name="Moyo")
db.add_all([user, patient])
db.commit()

done = models.Prescription(rx_number="RX-0001", patient_id=patient.id,
                           status="dispensed")
draft = models.Prescription(rx_number="RX-0002", patient_id=patient.id,
                            status="draft")
db.add_all([done, draft])
db.commit()

app.dependency_overrides[get_current_user] = lambda: user
app.dependency_overrides[get_db] = lambda: db
client = TestClient(app)

print("the first reprint")
r = client.post("/api/reprints", json={"kind": "label",
                                       "prescription_id": done.id,
                                       "reason": "the first one smudged"})
check(r.status_code == 200, f"recorded ({r.status_code})")
check(r.json().get("printed_by") == "Rose M", "against the person who printed it")

print("\nthe second")
r2 = client.post("/api/reprints", json={"kind": "label",
                                        "prescription_id": done.id,
                                        "reason": "wrong box"})
check(r2.json().get("previously_printed") == 2,
      f"the count is now 2 ({r2.json().get('previously_printed')}), which is "
      f"what the dialog puts in front of whoever asks for a third")

print("\nthe log the register reads")
rows = client.get(f"/api/reprints?prescription_id={done.id}&kind=label").json()
check(len(rows) == 2, f"both are there ({len(rows)})")
check([x["reason"] for x in rows] == ["wrong box", "the first one smudged"],
      "newest first, with the reasons kept")
check(all(x["rx_number"] == "RX-0001" for x in rows),
      "and each names the script")

print("\nan unfinished script")
r3 = client.post("/api/reprints", json={"kind": "label",
                                        "prescription_id": draft.id})
check(r3.status_code == 400,
      f"refused ({r3.status_code}) — a label for a script nobody has dispensed "
      f"is not a reprint, it is an invention")

print("\na kind that is not a document")
r4 = client.post("/api/reprints", json={"kind": "poster",
                                        "prescription_id": done.id})
check(r4.status_code == 400, f"refused ({r4.status_code})")

print("\nnothing to reprint at all")
r5 = client.post("/api/reprints", json={"kind": "label"})
check(r5.status_code == 400, f"refused ({r5.status_code}) — needs a script or a sale")

print()
if failures:
    print(f"{len(failures)} failed")
    sys.exit(1)
print("reprints are recorded, counted, and refused where they should be")
