"""The bag on the shelf says what the label says.

The will-call shelf listed the medicine and not how to take it, and the bag's
own page showed an empty Directions line with no explanation — which is what
every bag imported from the old system has, an invoice line never having
carried the directions.

Against a snapshot of the local database:

  - a bag dispensed here carries its directions onto the shelf list
  - the bag's page shows the same words
  - a line captured without directions comes back empty rather than wrong, for
    the page to explain

  python tests/test_willcall_directions.py
"""
import sys

from snapshot_app import client, sql

LINE = {"repeats_allowed": 0, "repeat_interval_days": 30, "auto_refill": False,
        "icd10_code": "I10"}


def run():
    c = client()
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=60").json()
               if (p.get("quantity_on_hand") or 0) >= 5]
    who = c.post("/api/patients", json={"first_name": "Shelf", "last_name": "Directions",
                                        "date_of_birth": "1991-01-01", "gender": "F",
                                        "phone": "0779345345", "confirmed_distinct": True}).json()

    said = "Take ONE tablet three times a day after food."
    rx = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": stocked[0]["id"], "quantity": 2,
                   "dosage_instructions": said},
                  {**LINE, "product_id": stocked[1]["id"], "quantity": 1,
                   "dosage_instructions": ""}]}).json()
    r = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
        "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
        "pharmacist_initial": "SD"})
    assert r.status_code == 200, r.text

    # Every row on the shelf carries the words, and they are the line's own.
    shelf = c.get("/api/dispensing/will-call?limit=200").json()
    rows = shelf["items"] if isinstance(shelf, dict) else shelf
    assert rows and all("directions" in b for b in rows), "the shelf does not carry directions"
    checked = 0
    for b in rows[:20]:
        line = sql("""select coalesce(pi.dosage_instructions, '') from dispensings d
                      join prescription_items pi on pi.id = d.prescription_item_id
                      where d.id = ?""", (b["dispensing_id"],))
        assert line and line[0][0] == b["directions"], (b["dispensing_id"], line, b["directions"])
        checked += 1
    print(f"ok    every bag on the shelf carries its line's directions ({checked} checked)")

    mine = sql("""select d.id, coalesce(pi.dosage_instructions, '') from dispensings d
                  join prescription_items pi on pi.id = d.prescription_item_id
                  where pi.prescription_id = ? order by d.id""", (rx["id"],))
    assert len(mine) == 2, mine
    with_words = [row for row in mine if row[1]][0]
    bag = c.get(f"/api/dispensing/will-call/{with_words[0]}").json()
    assert bag["directions"] == said, bag["directions"]
    print("ok    the bag's own page shows the same words")

    without = [row for row in mine if not row[1]][0]
    empty = c.get(f"/api/dispensing/will-call/{without[0]}").json()
    assert empty["directions"] == "", empty["directions"]
    print("ok    a line captured without directions comes back empty, for the page to explain")

    # And the imported history is off the shelf, where it cannot hide today's bags.
    left = sql("""select count(*) from dispensings d
                  join prescription_items pi on pi.id = d.prescription_item_id
                  join prescriptions p on p.id = pi.prescription_id
                  where d.collected_at is null and p.notes like 'Imported from %'""")[0][0]
    assert left == 0, f"{left} imported dispensing(s) are still on the will-call shelf"
    print("ok    imported history is off the shelf")


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
