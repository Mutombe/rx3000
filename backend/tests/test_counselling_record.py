"""What the patient was told is recorded, and required when the pharmacy says so.

CareXpress To-Be blueprint §5 (Patient Counselling Capture) and §8: a
structured counselling record replaces the verbal-only process. When it is
mandatory is §13's open decision, so it is a setting: never, controlled, always.

  - with no requirement, a dispensing needs no record
  - the points given are stored in the order they are said, an unknown point is
    dropped, and the record says who made it
  - "always" refuses a dispensing without a record, and saves nothing
  - "controlled" leaves an ordinary script alone
  - a misspelt rule is treated as never, so a typo cannot stop a pharmacy

  python tests/test_counselling_record.py
"""
import sys
from datetime import datetime

from snapshot_app import client, execute, sql

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def set_rule(value: str):
    execute("delete from settings where key = 'dispensing.require_counselling'")
    execute("insert into settings (key, value, updated_at) values (?, ?, ?)",
            ("dispensing.require_counselling", value, datetime.utcnow().isoformat(" ")))


def dispense(c, **extra):
    """A one-line prescription script, dispensed. Returns (response, rx)."""
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    product = [p for p in c.get("/api/dispensing/products?route=prescription&limit=40").json()
               if (p.get("quantity_on_hand") or 0) >= 5][0]
    for patient in c.get("/api/patients?q=o&limit=30").json():
        rx = c.post("/api/prescriptions", json={
            "patient_id": patient["id"], "doctor_id": doctor["id"], "notes": "counselling test",
            "items": [{**LINE, "product_id": product["id"], "quantity": 1}]}).json()
        r = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
            "item_ids": [rx["items"][0]["id"]], "payment_method": "cash",
            "pharmacist_initial": "TM", **extra})
        if r.status_code == 409:
            continue
        return r, rx
    raise AssertionError("no patient in the snapshot could be dispensed to")


def detail_of(c, rx):
    item_id = rx["items"][0]["id"]
    did = sql("select id from dispensings where prescription_item_id = ? order by id desc limit 1",
              (item_id,))
    assert did, "the dispensing was not recorded"
    return c.get(f"/api/dispensings/{did[0][0]}").json()


def run():
    c = client()

    set_rule("never")
    r, rx = dispense(c)
    assert r.status_code == 200, f"with no requirement a dispensing was refused: {r.text}"
    d = detail_of(c, rx)
    assert not any(p["covered"] for p in d["counselling"]) and d["counselled_by"] == "", d
    print("ok    with no requirement, a dispensing needs no record, and none is invented")

    r, rx = dispense(c, counselling_points=["storage", "dose", "made-up-point"],
                     counselling_notes="Take with food; keep out of the sun.")
    assert r.status_code == 200, r.text
    d = detail_of(c, rx)
    covered = [p["key"] for p in d["counselling"] if p["covered"]]
    assert covered == ["dose", "storage"], f"stored points were {covered}"
    assert [p["key"] for p in d["counselling"]][:2] == ["dose", "duration"], "points are not in the order said"
    assert d["counselling_notes"] == "Take with food; keep out of the sun.", d["counselling_notes"]
    assert d["counselled_by"], "the record does not say who made it"
    print("ok    the points given are stored in order, an unknown one dropped, with who recorded it")

    set_rule("always")
    before = sql("select count(*) from sales")[0][0]
    r, _ = dispense(c)
    after = sql("select count(*) from sales")[0][0]
    assert r.status_code == 400 and "counselling" in r.json()["detail"].lower(), (
        f"'always' let a dispensing through with no record: {r.status_code} {r.text}")
    assert after == before, f"a refused dispensing still made a sale ({before} -> {after})"
    r, _ = dispense(c, counselling_points=["dose"])
    assert r.status_code == 200, f"'always' refused a dispensing that had a record: {r.text}"
    print("ok    'always' refuses a dispensing without a record, saves nothing, and passes one with it")

    set_rule("controlled")
    r, _ = dispense(c)
    assert r.status_code == 200, f"'controlled' refused an ordinary script: {r.text}"
    print("ok    'controlled' leaves an ordinary script alone")

    set_rule("sometimes")
    r, _ = dispense(c)
    assert r.status_code == 200, f"a misspelt rule stopped a dispensing: {r.text}"
    print("ok    a misspelt rule is treated as never")


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"FAIL  {exc}")
        sys.exit(1)
