"""A blocking warning acknowledged at the counter is recorded on dispensing.

Against the running API, with a real patient and a real allergy match:

  Loveness Andela is recorded as allergic to penicillin; amoxicillin is a
  penicillin, so the allergy check raises a blocking warning with id
  -product.id.

  1. A new script dispensed WITHOUT the acknowledgement is refused, 409
     MESSAGE_UNACKNOWLEDGED — the guard is exactly as strict as it was.
  2. The same dispense WITH the acknowledgement goes through.
  3. The acknowledgement is on record against that script, in the dispensing
     user's name.
  4. An unrelated id sent alongside it is not recorded: only what is actually
     blocking this dispensing is taken.

Run against a local API on :8099:  python acknowledge_on_dispense.py
"""
import json
import pathlib
import sqlite3
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8099"
DB = pathlib.Path(__file__).resolve().parents[2] / "rx3000.db"
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def call(method, path, body=None, token=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


db = sqlite3.connect(DB)
patient_id = db.execute(
    "select id from patients where first_name='Loveness' and last_name='Andela'").fetchone()[0]
doctor_id = db.execute("select id from doctors where active=1 order by id limit 1").fetchone()[0]
product_id = db.execute(
    "select id from products where name='Amoxicillin' and strength='500mg' and active=1").fetchone()[0]
admin_id = db.execute("select id from users where username='admin'").fetchone()[0]

status, login = call("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
token = (login or {}).get("access_token")
check("signed in", status == 200 and bool(token), str(status))

status, found = call("GET", f"/api/counter-messages/for-dispensing?patient_id={patient_id}"
                            f"&product_ids={product_id}", token=token)
blocking = [m["id"] for m in (found or {}).get("blocking", [])]
check("the allergy match blocks amoxicillin for this patient", -product_id in blocking, str(blocking))


def new_script():
    s, rx = call("POST", "/api/prescriptions", {
        "patient_id": patient_id, "doctor_id": doctor_id,
        "items": [{"product_id": product_id, "quantity": 1,
                   "dosage_instructions": "take ONE capsule three times a day",
                   "repeats_allowed": 0, "repeat_interval_days": 30,
                   "auto_refill": False, "icd10_code": "Z76.9"}],
    }, token=token)
    assert s in (200, 201), (s, rx)
    return rx


rx = new_script()
items = [i["id"] for i in rx["items"]]

status, refused = call("POST", f"/api/prescriptions/{rx['id']}/dispense",
                       {"item_ids": items, "pharmacist_initial": "TM"}, token=token)
code = (refused or {}).get("detail", {}).get("error_code") if isinstance((refused or {}).get("detail"), dict) else None
check("without the acknowledgement: refused, 409 MESSAGE_UNACKNOWLEDGED",
      status == 409 and code == "MESSAGE_UNACKNOWLEDGED", f"{status} {refused}")

UNRELATED = 987654
status, sale = call("POST", f"/api/prescriptions/{rx['id']}/dispense",
                    {"item_ids": items, "pharmacist_initial": "TM",
                     "acknowledged_message_ids": [-product_id, UNRELATED]}, token=token)
check("with the acknowledgement: dispensed", status == 200 and bool((sale or {}).get("id")),
      f"{status} {str(sale)[:200]}")

rows = db.execute("select message_id, acknowledged_by_id from message_acknowledgements "
                  "where prescription_id = ?", (rx["id"],)).fetchall()
check("the acknowledgement is recorded against this script, in the dispensing user's name",
      (-product_id, admin_id) in rows, str(rows))
check("an unrelated id sent with it is not recorded",
      all(m != UNRELATED for m, _ in rows), str(rows))

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
