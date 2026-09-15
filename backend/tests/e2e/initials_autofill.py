"""Checked by is filled with the signed-in person's initials, and can be typed over.

  - on arrival the field already holds the initials of whoever is signed in
    (System Administrator -> SA)
  - so a script ready to go is not held up asking for them
  - the Finish dialog's copy holds the same
  - typing over it keeps what was typed
  - a new script puts the signed-in person's initials back

Run against a local dev server on :4177 and API on :8099:
  python initials_autofill.py [screenshot-dir]
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 900}, color_scheme="light")
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

    check("on arrival Checked by holds the signed-in person's initials",
          page.input_value("#disp-initials") == "SA", repr(page.input_value("#disp-initials")))

    page.fill("[data-hk='patient']", "Andela")
    page.wait_for_timeout(1600)
    page.query_selector_all("#step-patient .product-pick")[0].click()
    page.wait_for_timeout(1500)
    page.fill("#disp-doctor", "Dr")
    page.wait_for_timeout(700)
    page.query_selector_all("#step-patient .doc-pick")[0].click()
    page.wait_for_timeout(500)
    page.fill("[data-hk='product']", "atorva")
    page.wait_for_timeout(1600)
    page.query_selector_all("#step-items .product-pick")[0].click()
    page.wait_for_timeout(900)
    if page.query_selector(".disp-edit"):
        page.click(".disp-edit .disp-edit-actions .btn.primary")
        page.wait_for_timeout(1300)
    bar = page.inner_text(".disp-bar")
    check("a script ready to go is not held up asking for initials",
          "initials" not in bar.lower(), bar[:160])
    if SHOT:
        page.screenshot(path=str(SHOT / "initials-filled.png"))

    page.click(".disp-bar .disp-go")
    page.wait_for_timeout(1500)
    proceed = page.query_selector(".disp-finish .fin-proceed")
    if proceed and not proceed.is_disabled():
        proceed.click()
        page.wait_for_timeout(900)
    fi = page.query_selector("#finish-initials")
    check("Finish holds the same initials", fi is not None and fi.input_value() == "SA",
          repr(fi.input_value()) if fi else "no field")
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

    page.fill("#disp-initials", "tm")
    page.wait_for_timeout(300)
    page.locator("body").click(position={"x": 5, "y": 5})
    page.wait_for_timeout(600)
    check("typing over it keeps what was typed", page.input_value("#disp-initials") == "TM",
          repr(page.input_value("#disp-initials")))

    page.locator(".page-actions").get_by_role("button", name="New script").click()
    page.wait_for_timeout(1200)
    check("a new script puts the signed-in person's initials back",
          page.input_value("#disp-initials") == "SA", repr(page.input_value("#disp-initials")))
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
