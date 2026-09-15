"""Paid by medical aid, chosen in Finish, in a browser.

  - Finish offers Medical aid beside Send to till / Take payment now / Out for delivery
  - for a patient with no scheme on file it asks for the scheme, then the member
    number, before it will dispense
  - with the card entered, the bill shows what the scheme pays and the
    shortfall, and says the card is saved to the patient's record
  - the shortfall has to be taken before it will dispense
  - dispensed: one claim, the sale settled, the patient's record takes the card
  - Hold the claim asks why, makes the patient pay in full, and the claim is held
  - a scheme member paying on "Take payment now" is settled, not refused as short
  - all four choices fit, and the dialog still does not scroll

Run against a local dev server on :4177 and API on :8099:
  python medical_aid_payment.py [screenshot-dir]
"""
import json
import pathlib
import random
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
API = "http://127.0.0.1:8099"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
LINE = {"quantity": 2, "dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def api(path, data=None, token=None, method=None):
    req = urllib.request.Request(API + path, method=method or ("POST" if data is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None,
                                    timeout=60) as f:
            return json.loads(f.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"status": e.code, **json.loads(e.read() or b"{}")}


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
doctors = api("/api/doctors?limit=3", token=token)
doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
stocked = [p for p in api("/api/dispensing/products?route=prescription&limit=80", token=token)
           if (p.get("quantity_on_hand") or 0) >= 20 and (p.get("unit_price") or 0) > 0
           and not p.get("schedule_requires_compliance")]
scheme = api("/api/medical-aids", token=token)[0]
tag = random.randint(1000, 9999)


def new_patient(first):
    p = api("/api/patients", {"first_name": first, "last_name": f"Aidcase{tag}",
                              "date_of_birth": "1979-03-03", "gender": "F",
                              "phone": f"07719{tag}{random.randint(10, 99)}",
                              "confirmed_distinct": True}, token=token)
    assert "id" in p, p
    return p


def clean(p, product):
    q = (f"/api/counter-messages/for-dispensing?patient_id={p['id']}&product_ids={product['id']}"
         f"&doctor_id={doctor['id']}")
    return not api(q, token=token).get("blocking")


products = [x for x in stocked[:12]]
patient = new_patient("Rufaro")
products = [x for x in products if clean(patient, x)]
held_patient = new_patient("Chipo")


def script(p, product):
    rx = api("/api/prescriptions", {"patient_id": p["id"], "doctor_id": doctor["id"], "notes": "aid e2e",
                                    "items": [{**LINE, "product_id": product["id"]}]}, token=token)
    assert "id" in rx, rx
    return rx


def claims_for(sale_id):
    got = api(f"/api/claims?sale_id={sale_id}", token=token)
    return got if isinstance(got, list) else got.get("items", [])


rx1 = script(patient, products[0])
rx2 = script(held_patient, products[1])


def open_finish(page, rx):
    page.goto(f"{BASE}/dispense?rx={rx['id']}", wait_until="networkidle")
    page.wait_for_timeout(3200)
    page.click(".disp-bar .disp-go")
    page.wait_for_timeout(1500)
    proceed = page.query_selector(".disp-finish .fin-proceed")
    if proceed and not proceed.is_disabled():
        proceed.click()
        page.wait_for_timeout(900)


def foot_says(page):
    el = page.query_selector(".disp-finish .disp-blocked")
    return el.inner_text() if el else ""


def settle_exactly(page):
    amt = page.query_selector("#finish-aid .tender-amount, .disp-finish .tender-amount")
    owed = page.inner_text(".fin-due b").replace("$", "").replace("US", "").replace(",", "").strip()
    amt.fill(owed)
    page.wait_for_timeout(400)
    return float(owed)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 900}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)

    # ---- claim now, card not on file -------------------------------------------
    open_finish(page, rx1)
    choice = page.locator(".fin-seg").get_by_role("radio", name="Medical aid")
    check("Finish offers Medical aid as a fourth way to pay",
          choice.count() == 1 and page.locator(".fin-seg [role=radio]").count() == 4)
    choice.click()
    page.wait_for_timeout(1200)
    check("with no scheme on file it asks for the scheme first", "scheme" in foot_says(page).lower(),
          foot_says(page))
    check("…and will not dispense", page.locator(".fin-dispense").is_disabled())
    page.click("#aid-scheme")
    page.wait_for_timeout(400)
    page.locator(".sel-panel").get_by_text(scheme["name"], exact=True).first.click()
    page.wait_for_timeout(500)
    check("then the member number", "member number" in foot_says(page).lower(), foot_says(page))
    page.fill("#aid-member", f"MB-{tag}")
    page.wait_for_timeout(2000)
    bill = page.inner_text(".fin-bill")
    check("the bill shows what the scheme pays", f"{scheme['name']} pays" in bill, bill[:200])
    check("it says the card is saved to the patient's record",
          "Saved to the patient's record" in page.inner_text("#finish-aid"))
    check("the shortfall has to be taken first", "Take the patient" in foot_says(page), foot_says(page))
    owed = settle_exactly(page)
    check("with it taken, Dispense goes", page.locator(".fin-dispense").is_enabled(), foot_says(page))
    box = page.query_selector(".disp-finish")
    check("four choices and the card fit without the dialog scrolling",
          box.evaluate("b => b.scrollHeight <= b.clientHeight + 1"),
          str(box.evaluate("b => [b.scrollHeight, b.clientHeight]")))
    seg_ok = page.evaluate("""() => [...document.querySelectorAll('.fin-seg button')]
        .every(b => b.scrollWidth <= b.clientWidth + 1)""")
    check("no choice's label is clipped", seg_ok)
    if SHOT:
        page.screenshot(path=str(SHOT / "aid-claim-now.png"))
    page.click(".fin-dispense")
    said = ""
    for _ in range(40):
        page.wait_for_timeout(200)
        said += " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))
        if "on the scheme" in said or "settled" in said:
            break
    page.wait_for_timeout(1500)
    rec = api(f"/api/patients/{patient['id']}", token=token)
    check("the patient's record takes the card",
          rec.get("medical_aid_id") == scheme["id"] and rec.get("medical_aid_number") == f"MB-{tag}",
          f"{rec.get('medical_aid_id')} {rec.get('medical_aid_number')}")
    check("the toast says what the patient paid and what the scheme carries",
          "on the scheme" in said or "settled" in said, said[:200])
    worklist = api("/api/dispensary/worklist", token=token)["queue"]
    check("the script leaves the worklist", not any(q["prescription_id"] == rx1["id"] for q in worklist))

    # ---- hold the claim ----------------------------------------------------------
    open_finish(page, rx2)
    page.locator(".fin-seg").get_by_role("radio", name="Medical aid").click()
    page.wait_for_timeout(800)
    page.click("#aid-scheme")
    page.wait_for_timeout(400)
    page.locator(".sel-panel").get_by_text(scheme["name"], exact=True).first.click()
    page.fill("#aid-member", f"HD-{tag}")
    page.wait_for_timeout(1500)
    shortfall = page.inner_text(".fin-due b")
    page.locator("#finish-aid").get_by_role("radio", name="Hold the claim").click()
    page.wait_for_timeout(900)
    check("holding asks why", "why the claim is being held" in foot_says(page).lower(), foot_says(page))
    full = page.inner_text(".fin-due b")
    check("…and the patient pays in full while it is held", full != shortfall, f"{shortfall} -> {full}")
    page.fill("#aid-hold-reason", "Scheme switch offline")
    settle_exactly(page)
    if SHOT:
        page.screenshot(path=str(SHOT / "aid-hold.png"))
    check("with a reason and the money, Dispense goes", page.locator(".fin-dispense").is_enabled(),
          foot_says(page))
    page.click(".fin-dispense")
    page.wait_for_timeout(5000)

    # ---- a scheme member on "Take payment now" ------------------------------------
    rx3 = script(patient, products[2])     # the card is on file now
    open_finish(page, rx3)
    page.locator(".fin-seg").get_by_role("radio", name="Take payment now").click()
    page.wait_for_timeout(1800)
    check("Take payment now for a member asks only the shortfall",
          "Shortfall" in page.inner_text(".fin-due") or "SHORTFALL" in page.inner_text(".fin-due"),
          page.inner_text(".fin-due"))
    settle_exactly(page)
    page.click(".fin-dispense")
    said = ""
    for _ in range(40):
        page.wait_for_timeout(200)
        said += " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))
        if "on the scheme" in said or "did not go through" in said:
            break
    check("…and it settles rather than being refused as short", "did not go through" not in said, said[:200])
    page.wait_for_timeout(1500)
    browser.close()

# ---- server side -----------------------------------------------------------------
import sqlite3  # noqa: E402
db = sqlite3.connect(str(pathlib.Path(__file__).resolve().parents[2] / "rx3000.db"))


def sale_of(rx_id):
    return db.execute("""SELECT DISTINCT d.sale_id FROM dispensings d
                         JOIN prescription_items pi ON pi.id = d.prescription_item_id
                         WHERE pi.prescription_id = ?""", (rx_id,)).fetchall()


s1, s2 = sale_of(rx1["id"]), sale_of(rx2["id"])
check("claim now dispensed", len(s1) == 1, str(s1))
check("held dispensed", len(s2) == 1, str(s2))
if s1:
    c = db.execute("SELECT status, submitted_at FROM claims WHERE sale_id = ?", s1[0]).fetchall()
    st = db.execute("SELECT status FROM sales WHERE id = ?", s1[0]).fetchone()
    check("claim now: one claim, sent", len(c) == 1 and c[0][1] is not None, str(c))
    check("…and the sale is settled", st[0] == "paid", st[0])
s3 = sale_of(rx3["id"])
if s3:
    c = db.execute("SELECT COUNT(*) FROM claims WHERE sale_id = ?", s3[0]).fetchone()[0]
    st = db.execute("SELECT status FROM sales WHERE id = ?", s3[0]).fetchone()[0]
    check("Take payment now for a member: one claim, sale paid", c == 1 and st == "paid", f"{c} {st}")
else:
    check("Take payment now for a member dispensed", False)
if s2:
    c = db.execute("SELECT status, submitted_at, deferred_reason FROM claims WHERE sale_id = ?", s2[0]).fetchall()
    st = db.execute("SELECT status FROM sales WHERE id = ?", s2[0]).fetchone()
    check("hold: one claim, not sent, with the reason",
          len(c) == 1 and c[0][1] is None and c[0][2] == "Scheme switch offline", str(c))
    check("…and the sale is settled", st[0] == "paid", st[0])

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
