"""Dispense a script for a scheme patient, then settle it at the till.

The two screens are one workflow and they were only half joined. Dispensing
raised a pending sale and nothing else: no claim, one gross figure, and no way
to tell the patient what they owed. At the till, a payment split between the
scheme and cash recorded the scheme's share as collected and never billed
anybody for it.

This walks the whole thing and checks the money at each step, because every
fault in it is a fault you cannot see on a screen — the sale looks paid either
way.

    python qa/dispense-to-till.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("RX5000_API", "http://127.0.0.1:8192")
failures: list[str] = []


def call(path: str, token: str = "", data: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": "Bearer " + token} if token else {})},
        method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:200]
        raise SystemExit(f"{path} -> {exc.code}: {detail}")


def check(label: str, got, want, tol=0.005):
    ok = abs(float(got) - float(want)) <= tol
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got} (expected {want})")
    if not ok:
        failures.append(label)


token = call("/api/auth/login", data={"username": "admin", "password": "admin123"})["access_token"]

# A script that is genuinely still waiting, for a patient on a scheme.
#
# Taken from the worklist rather than by guessing at the prescription list: the
# worklist is the definition of "captured and not yet dispensed", and picking a
# script that has already gone out only produces "no repeats remaining".
queue = call("/api/dispensary/worklist", token)["queue"]
patients = {p["id"]: p for p in call("/api/patients?limit=400", token)}

script = scheme_patient = None
for row in queue:
    person = patients.get(row.get("patient_id"))
    if not person or not person.get("medical_aid_id"):
        continue
    candidate = call(f"/api/prescriptions/{row['prescription_id']}", token)
    pending = [i for i in candidate.get("items", []) if i["id"] == row["item_id"]]
    if pending:
        script, scheme_patient, wanted = candidate, person, pending
        break
if not script:
    raise SystemExit("nothing on the worklist belongs to a patient on a scheme")

print(f"patient {scheme_patient['id']} on scheme {scheme_patient['medical_aid_id']}, "
      f"script {script['rx_number']}\n")

# ---- dispense -------------------------------------------------------------
sale = call(f"/api/prescriptions/{script['id']}/dispense", token, data={
    "item_ids": [i["id"] for i in wanted],
    "payment_method": "medical_aid",
    "supply": {},
    "id_verified": True, "script_sighted": True, "prescriber_verified": True,
    "id_number_seen": "", "pharmacist_initial": "QA", "compliance_notes": "",
})
print(f"dispensed as {sale['sale_number']}, total {sale['total']}, status {sale['status']}")

claim = sale.get("claim")
if not claim:
    failures.append("dispensing raised no claim for a scheme patient")
    print("FAIL dispensing raised no claim, so nobody can tell the patient what they owe")
    raise SystemExit(1)

print(f"     claim {claim['claim_number']}: scheme {claim['amount_approved']}, "
      f"patient {claim['patient_liable']}, status {claim['status']}")
check("scheme + patient equals the sale",
      round(claim["amount_approved"] + claim["patient_liable"], 2), sale["total"])

owed = claim["patient_liable"]

# ---- settle at the till, split between the scheme portion and cash ---------
paid = call(f"/api/pos/sales/{sale['id']}/pay", token, data={
    "payment_method": "split",
    "amount_tendered": 0,
    "tenders": [
        {"method": "medical_aid", "currency_code": "USD",
         "amount": claim["amount_approved"]},
        {"method": "cash", "currency_code": "USD", "amount": owed},
    ],
})
print(f"\nsettled: method {paid['payment_method']}, status {paid['status']}")
check("tenders cover the sale",
      round(sum(t["amount"] for t in paid.get("tenders", []) if t["amount"] > 0), 2),
      sale["total"])

# The claim raised at dispensing must not have been raised a second time here.
claims = [c for c in call("/api/claims/deferred", token) if c["sale_id"] == sale["id"]]
after = paid.get("claim")
print(f"     claim on the settled sale: "
      f"{after['claim_number'] if after else 'none'}")
if after and after["claim_number"] != claim["claim_number"]:
    failures.append("the scheme was billed twice for one dispensing")
    print("FAIL a second claim was raised at the till")
elif after:
    print("ok   the same claim, not a second one")

print()
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(f"  · {f}")
    sys.exit(1)
print("dispensing bills the scheme, and the till collects the patient's share")
