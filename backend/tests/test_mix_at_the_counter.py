"""Something made up at the counter is a real thing, not a free-type sticker.

Against a snapshot of the local database:

  - a quote says what it costs and what schedule it would be, and writes nothing
  - making it up draws every ingredient from stock, batch by batch
  - the preparation becomes a product with its own batch number, an expiry from
    its shelf life, and the schedule of its strongest ingredient
  - it dispenses through the ordinary path, and its label names that batch
  - a controlled ingredient writes its register entry
  - not enough of an ingredient refuses before anything is drawn
  - it can be kept as a formula for next time

  python tests/test_mix_at_the_counter.py
"""
import sys
from datetime import date, timedelta

from snapshot_app import client, sql


def run():
    c = client()
    today = date.today()

    def product(name, *, schedule=0, qty=200, price=10.0):
        p = c.post("/api/products", json={"name": name, "schedule": schedule,
                                          "unit_price": price, "cost_price": price / 2,
                                          "units_per_pack": 1, "vat_rate": 0.0}).json()
        c.post("/api/stock/adjust", json={
            "product_id": p["id"], "quantity_delta": qty, "movement_type": "receive",
            "batch_number": f"ING-{p['id']}",
            "expiry_date": (today + timedelta(days=400)).isoformat()})
        return p

    calamine = product("Mix Calamine lotion 200ml", price=6.0)
    menthol = product("Mix Menthol crystals", schedule=2, price=4.0)
    tramadol = product("Mix Tramadol powder", schedule=5, qty=50, price=20.0)

    ingredients = [{"product_id": calamine["id"], "quantity": 150},
                   {"product_id": menthol["id"], "quantity": 2}]
    quoted = c.post("/api/compounding/at-the-counter/quote", json={"ingredients": ingredients})
    assert quoted.status_code == 200, quoted.text
    plan = quoted.json()
    assert plan["can_prepare"] and plan["effective_schedule"] == 2, plan
    assert sql("select count(*) from products where name = 'Calamine & Menthol Lotion'")[0][0] == 0
    print(f"ok    a quote costs it at {plan['total_cost']} and calls it schedule "
          f"{plan['effective_schedule']}, writing nothing")

    before = {p["id"]: sql("select quantity_on_hand from products where id = ?", (p["id"],))[0][0]
              for p in (calamine, menthol)}
    made = c.post("/api/compounding/at-the-counter", json={
        "name": "Calamine & Menthol Lotion", "ingredients": ingredients,
        "makes": 1, "unit": "bottle", "shelf_life_days": 30,
        "directions": "Apply twice a day as needed.", "price": 8.0, "keep_formula": True})
    assert made.status_code == 200, made.text
    mix = made.json()
    assert mix["schedule"] == 2 and mix["batch_number"].startswith("MIX"), mix
    assert mix["expiry_date"] == (today + timedelta(days=30)).isoformat(), mix["expiry_date"]
    print(f"ok    made up as {mix['reference']}, schedule {mix['schedule']}, "
          f"expires {mix['expiry_date']}")

    for p in (calamine, menthol):
        now = sql("select quantity_on_hand from products where id = ?", (p["id"],))[0][0]
        assert now < before[p["id"]], (p["name"], before[p["id"]], now)
    drawn = sql("""select count(*) from stock_movements where reference = ?
                   and movement_type = 'compound'""", (mix["reference"],))[0][0]
    assert drawn >= 2, drawn
    print(f"ok    every ingredient came off stock ({drawn} movements against {mix['reference']})")

    batch = sql("""select batch_number, quantity_remaining, expiry_date from stock_batches
                   where product_id = ?""", (mix["product_id"],))
    assert batch and batch[0][0] == mix["reference"] and batch[0][1] == 1, batch
    print(f"ok    the preparation has a batch of its own: {batch[0][0]}, {batch[0][1]} in stock")

    # It dispenses like anything else, and the label names the batch.
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    who = c.post("/api/patients", json={"first_name": "Rudo", "last_name": "Mixture",
                                        "date_of_birth": "1992-02-02", "gender": "F",
                                        "phone": "0779777888", "confirmed_distinct": True}).json()
    rx = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{"product_id": mix["product_id"], "quantity": 1,
                   "dosage_instructions": mix["directions"], "repeats_allowed": 0,
                   "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "L30"}]}).json()
    out = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
        "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
        "pharmacist_initial": "TM"})
    assert out.status_code == 200, out.text
    label = c.get(f"/api/prescriptions/{rx['id']}/labels").json()[0]
    assert label["printable"] and label["batch_number"] == mix["reference"], label
    assert label["schedule"] == 2 and label["expiry_date"] == mix["expiry_date"], label
    print(f"ok    it dispenses and its label names the batch ({label['batch_number']}) "
          f"and the schedule (S{label['schedule']})")

    # A controlled ingredient is controlled stock leaving the shelf.
    strong = c.post("/api/compounding/at-the-counter", json={
        "name": "Tramadol in aqueous cream", "makes": 1, "unit": "pot",
        "ingredients": [{"product_id": tramadol["id"], "quantity": 5},
                        {"product_id": calamine["id"], "quantity": 20}],
        "directions": "Apply sparingly.", "price": 30.0})
    assert strong.status_code == 200, strong.text
    hard = strong.json()
    assert hard["schedule"] == 5 and "Schedule 5" in hard["warning"], hard
    entries = sql("select count(*) from register_entries where reference = ?", (hard["reference"],))
    assert entries[0][0] >= 1, entries
    print(f"ok    a controlled ingredient makes a schedule {hard['schedule']} preparation, "
          f"and the register has it")

    short = c.post("/api/compounding/at-the-counter", json={
        "name": "More than the shelf holds", "makes": 1,
        "ingredients": [{"product_id": tramadol["id"], "quantity": 9999}],
        "price": 1.0})
    assert short.status_code == 400 and "short of" in short.json()["detail"], short.text
    print("ok    not enough of an ingredient refuses, before anything is drawn")

    kept = sql("select code, name from mixtures where code = ?", (mix["reference"],))
    assert kept and kept[0][1] == "Calamine & Menthol Lotion", kept
    print(f"ok    and it is kept as a formula for next time ({kept[0][0]})")


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
