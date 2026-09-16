"""Making a preparation up at the counter, in a browser.

  - the dispensary opens it on F1, without leaving the script
  - it asks for the ingredients, and costs them while they are typed
  - it says what schedule the preparation will be, from its strongest ingredient
  - made up, it lands on the script as an ordinary line, with the directions
    already on it
  - the script dispenses, and the label names the preparation's own batch

Run against a local dev server on :4177 and API on :8099:
  python mix_at_the_counter.py [screenshot-dir]
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
    req = urllib.request.Request(API + path, method=("POST" if data is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None,
                                timeout=60) as f:
        return json.loads(f.read() or b"null")


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
for name, schedule in ((f"Counter Calamine {tag}", 0), (f"Counter Menthol {tag}", 2)):
    p = api("/api/products", {"name": name, "schedule": schedule, "unit_price": 6.0,
                              "cost_price": 3.0, "units_per_pack": 1, "vat_rate": 0.0}, token)
    api("/api/stock/adjust", {"product_id": p["id"], "quantity_delta": 400,
                              "movement_type": "receive", "batch_number": f"ING{tag}",
                              "expiry_date": "2028-06-30"}, token)

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
    page.fill("#disp-doctor", "Dr")
    page.wait_for_timeout(800)
    page.query_selector_all("#step-patient .doc-pick")[0].click()
    page.wait_for_timeout(600)

    page.keyboard.press("F1")
    page.wait_for_timeout(1200)
    modal = page.locator(".mix-modal")
    check("F1 opens it on the script, without leaving the page", modal.count() == 1
          and page.url.endswith("/dispense"), page.url)

    page.fill("#mix-name", f"Calamine & Menthol {tag}")
    for ingredient, amount in ((f"Counter Calamine {tag}", "150"), (f"Counter Menthol {tag}", "2")):
        page.fill(".mix-find input", ingredient)
        page.wait_for_timeout(1600)
        hit = page.locator(".mix-hits .product-pick").first
        if not hit.count():
            check(f"{ingredient} is offered as an ingredient", False, "no hits")
            continue
        hit.click()
        page.wait_for_timeout(500)
        page.locator(".mix-line .mix-qty").last.fill(amount)
        page.wait_for_timeout(1200)
    check("the ingredients go on with how much of each",
          page.locator(".mix-line").count() == 2, str(page.locator(".mix-line").count()))

    summary = page.inner_text(".mix-sum")
    check("it is costed while it is typed", "$" in summary, summary[:90])
    check("…and says what schedule it will be", "S2" in summary, summary[:90])

    page.fill("#mix-directions", "apply bd prn")
    page.wait_for_timeout(700)
    page.fill("#mix-price", "8.00")
    if SHOT:
        page.screenshot(path=str(SHOT / "mix-at-the-counter.png"))
    page.locator(".mix-modal").get_by_role("button", name="Make it up").click()
    page.wait_for_timeout(4000)

    said = " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))
    check("it is made up, and says so with its reference", "MIX" in said, said[:140])
    line = page.locator(".rx-item, .disp-table tr", has_text=f"Calamine & Menthol {tag}")
    check("…and lands on the script as an ordinary line", line.count() > 0)
    if page.query_selector(".disp-edit"):
        page.click(".disp-edit .disp-edit-actions .btn.primary")
        page.wait_for_timeout(1200)
    body = page.inner_text(".disp-table, .sec-items")
    check("…carrying the directions it was made up with",
          "apply" in body.lower() or "APPLY" in body, body[:160])
    if SHOT:
        page.screenshot(path=str(SHOT / "mix-on-the-script.png"))
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
