"""The dangerous-drugs register says what went out, to whom, on whose authority.

It is the statutory record. An inspector reads it across: the medicine and the
quantity, the patient and the identity document that was checked, the prescriber
and their practice number, who handed it over and which pharmacist checked it.

Two things were wrong at once, and each hid the other. The screen fetched these
rows on every load of the Dangerous Drugs tab and rendered none of them, so the
register did not exist in the interface at all. And the endpoint behind it
returned `DispensingOut` — the compliance ticks and nothing else, no medicine,
no patient, no prescriber — which nobody noticed, because nothing displayed it
and so nothing missed the columns.

Against a snapshot of the local database:

  - a schedule 5 or 6 hand-over appears in the register
  - and carries the medicine, the patient, the prescriber and who dispensed it
  - the identity seen at the counter is what is shown, not what is on file
  - an ordinary prescription medicine never appears
  - the count is over the whole period, not the page
  - the rows do not cost a query each

  python tests/test_the_dangerous_drugs_register.py
"""
import sys
from datetime import date, timedelta

from sqlalchemy import event

from snapshot_app import client, sql

LINE = {"dosage_instructions": "One at night", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False}
LATER = (date.today() + timedelta(days=400)).isoformat()


def a_controlled_medicine(c):
    """Something schedule 5, in stock at this branch, that may be dispensed."""
    rows = c.get("/api/dispensing/products?route=controlled&limit=40").json()
    stocked = [p for p in rows
               if (p.get("here") or 0) >= 10 or (p.get("here_undated") or 0) >= 10]
    assert stocked, "the snapshot holds no controlled medicine in stock"
    return stocked[0]


def run():
    c = client()
    medicine = a_controlled_medicine(c)
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    who = c.post("/api/patients", json={
        "first_name": "Tarisai", "last_name": "Register", "date_of_birth": "1988-02-02",
        "gender": "M", "phone": "0772222222", "id_number": "63-111111A63",
        "confirmed_distinct": True}).json()

    rx = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": medicine["id"], "quantity": 5}]}).json()
    out = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
        "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
        "pharmacist_initial": "TM",
        # The compliance record a controlled hand-over needs.
        "id_verified": True, "id_number_seen": "63-999999Z63",
        "script_sighted": True, "prescriber_verified": True,
        "pack_expiries": {str(medicine["id"]): LATER}})
    assert out.status_code == 200, out.text
    print(f"      dispensed {medicine['name'][:40]} (S{medicine['schedule']})")

    page = c.get("/api/dispensing/controlled/log/paged?days=90&per_page=25")
    assert page.status_code == 200, page.text
    body = page.json()
    rows = body.get("items") or []
    mine = [r for r in rows if r.get("rx_number") == rx["rx_number"]]
    assert mine, f"the hand-over is not in the register: {rows[:2]}"
    row = mine[0]
    print("ok    the hand-over appears in the register")

    assert medicine["name"].split()[0].lower() in (row.get("medicine") or "").lower(), row
    assert row.get("quantity") == 5, row
    print(f"ok    it names the medicine and the quantity: {row['medicine'][:40]} x{row['quantity']}")

    assert "Register" in (row.get("patient") or ""), row
    assert "Abson" in (row.get("prescriber") or "") or row.get("prescriber"), row
    assert row.get("dispensed_by"), row
    print(f"ok    and the patient, the prescriber and who dispensed it: "
          f"{row['patient']} / {row['prescriber']} / {row['dispensed_by']}")

    # What was seen at the counter beats what is on file. The identity check is
    # the whole reason a schedule 5 hand-over is recorded at all, and showing
    # the number already on the record would make the column say nothing about
    # whether anybody actually looked at a document.
    assert row.get("patient_id_number") == "63-999999Z63", row.get("patient_id_number")
    print("ok    the identity shown is the one seen at the counter, not the one on file")

    for flag in ("id_verified", "script_sighted", "prescriber_verified"):
        assert row.get(flag) is True, (flag, row)
    assert row.get("pharmacist_initial") == "TM", row
    print("ok    the three checks and the checking pharmacist's initials are on the row")

    assert row.get("schedule", 0) >= 5, row
    ordinary = [r for r in rows if (r.get("schedule") or 0) < 5]
    assert not ordinary, f"an unscheduled medicine is in the register: {ordinary[:2]}"
    print("ok    nothing below schedule 5 is in it")

    # The count is over the period, not the page — the one place a silent cap
    # would not be a presentation choice.
    small = c.get("/api/dispensing/controlled/log/paged?days=90&per_page=1").json()
    assert small.get("total") == body.get("total"), (small.get("total"), body.get("total"))
    assert len(small.get("items") or []) == 1, small
    print(f"ok    the count is the whole register ({body.get('total')}), not the page")

    # And it does not walk the relationships a row at a time.
    from app.database import engine
    count = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _tick(*_args):
        count["n"] += 1

    count["n"] = 0
    c.get("/api/dispensing/controlled/log/paged?days=90&per_page=2")
    few = count["n"]
    count["n"] = 0
    many_body = c.get("/api/dispensing/controlled/log/paged?days=90&per_page=100").json()
    many = count["n"]
    shown = len(many_body.get("items") or [])
    assert many <= few + 6, (
        f"{few} statement(s) for 2 rows became {many} for {shown}: the register "
        "is walking to the medicine, the patient and the prescriber one row at a "
        "time, which is a round trip a row against the hosted database.")
    print(f"ok    {shown} rows cost {many} statements, 2 rows cost {few}")


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
