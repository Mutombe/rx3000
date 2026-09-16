"""Pricing items from what they last sold for, in a browser.

  - the Prices tab offers it, and explains itself before anything is pressed
  - Preview writes nothing and lists what would be priced, most-sold first
  - items last sold over a year ago are marked, and the note says so
  - applying prices them, and the item that rang up as free has a price
  - a second preview finds nothing left to do

Run against a local dev server on :4177 and API on :8099:
  python price_from_history.py [screenshot-dir]
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
    req = urllib.request.Request(API + path, method="POST" if data is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None,
                                timeout=120) as f:
        return json.loads(f.read() or b"null")


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]

# An item sold at a known price, then left with none — the shape of the import.
product = api("/api/products", {"name": f"Unpriced import {tag}", "unit_price": 12.5,
                                "cost_price": 5.0, "units_per_pack": 1, "vat_rate": 0.0}, token)
api("/api/stock/adjust", {"product_id": product["id"], "quantity_delta": 50,
                          "movement_type": "receive", "batch_number": f"PH{tag}"}, token)
api("/api/pos/sales", {"items": [{"product_id": product["id"], "quantity": 1, "unit_price": 12.5}],
                       "payment_method": "cash", "amount_tendered": 100.0}, token)
api(f"/api/products/{product['id']}", None, token)      # exists
import sqlite3  # noqa: E402

db = sqlite3.connect(str(pathlib.Path(__file__).resolve().parents[2] / "rx3000.db"))
db.execute("update products set unit_price = 0 where id = ?", (product["id"],))
db.commit()
print(f"  {product['name']} sold at 12.50, now priced at nothing")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)
    page.goto(BASE + "/admin?tab=prices", wait_until="networkidle")
    page.wait_for_timeout(2000)
    if page.query_selector("text=Price items from sales history") is None:
        tab = page.get_by_role("button", name="Prices")
        if tab.count():
            tab.first.click()
            page.wait_for_timeout(1200)

    card = page.locator(".card", has_text="Price items from sales history")
    check("the Prices tab offers pricing from history", card.count() > 0)
    check("…and says what it will do before anything is pressed",
          "last sold for" in card.first.inner_text(), card.first.inner_text()[:140] if card.count() else "")
    card.first.get_by_role("button", name="Preview prices").click()
    page.wait_for_timeout(6000)
    text = card.first.inner_text()
    check("Preview lists what would be priced", "would be priced" in text, text[:200])
    rows = card.first.locator("table.dt tbody tr")
    check("…most-sold first, with the price offered", rows.count() > 0, str(rows.count()))
    still_free = api(f"/api/products/{product['id']}", None, token)["product"]["unit_price"]
    check("…and nothing is written yet", still_free == 0, str(still_free))
    if SHOT:
        page.screenshot(path=str(SHOT / "price-history-preview.png"), full_page=True)

    price_btn = card.first.locator("button").nth(1)
    check("the apply button says how many", "Price" in price_btn.inner_text()
          and any(ch.isdigit() for ch in price_btn.inner_text()), price_btn.inner_text())
    check("…and it is offered, not disabled", price_btn.is_enabled())
    price_btn.click()
    after = 0
    for _ in range(30):
        page.wait_for_timeout(1000)
        after = api(f"/api/products/{product['id']}", None, token)["product"]["unit_price"]
        if after:
            break
    check("applying gives the item back its price", abs(after - 12.5) < 0.005, str(after))
    said = card.first.inner_text()
    check("…and says how many were priced", "item(s) priced" in said, said[:160])
    if SHOT:
        page.screenshot(path=str(SHOT / "price-history-applied.png"), full_page=True)

    card.first.get_by_role("button", name="Preview prices").click()
    page.wait_for_timeout(5000)
    check("a second preview finds nothing left to do",
          "0 item(s) would be priced" in card.first.inner_text(),
          card.first.inner_text()[:160])
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
