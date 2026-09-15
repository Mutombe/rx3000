"""The database work a dispensing does grows with its lines, and no faster.

Against a snapshot of the local database (16,000 medicines, 28,000 scripts):

  - capturing and dispensing a 1-line and a 15-line script, counting statements
  - each extra line costs a bounded number of statements, the same whether the
    script has two lines or fifteen: no query that repeats per line per line
  - the worklist, the next number and the operations board cost the same
    whatever the size of the history behind them

  python tests/test_dispensing_query_budget.py
"""
import sys
from datetime import date, timedelta

from sqlalchemy import event

from snapshot_app import client

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}
PER_LINE_BUDGET = 25          # statements for each line beyond the first
SCREEN_BUDGET = 40


def run():
    c = client()
    from app.database import engine

    count = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _tick(*_args):
        count["n"] += 1

    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    who = c.post("/api/patients", json={"first_name": "Budget", "last_name": "Patient",
                                        "date_of_birth": "1990-01-01", "gender": "F",
                                        "phone": "0778123123", "confirmed_distinct": True}).json()
    products = []
    for n in range(15):
        p = c.post("/api/products", json={"name": f"Budget line {n}", "units_per_pack": 10,
                                          "unit_price": 20.0, "cost_price": 10.0, "vat_rate": 0.0}).json()
        c.post("/api/stock/adjust", json={"product_id": p["id"], "quantity_delta": 500,
                                          "movement_type": "receive", "batch_number": f"QB{n}",
                                          "expiry_date": (date.today() + timedelta(days=300)).isoformat()})
        products.append(p)

    def measure(size):
        count["n"] = 0
        rx = c.post("/api/prescriptions", json={
            "patient_id": who["id"], "doctor_id": doctor["id"],
            "items": [{**LINE, "product_id": products[i]["id"], "quantity": 2} for i in range(size)]}).json()
        captured = count["n"]
        count["n"] = 0
        r = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
            "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash", "pharmacist_initial": "QB"})
        assert r.status_code == 200, r.text
        return captured, count["n"]

    measure(1)                                   # warm caches: settings, policy, permissions
    sizes = {n: measure(n) for n in (1, 2, 15)}
    for n, (cap, disp) in sizes.items():
        print(f"      {n:>2} line(s): capture {cap:4d} statements, dispense {disp:4d}")
    for what, index in (("capture", 0), ("dispense", 1)):
        early = sizes[2][index] - sizes[1][index]
        late = (sizes[15][index] - sizes[1][index]) / 14
        assert late <= PER_LINE_BUDGET, f"{what}: {late:.1f} statements per extra line"
        assert late <= early * 1.5 + 2, f"{what}: lines cost more as the script grows ({early} then {late:.1f})"
        print(f"ok    {what}: about {late:.0f} statements per extra line, flat as the script grows")

    for path in ("/api/dispensary/worklist", "/api/prescriptions/next-number", "/api/dispensary/operations"):
        c.get(path)
        count["n"] = 0
        assert c.get(path).status_code == 200
        assert count["n"] <= SCREEN_BUDGET, f"{path}: {count['n']} statements"
        print(f"ok    {path}: {count['n']} statements")


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
