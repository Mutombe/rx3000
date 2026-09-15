"""Two things a dispenser hit, reproduced in a browser.

  1  A refused dispensing of a new script used to leave the saved script
     behind, and pressing Dispense again saved another: three tries, three
     identical scripts on the worklist. A retry now dispenses the script
     already saved, and the screen shows its number.

  2  Stock that came in with no expiry recorded (the CareXpress opening stock)
     could not be dispensed, and was called expired. Finish now asks for the
     date on the pack before paying, refuses a date already past, and the
     dispensing dates the stock with it.

One batch at the main branch has its expiry cleared for the run, as the import
left the CareXpress stock, and is put back afterwards, pass or fail.

Run against a local dev server on :4177 and API on :8099:
  python undated_stock_and_retries.py [screenshot-dir]
"""
import json
import pathlib
import sqlite3
import sys
import urllib.request
from datetime import date, timedelta

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
API = "http://127.0.0.1:8099"
DB = pathlib.Path(__file__).resolve().parents[2] / "rx3000.db"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
MAIN = 1
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def api(path, data=None, token=None):
    req = urllib.request.Request(API + path, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, json.dumps(data).encode() if data else None, timeout=60) as f:
        return json.loads(f.read() or b"null")


def db(query, params=()):
    with sqlite3.connect(str(DB)) as c:
        return c.execute(query, params).fetchall()


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
patient = api("/api/patients?q=Andela&limit=3", token=token)[0]

# Two single-batch medicines at the main branch: one to over-order, one to undate.
singles = []
for p in api("/api/dispensing/products?route=prescription&limit=200", token=token):
    rows = db("select id, quantity_remaining, expiry_date from stock_batches "
              "where product_id = ? and branch_id = ? and quantity_remaining > 0", (p["id"], MAIN))
    if len(rows) == 1 and rows[0][1] >= 5 and rows[0][2]:
        singles.append((p, rows[0][0], rows[0][2]))
    if len(singles) == 2:
        break
(short, _short_batch, _), (undated, undated_batch, original_expiry) = singles
print(f"  over-ordering {short['name']}; undating {undated['name']} (batch {undated_batch}, was {original_expiry})")


def scripts_for_patient():
    return db("select count(*) from prescriptions where patient_id = ?", (patient["id"],))[0][0]


def start_script(page, product, quantity=None):
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(1800)
    if page.query_selector(".disp-patient-picked") or page.query_selector(
            ".disp-grid > .rx-item:not(.rx-item-waiting)"):
        page.locator(".page-actions").get_by_role("button", name="New script").click()
        page.wait_for_timeout(900)
    page.fill("[data-hk='patient']", patient["last_name"])
    page.wait_for_timeout(1600)
    page.query_selector_all("#step-patient .product-pick")[0].click()
    page.wait_for_timeout(1500)
    page.fill("#disp-doctor", "Dr")
    page.wait_for_timeout(700)
    page.query_selector_all("#step-patient .doc-pick")[0].click()
    page.wait_for_timeout(500)
    page.fill("[data-hk='product']", product["name"][:12])
    page.wait_for_timeout(1600)
    page.locator("#step-items .product-pick", has_text=product["name"][:12]).first.click()
    page.wait_for_timeout(900)
    if page.query_selector(".disp-edit"):
        page.click(".disp-edit .disp-edit-actions .btn.primary")
        page.wait_for_timeout(1300)
    if quantity:
        page.locator(".disp-grid > .rx-item:not(.rx-item-waiting) .rx-item-qty").first.dblclick()
        page.wait_for_timeout(300)
        page.fill(".rx-item-qty input", str(quantity))
        page.keyboard.press("Enter")
        page.wait_for_timeout(900)


def to_pay_and_dispense(page):
    page.click(".disp-bar .disp-go")
    page.wait_for_timeout(1500)
    proceed = page.query_selector(".disp-finish .fin-proceed")
    if proceed and not proceed.is_disabled():
        proceed.click()
        page.wait_for_timeout(900)
    init = page.query_selector("#finish-initials")
    if init:
        init.fill("SM")
        page.wait_for_timeout(300)
    page.click(".disp-finish .fin-dispense")
    page.wait_for_timeout(4500)


try:
    db("update stock_batches set expiry_date = null where id = ?", (undated_batch,))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1512, "height": 900}, color_scheme="light")
        page.goto(BASE, wait_until="networkidle")
        page.fill("#lg-user", "admin")
        page.fill("#lg-pass", "admin123")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_timeout(2500)

        # ---- 1 · a refused new script, retried ---------------------------------
        before = scripts_for_patient()
        start_script(page, short, quantity=999999)
        to_pay_and_dispense(page)
        after_first = scripts_for_patient()
        check("a refused dispensing of a new script keeps the script it saved",
              after_first == before + 1, f"{before} -> {after_first}")
        header = page.inner_text(".disp-scriptid-no").strip()
        saved_number = db("select rx_number from prescriptions where patient_id = ? order by id desc limit 1",
                          (patient["id"],))[0][0]
        check("…and the screen now shows that script's number", header == saved_number,
              f"header {header!r}, saved {saved_number!r}")
        if page.query_selector(".disp-finish"):
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        to_pay_and_dispense(page)
        after_retry = scripts_for_patient()
        check("pressing Dispense again does not save another copy", after_retry == after_first,
              f"{after_first} -> {after_retry}")
        if page.query_selector(".disp-finish"):
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

        # ---- 2 · stock with no expiry recorded ---------------------------------
        start_script(page, undated)
        page.wait_for_timeout(800)
        page.click(".disp-bar .disp-go")
        page.wait_for_timeout(1500)
        section = page.query_selector("#finish-expiry")
        check("Finish asks for the expiry on the pack before paying", section is not None)
        check("…naming the medicine", section is not None and undated["name"][:12] in section.inner_text(),
              section.inner_text()[:160] if section else "")
        proceed = page.query_selector(".disp-finish .fin-proceed")
        check("…and will not go on without it", proceed is not None and proceed.is_disabled())
        if SHOT:
            page.screenshot(path=str(SHOT / "expiry-asked.png"))

        box = page.locator(f"#pack-expiry-{undated['id']}")
        box.fill((date.today() - timedelta(days=5)).isoformat())
        page.wait_for_timeout(400)
        check("a date already past says the pack has expired",
              "has expired" in page.inner_text("#finish-expiry"))
        check("…and still will not go on", page.query_selector(".disp-finish .fin-proceed").is_disabled())

        expiry = (date.today() + timedelta(days=500)).isoformat()
        box.fill(expiry)
        page.wait_for_timeout(400)
        proceed = page.query_selector(".disp-finish .fin-proceed")
        check("the date on the pack lets it go on", proceed is not None and not proceed.is_disabled())
        if SHOT:
            page.screenshot(path=str(SHOT / "expiry-entered.png"))
        proceed.click()
        page.wait_for_timeout(900)
        init = page.query_selector("#finish-initials")
        if init:
            init.fill("SM")
            page.wait_for_timeout(300)
        page.click(".disp-finish .fin-dispense")
        page.wait_for_timeout(5000)

        stamped = db("select expiry_date from stock_batches where id = ?", (undated_batch,))[0][0]
        check("it dispenses, and the stock now carries the date from the pack",
              str(stamped).startswith(expiry), f"{stamped!r}")
        who = db("select user_id from stock_movements where product_id = ? and reference like 'EXPIRY %' "
                 "order by id desc limit 1", (undated["id"],))
        check("…with a record of who entered it", bool(who and who[0][0]), str(who))
        browser.close()
finally:
    db("update stock_batches set expiry_date = ? where id = ?", (original_expiry, undated_batch))
    print(f"  --    batch {undated_batch} expiry put back to {original_expiry}")

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
