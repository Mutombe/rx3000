"""Look at the dispensary in dark mode, empty and loaded, and check the alignment.

The complaint is that it looks unprofessional, and the specific fault underneath
that is alignment: inputs starting at different left edges down the same column.
So as well as a picture, this measures the one number that decides it — how many
distinct x-positions the inputs start at. On a screen that reads as designed
there is one.
"""
import pathlib

from playwright.sync_api import sync_playwright

WEB = "http://localhost:4177"
SHOT = pathlib.Path(
    r"C:\Users\PC\AppData\Local\Temp\claude\C--Users-PC-documents-rx3000"
    r"\6d5bc22f-b856-4dc0-91e1-75f436accb9d\scratchpad")

ALIGN = """
() => {
  const work = document.querySelector('.disp-with-worklist > div:first-child');
  if (!work) return { error: 'no work column' };
  const fields = [...work.querySelectorAll('.field')];
  const lefts = {};
  for (const f of fields) {
    const ctrl = f.querySelector('input, select, textarea, .sel-trigger, [class*="picker"]');
    if (!ctrl) continue;
    const x = Math.round(ctrl.getBoundingClientRect().left);
    const lbl = (f.querySelector('label')?.textContent || '(none)').trim().slice(0, 22);
    (lefts[x] = lefts[x] || []).push(lbl);
  }
  const labelWrap = fields.filter(f => {
    const l = f.querySelector('label');
    return l && l.getBoundingClientRect().height > 22;
  }).map(f => f.querySelector('label').textContent.trim().slice(0, 30));
  return {
    distinctLeftEdges: Object.keys(lefts).length,
    edges: Object.fromEntries(Object.entries(lefts).map(([k, v]) => [k, v])),
    labelsThatWrap: labelWrap,
    pageScrolls: document.documentElement.scrollHeight > window.innerHeight + 2,
  };
}
"""

with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": 1512, "height": 900},
                      color_scheme="dark")
    page.goto(WEB, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)
    page.goto(f"{WEB}/dispense", wait_until="networkidle")
    page.wait_for_timeout(1500)

    a = page.evaluate(ALIGN)
    print("\n  EMPTY SCRIPT")
    print(f"    distinct left edges for inputs: {a.get('distinctLeftEdges')}")
    for x, labels in (a.get("edges") or {}).items():
        print(f"      x={x}: {labels}")
    print(f"    labels that wrap: {a.get('labelsThatWrap')}")
    print(f"    page scrolls: {a.get('pageScrolls')}")
    page.screenshot(path=str(SHOT / "dark-empty.png"))

    page.fill('input#disp-patient', "a")
    page.wait_for_timeout(1500)
    picks = page.query_selector_all(".product-pick")
    if picks:
        picks[0].click(); page.wait_for_timeout(1200)
    for term in ("amox", "metfor"):
        box = page.query_selector('input[placeholder*="Search prescription"]')
        if not box: break
        box.fill(term); page.wait_for_timeout(1400)
        hits = page.query_selector_all(".product-pick")
        if hits: hits[0].click(); page.wait_for_timeout(900)

    a2 = page.evaluate(ALIGN)
    print("\n  WITH A SCRIPT ON IT")
    print(f"    distinct left edges for inputs: {a2.get('distinctLeftEdges')}")
    for x, labels in (a2.get("edges") or {}).items():
        print(f"      x={x}: {labels}")
    print(f"    labels that wrap: {a2.get('labelsThatWrap')}")
    print(f"    page scrolls: {a2.get('pageScrolls')}")
    page.screenshot(path=str(SHOT / "dark-loaded.png"))
    b.close()
print(f"\n  {SHOT}")
