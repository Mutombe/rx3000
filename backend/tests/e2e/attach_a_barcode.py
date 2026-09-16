"""A pack the catalogue does not know, taught to it at the counter.

Two thirds of this catalogue arrived with no barcode, so scanning a real pack
and being told "nothing is stocked under that code" is the ordinary case. The
dispenser is holding the pack and knows what it is.

  - an unrecognised scan asks which medicine it is, rather than stopping
  - it names the code, and searches the medicines this tab may dispense
  - kept, the code answers to that medicine from then on — for the till too
  - and the medicine goes onto the script, which is what the scan was for
  - a code that already belongs to another medicine is refused, saying which

Run against a local dev server on :4177 and API on :8099:
  python attach_a_barcode.py [screenshot-dir]
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
tag = random.randint(100000, 999999)
CODE = f"60012{tag}"


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
    try:
        with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None,
                                    timeout=60) as f:
            return json.loads(f.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"status": e.code, **json.loads(e.read() or b"{}")}


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
# A stocked medicine with no barcode of its own: the shape of two thirds of the
# CareXpress catalogue.
nameless = api("/api/products", {"name": f"Unbarcoded Syrup {tag}", "unit_price": 7.5,
                                 "cost_price": 3.0, "units_per_pack": 1, "vat_rate": 0.0,
                                 "category": "medicine", "barcode": ""}, token)
api("/api/stock/adjust", {"product_id": nameless["id"], "quantity_delta": 40,
                          "movement_type": "receive", "batch_number": f"UB{tag}",
                          "expiry_date": "2028-05-31"}, token)
print(f"  {nameless['name']} has no barcode; scanning {CODE}")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
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

    # Scanned like the hardware does it.
    page.locator("body").click(position={"x": 700, "y": 640})
    page.keyboard.type(CODE, delay=8)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2000)

    modal = page.locator(".attach-modal")
    check("an unrecognised pack asks which medicine it is", modal.count() == 1)
    check("…naming the code that was scanned", CODE in modal.first.inner_text(),
          modal.first.inner_text()[:120] if modal.count() else "no dialog")
    page.fill("#attach-find", f"Unbarcoded Syrup {tag}")
    page.wait_for_timeout(1600)
    hit = page.locator(".attach-hits .product-pick").first
    check("…and searches what this tab may dispense", hit.count() > 0)
    if SHOT and hit.count():
        page.screenshot(path=str(SHOT / "attach-barcode.png"))
    hit.click()
    page.wait_for_timeout(500)
    page.locator(".attach-modal").get_by_role("button", name="Keep this code").click()
    page.wait_for_timeout(3000)

    said = " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))
    check("kept, it says so", "code" in said.lower() or "answers" in said.lower(), said[:140])
    on_script = page.locator(".rx-item-sig").count()
    check("…and the medicine goes onto the script, which is what the scan was for",
          on_script >= 1, str(on_script))

    # The catalogue has learned it: the same scan is answered everywhere now.
    resolved = api("/api/scan", {"code": CODE, "context": "pos"}, token)
    check("the catalogue has learned the code",
          resolved.get("found") and resolved["product"]["id"] == nameless["id"],
          str(resolved)[:140])

    # A code that already belongs to something else is refused, by name.
    other = api("/api/products", {"name": f"Another Syrup {tag}", "unit_price": 3.0,
                                  "cost_price": 1.0, "units_per_pack": 1}, token)
    clash = api("/api/scan/link", {"code": CODE, "product_id": other["id"]}, token)
    check("a code that belongs to another medicine is refused, saying which",
          clash.get("status") == 409 and nameless["name"] in str(clash.get("detail")),
          str(clash)[:160])
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
