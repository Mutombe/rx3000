"""A prescriber who is not on file yet, added at the counter.

  - searching for a prescriber nobody has written down offers to add them
  - the dialog opens with the typed name already in it, and asks for the
    practice number and the AHFoZ number
  - it warns that a claim may come back unpaid without the AHFoZ number
  - saved, they are on the script straight away, with the number shown beside
    the name, and the server has both numbers
  - the script dispenses in their name

Run against a local dev server on :4177 and API on :8099:
  python add_prescriber.py [screenshot-dir]
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
fails = []
tag = random.randint(1000, 9999)


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def api(path, data=None, token=None):
    req = urllib.request.Request(API + path, method="POST" if data is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None,
                                timeout=60) as f:
        return json.loads(f.read() or b"null")


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
name = f"Dr Farai Mutsvairo{tag}"

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 900}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(2500)
    if page.query_selector(".disp-patient-picked"):
        page.locator(".page-actions").get_by_role("button", name="New script").click()
        page.wait_for_timeout(900)

    page.fill("[data-hk='patient']", "Andela")
    page.wait_for_timeout(1600)
    page.query_selector_all("#step-patient .product-pick")[0].click()
    page.wait_for_timeout(1200)

    page.fill("#disp-doctor", name)
    page.wait_for_timeout(1200)
    none = page.query_selector(".pick-none")
    check("a prescriber nobody has written down offers to add them",
          none is not None and "Add them" in none.inner_text(), none.inner_text() if none else "")
    if SHOT:
        page.screenshot(path=str(SHOT / "prescriber-none.png"))
    page.locator(".pick-none").get_by_role("button", name="Add them").click()
    page.wait_for_timeout(700)
    check("the dialog opens with the typed name already in it",
          page.input_value("#new-doc-name") == name, page.input_value("#new-doc-name"))
    box = page.inner_text(".disp-doctor-modal")
    check("…and asks for both numbers", "Practice number" in box and "AHFoZ number" in box)
    check("…warning what an empty AHFoZ number costs", "unpaid" in box, box[:160])
    page.fill("#new-doc-practice", "0301777")
    page.fill("#new-doc-ahfoz", f"AH-{tag}")
    page.fill("#new-doc-phone", "0772 555 444")
    page.wait_for_timeout(300)
    check("…and the warning goes once the number is in",
          "unpaid" not in page.inner_text(".disp-doctor-modal"))
    if SHOT:
        page.screenshot(path=str(SHOT / "prescriber-add.png"))
    page.locator(".disp-doctor-modal").get_by_role("button", name="Add prescriber").click()
    page.wait_for_timeout(2000)

    picked = page.query_selector(".disp-doctor.is-picked")
    check("saved, they are on the script straight away",
          picked is not None and name in picked.inner_text(), picked.inner_text() if picked else "")
    check("…with the AHFoZ number beside the name",
          picked is not None and f"AH-{tag}" in picked.inner_text(),
          picked.inner_text() if picked else "")
    doctors = api("/api/doctors", token=token)
    doctors = doctors["items"] if isinstance(doctors, dict) else doctors
    saved = next((d for d in doctors if d["name"] == name), None)
    check("…and the server has both numbers",
          saved is not None and saved.get("practice_number") == "0301777"
          and saved.get("ahfoz_number") == f"AH-{tag}", str(saved))

    page.fill("[data-hk='product']", "atorva")
    page.wait_for_timeout(1600)
    page.query_selector_all("#step-items .product-pick")[0].click()
    page.wait_for_timeout(1200)
    if page.query_selector(".disp-edit"):
        page.click(".disp-edit .disp-edit-actions .btn.primary")
        page.wait_for_timeout(1300)
    page.click(".disp-bar .disp-go")
    page.wait_for_timeout(1800)
    proceed = page.query_selector(".disp-finish .fin-proceed")
    if proceed and not proceed.is_disabled():
        proceed.click()
        page.wait_for_timeout(900)
    dispense = page.query_selector(".fin-dispense")
    check("the script is ready to dispense in their name",
          dispense is not None and dispense.is_enabled(),
          page.inner_text(".disp-finish .disp-blocked") if page.query_selector(".disp-finish .disp-blocked") else "")
    if dispense and dispense.is_enabled():
        dispense.click()
        page.wait_for_timeout(4000)
        scripts = api(f"/api/prescriptions?limit=5", token=token)
        rows = scripts["items"] if isinstance(scripts, dict) else scripts
        check("…and it goes out under the new prescriber",
              any(r.get("doctor_id") == saved["id"] for r in rows) if saved else False)
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
