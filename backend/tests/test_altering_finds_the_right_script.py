"""Altering a script finds the script you asked for.

The Alter-a-script screen took an Rx number, sent it as `?q=`, and opened the
first result. `/api/prescriptions` never declared `q`, and FastAPI drops a query
parameter an endpoint does not declare, so the search was silently thrown away
and the endpoint returned the most recent script in the pharmacy.

That is the worst shape a bug can take. It did not fail. It returned a script,
the screen filled in, and the correction — with its reason, its author and its
audit entry — was applied to a prescription nobody had gone looking for. It
would read afterwards as a deliberate edit.

Against a snapshot of the local database:

  - searching by Rx number returns that script, not the newest one
  - a search that matches nothing returns nothing, rather than the newest one
  - the patient's name and their ID number find it too
  - the picker the screen now opens with lists the most recent scripts
  - and searching it narrows to the one asked for

  python tests/test_altering_finds_the_right_script.py
"""
import sys

from snapshot_app import client

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False}


def run():
    c = client()
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    product = c.get("/api/dispensing/products?route=prescription&limit=1").json()[0]

    who = c.post("/api/patients", json={
        "first_name": "Rudo", "last_name": "Altersearch", "date_of_birth": "1991-03-03",
        "gender": "F", "phone": "0773333333", "id_number": "70-424242X70",
        "confirmed_distinct": True}).json()

    # The one we will go looking for.
    wanted = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": product["id"], "quantity": 30}]}).json()

    # And several captured AFTER it, so "the most recent" is never the answer.
    other = c.post("/api/patients", json={
        "first_name": "Tapiwa", "last_name": "Laterscript", "date_of_birth": "1985-05-05",
        "gender": "M", "phone": "0774444444", "confirmed_distinct": True}).json()
    for _ in range(3):
        newest = c.post("/api/prescriptions", json={
            "patient_id": other["id"], "doctor_id": doctor["id"],
            "items": [{**LINE, "product_id": product["id"], "quantity": 10}]}).json()
    assert newest["id"] != wanted["id"]
    print(f"      looking for {wanted['rx_number']}, with {newest['rx_number']} captured after it")

    # This is the call the screen used to make.
    hits = c.get(f"/api/prescriptions?q={wanted['rx_number']}&limit=1").json()
    assert hits, "searching by Rx number returned nothing"
    assert hits[0]["id"] == wanted["id"], (
        f"asked for {wanted['rx_number']} and got {hits[0].get('rx_number')} — "
        "the search is being ignored and the newest script returned")
    print("ok    searching by Rx number returns that script, not the newest")

    none = c.get("/api/prescriptions?q=RX-NO-SUCH-SCRIPT-999&limit=1").json()
    assert none == [], (
        f"a search matching nothing returned {len(none)} script(s); the first "
        "of them would have been opened as though it were the one asked for")
    print("ok    a search that matches nothing returns nothing")

    by_name = c.get("/api/prescriptions?q=Altersearch&limit=10").json()
    assert any(h["id"] == wanted["id"] for h in by_name), by_name[:2]
    by_id = c.get("/api/prescriptions?q=70-424242X70&limit=10").json()
    assert any(h["id"] == wanted["id"] for h in by_id), by_id[:2]
    print("ok    the patient's name and ID number find it too")

    # The picker the screen now opens with: most recent first, no search.
    recent = c.get("/api/prescriptions/table?per_page=8").json()
    rows = recent.get("items") or []
    assert len(rows) > 0, recent
    assert rows[0]["id"] == newest["id"], (rows[0].get("rx_number"), newest["rx_number"])
    for field in ("rx_number", "patient", "items", "state", "created_at"):
        assert field in rows[0], f"the picker row has no {field}: {rows[0]}"
    print(f"ok    the picker opens on the {len(rows)} most recent scripts, newest first")

    narrowed = c.get(f"/api/prescriptions/table?per_page=8&q={wanted['rx_number']}").json()
    got = narrowed.get("items") or []
    assert len(got) == 1 and got[0]["id"] == wanted["id"], got
    print("ok    and searching it narrows to the one asked for")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:                  # noqa: BLE001
        import os
        import traceback
        traceback.print_exc()
        print("FAIL", exc)
        sys.stdout.flush()
        os._exit(1)
    print("\nall passed")
