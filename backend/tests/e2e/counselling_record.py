"""Counselling, in a browser: captured at Finish, required when set, read back.

  - with the pharmacy requiring a record, Finish marks counselling Required
    and the dispense button will not go, saying why
  - ticking points covers them, and the button goes
  - the dispensing's own page lists what was said, ticked, with the notes

Sets `dispensing.require_counselling` to "always" on the local database for the
run and puts back whatever was there before, pass or fail.

Run against a local dev server on :4177 and API on :8099:
  python counselling_record.py [screenshot-dir]
"""
import pathlib
import sqlite3
import sys
from datetime import datetime

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
DB = pathlib.Path(__file__).resolve().parents[2] / "rx3000.db"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
KEY = "dispensing.require_counselling"
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def set_rule(value):
    with sqlite3.connect(str(DB)) as c:
        c.execute("delete from settings where key = ?", (KEY,))
        if value is not None:
            c.execute("insert into settings (key, value, updated_at) values (?, ?, ?)",
                      (KEY, value, datetime.utcnow().isoformat(" ")))


with sqlite3.connect(str(DB)) as _c:
    _row = _c.execute("select value from settings where key = ?", (KEY,)).fetchone()
previous = _row[0] if _row else None

set_rule("always")
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1512, "height": 900}, color_scheme="dark")
        page.goto(BASE, wait_until="networkidle")
        page.fill("#lg-user", "admin")
        page.fill("#lg-pass", "admin123")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_timeout(2500)
        page.goto(BASE + "/dispense", wait_until="networkidle")
        page.wait_for_timeout(2000)
        if page.query_selector(".disp-patient-picked") or page.query_selector(
                ".disp-grid > .rx-item:not(.rx-item-waiting)"):
            page.locator(".page-actions").get_by_role("button", name="New script").click()
            page.wait_for_timeout(900)

        page.fill("[data-hk='patient']", "Andela")
        page.wait_for_timeout(1600)
        page.query_selector_all("#step-patient .product-pick")[0].click()
        page.wait_for_timeout(1600)
        page.fill("#disp-doctor", "Dr")
        page.wait_for_timeout(700)
        page.query_selector_all("#step-patient .doc-pick")[0].click()
        page.wait_for_timeout(500)
        page.fill("[data-hk='product']", "amlo")
        page.wait_for_timeout(1600)
        page.query_selector_all("#step-items .product-pick")[0].click()
        page.wait_for_timeout(900)
        if page.query_selector(".disp-edit"):
            page.click(".disp-edit .disp-edit-actions .btn.primary")
            page.wait_for_timeout(1400)

        page.click(".disp-bar .disp-go")
        page.wait_for_timeout(1400)
        proceed = page.query_selector(".disp-finish .fin-proceed")
        if proceed and not proceed.is_disabled():
            proceed.click()
            page.wait_for_timeout(1000)
        fi = page.query_selector("#finish-initials")
        if fi:
            fi.fill("TM")
            page.wait_for_timeout(300)

        block = page.query_selector("#finish-counselling")
        check("Finish carries the counselling record", block is not None)
        check("…marked Required while nothing is ticked",
              block is not None and "Required" in block.inner_text(), block.inner_text() if block else "")
        go = page.query_selector(".disp-finish .fin-dispense")
        check("…and the dispense button will not go", go is not None and go.is_disabled())
        foot = page.inner_text(".disp-finish .finish-foot")
        check("…saying why", "Record what the patient was told" in foot, foot[:160])
        sizes = page.evaluate("(() => { const m = document.querySelector('.disp-finish');"
                              " return [m.scrollHeight, m.clientHeight]; })()")
        check("the dialog still does not scroll with counselling in it",
              sizes[0] <= sizes[1] + 1, str(sizes))
        if SHOT:
            page.screenshot(path=str(SHOT / "counselling-required.png"))

        for label in ("Dose & timing", "Storage"):
            page.locator("#finish-counselling").get_by_role("checkbox", name=label).click()
            page.wait_for_timeout(200)
        page.fill("#finish-counsel-notes", "Take with food; keep out of the sun.")
        page.wait_for_timeout(300)
        check("ticking points covers them",
              "2 covered" in page.inner_text("#finish-counselling"),
              page.inner_text("#finish-counselling")[:120])
        go = page.query_selector(".disp-finish .fin-dispense")
        check("…and the dispense button goes", go is not None and not go.is_disabled())
        if SHOT:
            page.screenshot(path=str(SHOT / "counselling-covered.png"))

        with sqlite3.connect(str(DB)) as c:
            last_before = c.execute("select coalesce(max(id), 0) from dispensings").fetchone()[0]
        go.click()
        page.wait_for_timeout(6000)
        with sqlite3.connect(str(DB)) as c:
            row = c.execute("select id from dispensings where id > ? order by id desc limit 1",
                            (last_before,)).fetchone()
        check("the dispensing went through", row is not None)

        if row:
            page.goto(f"{BASE}/dispensings/{row[0]}", wait_until="networkidle")
            page.wait_for_timeout(2000)
            rec = page.query_selector(".dd-counsel")
            text = rec.inner_text() if rec else ""
            check("its page shows the counselling record", rec is not None)
            check("…with what was said and who recorded it",
                  "How and when to take it" in text and "How to store it" in text
                  and "recorded by" in text, text[:240])
            check("…and the notes", "Take with food" in text, text[:240])
            ticked = page.evaluate("""() => [...document.querySelectorAll('.dd-counsel li')]
              .map((li) => ({ t: li.innerText.trim(), ok: !!li.querySelector('.ok, [data-ok="true"], svg.ok') || li.className.includes('ok') }))""")
            if SHOT:
                page.screenshot(path=str(SHOT / "counselling-detail.png"))
        browser.close()
finally:
    set_rule(previous)
    print(f"  --    {KEY} put back to {previous!r}")

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
