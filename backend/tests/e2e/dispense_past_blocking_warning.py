"""The penicillin case, end to end in the browser.

Loveness Andela is allergic to penicillin. Amoxicillin on a new script raises a
blocking warning. Until now that script could not be dispensed from the
dispensary at all: "I have checked this" answered "Capture the script first".

  Finish opens at the settling stage with Proceed held;
  "I have checked this" is accepted and Proceed opens;
  payment, initials, Dispense;
  the dispensing lands, and the acknowledgement is on record in the database.

Run against a local preview on :4177 and API on :8099:
  python dispense_past_blocking_warning.py [screenshot-dir]
"""
import pathlib
import sqlite3
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
DB = pathlib.Path(__file__).resolve().parents[2] / "rx3000.db"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


db = sqlite3.connect(DB)
product_id = db.execute(
    "select id from products where name='Amoxicillin' and strength='500mg' and active=1").fetchone()[0]
before = db.execute("select count(*) from message_acknowledgements where message_id = ?",
                    (-product_id,)).fetchone()[0]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1366, "height": 768}, color_scheme="dark")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2200)
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(1500)

    page.fill("[data-hk='patient']", "Andela")
    page.wait_for_timeout(1500)
    page.query_selector_all("#step-patient .product-pick")[0].click()
    page.wait_for_timeout(1200)
    page.fill("#disp-doctor", "Dr")
    page.wait_for_timeout(500)
    page.query_selector_all("#step-patient .doc-pick")[0].click()
    page.wait_for_timeout(400)
    page.fill("[data-hk='product']", "amox")
    page.wait_for_timeout(1500)
    page.query_selector_all("#step-items .product-pick")[0].click()
    page.wait_for_timeout(900)
    page.click(".disp-edit .disp-edit-actions .btn.primary")
    page.wait_for_timeout(1500)

    page.click(".disp-bar .disp-go")
    page.wait_for_timeout(900)
    check("Finish opens at the settling stage", page.query_selector(".disp-finish.is-settle") is not None)
    proceed = page.query_selector(".disp-finish .fin-proceed")
    check("…with Proceed held by the penicillin warning", proceed is not None and proceed.is_disabled())

    ack = page.query_selector(".disp-finish .fin-item.is-stop .fin-item-act .btn")
    check("the blocking warning offers 'I have checked this'", ack is not None)
    if ack:
        ack.click()
        page.wait_for_timeout(500)
    check("…and accepts it, with no 'capture the script first'",
          page.query_selector(".disp-finish .fin-ack") is not None
          and "Capture the script first" not in (page.inner_text(".disp-finish") or ""))
    proceed = page.query_selector(".disp-finish .fin-proceed")
    check("Proceed opens once it is acknowledged", proceed is not None and not proceed.is_disabled())
    if SHOT is not None:
        page.screenshot(path=str(SHOT / "ack-settled.png"))

    if proceed and not proceed.is_disabled():
        proceed.click()
        page.wait_for_timeout(700)
    check("…to payment", page.query_selector(".disp-finish.is-pay") is not None)
    if page.query_selector("#finish-initials"):
        page.fill("#finish-initials", "TM")
        page.wait_for_timeout(300)
    go = page.query_selector(".finish-foot .printmenu-main")
    check("Dispense is available", go is not None and not go.is_disabled())
    if go and not go.is_disabled():
        go.click()
        # "Send to till" is the default route, and it goes where the patient goes:
        # the Front Shop opens with the new invoice at the top, marked as just
        # dispensed. Paying at the counter stays on the dispensary and says so on
        # the bar. Either is the dispensing landing.
        try:
            page.wait_for_function(
                "() => !!document.querySelector('.disp-status .disp-done')"
                " || /just dispensed/i.test(document.body.innerText)", timeout=15000)
        except Exception:
            pass
    on_bar = page.query_selector(".disp-status .disp-done") is not None
    body = page.inner_text("body")
    at_till = "just dispensed" in body.lower() and "Loveness Andela" in body
    check("the dispensing lands (the till opens with it, just dispensed)", on_bar or at_till,
          page.url)
    if SHOT is not None:
        page.screenshot(path=str(SHOT / "ack-dispensed.png"))
    browser.close()

after = db.execute("select count(*) from message_acknowledgements where message_id = ?",
                   (-product_id,)).fetchone()[0]
check("the acknowledgement is on record", after == before + 1, f"{before} -> {after}")

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
