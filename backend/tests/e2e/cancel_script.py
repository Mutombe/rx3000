"""Cancel script, in a browser.

  - a saved script opened in the dispensary offers Cancel script
  - the dialog will not cancel without a reason, and a common reason fills it
  - cancelling clears the screen, takes the script off the worklist, and the
    server has it cancelled
  - a script already dispensed in part is refused, saying to use Alter script,
    and the dialog stays open with the reason still in it
  - Escape closes the dialog

Run against a local dev server on :4177 and API on :8099:
  python cancel_script.py [screenshot-dir]
"""
import json
import pathlib
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
API = "http://127.0.0.1:8099"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
LINE = {"quantity": 1, "dosage_instructions": "One daily", "repeats_allowed": 0,
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
stocked = [p for p in api("/api/dispensing/products?route=prescription&limit=60", token=token)
           if (p.get("quantity_on_hand") or 0) >= 5]
patients = api("/api/patients?q=e&limit=40", token=token)


def no_blocking(p, product):
    q = (f"/api/counter-messages/for-dispensing?patient_id={p['id']}&product_ids={product['id']}"
         f"&doctor_id={doctor['id']}")
    return not api(q, token=token).get("blocking")


patient = next(p for p in patients if no_blocking(p, stocked[0]) and no_blocking(p, stocked[1]))
to_cancel = api("/api/prescriptions", {"patient_id": patient["id"], "doctor_id": doctor["id"],
                                       "notes": "cancel in the browser",
                                       "items": [{**LINE, "product_id": stocked[0]["id"]}]}, token=token)
part = api("/api/prescriptions", {"patient_id": patient["id"], "doctor_id": doctor["id"],
                                  "notes": "partly dispensed",
                                  "items": [{**LINE, "product_id": stocked[0]["id"]},
                                            {**LINE, "product_id": stocked[1]["id"]}]}, token=token)
d = api(f"/api/prescriptions/{part['id']}/dispense",
        {"item_ids": [part["items"][0]["id"]], "payment_method": "cash", "pharmacist_initial": "TM"},
        token=token)
assert "sale_number" in d, f"could not part-dispense the second script: {d}"
print(f"  cancelling {to_cancel['rx_number']}; part-dispensed {part['rx_number']}")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 900}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)

    page.goto(f"{BASE}/dispense?rx={to_cancel['id']}", wait_until="networkidle")
    page.wait_for_timeout(3200)
    open_btn = page.locator(".page-actions").get_by_role("button", name="Cancel script")
    check("a saved script offers Cancel script", open_btn.count() == 1 and open_btn.is_enabled())
    open_btn.click()
    page.wait_for_timeout(700)
    confirm = page.locator(".disp-cancel-modal").get_by_role("button", name="Cancel script")
    check("the dialog will not cancel without a reason", confirm.is_disabled())
    page.locator(".disp-cancel-modal .hold-reason", has_text="Captured twice by mistake").click()
    page.wait_for_timeout(300)
    check("…and a common reason fills it in",
          page.input_value("#cancel-reason") == "Captured twice by mistake" and confirm.is_enabled())
    if SHOT:
        page.screenshot(path=str(SHOT / "cancel-dialog.png"))
    confirm.click()
    page.wait_for_timeout(2200)
    check("cancelling closes the dialog and clears the screen",
          page.query_selector(".disp-cancel-modal") is None
          and page.query_selector(".disp-patient-picked") is None)
    server = api(f"/api/prescriptions/{to_cancel['id']}", token=token)
    check("…the server has it cancelled", server.get("status") == "cancelled", str(server.get("status")))
    queue = api("/api/dispensary/worklist", token=token)["queue"]
    check("…and it is off the worklist", not any(q["prescription_id"] == to_cancel["id"] for q in queue))

    page.goto(f"{BASE}/dispense?rx={part['id']}", wait_until="networkidle")
    page.wait_for_timeout(3200)
    page.locator(".page-actions").get_by_role("button", name="Cancel script").click()
    page.wait_for_timeout(600)
    page.fill("#cancel-reason", "Second line not wanted")
    page.locator(".disp-cancel-modal").get_by_role("button", name="Cancel script").click()
    page.wait_for_timeout(1800)
    said = " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))
    check("a part-dispensed script is refused, pointing to Alter script", "Alter script" in said, said[:200])
    check("…and the dialog stays open with the reason still in it",
          page.query_selector(".disp-cancel-modal") is not None
          and page.input_value("#cancel-reason") == "Second line not wanted")
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    check("Escape closes the dialog", page.query_selector(".disp-cancel-modal") is None)

    # ---- straight from the worklist, the way the duplicates are found ---------
    twin_a = api("/api/prescriptions", {"patient_id": patient["id"], "doctor_id": doctor["id"],
                                        "notes": "duplicate a", "items": [{**LINE, "product_id": stocked[0]["id"]}]},
                 token=token)
    twin_b = api("/api/prescriptions", {"patient_id": patient["id"], "doctor_id": doctor["id"],
                                        "notes": "duplicate b", "items": [{**LINE, "product_id": stocked[0]["id"]}]},
                 token=token)
    pair = api("/api/prescriptions", {"patient_id": patient["id"], "doctor_id": doctor["id"],
                                      "notes": "two lines", "items": [{**LINE, "product_id": stocked[0]["id"]},
                                                                      {**LINE, "product_id": stocked[1]["id"]}]},
               token=token)
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(2500)
    if page.query_selector(".disp-patient-picked"):
        page.locator(".page-actions").get_by_role("button", name="New script").click()
        page.wait_for_timeout(900)

    def wrap_index(rx_id):
        queue = api("/api/dispensary/worklist", token=token)["queue"]
        shown = page.locator(".wl-row-wrap").count()
        return next((i for i, q in enumerate(queue) if q["prescription_id"] == rx_id and i < shown), None)

    check("worklist rows carry a cancel control", page.locator(".wl-row-wrap .wl-row-cancel").count() > 0)
    idx = wrap_index(twin_a["id"])
    check("the duplicate is on the worklist", idx is not None, f"{twin_a['rx_number']} not among the rows shown")
    if idx is not None:
        page.locator(".wl-row-wrap").nth(idx).locator(".wl-row-cancel").click()
        page.wait_for_timeout(700)
        modal = page.query_selector(".disp-cancel-modal")
        check("pressing it opens the dialog for that script",
              modal is not None and twin_a["rx_number"] in modal.inner_text(),
              modal.inner_text()[:120] if modal else "")
        check("…naming the patient", modal is not None and patient["last_name"] in modal.inner_text())
        check("…without opening the script behind it", page.query_selector(".disp-patient-picked") is None)
        if SHOT:
            page.screenshot(path=str(SHOT / "cancel-from-worklist.png"))
        page.locator(".disp-cancel-modal .hold-reason", has_text="Captured twice by mistake").click()
        page.locator(".disp-cancel-modal").get_by_role("button", name="Cancel script").click()
        page.wait_for_timeout(2200)
        queue = api("/api/dispensary/worklist", token=token)["queue"]
        check("cancelled from the worklist, its line leaves the rail",
              not any(q["prescription_id"] == twin_a["id"] for q in queue)
              and page.locator(f".wl-row-wrap").count() >= 1)
        check("…and its twin stays, still waiting", any(q["prescription_id"] == twin_b["id"] for q in queue))

    idx = wrap_index(pair["id"])
    if idx is not None:
        page.locator(".wl-row-wrap").nth(idx).locator(".wl-row-cancel").click()
        page.wait_for_timeout(700)
        text = page.inner_text(".disp-cancel-modal")
        check("a two-line script says cancelling takes the whole script", "all 2 lines" in text, text[:160])
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    else:
        print("  --    the two-line script is past the rows shown; not exercised")
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
