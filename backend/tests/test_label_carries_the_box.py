"""What the sticker on the box has to say.

A dispensing label is the only piece of paper the patient keeps. It has to name
the medicine and how to take it, and it has to carry the things somebody else
will need later: the batch and the manufacturer a recall is traced by, the
schedule the law knows it as, and the shop that handed it over — its address,
its telephone number and the number its premises are registered under.

The pharmacy's own record is where those come from. They used to come from
environment variables on the server, so every tenant of a hosted install printed
"RX5000 Pharmacy" and the placeholder registration number the software ships
with, on their own boxes.

  python tests/test_label_carries_the_box.py
"""
import sys
from datetime import date, timedelta

from snapshot_app import client, execute, sql


def run():
    c = client()
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]

    product = c.post("/api/products", json={
        "name": "Labelled Amoxicillin", "strength": "500mg", "dosage_form": "Capsule",
        "manufacturer": "Varichem Pharmaceuticals", "units_per_pack": 21,
        "unit_price": 6.3, "cost_price": 3.0, "schedule": 4, "vat_rate": 0.0}).json()
    c.post("/api/stock/adjust", json={
        "product_id": product["id"], "quantity_delta": 210, "movement_type": "receive",
        "batch_number": "VX-4471", "expiry_date": (date.today() + timedelta(days=500)).isoformat()})
    who = c.post("/api/patients", json={"first_name": "Tapiwa", "last_name": "Sticker",
                                        "date_of_birth": "1990-05-05", "gender": "M",
                                        "phone": "0771555999", "confirmed_distinct": True}).json()
    rx = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{"product_id": product["id"], "quantity": 21,
                   "dosage_instructions": "Take ONE capsule three times a day after food.",
                   "repeats_allowed": 0, "repeat_interval_days": 30, "auto_refill": False,
                   "icd10_code": "J02"}]}).json()
    r = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
        "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
        "pharmacist_initial": "TM"})
    assert r.status_code == 200, r.text

    label = c.get(f"/api/prescriptions/{rx['id']}/labels").json()[0]
    assert label["printable"], label["blocked_reason"]
    assert label["batch_number"] == "VX-4471" and label["expiry_date"], label
    print(f"ok    the batch and expiry are on it ({label['batch_number']}, {label['expiry_date']})")

    assert label["manufacturer"] == "Varichem Pharmaceuticals", label["manufacturer"]
    print(f"ok    so is who made it ({label['manufacturer']})")

    assert label["schedule"] == 4, label["schedule"]
    print("ok    and the schedule it is dispensed under")

    pharmacy = sql("select name, trading_name, registration_no, address, phone "
                   "from pharmacies where id = 1")[0]
    assert label["pharmacy_name"] in (pharmacy[1] or "", pharmacy[0] or ""), (label, pharmacy)
    assert label["pharmacy_reg_no"] == (pharmacy[2] or ""), (label["pharmacy_reg_no"], pharmacy[2])
    assert label["pharmacy_address"] == (pharmacy[3] or ""), label["pharmacy_address"]
    assert label["pharmacy_phone"] == (pharmacy[4] or ""), label["pharmacy_phone"]
    print(f"ok    the pharmacy is this pharmacy: {label['pharmacy_name']}, "
          f"{label['pharmacy_phone']}, reg {label['pharmacy_reg_no']}")

    # The shop that actually handed it over, which on a chain is not the company
    # on the licence.
    assert label["branch_name"] and (label["branch_reg_no"] or label["pharmacy_reg_no"])
    print(f"ok    …and the branch that handed it over: {label['branch_name']} [{label['branch_code']}]")

    # A pharmacy that has recorded nothing prints nothing, rather than the
    # software's own placeholder registration number on somebody's medicine.
    was = sql("select registration_no, address, phone from pharmacies where id = 1")[0]
    execute("update pharmacies set registration_no = '', address = '', phone = '' where id = 1")
    execute("update branches set registration_no = '', address = '', phone = '' where pharmacy_id = 1")
    bare = c.get(f"/api/prescriptions/{rx['id']}/labels").json()[0]
    assert bare["pharmacy_reg_no"] == "" and bare["branch_reg_no"] == "", bare
    assert "Y123456" not in str(bare), "the placeholder registration number reached a label"
    print("ok    nothing recorded prints nothing — never the software's placeholder")
    execute("update pharmacies set registration_no = ?, address = ?, phone = ? where id = 1", was)


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
