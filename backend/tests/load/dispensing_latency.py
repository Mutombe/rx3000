"""How long the dispensary's requests take, one at a time and by script size.

  capture and dispense a 1-line, 5-line and 15-line script, several times each
  the worklist, the next script number and the operations board

A script with fifteen lines should not take fifteen times as long as one, and
the screens a dispenser opens all day should answer in well under a second.

  python dispensing_latency.py http://127.0.0.1:8099
"""
import json
import statistics
import sys
import time
import urllib.request
from datetime import date, timedelta

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}
fails = []


def call(path, data=None, token=None):
    req = urllib.request.Request(API + path, method="POST" if data is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    started = time.perf_counter()
    with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None,
                                timeout=120) as f:
        body = json.loads(f.read() or b"null")
    return body, (time.perf_counter() - started) * 1000


token = call("/api/auth/login", {"username": "admin", "password": "admin123"})[0]["access_token"]
stamp = int(time.time())
doctors = call("/api/doctors?limit=3", token=token)[0]
doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
patient = call("/api/patients", {"first_name": "Latency", "last_name": f"Check{stamp}",
                                 "date_of_birth": "1990-01-01", "gender": "F",
                                 "phone": f"0778{stamp % 1000000:06d}", "confirmed_distinct": True},
               token)[0]
products = []
for n in range(15):
    p = call("/api/products", {"name": f"Latency {n} {stamp}", "units_per_pack": 10,
                               "unit_price": 20.0, "cost_price": 10.0, "vat_rate": 0.0}, token)[0]
    call("/api/stock/adjust", {"product_id": p["id"], "quantity_delta": 5000, "movement_type": "receive",
                               "batch_number": f"LT{stamp}", "expiry_date":
                               (date.today() + timedelta(days=400)).isoformat()}, token)
    products.append(p)

rows = {}
for size in (1, 5, 15):
    capture, dispense = [], []
    for _ in range(6):
        rx, took = call("/api/prescriptions", {
            "patient_id": patient["id"], "doctor_id": doctor["id"],
            "items": [{**LINE, "product_id": products[i]["id"], "quantity": 2} for i in range(size)]}, token)
        capture.append(took)
        _, took = call(f"/api/prescriptions/{rx['id']}/dispense", {
            "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
            "pharmacist_initial": "LT"}, token)
        dispense.append(took)
    rows[size] = (statistics.median(capture[1:]), statistics.median(dispense[1:]))
    print(f"  {size:>2}-line script: capture {rows[size][0]:6.0f} ms   dispense {rows[size][1]:6.0f} ms")

for path in ("/api/dispensary/worklist", "/api/prescriptions/next-number", "/api/dispensary/operations"):
    times = [call(path, token=token)[1] for _ in range(5)]
    median = statistics.median(times[1:])
    print(f"  {path:<34} {median:6.0f} ms")
    if median > 1500:
        fails.append(f"{path} took {median:.0f} ms")

per_line = (rows[15][1] - rows[1][1]) / 14
print(f"\n  each extra line adds about {per_line:.0f} ms to a dispensing")
if rows[15][1] > rows[1][1] * 8:
    fails.append(f"a 15-line dispensing took {rows[15][1] / rows[1][1]:.1f} times a 1-line one")

print(f"\n{len(fails)} failed" if fails else "\nall within bounds")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
