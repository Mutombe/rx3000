"""A till is a queue, so the screen is free before the sale has finished.

The old flow held everything — button disabled, basket frozen, cashier watching
a spinner — for as long as a hosted database in another city took to write a
sale, its lines, its tenders and its stock movements. At a counter with four
people in it that is the whole cost of the software.

  - the basket is ruled to the floor, so a cashier sees where the next scan goes
  - the total is the table's own last row, and it is on screen, not clipped
  - the keys the till answers to are said out loud
  - taking the money clears the counter on the keystroke
  - …the sale carries on in the tray, named, while the next item is scanned
  - …it ends in a word: the sale number and what was taken
  - …and the receipt prints by itself, with nobody pressing Print
  - the server really has the sale
  - nothing scrolls, and the key strip is on screen at 1512x950 and 1366x768

Run against a local dev server on :4177 and API on :8099:
  python the_till_is_quick.py [screenshot-dir]
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
shelf = api("/api/products", {"name": f"Counter Sweets {tag}", "unit_price": 4.00,
                              "cost_price": 2.00, "units_per_pack": 1, "vat_rate": 0.0}, token)
api("/api/stock/adjust", {"product_id": shelf["id"], "quantity_delta": 60,
                          "movement_type": "receive", "batch_number": f"CS{tag}",
                          "expiry_date": "2028-05-31"}, token)
second = api("/api/products", {"name": f"Counter Crisps {tag}", "unit_price": 3.00,
                               "cost_price": 1.50, "units_per_pack": 1, "vat_rate": 0.0}, token)
api("/api/stock/adjust", {"product_id": second["id"], "quantity_delta": 60,
                          "movement_type": "receive", "batch_number": f"CC{tag}",
                          "expiry_date": "2028-05-31"}, token)

printed: list = []

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
    # The receipt would otherwise open the browser's print dialog and block
    # everything behind it. Recorded instead, which is what the check needs.
    # The receipt prints into a popup window, so it is `window.open` that has
    # to be watched, not this page's own `print`. A real popup would also block
    # everything behind it in a headless run.
    page.add_init_script("""
      window.__printed = 0;
      window.open = () => {
        window.__printed++;
        const d = { write(){}, close(){}, images: [], readyState: 'complete',
                    addEventListener(){}, body: {} };
        return { document: d, focus(){}, print(){}, close(){},
                 addEventListener(){}, setTimeout: window.setTimeout.bind(window) };
      };
    """)
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)
    page.goto(BASE + "/pos", wait_until="networkidle")
    page.wait_for_timeout(2800)

    ruled = page.locator(".till-row-empty")
    check("the basket is ruled to the floor before anything is scanned",
          ruled.count() >= 8, f"{ruled.count()} waiting rows")
    check("the keys the till answers to are said out loud",
          page.locator(".keybar .keybar-item").count() >= 2,
          str(page.locator(".keybar .keybar-item").count()))

    def add(name):
        page.fill("input[placeholder*='Scan a barcode']", name)
        page.wait_for_timeout(1500)
        hit = page.locator(".product-pick").first
        if hit.count():
            hit.click()
        page.wait_for_timeout(900)

    add(f"Counter Sweets {tag}")
    add(f"Counter Crisps {tag}")

    foot = page.locator(".till-foot")
    check("the total is the table's own last row", foot.count() == 1)
    if foot.count():
        said = foot.first.inner_text()
        check("…and it says what is due", "7.00" in said, said[:90])
        on_screen = page.evaluate(
            """() => { const f = document.querySelector('.till-foot').getBoundingClientRect();
                       return f.bottom <= window.innerHeight + 1 && f.top > 0; }""")
        check("…and it is on screen, not clipped off the bottom", on_screen)
    if SHOT:
        page.screenshot(path=str(SHOT / "till-basket.png"))

    # Take the money.
    page.fill("input[placeholder='0.00']", "10")
    page.wait_for_timeout(300)
    page.get_by_role("button", name="Complete sale").click()
    page.wait_for_timeout(350)

    # The counter is free immediately — this is the whole point.
    lines_now = page.locator(".till-row:not(.till-row-empty):not(.till-row-head)").count()
    check("the counter clears on the keystroke", lines_now == 0, f"{lines_now} lines still there")
    tray = page.locator(".doing-chip")
    check("…and the sale carries on in the tray, named", tray.count() >= 1,
          f"{tray.count()} chips")
    if SHOT and tray.count():
        page.screenshot(path=str(SHOT / "till-optimistic.png"))

    # The next customer can start while it is still in flight.
    page.fill("input[placeholder*='Scan a barcode']", f"Counter Crisps {tag}")
    page.wait_for_timeout(1500)
    nxt = page.locator(".product-pick").first
    if nxt.count():
        nxt.click()
    page.wait_for_timeout(600)
    check("the next customer can be scanned while it is still going",
          page.locator(".till-row:not(.till-row-empty):not(.till-row-head)").count() >= 1)

    # Checked while the chip is still up: a landed chip is cleared after a few
    # seconds, and a test that looks too late reports "no chip" for work that
    # went perfectly.
    landed_seen = False
    for _ in range(30):
        if page.locator(".doing-chip.is-done").count():
            landed_seen = True
            break
        page.wait_for_timeout(400)
    said = " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))
    check("it ends in a word: what was taken", "taken" in said.lower() or "$" in said,
          said[:140])
    check("…and the chip turns as it lands", landed_seen, "never turned")
    check("…and the receipt printed itself, with nobody pressing Print",
          page.evaluate("() => window.__printed") >= 1,
          str(page.evaluate("() => window.__printed")))

    for w, h in ((1512, 950), (1366, 768)):
        page.set_viewport_size({"width": w, "height": h})
        page.wait_for_timeout(700)
        fits = page.evaluate("""() => {
          const k = document.querySelector('.keybar');
          const kb = k ? k.getBoundingClientRect() : null;
          return {scrolls: document.documentElement.scrollHeight > window.innerHeight + 2,
                  keysOn: kb ? kb.bottom <= window.innerHeight + 1 : false};
        }""")
        check(f"nothing scrolls at {w}x{h}, and the keys are on screen",
              not fits["scrolls"] and fits["keysOn"], str(fits))

    browser.close()

sales = api("/api/pos/sales?status=paid&limit=5", token=token)
mine = [s for s in (sales or []) if any(f"Counter Sweets {tag}" in (i.get("description") or "")
                                        for i in (s.get("items") or []))]
check("the server really has the sale", bool(mine), f"{len(sales or [])} recent sales")

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
