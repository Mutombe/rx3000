"""Scanning packs in the dispensary, in a browser — as a wedge scanner does it:
the code typed into the medicine box, then Enter.

  - the wrong pack on a saved script is refused, and its line is not ticked
  - the right pack ticks its line
  - with scanning required, the bar counts what is still unscanned until the
    pack is scanned
  - typing a name still searches, rather than being taken for a scan

Sets `dispensing.require_scan_check` on the local database for part of the run
and puts back whatever was there, pass or fail.

Run against a local dev server on :4177 and API on :8099:
  python scan_at_dispensing.py [screenshot-dir]
"""
import json
import pathlib
import sqlite3
import sys
import urllib.request
from datetime import datetime

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
API = "http://127.0.0.1:8099"
DB = pathlib.Path(__file__).resolve().parents[2] / "rx3000.db"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
KEY = "dispensing.require_scan_check"
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


def set_rule(value):
    with sqlite3.connect(str(DB)) as c:
        c.execute("delete from settings where key = ?", (KEY,))
        if value is not None:
            c.execute("insert into settings (key, value, updated_at) values (?, ?, ?)",
                      (KEY, value, datetime.utcnow().isoformat(" ")))


def toasts(page):
    return " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
barcoded = []
for p in api("/api/dispensing/products?route=prescription&limit=200", token=token):
    if (p.get("quantity_on_hand") or 0) < 5:
        continue
    with sqlite3.connect(str(DB)) as c:
        code = c.execute("select barcode from products where id = ?", (p["id"],)).fetchone()[0]
    if code and code.isdigit() and 8 <= len(code) <= 14:
        barcoded.append((p, code))
    if len(barcoded) == 2:
        break
(right, right_code), (wrong, wrong_code) = barcoded
patient = api("/api/patients?q=Andela&limit=3", token=token)[0]
doctors = api("/api/doctors?limit=3", token=token)
doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
rx = api("/api/prescriptions", {
    "patient_id": patient["id"], "doctor_id": doctor["id"], "notes": "scan in the browser",
    "items": [{"product_id": right["id"], "quantity": 1, "dosage_instructions": "One daily",
               "repeats_allowed": 0, "repeat_interval_days": 30, "auto_refill": False,
               "icd10_code": "I10"}]}, token=token)
print(f"  {rx.get('rx_number')} · {right['name']} ({right_code}); wrong pack {wrong['name']} ({wrong_code})")

with sqlite3.connect(str(DB)) as _c:
    _row = _c.execute("select value from settings where key = ?", (KEY,)).fetchone()
previous = _row[0] if _row else None

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1512, "height": 900}, color_scheme="dark")
        page.goto(BASE, wait_until="networkidle")
        page.fill("#lg-user", "admin")
        page.fill("#lg-pass", "admin123")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_timeout(2500)

        def open_script():
            page.goto(f"{BASE}/dispense?rx={rx['id']}", wait_until="networkidle")
            page.wait_for_timeout(3200)

        def scan(code):
            box = page.locator("[data-hk='product']").first
            box.click()
            box.fill(code)
            box.press("Enter")
            page.wait_for_timeout(1600)

        open_script()
        scan(wrong_code)
        said = toasts(page)
        check("the wrong pack is refused, by name", "not on this script" in said, said[:200])
        check("…and its line is not ticked", page.locator(".rx-scan-ok").count() == 0)
        check("…and nothing is added to the script",
              page.locator(".disp-grid > .rx-item:not(.rx-item-waiting)").count() == 1)

        scan(right_code)
        said = toasts(page)
        check("the right pack says it matches", "matches the script" in said, said[:200])
        check("…and ticks its line", page.locator(".rx-scan-ok").count() == 1)
        if SHOT:
            page.screenshot(path=str(SHOT / "scan-matched.png"))

        set_rule("true")
        open_script()
        status = page.inner_text(".disp-bar")
        check("with scanning required, the bar counts what is unscanned",
              "not yet scanned" in status, status[:200])
        scan(right_code)
        status = page.inner_text(".disp-bar")
        check("…until the pack is scanned", "not yet scanned" not in status, status[:200])

        page.locator("[data-hk='product']").first.fill("amlo")
        page.locator("[data-hk='product']").first.press("Enter")
        page.wait_for_timeout(1600)
        check("typing a name still searches", page.locator("#step-items .product-pick").count() > 0
              or page.locator(".product-pick").count() > 0)
        browser.close()
finally:
    set_rule(previous)
    print(f"  --    {KEY} put back to {previous!r}")

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
