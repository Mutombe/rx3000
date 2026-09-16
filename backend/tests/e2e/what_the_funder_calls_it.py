"""The scheme's NAPPI code, only where and when it matters.

A claim is adjudicated on the code, not the name. A line the funder cannot
identify is not paid, and the pharmacy finds out weeks later in a remittance,
when the medicine is gone and so is the patient.

The rule that keeps the screen usable is that the code is invisible until it is
somebody's problem. On a cash script — most of them — it appears nowhere at all.

  - a cash script shows no code anywhere: not on the row, not in the line editor
  - on a scheme, a line the funder cannot identify is marked on the row
  - …and a line that already has a code is NOT marked
  - the line editor carries the code, where the dispenser is holding the box
  - the billing step lists what the funder will be sent, and counts what it
    cannot identify
  - typing a code there fixes it, and the mark on the row goes
  - …and it is kept against the medicine, so the next script is already right
  - a code that is not digits is refused

Run against a local dev server on :4177 and API on :8099:
  python what_the_funder_calls_it.py [screenshot-dir]
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
schemes = api("/api/medical-aids", token=token)
scheme = schemes[0]
print(f"  claiming against {scheme['name']}")

# Two medicines: one the scheme knows, one it has never heard of.
known = api("/api/products", {"name": f"Known To Scheme {tag}", "unit_price": 10.0,
                              "cost_price": 5.0, "units_per_pack": 1, "vat_rate": 0.0,
                              "category": "medicine"}, token)
stranger = api("/api/products", {"name": f"Stranger To Scheme {tag}", "unit_price": 12.0,
                                 "cost_price": 6.0, "units_per_pack": 1, "vat_rate": 0.0,
                                 "category": "medicine"}, token)
for product in (known, stranger):
    api("/api/stock/adjust", {"product_id": product["id"], "quantity_delta": 40,
                              "movement_type": "receive", "batch_number": f"SC{tag}",
                              "expiry_date": "2028-05-31"}, token)
api(f"/api/scheme-codes/{scheme['id']}/{known['id']}", {"code": "37058"}, token, method="PUT")

bad = api(f"/api/scheme-codes/{scheme['id']}/{stranger['id']}", {"code": "ABC123"},
          token, method="PUT")
check("a code that is not digits is refused",
      bad.get("status") == 400 and "digits" in str(bad.get("detail")), str(bad)[:120])


def add_medicine(page, name):
    page.fill("[data-hk='product']", name)
    page.wait_for_timeout(1700)
    page.locator("#step-items .product-pick").first.click()
    page.wait_for_timeout(1300)
    if page.locator(".disp-edit").count():
        page.locator(".disp-edit").get_by_role("button", name="Done").click()
        page.wait_for_timeout(600)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(2600)
    if page.query_selector(".disp-patient-picked"):
        page.locator(".page-actions").get_by_role("button", name="New script").click()
        page.wait_for_timeout(900)

    # A cash patient: the code must be nowhere on this screen.
    cash = api("/api/patients", {"first_name": "Tarisai", "last_name": f"Cash{tag}",
                                 "date_of_birth": "1990-02-02", "gender": "F",
                                 "phone": f"077{tag}", "confirmed_distinct": True}, token)
    page.fill("[data-hk='patient']", f"Cash{tag}")
    page.wait_for_timeout(1700)
    page.query_selector_all("#step-patient .product-pick")[0].click()
    page.wait_for_timeout(1300)
    add_medicine(page, f"Stranger To Scheme {tag}")

    check("a cash script shows no code mark on the row", page.locator(".rx-nocode").count() == 0,
          str(page.locator(".rx-nocode").count()))
    page.locator(".rx-item-actions .rx-icon").nth(1).click()
    page.wait_for_timeout(1100)
    check("…and none in the line editor either", page.locator(".sc-line").count() == 0,
          str(page.locator(".sc-line").count()))
    if SHOT:
        page.screenshot(path=str(SHOT / "nappi-absent-on-cash.png"))
    page.locator(".disp-edit").get_by_role("button", name="Done").click()
    page.wait_for_timeout(700)

    # Now a scheme member.
    member = api("/api/patients", {"first_name": "Rutendo", "last_name": f"Member{tag}",
                                   "date_of_birth": "1985-06-06", "gender": "F",
                                   "phone": f"078{tag}", "medical_aid_id": scheme["id"],
                                   "medical_aid_number": f"M{tag}",
                                   "confirmed_distinct": True}, token)
    page.locator(".page-actions").get_by_role("button", name="New script").click()
    page.wait_for_timeout(1000)
    page.fill("[data-hk='patient']", f"Member{tag}")
    page.wait_for_timeout(1700)
    page.query_selector_all("#step-patient .product-pick")[0].click()
    page.wait_for_timeout(1400)
    add_medicine(page, f"Known To Scheme {tag}")
    add_medicine(page, f"Stranger To Scheme {tag}")
    page.wait_for_timeout(1800)

    rows = page.locator(".disp-grid .rx-item:not(.rx-item-waiting)")
    marked = page.locator(".rx-nocode")
    check("on a scheme, the line the funder cannot identify is marked",
          marked.count() == 1, f"{marked.count()} marks on {rows.count()} rows")
    stranger_row = rows.filter(has_text=f"Stranger To Scheme {tag}")
    known_row = rows.filter(has_text=f"Known To Scheme {tag}")
    check("…it is the right line", stranger_row.locator(".rx-nocode").count() == 1)
    check("…and the line that has a code is not marked",
          known_row.locator(".rx-nocode").count() == 0)
    if SHOT:
        page.screenshot(path=str(SHOT / "nappi-marked-on-the-row.png"))

    # The line editor carries it, where the box is in hand.
    known_row.locator(".rx-item-actions .rx-icon").nth(1).click()
    page.wait_for_timeout(1200)
    field = page.locator(".sc-line .sc-input")
    check("the line editor carries the code", field.count() == 1
          and field.first.input_value() == "37058",
          field.first.input_value() if field.count() else "no field")
    if SHOT and field.count():
        page.screenshot(path=str(SHOT / "nappi-in-the-line-editor.png"))
    page.locator(".disp-edit").get_by_role("button", name="Done").click()
    page.wait_for_timeout(800)

    # The billing step: what the funder will be sent.
    page.get_by_role("button", name="Finish").first.click()
    page.wait_for_timeout(1800)
    if page.locator(".seg").filter(has_text="Medical aid").count():
        page.locator(".seg").filter(has_text="Medical aid").first \
            .get_by_role("radio", name="Medical aid").click()
        page.wait_for_timeout(1200)
    panel = page.locator(".fin-codes")
    check("the billing step lists what the funder will be billed", panel.count() == 1,
          "no list")
    if panel.count():
        said = panel.first.inner_text().lower()
        check("…and counts the lines it cannot identify",
              "1 line it cannot identify" in said, said[:200])
        check("…with a way to add the missing one",
              panel.locator(".sc-missing").count() == 1,
              str(panel.locator(".sc-missing").count()))
        if SHOT:
            page.screenshot(path=str(SHOT / "nappi-at-billing.png"))

        panel.locator(".sc-missing").first.click()
        page.wait_for_timeout(500)
        box = panel.locator(".sc-input").last
        box.fill("20797")
        box.press("Enter")
        page.wait_for_timeout(2200)
        check("typing the code there clears the warning",
              "cannot identify" not in panel.first.inner_text().lower(),
              panel.first.inner_text()[:200])

        fits = page.evaluate("""() => {
          const p = document.querySelector('.fin-codes');
          const h = p.querySelector('h4');
          const rows = [...p.querySelectorAll('.fin-code-list li')];
          const wide = rows.some((r) => r.scrollWidth > r.clientWidth + 1);
          return {heading: h.getBoundingClientRect().width,
                  panel: p.getBoundingClientRect().width, wide};
        }""")
        check("…and the list fits the column it is in",
              not fits["wide"] and fits["heading"] > fits["panel"] * 0.6,
              f"heading {fits['heading']:.0f} of panel {fits['panel']:.0f}, "
              f"rows overflow: {fits['wide']}")

    page.keyboard.press("Escape")
    page.wait_for_timeout(1200)
    check("…and the mark on the row is gone", page.locator(".rx-nocode").count() == 0,
          str(page.locator(".rx-nocode").count()))

    browser.close()

# Kept against the medicine, for every script after this one.
after = api("/api/scheme-codes", {"medical_aid_id": scheme["id"],
                                  "product_ids": [stranger["id"]]}, token)
row = (after.get("codes") or [{}])[0]
check("…and kept against the medicine, so the next script is already right",
      row.get("code") == "20797" and row.get("origin") == "scheme", str(row)[:140])

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
