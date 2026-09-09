"""Open the dispensary at a real screen size and measure whether it fits.

The whole complaint is visual and the last two "it is fixed" claims were made
from source. So this signs in, opens the dispensary, puts a patient and a
medicine on the script, and then asks the browser the only question that
matters: is the page taller than the window?

It reports the height of every band as well, because "it does not fit" is not
actionable and "the four cards cost 376px" is.
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

WEB = "http://localhost:4177"
SHOT = pathlib.Path(
    r"C:\Users\PC\AppData\Local\Temp\claude\C--Users-PC-documents-rx3000"
    r"\6d5bc22f-b856-4dc0-91e1-75f436accb9d\scratchpad")

MEASURE = """
() => {
  const px = (n) => Math.round(n);
  const bits = {};
  const one = (sel) => {
    const el = document.querySelector(sel);
    return el ? px(el.getBoundingClientRect().height) : null;
  };
  bits.viewport   = window.innerHeight;
  bits.document   = px(document.documentElement.scrollHeight);
  bits.scrolls    = document.documentElement.scrollHeight > window.innerHeight + 2;
  bits.head       = one('.disp-head');
  bits.routes     = one('.disp-head .disp-routes');
  bits.steptrail  = one('[class*="step"]');
  bits.items      = one('.card.sec-items');
  bits.itemsScroll= (() => {
    const el = document.querySelector('.card.sec-items');
    return el ? el.scrollHeight > el.clientHeight + 2 : null;
  })();
  bits.cards = [...document.querySelectorAll('.disp-dense .card')]
    .map(c => ({ h: px(c.getBoundingClientRect().height),
                 what: (c.querySelector('h3')?.textContent || c.className).slice(0, 34) }));
  return bits;
}
"""


def show(label, m):
    print(f"\n  === {label} ===")
    print(f"    viewport {m['viewport']}px   document {m['document']}px")
    print(f"    PAGE SCROLLS: {m['scrolls']}")
    print(f"    head {m['head']}  routes {m['routes']}  steptrail {m['steptrail']}")
    print(f"    items band {m['items']}  (scrolls inside: {m['itemsScroll']})")
    for c in m["cards"]:
        print(f"      {c['h']:>4}px  {c['what']}")


with sync_playwright() as pw:
    b = pw.chromium.launch()
    # A common till: 1366x768 is what most counter machines actually are, and
    # it is the hardest case that still has to work.
    page = b.new_page(viewport={"width": 1366, "height": 768})
    page.goto(WEB, wait_until="networkidle")

    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)

    page.goto(f"{WEB}/dispense", wait_until="networkidle")
    page.wait_for_timeout(1500)
    m = page.evaluate(MEASURE)
    show("empty script, 1366x768", m)
    page.screenshot(path=str(SHOT / "disp-empty.png"))

    # Put something on it, which is when the page actually has to hold content.
    try:
        page.fill('input[data-hk="patient"], input[type="search"]', "a")
        page.wait_for_timeout(1200)
        page.keyboard.press("Enter")
        page.wait_for_timeout(800)
    except Exception as e:
        print(f"\n  (could not load a patient: {type(e).__name__})")

    m2 = page.evaluate(MEASURE)
    show("after typing, 1366x768", m2)
    page.screenshot(path=str(SHOT / "disp-filled.png"), full_page=False)

    # And the size most laptops are.
    page.set_viewport_size({"width": 1512, "height": 900})
    page.wait_for_timeout(600)
    show("1512x900", page.evaluate(MEASURE))
    page.screenshot(path=str(SHOT / "disp-900.png"))
    b.close()

print(f"\n  screenshots in {SHOT}")
