"""The dispensary flow, end to end, in a real browser.

Measures what the change claims, not what it renders:

  the columns are single unbroken rules, from the headings to the floor;
  deleting the last line takes the totals row with it;
  the shield checks on the first press and opens the detail on the second;
  the pencil opens the editor, the bin deletes;
  Escape closes a dialog without clearing the script behind it;
  Escape on the direction-code list does not close the editor it is in;
  Finish opens with payment in it and Dispense on screen;
  and nothing on the page scrolls, at a laptop size and a till size.

Run against a local preview: python dispensary_flow.py [screenshot-dir]
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


# A column is unbroken when, for every pair of consecutive rows, its cell in the
# lower row starts where the one above ends (allowing the 1–2px of the row rule
# between them) at the same x, with a solid left border.
RULES_JS = """() => {
  const grid = document.querySelector('.disp-grid');
  const g = grid.getBoundingClientRect();
  const foot = grid.querySelector('.st-foot');
  const floor = foot ? foot.getBoundingClientRect().top : g.bottom - 1;
  // Only what is on show: the waiting rows past the floor are clipped by design.
  const rows = [...grid.querySelectorAll('.rx-item-cols, .rx-item > .rx-item-head')]
    .filter((r) => r.getBoundingClientRect().top < floor - 1);
  const broken = [];
  for (let c = 1; c < 6; c++) {
    for (let r = 0; r + 1 < rows.length; r++) {
      const a = rows[r].children[c], b = rows[r + 1].children[c];
      if (!a || !b) { broken.push(`row ${r} col ${c} missing`); continue; }
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const gap = rb.top - ra.bottom;
      if (gap > 2.5 || Math.abs(ra.left - rb.left) > 1)
        broken.push(`col ${c} rows ${r}/${r + 1}: gap ${gap.toFixed(1)} dx ${(rb.left - ra.left).toFixed(1)}`);
      const st = getComputedStyle(a);
      if (st.borderLeftStyle !== 'solid' || parseFloat(st.borderLeftWidth) < 1)
        broken.push(`col ${c} row ${r}: border ${st.borderLeftStyle} ${st.borderLeftWidth}`);
    }
  }
  const last = rows[rows.length - 1].getBoundingClientRect();
  // Reaching the floor, or running under it and being clipped there, both count.
  // A table that has to scroll to show rows with nothing in them does not.
  const scrolls = grid.scrollHeight > grid.clientHeight + 1;
  return { rows: rows.length, broken: broken.slice(0, 6),
           toFloor: Math.round(Math.max(0, floor - last.bottom)) + (scrolls ? 999 : 0) };
}"""

SCROLLS_JS = "() => document.documentElement.scrollHeight > window.innerHeight + 2"
LINES = ".disp-grid > .rx-item:not(.rx-item-waiting)"


def line_count(page):
    return len(page.query_selector_all(LINES))


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for w, h in ((1512, 900), (1366, 768)):
        print(f"\n  {w}x{h}")
        page = browser.new_page(viewport={"width": w, "height": h}, color_scheme="dark")
        page.goto(BASE, wait_until="networkidle")
        page.fill("#lg-user", "admin")
        page.fill("#lg-pass", "admin123")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_timeout(2200)
        page.goto(BASE + "/dispense", wait_until="networkidle")
        page.wait_for_timeout(1500)
        shots = SHOT is not None and w == 1512

        # ---- empty ----------------------------------------------------------
        m = page.evaluate(RULES_JS)
        check("empty: columns are unbroken rules", not m["broken"], "; ".join(m["broken"]))
        check("empty: the rules reach the floor of the table", abs(m["toFloor"]) <= 2,
              f"{m['toFloor']}px short")
        check("empty: no totals row", page.query_selector(".st-foot") is None)
        heads = page.evaluate(
            "[...document.querySelectorAll('.rx-item-cols > *')].map(e => e.textContent.trim()).join('|')")
        check("empty: the headings end in Action",
              heads == "Medicine|Qty|Directions|Amount|Margin|Action", heads)
        check("empty: the page does not scroll", not page.evaluate(SCROLLS_JS))
        if shots:
            page.screenshot(path=str(SHOT / "flow-empty.png"))

        # ---- a patient, a prescriber, two medicines ---------------------------
        page.fill("[data-hk='patient']", "Andela")   # the box searches from two letters
        page.wait_for_timeout(1500)
        picks = page.query_selector_all("#step-patient .product-pick")
        if picks:
            picks[0].click()
            page.wait_for_timeout(1200)
        page.click(".disp-doctor .sel-trigger")
        page.wait_for_timeout(400)
        opts = [o for o in page.query_selector_all(
                    ".sel-panel [role='option'], .sel-list > div:not(.sel-group):not(.sel-empty)")
                if "Select doctor" not in (o.text_content() or "")]
        if opts:
            opts[0].click()
            page.wait_for_timeout(400)
        else:
            page.keyboard.press("Escape")
        check("a patient and a prescriber are chosen", bool(picks) and bool(opts),
              f"patients {len(picks)}, doctors {len(opts)}")

        # Picking a patient must not take the screen from the table.
        lane = page.evaluate("""() => {
          const lane = document.querySelector('.sec-patient').getBoundingClientRect();
          const who = document.querySelector('.disp-patient-picked')?.getBoundingClientRect();
          const doc = document.querySelector('.disp-doctor').getBoundingClientRect();
          return { lane: Math.round(lane.height),
                   overlap: !!who && who.right > doc.left + 1,
                   grid: Math.round(document.querySelector('.disp-grid').getBoundingClientRect().height) };
        }""")
        check("with a patient: the lane stays slim", lane["lane"] <= 110, f"{lane['lane']}px")
        check("with a patient: the name does not run into the prescriber", not lane["overlap"])
        check("with a patient: the table keeps the screen",
              lane["grid"] >= (320 if w == 1512 else 220), f"{lane['grid']}px")
        chip = page.query_selector(".rd-chip")
        if chip:
            chip.click()
            page.wait_for_timeout(900)
            check("the repeats chip opens the list", page.query_selector(".disp-lane-modal .rd-list") is not None)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            check("Escape closes it", page.query_selector(".disp-lane-modal") is None)
        else:
            print("  --    no repeats due for this patient; chip not exercised")
        if shots:
            page.screenshot(path=str(SHOT / "flow-patient.png"))

        for term in ("amox", "metfor"):
            page.fill("[data-hk='product']", term)
            page.wait_for_timeout(1500)
            hits = page.query_selector_all("#step-items .product-pick")
            if not hits:
                continue
            hits[0].click()
            page.wait_for_timeout(900)
            check(f"adding {term} opens its editor", page.query_selector(".disp-edit .ed-body") is not None)
            page.click(".disp-edit .disp-edit-actions .btn.primary")
            page.wait_for_timeout(500)
        check("two lines on the script", line_count(page) == 2, str(line_count(page)))
        page.wait_for_timeout(1500)
        check("the totals row sits under the lines", page.query_selector(".disp-grid > .st-foot") is not None)
        m = page.evaluate(RULES_JS)
        check("with lines: columns are unbroken rules", not m["broken"], "; ".join(m["broken"]))
        check("with lines: every line carries three action icons", page.evaluate(
            f"[...document.querySelectorAll('{LINES}')].every(r => r.querySelectorAll('.rx-icon').length === 3)"))
        check("with lines: the page does not scroll", not page.evaluate(SCROLLS_JS))
        check("the bar's sentence is readable", page.evaluate(
            "(() => { const s = document.querySelector('.disp-status > p > span, .disp-status > .disp-say > span');"
            " return !s || s.getBoundingClientRect().width > 40; })()"))
        check("the bar's pieces do not overlap", page.evaluate(
            "(() => { const r = [...document.querySelectorAll('.disp-status > *')]"
            ".map((x) => x.getBoundingClientRect()).filter((b) => b.width > 0);"
            " for (let i = 1; i < r.length; i++) if (r[i].left < r[i - 1].right - 1) return false;"
            " return true; })()"))
        check("with a patient: the name is not cut off", page.evaluate(
            "(() => { const b = document.querySelector('.dpp-who b'); if (!b) return true;"
            " const w = document.querySelector('.dpp-who').getBoundingClientRect();"
            " return b.getBoundingClientRect().right <= w.right + 1; })()"))
        if shots:
            page.screenshot(path=str(SHOT / "flow-lines.png"))

        # ---- the shield ---------------------------------------------------------
        shield = f"{LINES} .rx-icon:first-child"
        check("the shield starts unchecked", "chk-idle" in (page.get_attribute(shield, "class") or ""))
        page.click(shield)
        try:
            page.wait_for_selector(
                f"{LINES} .rx-icon:first-child:is(.chk-clean, .chk-minor, .chk-major, .chk-error)",
                timeout=8000)
        except Exception:
            pass
        cls = page.get_attribute(shield, "class") or ""
        check("pressed once, it checks and shows the answer",
              "chk-idle" not in cls and "chk-loading" not in cls, cls)
        check("…without opening anything", page.query_selector(".disp-check") is None)
        page.click(shield)
        page.wait_for_timeout(500)
        check("pressed on the answer, it opens the detail", page.query_selector(".disp-check") is not None)
        if shots:
            page.screenshot(path=str(SHOT / "flow-check.png"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check("Escape closes the check", page.query_selector(".disp-check") is None)
        check("…and leaves the script alone", line_count(page) == 2, str(line_count(page)))

        # ---- the pencil -----------------------------------------------------------
        page.click(f"{LINES} .rx-icon[title='Edit this line']")
        page.wait_for_timeout(500)
        check("the pencil opens the editor, with its side rail", page.query_selector(".disp-edit .ed-rail") is not None)
        check("the editor shows characters, not escape codes", not page.evaluate(
            r"document.querySelector('.disp-edit').innerText.includes('\\u')"))
        box = page.query_selector(".disp-edit .ed-main .ed-sec:nth-of-type(2) input")
        if box:
            box.click()
            box.type("1")
            page.wait_for_timeout(600)
            if page.query_selector(".disp-edit [role='listbox']"):
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                check("Escape on the code list keeps the editor open", page.query_selector(".disp-edit") is not None)
            else:
                print("  --    no code list appeared for '1'; Escape-on-list not exercised")
            if page.query_selector(".disp-edit"):
                page.fill(".disp-edit .ed-main .ed-sec:nth-of-type(2) input", "")
        if shots and page.query_selector(".disp-edit"):
            page.screenshot(path=str(SHOT / "flow-edit.png"))
        if page.query_selector(".disp-edit"):
            page.click(".disp-edit .disp-edit-actions .btn.primary")
            page.wait_for_timeout(300)
        check("Done closes the editor", page.query_selector(".disp-edit") is None)

        # ---- Finish ---------------------------------------------------------------
        page.click(".disp-bar .disp-go")
        page.wait_for_timeout(700)
        check("Finish opens the finish dialog", page.query_selector(".disp-finish") is not None)
        if page.query_selector(".disp-finish"):
            check("…with payment in it", page.query_selector(".disp-finish #finish-pay .seg") is not None)
            check("…and Dispense in its foot", page.query_selector(".finish-foot .printmenu-main") is not None)
            check("Finish shows characters, not escape codes", not page.evaluate(
                r"document.querySelector('.disp-finish').innerText.includes('\\u')"))
            check("…with the foot on screen", page.evaluate(
                "(() => { const f = document.querySelector('.finish-foot').getBoundingClientRect();"
                " return f.top >= 0 && f.bottom <= window.innerHeight + 1; })()"))
            if shots:
                page.screenshot(path=str(SHOT / "flow-finish.png"))
            page.click(".finish-foot .btn.secondary")
            page.wait_for_timeout(300)
            check("Back to the script closes it", page.query_selector(".disp-finish") is None)
        page.keyboard.press("F12")
        page.wait_for_timeout(600)
        check("F12 opens Finish", page.query_selector(".disp-finish") is not None)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check("Escape closes Finish without clearing the script",
              page.query_selector(".disp-finish") is None and line_count(page) == 2,
              f"open={page.query_selector('.disp-finish') is not None} lines={line_count(page)}")

        # ---- the bin --------------------------------------------------------------
        for _ in range(2):
            if line_count(page):
                page.click(f"{LINES} .rx-icon.is-remove")
                page.wait_for_timeout(500)
        check("the bin deletes both lines", line_count(page) == 0, str(line_count(page)))
        page.wait_for_timeout(800)
        check("deleting the last line takes the totals row with it", page.query_selector(".st-foot") is None)
        m = page.evaluate(RULES_JS)
        check("after deleting: the rules are unbroken to the floor",
              not m["broken"] and abs(m["toFloor"]) <= 2, f"{m['broken']} {m['toFloor']}")
        check("after deleting: the page does not scroll", not page.evaluate(SCROLLS_JS))
        page.close()
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
