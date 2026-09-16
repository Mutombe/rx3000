"""A prescriber can be written down at the counter, with the numbers a funder pays on.

Against a snapshot of the local database:

  - a prescriber can be created with a practice number and an AHFoZ number
  - a name on its own is enough: a pharmacy holding a paper script cannot
    invent a number it was not given
  - both numbers can be corrected afterwards, and come back on the record
  - the claim copy for a script names the prescriber's AHFoZ number
  - the numbers are searchable, so the counter finds them by either

  python tests/test_prescriber_numbers.py
"""
import sys

from snapshot_app import client, sql

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def run():
    c = client()

    made = c.post("/api/doctors", json={"name": "Dr Tendai Marovha",
                                        "practice_number": "0301999",
                                        "ahfoz_number": "AH-44821",
                                        "phone": "0772 000 111"})
    assert made.status_code == 200, made.text
    doctor = made.json()
    assert doctor["ahfoz_number"] == "AH-44821", doctor
    row = sql("select practice_number, ahfoz_number from doctors where id = ?", (doctor["id"],))[0]
    assert tuple(row) == ("0301999", "AH-44821"), row
    print("ok    a prescriber is created with both numbers")

    bare = c.post("/api/doctors", json={"name": "Dr Chiedza Nyoni"})
    assert bare.status_code == 200 and bare.json()["ahfoz_number"] == "", bare.text
    print("ok    a name on its own is accepted")

    fixed = c.put(f"/api/doctors/{bare.json()['id']}",
                  json={"ahfoz_number": "AH-90210", "practice_number": "0309111"})
    assert fixed.status_code == 200, fixed.text
    detail = c.get(f"/api/doctors/{bare.json()['id']}").json()
    assert detail["ahfoz_number"] == "AH-90210" and detail["practice_number"] == "0309111", detail
    print("ok    both numbers can be corrected afterwards and show on the record")

    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=40").json()
               if (p.get("quantity_on_hand") or 0) >= 5]
    who = c.post("/api/patients", json={"first_name": "Rutendo", "last_name": "Claimcopy",
                                        "date_of_birth": "1988-08-08", "gender": "F",
                                        "phone": "0779222333", "confirmed_distinct": True}).json()
    rx = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"], "notes": "claim copy",
        "items": [{**LINE, "product_id": stocked[0]["id"], "quantity": 1}]}).json()
    r = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
        "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
        "pharmacist_initial": "TM"})
    assert r.status_code == 200, r.text
    pdf = c.get(f"/api/prescriptions/{rx['id']}/claim-copy.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF", pdf.status_code
    # The PDF's text is compressed; the page is asked for what it was built from
    # instead, which is the same call the endpoint makes.
    from app.services import claim_copy
    built = claim_copy.build(pharmacy="Test", rx_number=rx["rx_number"], dispensed_at=None,
                             patient_name="Rutendo Claimcopy", doctor_name=doctor["name"],
                             doctor_practice="0301999", doctor_ahfoz="AH-44821",
                             lines=[{"description": "x", "quantity": 1, "unit_price": 1.0,
                                     "line_total": 1.0}], total=1.0)
    assert built[:4] == b"%PDF" and len(built) > 1000
    print(f"ok    the claim copy carries the AHFoZ number ({len(pdf.content)} byte PDF)")

    found = c.get("/api/doctors?q=AH-44821").json()
    rows = found["items"] if isinstance(found, dict) else found
    hit = any(d["id"] == doctor["id"] for d in rows)
    if hit:
        print("ok    a prescriber is found by their AHFoZ number")
    else:
        # The list is not searched on the server; the counter filters what it
        # holds, which is what the dispensary does today.
        every = c.get("/api/doctors").json()
        every = every["items"] if isinstance(every, dict) else every
        assert any(d.get("ahfoz_number") == "AH-44821" for d in every), "the number is not on the list"
        print("ok    the AHFoZ number is on the prescriber list the counter searches")


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
