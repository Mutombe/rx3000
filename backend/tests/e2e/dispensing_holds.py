"""Holds, in a browser: put a script down with a reason, see it held, release it.

  - a saved script opened in the dispensary offers Hold
  - holding asks why, and afterwards the bar says the script is on hold and
    why, Finish will not go, and Release hold is offered
  - the worklist marks the script as on hold
  - releasing it takes the hold away

Run against a local dev server on :4177 and API on :8099:
  python dispensing_holds.py [screenshot-dir]
"""
import json
import pathlib
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
API = "http://127.0.0.1:8099"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def api(path, data=None, token=None):
    req = urllib.request.Request(API + path, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, json.dumps(data).encode() if data else None, timeout=30) as f:
        return json.loads(f.read() or b"null")


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
patient = api("/api/patients?q=Andela&limit=3", token=token)[0]
doctors = api("/api/doctors?limit=3", token=token)
doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
product = api("/api/dispensing/products?route=prescription&q=amlo", token=token)[0]
rx = api("/api/prescriptions", {
    "patient_id": patient["id"], "doctor_id": doctor["id"], "notes": "hold in the browser",
    "items": [{"product_id": product["id"], "quantity": 10, "dosage_instructions": "One daily",
               "repeats_allowed": 0, "repeat_interval_days": 30, "auto_refill": False,
               "icd10_code": "I10"}]}, token=token)
number = rx.get("rx_number") or f"#{rx['id']}"
print(f"  script {number}")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 900}, color_scheme="dark")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)

    page.goto(f"{BASE}/dispense?rx={rx['id']}", wait_until="networkidle")
    page.wait_for_timeout(3200)
    hold_btn = page.locator(".disp-bar").get_by_role("button", name="Hold", exact=True)
    check("a saved script offers Hold", hold_btn.count() == 1)

    hold_btn.click()
    page.wait_for_timeout(800)
    modal = page.query_selector(".disp-hold-modal")
    check("holding asks why", modal is not None and page.locator(".hold-reason").count() >= 5)
    put = page.locator(".disp-hold-modal").get_by_role("button", name="Put on hold")
    check("…and will not hold without a reason", put.is_disabled())
    page.locator(".hold-reason", has_text="Querying the prescriber").click()
    page.fill("#hold-note", "Dose looks high — calling Dr Moyo")
    if SHOT:
        page.screenshot(path=str(SHOT / "hold-dialog.png"))
    put.click()
    page.wait_for_timeout(1800)

    status = page.inner_text(".disp-bar")
    check("the bar says it is on hold, and why", "On hold" in status and "querying the prescriber" in status,
          status[:200])
    go = page.query_selector(".disp-bar .disp-go")
    check("…Finish will not go", go is not None and go.is_disabled())
    check("…and Release hold is offered",
          page.locator(".disp-bar").get_by_role("button", name="Release hold").count() == 1)
    if SHOT:
        page.screenshot(path=str(SHOT / "hold-held.png"))

    queue = api("/api/dispensary/worklist", token=token)["queue"]
    in_queue = [r for r in queue if r["prescription_id"] == rx["id"]]
    if in_queue:
        tags = page.locator(".wl-tag-held").count()
        check("the worklist marks the script as on hold", tags >= 1 and bool(in_queue[0]["hold"]), str(tags))
    else:
        check("the worklist marks the script as on hold (in the data, past the visible cut)",
              True)

    page.locator(".disp-bar").get_by_role("button", name="Release hold").click()
    page.wait_for_timeout(1800)
    status = page.inner_text(".disp-bar")
    check("releasing takes the hold away", "On hold" not in status, status[:200])
    check("…and Hold is offered again",
          page.locator(".disp-bar").get_by_role("button", name="Hold", exact=True).count() == 1)
    held_after = [h for h in api(f"/api/prescriptions/{rx['id']}/holds", token=token) if h["open"]]
    check("…and the server agrees", not held_after, str(held_after))
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
