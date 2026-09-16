"""Typing directions: a code in full takes its own space.

  - typing `1t` completes it and leaves the caret ready for the next code
  - `1t tds pc` is typed straight through, with no Enter between the codes,
    and the label preview reads as a sentence
  - a code other codes begin with (`i`, on its way to `ii`) does not advance:
    the list stays open to be chosen from
  - the suggestion list still takes Enter, for a code somebody half remembers
  - it behaves the same in the dispensing table's own cell

Run against a local dev server on :4177 and API on :8099:
  python directions_shorthand.py [screenshot-dir]
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
    page.fill("#disp-doctor", "Dr")
    page.wait_for_timeout(800)
    page.query_selector_all("#step-patient .doc-pick")[0].click()
    page.wait_for_timeout(500)
    page.fill("[data-hk='product']", "atorva")
    page.wait_for_timeout(1600)
    page.query_selector_all("#step-items .product-pick")[0].click()
    page.wait_for_timeout(1500)

    box = page.query_selector(".disp-edit")
    check("the line opens for its directions", box is not None)
    field = page.locator(".disp-edit .sig input").first
    field.click()
    field.fill("")
    page.wait_for_timeout(300)

    # ---- a code in full takes its own space ---------------------------------------
    page.keyboard.type("1t", delay=90)
    page.wait_for_timeout(600)
    check("typing a code in full completes it and adds the space",
          field.input_value() == "1t ", repr(field.input_value()))
    check("…and the suggestion list has closed", page.query_selector(".sig-suggest") is None)

    page.keyboard.type("tds", delay=90)
    page.wait_for_timeout(600)
    check("the next code is typed straight after it", field.input_value() == "1t tds ",
          repr(field.input_value()))
    page.keyboard.type("pc", delay=90)
    page.wait_for_timeout(700)
    check("and the third, with no Enter anywhere", field.input_value() == "1t tds pc ",
          repr(field.input_value()))
    preview = page.query_selector(".disp-edit .sig-preview")
    check("the label preview reads as a sentence",
          preview is not None and "ONE tablet" in preview.inner_text()
          and "three times a day" in preview.inner_text(),
          preview.inner_text()[:120] if preview else "no preview")
    if SHOT:
        page.screenshot(path=str(SHOT / "directions-typed.png"))

    # ---- a code others begin with waits to be chosen --------------------------------
    field.fill("")
    page.wait_for_timeout(300)
    page.keyboard.type("i", delay=90)
    page.wait_for_timeout(700)
    check("a code that others begin with does not advance on its own",
          field.input_value() == "i", repr(field.input_value()))
    check("…and the list is there to choose from", page.query_selector(".sig-suggest") is not None)
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)
    check("…where Enter still takes the highlighted one",
          field.input_value().startswith("i") and field.input_value().endswith(" "),
          repr(field.input_value()))

    # ---- the same in the table's own cell --------------------------------------------
    field.fill("1t tds")
    page.wait_for_timeout(300)
    page.click(".disp-edit .disp-edit-actions .btn.primary")
    page.wait_for_timeout(1500)
    row_sig = page.locator(".rx-item-sig").first
    if row_sig.count():
        row_sig.dblclick()
        page.wait_for_timeout(900)
    cell = page.locator(".rx-item-sig .sig input").first
    if cell.count():
        cell.fill("")
        page.wait_for_timeout(300)
        page.keyboard.type("2t", delay=90)
        page.wait_for_timeout(600)
        check("the dispensing table's own cell behaves the same",
              cell.input_value() == "2t ", repr(cell.input_value()))
    else:
        print("  --    no directions cell on the table to try")
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
