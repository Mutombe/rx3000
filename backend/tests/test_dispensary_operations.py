"""The dispensary's day, as the operations dashboard reads it.

CareXpress To-Be blueprint §10 (Dispensing Operations Dashboard): scripts
processed, queue depth, processing time, holds, and reversals today.
Against a snapshot of the local database:

  - queue depth is the worklist's own count, not a second opinion of it
  - a dispensing appears with its time marked as UTC, who dispensed it, and
    how long the script waited
  - a hold appears among the open holds, with its reason and time held
  - a voided sale is counted only when it carried a dispensing

The void is made the way a void leaves its trace — the stock movement
referenced "VOID <sale number>" — because voiding through the API needs a
second person's approval that a test cannot give.

  python tests/test_dispensary_operations.py
"""
import sys
from datetime import datetime

from snapshot_app import client, execute, sql

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def run():
    c = client()

    ops = c.get("/api/dispensary/operations").json()
    work = c.get("/api/dispensary/worklist").json()
    assert ops["queue_lines"] == work["counts"]["waiting"], (
        f"queue depth {ops['queue_lines']} disagrees with the worklist's {work['counts']['waiting']}")
    assert ops["as_of"].endswith("Z"), ops["as_of"]
    print("ok    queue depth is the worklist's own count, and the time is marked UTC")

    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    product = [p for p in c.get("/api/dispensing/products?route=prescription&limit=40").json()
               if (p.get("quantity_on_hand") or 0) >= 5][0]
    dispensed = None
    for patient in c.get("/api/patients?q=a&limit=30").json():
        rx = c.post("/api/prescriptions", json={
            "patient_id": patient["id"], "doctor_id": doctor["id"], "notes": "operations test",
            "items": [{**LINE, "product_id": product["id"], "quantity": 1}]}).json()
        r = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
            "item_ids": [rx["items"][0]["id"]], "payment_method": "cash", "pharmacist_initial": "TM"})
        if r.status_code == 409:
            continue
        assert r.status_code == 200, r.text
        dispensed = (rx, r.json())
        break
    assert dispensed, "no patient in the snapshot could be dispensed to"
    rx, sale = dispensed

    ops = c.get("/api/dispensary/operations").json()
    mine = [d for d in ops["dispensings"] if d["prescription_id"] == rx["id"]]
    assert mine, "a dispensing made just now is not on the dashboard"
    d = mine[0]
    assert d["at"].endswith("Z") and d["dispenser"], d
    assert d["waited_minutes"] is not None and d["waited_minutes"] >= 0, d
    print("ok    a dispensing appears with its UTC time, its dispenser, and how long it waited")

    held_rx = c.post("/api/prescriptions", json={
        "patient_id": rx["patient_id"], "doctor_id": doctor["id"], "notes": "operations hold",
        "items": [{**LINE, "product_id": product["id"], "quantity": 1}]}).json()
    r = c.post(f"/api/prescriptions/{held_rx['id']}/holds", json={"reason_code": "awaiting_stock"})
    assert r.status_code == 200, r.text
    ops = c.get("/api/dispensary/operations").json()
    hold = next((h for h in ops["open_holds"] if h["prescription_id"] == held_rx["id"]), None)
    assert hold and hold["reason"] == "Waiting for stock" and hold["hours_held"] >= 0, ops["open_holds"][:3]
    assert len(ops["holds_placed"]) >= 1, ops["holds_placed"]
    print("ok    a hold appears among the open holds, with its reason and time held")

    now = datetime.utcnow().isoformat(" ")
    sale_number = sale["sale_number"]
    # Stamped with the same pharmacy and branch as the sale's own stock
    # movement, as a real void's return is: every read is filtered by both, and
    # a row with neither is — correctly — invisible to the dashboard.
    stamp = sql("select pharmacy_id, branch_id from stock_movements where reference = ? limit 1",
                (rx["rx_number"],))
    pharmacy_id, branch_id = stamp[0] if stamp else (None, None)
    other = sql("select s.sale_number from sales s where not exists "
                "(select 1 from dispensings d where d.sale_id = s.id) and s.pharmacy_id is ? limit 1",
                (pharmacy_id,))

    def void_trace(number):
        execute("insert into stock_movements (product_id, movement_type, quantity_delta, balance_after, "
                "reference, notes, created_at, pharmacy_id, branch_id) "
                "values (?, 'return', 1, 0, ?, 'test void', ?, ?, ?)",
                (product["id"], f"VOID {number}", now, pharmacy_id, branch_id))

    # One void of a dispensed sale, and one of a sale that dispensed nothing.
    void_trace(sale_number)
    if other:
        void_trace(other[0][0])
    ops = c.get("/api/dispensary/operations").json()
    numbers = {v["sale_number"] for v in ops["voids"]}
    assert sale_number in numbers, f"a voided dispensed sale was not counted: {ops['voids']}"
    if other:
        assert other[0][0] not in numbers, "a voided sale with no dispensing was counted as a dispensing void"
    print("ok    a voided sale is counted only when it carried a dispensing")


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"FAIL  {exc}")
        sys.exit(1)
