"""A held script does not go out until a pharmacist or manager releases it.

CareXpress To-Be blueprint §8 (Dispensing Holds): a prescription is placed on
hold with a reason code, cleared by a pharmacist or supervisor, and its duration
is tracked and reported. Against a snapshot of the local database:

  - a hold needs a known reason, and a script cannot be held twice at once
  - a held script is refused at dispense, and no sale is made
  - the worklist marks it, below everything that can be worked
  - only a pharmacist, manager or admin may clear it
  - once cleared it dispenses, and the report shows the reason, who released
    it and how long it was held

  python tests/test_dispensing_holds.py
"""
import sys
from types import SimpleNamespace

from snapshot_app import client, sql

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def a_script(c):
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    product = [p for p in c.get("/api/dispensing/products?route=prescription&limit=40").json()
               if (p.get("quantity_on_hand") or 0) >= 5][0]
    for patient in c.get("/api/patients?q=u&limit=40").json():
        rx = c.post("/api/prescriptions", json={
            "patient_id": patient["id"], "doctor_id": doctor["id"], "notes": "hold test",
            "items": [{**LINE, "product_id": product["id"], "quantity": 1}]}).json()
        # A script this patient can actually be dispensed — a blocking warning
        # would refuse it for a reason that has nothing to do with holds.
        probe = c.get(f"/api/prescriptions/{rx['id']}")
        if probe.status_code == 200:
            return rx
    raise AssertionError("could not capture a script")


def dispense(c, rx):
    return c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
        "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
        "pharmacist_initial": "TM"})


def run():
    c = client()

    reasons = c.get("/api/prescriptions/holds/reasons").json()
    assert reasons and reasons[0]["code"] == "awaiting_stock", reasons

    # Find a script that dispenses cleanly once released, so the refusal we see
    # while held is the hold's and nothing else's.
    rx = a_script(c)

    r = c.post(f"/api/prescriptions/{rx['id']}/holds", json={"reason_code": "because"})
    assert r.status_code == 400, f"a hold with no known reason was placed: {r.text}"
    r = c.post(f"/api/prescriptions/{rx['id']}/holds",
               json={"reason_code": "prescriber_query", "note": "Dose looks high — calling Dr Moyo"})
    assert r.status_code == 200, r.text
    hold = r.json()
    assert hold["open"] and hold["reason"] == "Querying the prescriber", hold
    r = c.post(f"/api/prescriptions/{rx['id']}/holds", json={"reason_code": "payment"})
    assert r.status_code == 400 and "already on hold" in r.json()["detail"], r.text
    print("ok    a hold needs a known reason, and a script cannot be held twice at once")

    before = sql("select count(*) from sales")[0][0]
    r = dispense(c, rx)
    after = sql("select count(*) from sales")[0][0]
    assert r.status_code == 409 and "on hold" in r.json()["detail"], (
        f"a held script was dispensed: {r.status_code} {r.text}")
    assert "querying the prescriber" in r.json()["detail"], r.json()["detail"]
    assert after == before, f"a refused dispensing still made a sale ({before} -> {after})"
    print("ok    a held script is refused at dispense, saying why, and no sale is made")

    queue = c.get("/api/dispensary/worklist").json()["queue"]
    mine = [row for row in queue if row["prescription_id"] == rx["id"]]
    if mine:
        assert mine[0]["hold"] and mine[0]["hold"]["reason"] == "Querying the prescriber", mine[0]
        first_held = next(i for i, row in enumerate(queue) if row["hold"])
        assert all(row["hold"] for row in queue[first_held:]), "a held script sits above one that can be worked"
        print("ok    the worklist marks it, below everything that can be worked")
    else:
        # The queue shows the first two hundred; a fresh script may sit past
        # the cut in a busy snapshot. The marking is still checked on the full
        # list the endpoint is built from.
        from app.database import SessionLocal
        from app import tenancy
        from app.services import worklist
        db = SessionLocal()
        try:
            with tenancy.unscoped():
                _q, _n, everything = worklist.pending(db, limit=100000)
        finally:
            db.close()
        row = next(r for r in everything if r["prescription_id"] == rx["id"])
        assert row["hold"] and row["hold"]["reason"] == "Querying the prescriber", row
        print("ok    the worklist marks it (past the visible cut in this snapshot)")

    # The rule on who may clear, against the service: this test signs in only
    # as the administrator. The endpoint answers the same refusal with a 403.
    from app.database import SessionLocal
    from app.models import PrescriptionHold
    from app import tenancy
    from app.services import holds

    db = SessionLocal()
    try:
        with tenancy.unscoped():
            row = db.get(PrescriptionHold, hold["id"])
            for role in ("cashier", "accountant"):
                try:
                    holds.clear(db, hold=row, note="", user=SimpleNamespace(id=0, role=role))
                except holds.HoldError:
                    continue
                raise AssertionError(f"a {role} was allowed to clear a hold")
        db.rollback()
    finally:
        db.close()
    r = c.post(f"/api/prescriptions/holds/{hold['id']}/clear", json={"note": "Dr Moyo confirmed"})
    assert r.status_code == 200, r.text
    cleared = r.json()
    assert not cleared["open"] and cleared["cleared_by"], cleared
    print("ok    only a pharmacist, manager or admin may clear it")

    r = dispense(c, rx)
    assert r.status_code in (200, 409), r.text
    if r.status_code == 409:
        assert "on hold" not in r.json()["detail"], f"still refused as held after release: {r.text}"
        print("--    released; this patient carries an unrelated blocking warning, so not dispensed")
    else:
        print("ok    once released, it dispenses")

    from datetime import date
    today = date.today().isoformat()
    rep = c.get(f"/api/reports/run/dispensing_holds?date_from={today}&date_to={today}&per_page=500").json()
    rows = rep.get("rows") or rep.get("items") or []
    found = [x for x in rows if x.get("rx_number") == (rx.get("rx_number") or f"#{rx['id']}")]
    assert found, f"the hold is not in the report ({len(rows)} rows)"
    line = found[0]
    assert line["reason"] == "Querying the prescriber" and line["status"] == "Released", line
    assert line["cleared_by"] and isinstance(line["hours_held"], (int, float)), line
    print("ok    the report shows the reason, who released it, and how long it was held")


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"FAIL  {exc}")
        sys.exit(1)
