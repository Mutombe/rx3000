"""A control drawn for one field must not come to rest on another.

The camera belongs to the medicine search. It was given `.lane-icon-btn`, a
class written for the picked-patient box — a flex row that lays its children out
side by side — and dropped into the medicine field, which is a plain relative
block. With no position of its own it flowed underneath the input and landed on
top of the prescriber's results: somebody searching for a doctor got a camera
sitting in the middle of the answer, attached to a different field entirely.

That is a whole class of bug rather than one icon, so this asks the question
generally, on the lane the dispensary works in all day:

  - the camera sits inside the medicine field's own box
  - …at its right-hand end, where the eye goes for a field's controls
  - …and clear of the magnifier beside it
  - the medicine field's text never runs under either icon
  - with a prescriber search open, nothing from another field is on top of it
  - and the camera still opens the scanner

Run against a local dev server on :4177 and API on :8099:
  python controls_stay_in_their_field.py [screenshot-dir]
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
fails = []


def check(label, ok, detail=""):
    line = f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else "")
    print(line.encode("ascii", "replace").decode("ascii"))
    if not ok:
        fails.append(label)


def box(page, selector):
    return page.evaluate(
        """(sel) => {
             const el = document.querySelector(sel);
             if (!el) return null;
             const r = el.getBoundingClientRect();
             return {l: r.left, r: r.right, t: r.top, b: r.bottom,
                     w: r.width, h: r.height};
           }""", selector)


with sync_playwright() as pw:
    browser = pw.chromium.launch(args=["--use-fake-ui-for-media-stream",
                                       "--use-fake-device-for-media-stream"])
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
    page.fill("[data-hk='patient']", "Andela")
    page.wait_for_timeout(1600)
    page.query_selector_all("#step-patient .product-pick")[0].click()
    page.wait_for_timeout(1400)

    field = box(page, ".lane-field.disp-medicine")
    camera = box(page, ".lane-scan")
    glass = box(page, ".lane-field.disp-medicine > .lane-icon")
    medicine = box(page, "[data-hk='product']")

    if camera is None:
        print("  the camera is not offered here (no camera on this browser) — nothing to check")
        browser.close()
        sys.exit(0)

    inside = (camera["t"] >= field["t"] - 1 and camera["b"] <= field["b"] + 1
              and camera["l"] >= field["l"] - 1 and camera["r"] <= field["r"] + 1)
    check("the camera sits inside the medicine field's own box", inside,
          f"field {field['t']:.0f}-{field['b']:.0f}, camera {camera['t']:.0f}-{camera['b']:.0f}")

    check("…at its right-hand end, not floating in the middle",
          field["r"] - camera["r"] < 60,
          f"{field['r'] - camera['r']:.0f}px in from the right edge")

    if glass:
        check("…and clear of the magnifier beside it",
              camera["r"] <= glass["l"] + 1,
              f"camera ends {camera['r']:.0f}, magnifier starts {glass['l']:.0f}")

    # Typed text must not run under either icon.
    page.fill("[data-hk='product']", "Hydrochlorothiazide 12.5mg tablets")
    page.wait_for_timeout(400)
    pad = page.evaluate(
        """() => parseFloat(getComputedStyle(
             document.querySelector("[data-hk='product']")).paddingRight)""")
    needed = medicine["r"] - camera["l"]
    check("the medicine's own text never runs under either icon", pad >= needed - 2,
          f"padding {pad:.0f}px, icons take {needed:.0f}px")
    page.fill("[data-hk='product']", "")
    page.wait_for_timeout(300)

    # The case from the screenshot: a prescriber search open, and a control
    # from the field next door sitting on the answer.
    page.fill("[data-hk='doctor']", "pari")
    page.wait_for_timeout(1800)
    results = page.locator(".doc-pick, #step-doctor .product-pick")
    if results.count():
        hit = results.first.bounding_box()
        overlap = (camera["l"] < hit["x"] + hit["width"]
                   and camera["r"] > hit["x"]
                   and camera["t"] < hit["y"] + hit["height"]
                   and camera["b"] > hit["y"])
        check("with a prescriber search open, no control from another field is on it",
              not overlap,
              f"camera {camera['l']:.0f},{camera['t']:.0f} over result "
              f"{hit['x']:.0f},{hit['y']:.0f} {hit['width']:.0f}x{hit['height']:.0f}")
        if SHOT:
            page.screenshot(path=str(SHOT / "prescriber-search-is-clear.png"))
    else:
        print("  no prescriber matched 'pari' here — that overlap is not checked")

    page.fill("[data-hk='doctor']", "")
    page.wait_for_timeout(600)
    page.locator(".lane-scan").click()
    page.wait_for_timeout(2000)
    check("and the camera still opens the scanner",
          page.locator(".scan-sheet").count() > 0,
          "nothing opened")

    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
