"""Rounding a price off at the counter, on the screen it is done on.

Two places, one rule. The amount on the table and the price in the line editor
are the same decision, so both cost a code and both are recorded — a screen where
the same act has two different rules is a screen people work out how to route
around.

  - the Amount column says it can be edited, before anybody touches it
  - double-clicking one opens it with the current amount, selected
  - typing a rounder figure asks for a code rather than just doing it
  - cancelling the code leaves the old amount, not the new one
  - authorised, the row shows the new amount, marked as set by hand
  - the footer under the table adds up the figures the rows are showing
  - the line editor shows the same price and offers the way back to the shelf's
  - and the way back is free: nobody needs approval to charge what the shelf says

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
    page.wait_for_timeout(600)
    box = page.locator(".rx-item-money .cell-input")
    check("double-clicking opens it, holding the amount that is there",
          box.count() == 1 and (box.first.input_value() or "").startswith("8.97"),
          box.first.input_value() if box.count() else "no field")

    # Rounded off, the way a counter rounds.
    box.first.fill("9.00")
    box.first.press("Enter")
    page.wait_for_timeout(1500)

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
    page.wait_for_timeout(500)
    page.locator(".rx-item-money .cell-input").first.fill("9.00")
    page.locator(".rx-item-money .cell-input").first.press("Enter")
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
    field = page.locator("#ed-price")
    check("the line editor shows the same price", field.count() == 1
          and (field.first.input_value() or "").startswith("9.00"),
          field.first.input_value() if field.count() else "no price field")
    back = page.locator(".ed-price-row .linkish")
    check("…and offers the way back to the shelf price, naming it",
          back.count() == 1 and "8.97" in back.first.inner_text(),
          back.first.inner_text() if back.count() else "no way back")
    if SHOT and field.count():
        page.screenshot(path=str(SHOT / "price-in-the-line-editor.png"))

    back.first.click()
    page.wait_for_timeout(1200)
    check("the way back is free — nobody needs approval to charge what the shelf says",
          page.locator(".modal h2").count() == 0
          or "code" not in page.locator(".modal h2").first.inner_text().lower(),
          page.locator(".modal h2").first.inner_text() if page.locator(".modal h2").count() else "")
    check("…and the price goes back to the catalogue's",
          (page.locator("#ed-price").first.input_value() or "").startswith("8.97"),
          page.locator("#ed-price").first.input_value())

    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
