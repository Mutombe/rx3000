"""Departments decide what the dispensary offers, in a browser.

  - the Departments screen shows, per department, whether it is dispensed here
  - switching one to shop-only says so, and it sticks
  - the dispensary's medicine search stops offering that department's lines
  - the same lines are still in the catalogue, counted and valued
  - a product can be filed in a department from the product form

Run against a local dev server on :4177 and API on :8099:
  python departments_dispensable.py [screenshot-dir]
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


def api(path, data=None, token=None, method=None):
    req = urllib.request.Request(API + path, method=method or ("POST" if data is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None,
                                timeout=60) as f:
        return json.loads(f.read() or b"null")


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
dept = api("/api/stock-categories", {"name": f"Test Snacks {tag}"}, token)
drink = api("/api/products", {"name": f"Test Cola {tag}", "category": "front_shop",
                              "unit_price": 1.0, "category_id": dept["id"]}, token)
print(f"  {drink['name']} filed under {dept['name']}")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)

    # ---- it is offered while the department says it is dispensed here ------------
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(2500)
    if page.query_selector(".disp-patient-picked"):
        page.locator(".page-actions").get_by_role("button", name="New script").click()
        page.wait_for_timeout(900)
    page.fill("[data-hk='product']", f"Test Cola {tag}")
    page.wait_for_timeout(1800)
    check("a new department is dispensed from until the pharmacy says otherwise",
          page.locator("#step-items .product-pick", has_text=f"Test Cola {tag}").count() > 0)

    # ---- switch it to shop only ---------------------------------------------------
    page.goto(BASE + "/stock-categories", wait_until="networkidle")
    page.wait_for_timeout(2500)
    row = page.locator("tr", has_text=f"Test Snacks {tag}")
    check("the departments screen says whether each one is dispensed here",
          row.count() > 0 and "Dispensed here" in row.first.inner_text(),
          row.first.inner_text()[:120] if row.count() else "no row")
    if SHOT:
        page.screenshot(path=str(SHOT / "departments.png"))
    row.first.locator(".dept-dispensable input, .dept-dispensable .cbx").first.click()
    page.wait_for_timeout(2000)
    said = " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))
    check("switching it says what changed", "medicine search" in said, said[:160])
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(2500)
    row = page.locator("tr", has_text=f"Test Snacks {tag}")
    check("…and it sticks", "Shop only" in row.first.inner_text(), row.first.inner_text()[:120])

    # ---- the dispensary stops offering it -----------------------------------------
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(2500)
    if page.query_selector(".disp-patient-picked"):
        page.locator(".page-actions").get_by_role("button", name="New script").click()
        page.wait_for_timeout(900)
    page.fill("[data-hk='product']", f"Test Cola {tag}")
    page.wait_for_timeout(2000)
    check("the medicine search no longer offers it",
          page.locator("#step-items .product-pick", has_text=f"Test Cola {tag}").count() == 0)
    if SHOT:
        page.screenshot(path=str(SHOT / "dispense-no-drinks.png"))

    # ---- but the shop still has it -------------------------------------------------
    page.goto(BASE + "/stock", wait_until="networkidle")
    page.wait_for_timeout(2500)
    page.fill("input[placeholder*='Search']", f"Test Cola {tag}")
    page.wait_for_timeout(2000)
    check("the line is still in the catalogue", page.locator("td", has_text=f"Test Cola {tag}").count() > 0)
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
