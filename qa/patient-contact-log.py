"""What was said to a patient, and who owes them a call back.

The medicine was recorded meticulously and the conversation about it was not.
"I rang her twice about that repeat" lived in one person's memory, so the next
person to pick up the record rang a third time, or nobody did.

The parts for this were already built — activities carry a patient_id, and
/api/crm/timeline has accepted patient_id since the day it was written and calls
itself the 360 view. No screen had ever passed one. This asserts the round trip
the new Contact log tab makes, and the thing that made a logged call useless:
a call that has already happened must not sit open for ever waiting for somebody
to tick off a conversation they already had.
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"patient-contact-log.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient              # noqa: E402
from app.database import Base, engine, SessionLocal    # noqa: E402
from app import models                                 # noqa: E402
from app.main import app                               # noqa: E402
from app.auth import get_current_user                  # noqa: E402
from app.database import get_db                        # noqa: E402

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
other = models.Patient(first_name="Farai", last_name="Ncube")
db.add_all([user, patient, other])
db.commit()

app.dependency_overrides[get_current_user] = lambda: user
app.dependency_overrides[get_db] = lambda: db
client = TestClient(app)


def log(**kw):
    r = client.post("/api/crm/activities", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


print("a call that has already happened")
called = log(activity_type="call", patient_id=patient.id,
             subject="Rang about the metformin repeat — no answer")
check(called["patient_id"] == patient.id, "it is filed against that patient")
check(called["completed_at"] is not None,
      "it closes itself — a conversation already had is not a task")

print("\nsomething still owed")
owed = log(activity_type="task", patient_id=patient.id,
           subject="Try her again", due_at="2026-09-01T09:00:00")
check(owed["completed_at"] is None, "a dated follow-up stays open")

print("\nthe timeline the new tab reads")
feed = client.get(f"/api/crm/timeline?patient_id={patient.id}").json()
check(len(feed) == 2, f"both entries come back ({len(feed)})")
check({f["subject"] for f in feed} == {called["subject"], owed["subject"]},
      "and they are the right two")

print("\nanother patient's record")
check(client.get(f"/api/crm/timeline?patient_id={other.id}").json() == [],
      "shows nothing — a call log that bleeds between patients is worse "
      "than none at all")

print("\nticking the follow-up off")
done = client.post(f"/api/crm/activities/{owed['id']}/complete", json={}).json()
check(done["completed_at"] is not None, "it closes")

print()
if failures:
    print(f"{len(failures)} failed")
    sys.exit(1)
print("the contact log holds")
