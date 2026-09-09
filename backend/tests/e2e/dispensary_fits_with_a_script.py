"""Measure the dispensary with a real script on it.

An empty screen fits easily; the question is whether it still fits once there
is a patient and three medicines on it, because that is the state a dispenser
is actually in. So this picks a patient off the search, adds three medicines,
and then asks how tall each item row is and whether anything has to scroll.
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
  const px = n => Math.round(n);
  const items = document.querySelector('.card.sec-items');
  return {
    viewport: window.innerHeight,
    document: px(document.documentElement.scrollHeight),
    pageScrolls: document.documentElement.scrollHeight > window.innerHeight + 2,
    head: px(document.querySelector('.disp-head')?.getBoundingClientRect().height || 0),
    patient: px(document.querySelector('.sec-patient')?.getBoundingClientRect().height || 0),
    itemsBand: items ? px(items.getBoundingClientRect().height) : 0,
    itemsScrollsInside: items ? items.scrollHeight > items.clientHeight + 2 : null,
    perItem: [...document.querySelectorAll('.card.sec-items .disp-line, .card.sec-items > div')]
      .map(d => px(d.getBoundingClientRect().height)).filter(h => h > 60),
    dispenseVisible: (() => {
      const b = [...document.querySelectorAll('button')]
        .find(b => /Dispense \\d/.test(b.textContent || ''));
      if (!b) return 'not found';
      const r = b.getBoundingClientRect();
      return r.bottom <= window.innerHeight && r.top >= 0;
    })(),
  };
}
"""

with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": 1366, "height": 768})
    page.goto(WEB, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)
    page.goto(f"{WEB}/dispense", wait_until="networkidle")
    page.wait_for_timeout(1500)

    # A patient off the search.
    page.fill('input[placeholder*="Search patient"]', "a")
    page.wait_for_timeout(1500)
    picks = page.query_selector_all(".product-pick")
    if picks:
        picks[0].click()
        page.wait_for_timeout(1200)
        print(f"  picked a patient ({len(picks)} matched)")

    # Three medicines.
    added = 0
    for term in ("amox", "para", "metfor"):
        box = page.query_selector('input[placeholder*="Search prescription"]')
        if not box:
            break
        box.fill(term)
        page.wait_for_timeout(1400)
        hits = page.query_selector_all(".product-pick")
        if hits:
            hits[0].click()
            added += 1
            page.wait_for_timeout(900)
    print(f"  put {added} medicine(s) on the script")

    m = page.evaluate(MEASURE)
    print(f"\n  viewport {m['viewport']}   document {m['document']}")
    print(f"  PAGE SCROLLS: {m['pageScrolls']}")
    print(f"  head {m['head']}  patient band {m['patient']}  items band {m['itemsBand']}")
    print(f"  items scroll inside themselves: {m['itemsScrollsInside']}")
    print(f"  height of each script line: {m['perItem']}")
    print(f"  the Dispense button is on screen: {m['dispenseVisible']}")
    page.screenshot(path=str(SHOT / "disp-loaded.png"))
    b.close()
print(f"\n  screenshot: {SHOT / 'disp-loaded.png'}")
