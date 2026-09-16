"""Rounding a price off at the counter, on the screen it is done on.

Two places, one rule. The amount on the table and the price in the line editor
are the same decision, so both cost a code and both are recorded — a screen where
the same act has two different rules is a screen people work out how to route
around.

  - the Amount column says it can be edited, before anybody touches it
  - double-clicking one opens the dialog that holds the whole decision
  - price and margin are one number read two ways, and each moves the other
  - it asks for a code rather than just doing it
  - cancelling the code leaves the old amount, not the new one
  - authorised, the row shows the new amount, marked as set by hand
  - the footer under the table adds up the figures the rows are showing
  - the line editor opens the same dialog, and offers the way back to the shelf
  - and the way back is free: nobody needs approval to charge what the shelf says
  - "keep this price for good" changes the catalogue, so the next script is
    priced at it and the line is no longer marked as a one-off

Run against a local dev server on :4177 and API on :8099:
  python a_price_set_by_hand.py [screenshot-dir]
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
PIN = "8261"


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
# A code for the admin, so the prompt can be answered. The JIT path — making one
# from inside the prompt — is its own test.
api("/api/auth/pin", {"pin": PIN, "password": "admin123"}, token)

# Something with an awkward price, which is the whole reason this exists.
awkward = api("/api/products", {"name": f"Awkward Syrup {tag}", "unit_price": 8.97,
                                "cost_price": 4.0, "units_per_pack": 1, "vat_rate": 0.0,
                                "category": "medicine"}, token)
api("/api/stock/adjust", {"product_id": awkward["id"], "quantity_delta": 60,
                          "movement_type": "receive", "batch_number": f"AW{tag}",
                          "expiry_date": "2028-05-31"}, token)
print(f"  {awkward['name']} is priced at 8.97 each")


def amount_cell(page):
    return page.locator(".disp-grid .rx-item:not(.rx-item-waiting) .rx-item-money").first


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

    head = page.locator(".rx-item-head.rx-item-cols .rx-item-money")
    check("the Amount column says it can be edited, before anybody touches it",
          head.count() == 1 and head.first.locator("svg").count() >= 1,
          head.first.inner_text() if head.count() else "no header")

    page.fill("[data-hk='product']", f"Awkward Syrup {tag}")
    page.wait_for_timeout(1700)
    page.locator("#step-items .product-pick").first.click()
    page.wait_for_timeout(1400)
    # The line editor opens on selection; close it and work on the table.
    if page.locator(".disp-edit").count():
        page.locator(".disp-edit").get_by_role("button", name="Done").click()
        page.wait_for_timeout(600)

    cell = amount_cell(page)
    before = cell.inner_text().strip()
    check("the amount starts on the catalogue's figure", "8.97" in before, before)

    cell.dblclick()
    page.wait_for_timeout(900)
    box = page.locator("#price-each")
    check("double-clicking opens the price dialog, on the price it is at",
          box.count() == 1 and (box.first.input_value() or "").startswith("8.97"),
          box.first.input_value() if box.count() else "no dialog")

    # Price and margin are one number read two ways. Cost is 4.00 against a
    # price of 8.97, so the margin starts near 55%.
    started = page.locator("#price-margin").input_value()
    check("...and shows the margin that price makes",
          abs(float(started or 0) - 55.4) < 0.4, started)
    page.fill("#price-margin", "60")
    page.wait_for_timeout(500)
    worked = page.locator("#price-each").input_value()
    check("typing a margin works out the price",
          abs(float(worked or 0) - 10.00) < 0.02, worked)
    if SHOT:
        page.screenshot(path=str(SHOT / "price-dialog.png"))

    # Rounded off, the way a counter rounds.
    page.fill("#price-each", "9.00")
    page.wait_for_timeout(400)
    page.locator(".price-modal").get_by_role("button", name="Set it for this script").click()
    page.wait_for_timeout(1600)

    prompt = page.locator(".modal h2")
    said = prompt.first.inner_text() if prompt.count() else ""
    check("it asks for a code rather than just doing it", "price" in said.lower(), said[:90])
    if SHOT and prompt.count():
        page.screenshot(path=str(SHOT / "price-asks-for-a-code.png"))

    # Cancelled: nothing moved.
    page.locator(".modal").get_by_role("button", name="Cancel").click()
    page.wait_for_timeout(1200)
    check("cancelling leaves the old amount, not the new one",
          "8.97" in amount_cell(page).inner_text(), amount_cell(page).inner_text())

    # Again, and authorised this time.
    amount_cell(page).dblclick()
    page.wait_for_timeout(800)
    page.fill("#price-each", "9.00")
    page.wait_for_timeout(300)
    page.locator(".price-modal").get_by_role("button", name="Set it for this script").click()
    page.wait_for_timeout(1500)
    for digit in PIN:
        page.keyboard.type(digit)
        page.wait_for_timeout(120)
    page.wait_for_timeout(2600)

    cell = amount_cell(page)
    now = cell.inner_text().strip()
    check("authorised, the row shows the amount that was typed", "9.00" in now, now)
    check("…and marks it as set by hand, so the next person can see it is a decision",
          "is-hand-set" in (cell.get_attribute("class") or ""),
          cell.get_attribute("class") or "")
    said = " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))
    check("…and says so", "each" in said.lower() or "9.00" in said, said[:140])
    if SHOT:
        page.screenshot(path=str(SHOT / "price-set-by-hand.png"))

    foot = page.locator(".st-foot")
    check("the footer adds up what the rows are showing",
          foot.count() > 0 and "9.00" in foot.first.inner_text(),
          foot.first.inner_text()[:120] if foot.count() else "no footer")

    # The line editor: the same price, and the way back.
    page.locator(".rx-item-actions .rx-icon").nth(1).click()
    page.wait_for_timeout(1200)
    shown = page.locator(".ed-price-row .btn")
    check("the line editor shows the same price", shown.count() >= 1
          and "9.00" in shown.first.inner_text(),
          shown.first.inner_text() if shown.count() else "no price control")
    back = page.locator(".ed-price-row .linkish")
    check("…and offers the way back to the shelf price, naming it",
          back.count() == 1 and "8.97" in back.first.inner_text(),
          back.first.inner_text() if back.count() else "no way back")
    if SHOT and shown.count():
        page.screenshot(path=str(SHOT / "price-in-the-line-editor.png"))

    back.first.click()
    page.wait_for_timeout(1200)
    check("the way back is free - nobody needs approval to charge what the shelf says",
          page.locator(".price-modal").count() == 0
          and page.locator(".su-pin").count() == 0)
    check("...and the price goes back to the catalogue's",
          "8.97" in page.locator(".ed-price-row .btn").first.inner_text(),
          page.locator(".ed-price-row .btn").first.inner_text())
    page.locator(".disp-edit").get_by_role("button", name="Done").click()
    page.wait_for_timeout(800)

    # Kept for good: the catalogue itself changes.
    amount_cell(page).dblclick()
    page.wait_for_timeout(800)
    page.fill("#price-each", "9.50")
    page.wait_for_timeout(300)
    page.locator("#price-keep").click()
    page.wait_for_timeout(400)
    page.locator(".price-modal").get_by_role("button", name="Set it, and keep it").click()
    page.wait_for_timeout(1500)
    for digit in PIN:
        page.keyboard.type(digit)
        page.wait_for_timeout(120)
    page.wait_for_timeout(2800)

    cell = amount_cell(page)
    check("kept for good, the row shows the new amount", "9.50" in cell.inner_text(),
          cell.inner_text().strip())
    check("...and is NOT marked as a one-off, because the shelf now says this",
          "is-hand-set" not in (cell.get_attribute("class") or ""),
          cell.get_attribute("class") or "")
    if SHOT:
        page.screenshot(path=str(SHOT / "price-kept-for-good.png"))

    browser.close()

# The catalogue itself carries it now, so the next script is priced at it.
found = api(f"/api/products?q=Awkward+Syrup+{tag}", token=token)
again = next((p for p in (found or []) if p.get("id") == awkward["id"]), {})
check("...and the catalogue itself now says 9.50",
      abs((again.get("unit_price") or 0) - 9.50) < 0.005, str(again.get("unit_price")))

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
