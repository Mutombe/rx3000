"""Several counters dispensing at once, against a running API.

What a single request can never show, and a pharmacy with three terminals meets
on a busy morning:

  last units   twenty scripts for a medicine with ten units on the shelf, sent at
               once: exactly ten go out, the shelf reads nought, no batch goes
               negative, and what was drawn equals what was sold
  same line    one script pressed from eight terminals at once goes out once
  numbering    thirty scripts captured, then dispensed, at once: every request
               answered, every script and sale number distinct
  latency      the time each dispensing took while the others were running

Run against an API you can write to — never production:
  python dispensing_concurrency.py http://127.0.0.1:8099
"""
import json
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def call(path, data=None, token=None, method=None):
    req = urllib.request.Request(API + path, method=method or ("POST" if data is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None,
                                    timeout=120) as f:
            return f.status, json.loads(f.read() or b"null"), time.perf_counter() - started
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            parsed = json.loads(body or b"{}")
        except ValueError:
            parsed = {"detail": body.decode(errors="replace")[:200]}
        return e.code, parsed, time.perf_counter() - started


status, login, _ = call("/api/auth/login", {"username": "admin", "password": "admin123"})
assert status == 200, login
token = login["access_token"]
stamp = int(time.time())


def ok_json(path, data=None):
    status, body, _ = call(path, data, token)
    assert status == 200, f"{path}: {status} {body}"
    return body


doctors = ok_json("/api/doctors?limit=3")
doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)
if not doctor:
    doctor = [ok_json("/api/doctors", {"first_name": "Load", "last_name": "Prescriber",
                                       "practice_number": f"LP{stamp}"})]
doctor = doctor[0]


def product(name, units):
    p = ok_json("/api/products", {"name": f"Load {name} {stamp}", "units_per_pack": 10,
                                  "unit_price": 20.0, "cost_price": 10.0, "vat_rate": 0.0})
    if units:
        ok_json("/api/stock/adjust", {"product_id": p["id"], "quantity_delta": units,
                                      "movement_type": "receive", "batch_number": f"L{stamp}",
                                      "expiry_date": (date.today() + timedelta(days=400)).isoformat()})
    return p


def patient(n):
    return ok_json("/api/patients", {"first_name": "Load", "last_name": f"Patient{stamp}{n}",
                                     "date_of_birth": "1990-01-01", "gender": "F",
                                     "phone": f"0779{stamp % 100000:05d}{n:02d}", "confirmed_distinct": True})


def script(who, prod, qty=1):
    return ok_json("/api/prescriptions", {"patient_id": who["id"], "doctor_id": doctor["id"],
                                          "items": [{**LINE, "product_id": prod["id"], "quantity": qty}]})


def dispense(rx):
    return call(f"/api/prescriptions/{rx['id']}/dispense",
                {"item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
                 "pharmacist_initial": "LT"}, token)


def product_state(p):
    got = ok_json(f"/api/products/{p['id']}")
    return got["product"]["quantity_on_hand"], [b.get("quantity_remaining") for b in got["batches"]]


who = patient(1)

# ---- the last ten units, twenty scripts at once ---------------------------------
scarce = product("Scarce", 10)
scripts = [script(who, scarce) for _ in range(20)]
with ThreadPoolExecutor(max_workers=20) as pool:
    results = list(pool.map(dispense, scripts))
went = [r for r in results if r[0] == 200]
errors = [r for r in results if r[0] >= 500]
on_hand, remaining = product_state(scarce)
check("twenty at once for ten units: exactly ten go out", len(went) == 10,
      f"{len(went)} went; statuses {sorted(r[0] for r in results)}")
check("…no request fails with a server error", not errors, str([e[1] for e in errors][:2]))
check("…the shelf reads nought", on_hand == 0, str(on_hand))
check("…no batch is negative, and none is left over", all((q or 0) == 0 for q in remaining), str(remaining))
sold = sum(sum(i["quantity"] for i in r[1]["items"]) for r in went)
check("…what was sold equals what was drawn", sold == 10 - on_hand, f"sold {sold}, drawn {10 - on_hand}")

# ---- one script from eight terminals ----------------------------------------------
plenty = product("Plenty", 500)
one = script(who, plenty)
with ThreadPoolExecutor(max_workers=8) as pool:
    results = list(pool.map(lambda _: dispense(one), range(8)))
went = [r for r in results if r[0] == 200]
check("one script pressed from eight terminals goes out once", len(went) == 1,
      f"{len(went)} went; statuses {sorted(r[0] for r in results)}")
check("…the others are refused, not crashed", not [r for r in results if r[0] >= 500],
      str([r[1] for r in results if r[0] >= 500][:2]))
on_hand, _ = product_state(plenty)
check("…and one unit left the shelf", on_hand == 499, str(on_hand))

# ---- numbering under load ----------------------------------------------------------
people = [patient(10 + n) for n in range(6)]
with ThreadPoolExecutor(max_workers=30) as pool:
    made = list(pool.map(lambda n: call("/api/prescriptions", {
        "patient_id": people[n % 6]["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": plenty["id"], "quantity": 1}]}, token), range(30)))
captured = [m[1] for m in made if m[0] == 200]
check("thirty scripts captured at once are all saved", len(captured) == 30,
      str(sorted({m[0] for m in made})) + " " + str([m[1] for m in made if m[0] != 200][:2]))
check("…with thirty distinct script numbers", len({c["rx_number"] for c in captured}) == len(captured))
with ThreadPoolExecutor(max_workers=30) as pool:
    results = list(pool.map(dispense, captured))
went = [r for r in results if r[0] == 200]
check("…and dispensed at once, every one goes out", len(went) == len(captured),
      str(sorted({r[0] for r in results})) + " " + str([r[1] for r in results if r[0] != 200][:2]))
check("…with distinct sale numbers", len({r[1]["sale_number"] for r in went}) == len(went))
on_hand, _ = product_state(plenty)
check("…and the shelf fell by exactly that many", on_hand == 499 - len(went), str(on_hand))

times = sorted(r[2] for r in results)
if times:
    p95 = times[max(0, int(len(times) * 0.95) - 1)]
    print(f"\n  dispensing, 30 at once: median {statistics.median(times) * 1000:.0f} ms, "
          f"p95 {p95 * 1000:.0f} ms, slowest {times[-1] * 1000:.0f} ms")
    status, _, took = call("/api/dispensary/worklist", None, token)
    print(f"  worklist afterwards: {took * 1000:.0f} ms ({status})")

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
