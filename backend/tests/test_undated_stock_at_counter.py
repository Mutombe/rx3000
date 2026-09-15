"""Stock with no expiry recorded: said plainly, and dated from the pack at the counter.

The CareXpress import brought each product's opening stock in as one batch,
"OPENING", with no expiry date — 1,568 batches, and for 1,502 products it is
all the stock there is. Dispensing refuses anything it cannot show is in date,
so those products could not be dispensed, and the refusal said "check batches
for expired stock" about stock that was not expired.

Recreated here on the administrator's own branch, as the import left it, in a
snapshot of the local database:

  - the refusal says the stock has no expiry recorded, and what to do
  - the screen can ask which lines need the date from the pack
  - a pack already past its expiry is refused, and the batch stays undated
  - the date from the pack dispenses it, dates the batch, records who read
    the date, and the label prints with that expiry
  - once dated, the line no longer needs asking
  - stock that really is past its expiry is called that, not undated

  python tests/test_undated_stock_at_counter.py
"""
import sys
from datetime import date, timedelta

from snapshot_app import client, execute, sql

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}
MAIN = 1   # the administrator's default branch in the local database


def stocked_single_batch(c, skip=()):
    """A prescription medicine whose stock at the main branch is one batch."""
    for p in c.get("/api/dispensing/products?route=prescription&limit=200").json():
        if p["id"] in skip:
            continue
        rows = sql("select id, quantity_remaining from stock_batches "
                   "where product_id = ? and branch_id = ? and quantity_remaining > 0", (p["id"], MAIN))
        if len(rows) == 1 and rows[0][1] >= 5:
            return p, rows[0][0]
    raise AssertionError("no prescription medicine held as a single batch at the main branch")


def dispense_one(c, product, patients, doctor, **extra):
    for patient in patients:
        rx = c.post("/api/prescriptions", json={
            "patient_id": patient["id"], "doctor_id": doctor["id"], "notes": "undated stock",
            "items": [{**LINE, "product_id": product["id"], "quantity": 1}]}).json()
        r = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
            "item_ids": [rx["items"][0]["id"]], "payment_method": "cash",
            "pharmacist_initial": "TM", **extra})
        if r.status_code == 409:
            continue
        return r, rx
    raise AssertionError("no patient in the snapshot could be dispensed to")


def run():
    c = client()
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    patients = c.get("/api/patients?q=a&limit=30").json()

    product, batch_id = stocked_single_batch(c)
    execute("update stock_batches set expiry_date = null where id = ?", (batch_id,))

    r, _ = dispense_one(c, product, patients, doctor)
    detail = r.json().get("detail", "")
    assert r.status_code == 400, f"undated stock was dispensed without a date: {r.status_code} {r.text}"
    assert "no expiry date recorded" in detail and "Enter the expiry printed on the pack" in detail, detail
    assert "Check batches for expired stock" not in detail, detail
    print("ok    the refusal says the stock has no expiry recorded, and what to do")

    need = c.post("/api/dispensing/expiry-needed",
                  json={"lines": [{"product_id": product["id"], "quantity": 1}]}).json()
    assert need and need[0]["product_id"] == product["id"] and need[0]["undated_units"] > 0, need
    print("ok    the screen can ask which lines need the date from the pack")

    past = (date.today() - timedelta(days=3)).isoformat()
    r, _ = dispense_one(c, product, patients, doctor, pack_expiries={str(product["id"]): past})
    assert r.status_code == 400 and "expired on" in r.json()["detail"], r.text
    still = sql("select expiry_date from stock_batches where id = ?", (batch_id,))[0][0]
    assert still is None, f"a refused pack still dated the batch ({still})"
    print("ok    a pack already past its expiry is refused, and the batch stays undated")

    future = (date.today() + timedelta(days=400)).isoformat()
    r, rx = dispense_one(c, product, patients, doctor, pack_expiries={str(product["id"]): future})
    assert r.status_code == 200, f"a dated pack was refused: {r.text}"
    dated = sql("select expiry_date from stock_batches where id = ?", (batch_id,))[0][0]
    assert str(dated).startswith(future), f"the batch was not dated from the pack ({dated})"
    moved = sql("select user_id, notes from stock_movements where product_id = ? and reference like 'EXPIRY %' "
                "order by id desc limit 1", (product["id"],))
    assert moved and moved[0][0] and "recorded from the pack" in moved[0][1], moved
    label = next(l for l in c.get(f"/api/prescriptions/{rx['id']}/labels").json()
                 if l["product_name"] == product["name"])
    assert label["printable"] and str(label["expiry_date"]).startswith(future), label
    print("ok    the date from the pack dispenses it, dates the batch, records who, and the label prints")

    need = c.post("/api/dispensing/expiry-needed",
                  json={"lines": [{"product_id": product["id"], "quantity": 1}]}).json()
    assert need == [], f"a dated line is still asking for a date: {need}"
    print("ok    once dated, the line no longer needs asking")

    other, other_batch = stocked_single_batch(c, skip={product["id"]})
    execute("update stock_batches set expiry_date = ? where id = ?",
            ((date.today() - timedelta(days=30)).isoformat(), other_batch))
    r, _ = dispense_one(c, other, patients, doctor)
    detail = r.json().get("detail", "")
    assert r.status_code == 400 and "past their expiry" in detail and "Take the expired stock off" in detail, detail
    assert "no expiry date recorded" not in detail, detail
    print("ok    stock that really is past its expiry is called that, not undated")


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"FAIL  {exc}")
        sys.exit(1)
