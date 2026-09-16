"""Asked for a code they have not got, and making one without losing their place.

The prompt is where people find out they have no code, and it is also where the
work they would lose by going to look for one is sitting. So the code is made
from the prompt, and what they were doing is still there afterwards — the same
script, the same line, the same amount typed into it.

  - the prompt offers to make one before anybody has failed at anything
  - refused for want of a code, the offer stops being a footnote
  - the panel sets it for a named person, on that person's own password
  - two codes that do not match are said so before the server is troubled
  - set, it comes straight back to the prompt, saying whose code it is
  - the code works on the very action that asked for it
  - and the script underneath is untouched: same line, and now the new price

Run against a local dev server on :4177 and API on :8099:
  python a_code_made_on_the_spot.py [screenshot-dir]
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
WHO = f"jit_pharm_{tag}"
PASS = "Their-own-pass-1"
NEW_CODE = "8261"


def check(label, ok, detail=""):
    line = f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else "")
    print(line.encode("ascii", "replace").decode("ascii"))
    if not ok:
        fails.append(label)


def api(path, data=None, token=None, method=None):
    req = urllib.request.Request(API + path,
                                 method=method or ("POST" if data is not None else "GET"))
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
# A pharmacist who has never set a code. This is the ordinary state of a new
# member of staff, not an edge case.
api("/api/auth/users", {"username": WHO, "password": PASS, "full_name": "Nyasha, new here",
                   "role": "pharmacist", "active": True}, token)
print(f"  {WHO} exists, and has never set a code")

awkward = api("/api/products", {"name": f"Odd Price Syrup {tag}", "unit_price": 8.97,
                                "cost_price": 4.0, "units_per_pack": 1, "vat_rate": 0.0,
                                "category": "medicine"}, token)
api("/api/stock/adjust", {"product_id": awkward["id"], "quantity_delta": 60,
                          "movement_type": "receive", "batch_number": f"OP{tag}",
                          "expiry_date": "2028-05-31"}, token)


def amount_cell(page):
    return page.locator(".disp-grid .rx-item:not(.rx-item-waiting) .rx-item-money").first


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", WHO)
    page.fill("#lg-pass", PASS)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(3000)
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(2500)
    if page.query_selector(".disp-patient-picked"):
        page.locator(".page-actions").get_by_role("button", name="New script").click()
        page.wait_for_timeout(900)
    page.fill("[data-hk='patient']", "Andela")
    page.wait_for_timeout(1700)
    page.query_selector_all("#step-patient .product-pick")[0].click()
    page.wait_for_timeout(1200)
    page.fill("[data-hk='product']", f"Odd Price Syrup {tag}")
    page.wait_for_timeout(1700)
    page.locator("#step-items .product-pick").first.click()
    page.wait_for_timeout(1400)
    if page.locator(".disp-edit").count():
        page.locator(".disp-edit").get_by_role("button", name="Done").click()
        page.wait_for_timeout(600)

    amount_cell(page).dblclick()
    page.wait_for_timeout(500)
    page.locator(".rx-item-money .cell-input").first.fill("9.00")
    page.locator(".rx-item-money .cell-input").first.press("Enter")
    page.wait_for_timeout(1600)

    offer = page.locator(".su-make-offer")
    check("the prompt offers to make a code before anybody has failed at anything",
          offer.count() == 1, str(offer.count()))

    # Try the code they have not got. The server says so in its own words.
    for digit in "1357":
        page.keyboard.type(digit)
        page.wait_for_timeout(120)
    page.wait_for_timeout(2000)
    said = page.locator(".su-error").inner_text() if page.locator(".su-error").count() else ""
    check("refused, it says there is no code yet", "no pin is set" in said.lower(), said[:100])
    offer = page.locator(".su-make-offer")
    check("…and the offer stops being a footnote",
          "is-needed" in (offer.first.get_attribute("class") or "")
          and "Set a code now" in offer.first.inner_text(),
          (offer.first.get_attribute("class") or "") if offer.count() else "no offer")
    if SHOT:
        page.screenshot(path=str(SHOT / "code-offered-when-missing.png"))

    offer.first.click()
    page.wait_for_timeout(900)
    panel = page.locator(".su-make")
    check("the panel opens in place, over the script it came from", panel.count() == 1)
    who = page.locator("#su-make-who")
    check("…already filled in with whose code it is", (who.input_value() or "") == WHO,
          who.input_value())
    check("…and says they will come back to what they were doing",
          "come straight back" in panel.first.inner_text(),
          panel.first.inner_text()[:160])

    page.fill("#su-make-pass", PASS)
    boxes = page.locator(".su-make .pin-box")
    for i, digit in enumerate(NEW_CODE):
        boxes.nth(i).fill(digit)
        page.wait_for_timeout(90)
    # Mismatched on purpose the first time.
    for i, digit in enumerate("9999"):
        boxes.nth(4 + i).fill(digit)
        page.wait_for_timeout(90)
    if SHOT:
        page.screenshot(path=str(SHOT / "code-being-made.png"))
    page.locator(".su-make").get_by_role("button", name="Set the code").click()
    page.wait_for_timeout(1200)
    said = page.locator(".su-error").inner_text() if page.locator(".su-error").count() else ""
    check("two codes that do not match are said so, without troubling the server",
          "not the same" in said.lower(), said[:100])

    boxes = page.locator(".su-make .pin-box")
    for i, digit in enumerate(NEW_CODE):
        boxes.nth(4 + i).fill(digit)
        page.wait_for_timeout(90)
    page.locator(".su-make").get_by_role("button", name="Set the code").click()
    page.wait_for_timeout(2500)

    check("set, it is back on the prompt it came from",
          page.locator(".su-make").count() == 0
          and page.locator(".su-pin").count() >= 1,
          "still on the making panel" if page.locator(".su-make").count() else "no prompt")
    made = page.locator(".su-made")
    check("…saying whose code it now is",
          made.count() == 1 and "Nyasha" in made.first.inner_text(),
          made.first.inner_text() if made.count() else "nothing said")
    if SHOT:
        page.screenshot(path=str(SHOT / "code-made-back-on-the-prompt.png"))

    # And it works on the very thing that asked for it.
    for digit in NEW_CODE:
        page.keyboard.type(digit)
        page.wait_for_timeout(120)
    page.wait_for_timeout(2800)

    check("the new code authorises the action that asked for it",
          page.locator(".su-pin").count() == 0,
          "the prompt is still up")
    cell = amount_cell(page)
    check("…and the script underneath is untouched, now at the price that was typed",
          "9.00" in cell.inner_text() and "is-hand-set" in (cell.get_attribute("class") or ""),
          cell.inner_text().strip())
    rows = page.locator(".disp-grid .rx-item:not(.rx-item-waiting)")
    check("…still one line, on the same medicine", rows.count() == 1
          and f"Odd Price Syrup {tag}" in rows.first.inner_text(),
          rows.first.inner_text()[:80] if rows.count() else "no lines")
    if SHOT:
        page.screenshot(path=str(SHOT / "code-made-and-used.png"))

    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
