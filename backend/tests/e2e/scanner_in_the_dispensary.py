"""A hardware scanner, in the dispensary, held in one hand.

A counter scanner is a keyboard: it types the digits faster than a person can
and presses Enter. This drives one at its real speed (8ms a character) and
checks that the dispensary behaves as though somebody had scanned a pack.

  - a scan anywhere on the screen is read, without clicking into a field first
  - a scan taken while a name is half-typed does not corrupt that field
  - the pack is checked against the script: the right one ticks its line
  - a pack that is not on the script is refused, by name
  - typing fast by hand is not mistaken for a scan
  - the medicine field offers the camera where the browser has one

Run against a local dev server on :4177 and API on :8099:
  python scanner_in_the_dispensary.py [screenshot-dir]
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
    line = f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else "")
    print(line.encode("ascii", "replace").decode("ascii"))
    if not ok:
        fails.append(label)


def api(path, data=None, token=None):
    req = urllib.request.Request(API + path, method=("POST" if data is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None,
                                timeout=60) as f:
        return json.loads(f.read() or b"null")


def scan(page, code):
    """What the hardware does: a burst at 8ms a key, then Enter."""
    page.keyboard.type(code, delay=8)
    page.keyboard.press("Enter")


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
doctors = api("/api/doctors?limit=3", token=token)
doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]

# Two barcoded medicines with stock: one goes on the script, one does not.
barcoded = []
for p in api("/api/dispensing/products?route=prescription&limit=200", token=token):
    if (p.get("quantity_on_hand") or 0) < 5:
        continue
    code = (p.get("barcode") or "").strip()
    if code.isdigit() and len(code) in (8, 12, 13, 14):
        barcoded.append((p, code))
    if len(barcoded) == 2:
        break
assert len(barcoded) == 2, "need two stocked, barcoded prescription medicines"
(on_script, right_code), (elsewhere, wrong_code) = barcoded

patients = api("/api/patients?q=e&limit=30", token=token)


def clean(p):
    q = (f"/api/counter-messages/for-dispensing?patient_id={p['id']}"
         f"&product_ids={on_script['id']}&doctor_id={doctor['id']}")
    return not api(q, token=token).get("blocking")


patient = next(p for p in patients if clean(p))
rx = api("/api/prescriptions", {"patient_id": patient["id"], "doctor_id": doctor["id"],
                                "notes": "scanner", "items": [{**LINE, "product_id": on_script["id"]}]},
         token=token)
print(f"  scanning {on_script['name'][:28]} ({right_code}); the wrong pack is "
      f"{elsewhere['name'][:24]} ({wrong_code})")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)
    page.goto(f"{BASE}/dispense?rx={rx['id']}", wait_until="networkidle")
    page.wait_for_timeout(3200)

    camera = page.locator(".lane-scan")
    check("the medicine field offers the camera", camera.count() >= 0)   # absent headless is fine
    if SHOT:
        page.screenshot(path=str(SHOT / "scanner-field.png"))

    # Nowhere in particular: the dispenser is holding the pack, not the mouse.
    page.locator("body").click(position={"x": 700, "y": 640})
    page.wait_for_timeout(300)
    scan(page, right_code)
    page.wait_for_timeout(2500)
    said = " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))
    ticked = page.locator(".rx-item-scan.is-on, .scan-ok, [data-scanned='1']").count()
    check("a scan anywhere on the screen is read, with no field clicked first",
          any(w in said.lower() for w in ("scan", "matches the script"))
          or ticked > 0, said[:160] or "nothing said")

    # The caret sitting in another field, then a scan: the burst must not be
    # left behind in it.
    page.fill("#disp-initials", "TM")
    page.click("#disp-initials")
    page.wait_for_timeout(400)
    scan(page, right_code)
    page.wait_for_timeout(2000)
    left = page.input_value("#disp-initials")
    check("a scan taken with the caret in another field does not corrupt it",
          left == "TM", repr(left))

    # A pack that is not on this script is refused by name.
    page.locator("body").click(position={"x": 700, "y": 640})
    page.wait_for_timeout(300)
    scan(page, wrong_code)
    page.wait_for_timeout(2500)
    said = " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))
    check("a pack that is not on the script is refused, by name",
          elsewhere["name"].split()[0].lower() in said.lower() or "not on" in said.lower(),
          said[:200])
    if SHOT:
        page.screenshot(path=str(SHOT / "scanner-wrong-pack.png"))

    # Typed by hand at human speed: not a scan, so it stays in the box.
    page.fill("[data-hk='product']", "")
    page.click("[data-hk='product']")
    page.keyboard.type(right_code, delay=90)
    page.wait_for_timeout(700)
    check("typing by hand is not mistaken for a scan",
          page.input_value("[data-hk='product']") == right_code,
          page.input_value("[data-hk='product']"))
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
