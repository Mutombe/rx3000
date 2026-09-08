"""Dispense a packed medicine through the real API and check every figure.

Written because the last two fixes were declared done from the source rather
than from the running thing, and both times the screen was still wrong. The
backend readers were corrected and the display was not, so a dispenser saw a
pack price and was charged a unit price — the two disagreeing is worse than
either being wrong on its own.

So this drives the actual endpoints a dispenser's screen calls, in the order it
calls them, and asserts the numbers that appear:

  the product search      what the picker shows when a name is typed
  the claim estimate      what the coverage panel quotes before dispensing
  the dispense            what is actually charged
  the labels              what prints on the box
  the claim copy          what goes in the file

A pack of 1000 at $50 is set up on purpose: it is the case that was wrong by a
factor of a thousand, so any figure that is still per-pack is unmissable rather
than a rounding difference somebody could argue about.
"""
import json
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8099"
fails = []


def call(method, path, body=None, token=None, raw=False):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data, timeout=60) as r:
            return r.read() if raw else json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        raise SystemExit(f"{method} {path} -> {e.code}\n  {detail}")


def check(label, got, want, tol=0.005):
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    print(f"  {'ok  ' if ok else 'FAIL'}  {label:52} {got}"
          + ("" if ok else f"   wanted {want}"))
    if not ok:
        fails.append(label)


print("\n  signing in\n")
auth = call("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
tok = auth["access_token"]
me = call("GET", "/api/auth/me", token=tok)
print(f"    {me['full_name']} ({me['role']})")

# ---------------------------------------------------------------- the setup
print("\n  a tub of 1000 capsules at $50, cost $32\n")
prod = call("POST", "/api/products", {
    "name": "E2E AMOXYCILLIN 250MG 1000S", "category": "medicine",
    "schedule": 3, "unit_price": 50.0, "cost_price": 32.0,
    "pack_size": "1000", "units_per_pack": 1000,
    "quantity_on_hand": 2000, "vat_rate": 0.15, "strength": "250mg",
    "dosage_form": "capsule",
}, token=tok)
pid = prod["id"]
print(f"    product {pid}  pack {prod.get('units_per_pack')}  "
      f"pack price ${prod['unit_price']:.2f}")
check("the pack size survived the round trip", prod.get("units_per_pack"), 1000)

QTY = 21
EACH = 50.0 / 1000
EXPECT = round(EACH * QTY, 2)          # $1.05
print(f"\n  dispensing {QTY} capsules — should cost ${EXPECT:.2f}, "
      f"NOT ${50.0 * QTY:,.2f}\n")

# ------------------------------------------- what the counter quotes, in cash
#
# The claim estimate is not the check here: with no medical aid it correctly
# reports nothing to claim, which is a fact about schemes and not about packs.
# The cash price is the figure a dispenser reads out to somebody standing at
# the counter, so that is the one that must not say a thousand times too much.
quote = call("POST", "/api/quick-price",
             {"product_id": pid, "quantity": QTY}, token=tok)
cash = float(quote.get("cash_price") or 0)
check("the cash price quoted at the counter", cash, EXPECT)
check("the scheme price beside it", float(quote.get("scheme_price") or 0), EXPECT)
check("what the patient pays", float(quote.get("patient_pays") or 0), EXPECT)
# The quote runs BEFORE the dispensing, so the full 2000 is right here.
check("stock on the quote, in units", quote.get("in_stock"), 2000)

# ----------------------------------------------------------- the dispensing
patient = call("POST", "/api/patients", {
    "first_name": "E2E", "last_name": "Checkpatient",
    "phone": "0771000000", "address": "1 Test Road\\nHarare",
}, token=tok)
# A finalised script needs a prescriber, which is the server being right: a
# schedule 3 dispensed against nobody is a script an inspector would ask about.
doctors = call("GET", "/api/doctors?limit=1", token=tok)
doc = (doctors if isinstance(doctors, list) else doctors.get("items", []))
doctor_id = doc[0]["id"] if doc else call("POST", "/api/doctors", {
    "name": "Dr E2E Prescriber", "practice_number": "E2E-001"}, token=tok)["id"]

rx = call("POST", "/api/prescriptions", {
    "patient_id": patient["id"],
    "doctor_id": doctor_id,
    "items": [{"product_id": pid, "quantity": QTY,
               "dosage_instructions": "1c tds pc", "repeats_allowed": 2,
               "repeat_interval_days": 30, "icd10_code": "Z76.9"}],
}, token=tok)
sale = call("POST", f"/api/prescriptions/{rx['id']}/dispense",
            {"item_ids": [i["id"] for i in rx["items"]],
             "payment_method": "cash", "pharmacist_initial": "AB"}, token=tok)

line = sale["items"][0]
check("what the sale charged", float(line["line_total"]), EXPECT)
check("the unit price it recorded", float(line["unit_price"]), EACH, tol=1e-6)
check("the unit cost it recorded", float(line["unit_cost"]), 32.0 / 1000, tol=1e-6)
check("the sale total", float(sale["total"]), EXPECT)

margin = (float(line["unit_price"]) - float(line["unit_cost"])) / float(line["unit_price"])
check("margin, which must match a whole pack's", round(margin, 4),
      round((50.0 - 32.0) / 50.0, 4))

# ------------------------------------------------------------ the stock
# This endpoint answers with an envelope — {product, batches, movements, …} —
# not a bare product. Declaring otherwise is what once put `id: undefined` into
# a basket, and the note about it is still in Dispense.tsx.
after = call("GET", f"/api/products/{pid}", token=tok)["product"]
check("stock fell by the units dispensed, not by packs",
      after["quantity_on_hand"], 2000 - QTY)
check("and the pack size is still on the wire", after.get("units_per_pack"), 1000)

# ------------------------------------------------------------ the label
labels = call("GET", f"/api/prescriptions/{rx['id']}/labels", token=tok)
check("a label was produced", len(labels), 1)
if labels:
    check("the label's line total", float(labels[0].get("line_total") or 0), EXPECT)
    print(f"        directions: {labels[0].get('dosage_instructions')!r}")

# ------------------------------------------------------- the claim copy
pdf = call("GET", f"/api/prescriptions/{rx['id']}/claim-copy.pdf", token=tok, raw=True)
check("the claim copy is a PDF", pdf[:4], b"%PDF")
print(f"        {len(pdf):,} bytes")

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
