"""Can a patient pay part now and owe the rest?

They could not. A sale was unpaid or fully paid, and a till asked to take
twenty of fifty-seven refused, which is what makes a counter ring the whole
thing up as cash and lose the difference where nobody can find it.

The three things that have to be true, in order:

  a short payment is refused unless it is deliberately marked as one
  a deliberate one still needs a pharmacist, because the pharmacy is lending
  the balance is then visible, and collectable later against the same sale

    python qa/part-payment.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("RX5000_API", "http://127.0.0.1:8192")
failures: list[str] = []


def call(path, token="", data=None, headers=None, expect=200):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": "Bearer " + token} if token else {}),
                 **(headers or {})},
        method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, {"detail": body[:200]}


def note(label, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


_, login = call("/api/auth/login", data={"username": "admin", "password": "admin123"})
token = login["access_token"]

_, patients = call("/api/patients?limit=50", token)
patient = patients[0]
_, products = call("/api/products?limit=1", token)
product = products[0]

# A sale that is genuinely awaiting payment.
#
# A counter sale settles the moment it is rung up, so the only thing that
# leaves a sale pending is dispensing a script, which is exactly the case this
# feature is for: the medicine has gone out and the money has not come in.
_, queue = call("/api/dispensary/worklist", token)
row = next((r for r in queue["queue"]), None)
if row is None:
    raise SystemExit("nothing on the worklist to dispense")
_, script = call(f"/api/prescriptions/{row['prescription_id']}", token)
status, sale = call(f"/api/prescriptions/{script['id']}/dispense", token, data={
    "item_ids": [row["item_id"]],
    "payment_method": "cash",
    "supply": {},
    "id_verified": True, "script_sighted": True, "prescriber_verified": True,
    "id_number_seen": "", "pharmacist_initial": "QA", "compliance_notes": "",
})
if status != 200:
    raise SystemExit(f"could not dispense: {sale}")
total = sale["total"]
part = round(total / 3, 2)
print(f"sale {sale['sale_number']} for {total}; the patient can find {part}\n")

# 1. Short, and not declared. Must be refused.
status, body = call("/api/pos/sales/%d/pay" % sale["id"], token, data={
    "payment_method": "split",
    "tenders": [{"method": "cash", "currency_code": "USD", "amount": part}],
})
note("a short payment is refused when it is not declared",
     status == 400 and "short by" in str(body.get("detail", "")).lower(),
     str(body.get("detail", ""))[:80])

# 2. Declared, but with no pharmacist behind it. Must still be refused.
status, body = call("/api/pos/sales/%d/pay" % sale["id"], token, data={
    "payment_method": "split",
    "part_payment": True,
    "tenders": [{"method": "cash", "currency_code": "USD", "amount": part}],
})
note("a declared part payment still needs authorising",
     status == 428, str(body.get("detail", ""))[:80])

# 3. With authorisation. Must go through and leave a balance.
status, grant = call("/api/step-up", token, data={
    "action": "sale.part_payment", "password": "admin123",
})
if status != 200:
    note("a pharmacist can authorise it", False, str(grant)[:120])
else:
    status, paid = call("/api/pos/sales/%d/pay" % sale["id"], token,
                        data={
                            "payment_method": "split",
                            "part_payment": True,
                            "tenders": [{"method": "cash", "currency_code": "USD",
                                         "amount": part}],
                        },
                        headers={"X-Step-Up": grant.get("token", "")})
    note("an authorised part payment goes through",
         status == 200 and paid.get("status") == "part_paid",
         f"status {paid.get('status')}")

    # 4. The balance is visible and correct.
    _, owed = call("/api/pos/owed", token)
    mine = [r for r in owed["items"] if r["sale_id"] == sale["id"]]
    if not mine:
        note("the balance appears on the money-owed list", False, "not listed")
    else:
        row = mine[0]
        note("the balance is what is actually outstanding",
             abs(row["balance"] - round(total - part, 2)) < 0.005,
             f"{row['balance']} of {row['total']}, {row['paid']} paid")

        # 5. The rest can be collected against the same sale.
        status, settled = call("/api/pos/sales/%d/pay" % sale["id"], token, data={
            "payment_method": "cash",
            "amount_tendered": row["balance"],
        })
        note("the balance can be collected later",
             status == 200 and settled.get("status") == "paid",
             f"status {settled.get('status')}")

        _, after = call("/api/pos/owed", token)
        note("and it leaves the money-owed list",
             not [r for r in after["items"] if r["sale_id"] == sale["id"]])

print()
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(f"  · {f}")
    sys.exit(1)
print("a patient can pay part now and the rest later, with a name against it")
