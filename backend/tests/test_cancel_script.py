"""A script with nothing dispensed can be cancelled, with a reason, by the right people.

Scripts saved and never dispensed stayed on the worklist for good — including
the identical copies left behind by refused dispensings. Against a snapshot of
the local database:

  - a reason is required
  - only a pharmacist, manager or admin may cancel
  - cancelled, the script leaves the worklist, cannot be dispensed, and the
    change trail says who, when and why
  - it cannot be cancelled twice
  - a held script's hold is released with it
  - a script already dispensed in part cannot be cancelled
  - a draft is deleted, not cancelled

  python tests/test_cancel_script.py
"""
import sys
from types import SimpleNamespace

from snapshot_app import client, sql

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def run():
    c = client()
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=40").json()
               if (p.get("quantity_on_hand") or 0) >= 5]
    patients = c.get("/api/patients?q=a&limit=30").json()

    def script(lines=1, patient=None, draft=False):
        return c.post("/api/prescriptions", json={
            "patient_id": (patient or patients[0])["id"], "doctor_id": doctor["id"],
            "notes": "cancel test", "draft": draft,
            "items": [{**LINE, "product_id": stocked[i]["id"], "quantity": 1} for i in range(lines)]}).json()

    rx = script()
    r = c.post(f"/api/prescriptions/{rx['id']}/cancel", json={"reason": "  "})
    assert r.status_code == 400 and "Say why" in r.json()["detail"], r.text
    print("ok    a reason is required")

    from app.database import SessionLocal
    from app.models import Prescription
    from app import tenancy
    from app.services import script_cancel
    db = SessionLocal()
    try:
        with tenancy.unscoped():
            row = db.get(Prescription, rx["id"])
            for role in ("cashier", "accountant"):
                try:
                    script_cancel.cancel(db, rx=row, reason="duplicate",
                                         user=SimpleNamespace(id=0, role=role))
                except script_cancel.CancelError as exc:
                    assert exc.status == 403, exc.status
                    continue
                raise AssertionError(f"a {role} was allowed to cancel a script")
        db.rollback()
    finally:
        db.close()
    print("ok    only a pharmacist, manager or admin may cancel (a 403 for anyone else)")

    r = c.post(f"/api/prescriptions/{rx['id']}/cancel", json={"reason": "Captured twice by mistake"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    queue = c.get("/api/dispensary/worklist").json()["queue"]
    assert not any(q["prescription_id"] == rx["id"] for q in queue), "a cancelled script is still on the worklist"
    d = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
        "item_ids": [rx["items"][0]["id"]], "payment_method": "cash", "pharmacist_initial": "TM"})
    assert d.status_code == 400 and "cancelled" in d.json()["detail"], d.text
    trail = sql("select field, old_value, new_value, reason, changed_by_id from script_changes "
                "where prescription_id = ? order by id desc limit 1", (rx["id"],))
    assert trail and trail[0][:4] == ("status", "active", "cancelled", "Captured twice by mistake") \
        and trail[0][4], trail
    print("ok    cancelled, it leaves the worklist, cannot be dispensed, and the trail says who and why")

    r = c.post(f"/api/prescriptions/{rx['id']}/cancel", json={"reason": "again"})
    assert r.status_code == 400 and "already cancelled" in r.json()["detail"], r.text
    print("ok    it cannot be cancelled twice")

    held = script()
    h = c.post(f"/api/prescriptions/{held['id']}/holds", json={"reason_code": "patient_request"}).json()
    r = c.post(f"/api/prescriptions/{held['id']}/cancel", json={"reason": "Patient no longer wants it"})
    assert r.status_code == 200, r.text
    left_open = [x for x in c.get(f"/api/prescriptions/{held['id']}/holds").json() if x["open"]]
    assert not left_open, f"the hold stayed open on a cancelled script: {left_open}"
    print("ok    a held script's hold is released with it")

    part = None
    for patient in patients:
        cand = script(lines=2, patient=patient)
        first = cand["items"][0]["id"]
        d = c.post(f"/api/prescriptions/{cand['id']}/dispense", json={
            "item_ids": [first], "payment_method": "cash", "pharmacist_initial": "TM"})
        if d.status_code == 409:
            continue
        assert d.status_code == 200, d.text
        part = cand
        break
    assert part, "no patient in the snapshot could be dispensed to"
    r = c.post(f"/api/prescriptions/{part['id']}/cancel", json={"reason": "second line not wanted"})
    assert r.status_code == 400 and "Alter script" in r.json()["detail"], r.text
    print("ok    a script already dispensed in part cannot be cancelled, and says where to go")

    draft = script(draft=True)
    r = c.post(f"/api/prescriptions/{draft['id']}/cancel", json={"reason": "not needed"})
    assert r.status_code == 400 and "Delete the draft" in r.json()["detail"], r.text
    print("ok    a draft is deleted, not cancelled")


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"FAIL  {exc}")
        sys.exit(1)
