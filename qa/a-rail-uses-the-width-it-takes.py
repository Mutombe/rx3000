# -*- coding: utf-8 -*-
"""A strip of controls either fills the width it takes, or takes less of it.

WHAT WAS REPORTED

"In the suppliers there's a top field for search and immediately beside it is a
Show Retired button. I think the positioning was supposed to be at the far
right. These buttons are just displayed randomly in the middle or very close to
the search. If we only have two operations there, they have to be spaced. One
has to go to the far right and one to the far left, or they have to be divided
into that space that they have. Find every other instance and fix it."

Measured, the complaint was exact and it had two causes stacked on each other.

  The rail drew a metre of border.   Suppliers' rail was 1148px wide and its
                                     controls stopped at 462px, so 686px of it
                                     was an empty bordered box. Patients wasted
                                     807px, the register 643px.

  A pre-unification rule capped the  `.toolbar input[type="search"]
  one control that should grow.       { max-width: 340px }` survived the move to
                                     the shared rail. The unified rule was
                                     saying `flex: 1 1 18rem` and the cap was
                                     beating it, which is why the field stopped
                                     dead beside the button instead of pushing
                                     it to the far right.

The `.dt-filters` rails were already right, which is what made this worth
measuring rather than reading: the fault was only ever on the pages that drop a
bare `<input type="search">` into a `.toolbar`.

Widening the same measurement past the rails found it a second time, in a place
nobody had complained about yet. The tab strips — `.pill-tabs` and
`.section-nav` — drew a sunk, bordered trough the full width of the page around
tabs that ended a quarter of the way along it: lay-bys 271px of 1,190, the
compliance nav 248px, twenty-two strips across the product. A segmented control
is one object you choose a side of, and a trough with the object in one corner
reads as a bar that failed to fill. Both are the size of their tabs now, and
`.pill-tabs` still goes full width and scrolls the moment its tabs outgrow the
page.

WHAT THE RULE IS

A strip of controls is one instrument. Its controls must reach its right edge,
and if there are not enough controls to reach it, the strip is the wrong width
and should shrink to what it holds. Either way the distance from the last
control to the strip's own right edge is small. Forty pixels is the allowance:
it covers the padding drawn inside the border and the odd pixel of flex
rounding, and it is well under the 686px that started this.

A strip that wraps to a second row still passes on its first row, which is
correct — the second row is a continuation, not dead space. A strip that
scrolls passes too: its children run past its right edge rather than short of
it.

WHAT IT DOES NOT COVER

Strips that only exist behind a tab or inside a modal, and strips narrower than
100px, which are decorations rather than instruments.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "http://localhost:5173"
API = "http://127.0.0.1:8000"

# Padding plus flex rounding. Anything past this is a gap somebody can see.
SLACK = 40

ROUTES = [
    "/suppliers", "/patients", "/scripts", "/dispensing-history", "/stock",
    "/orders", "/deliveries", "/drivers", "/register", "/laybys", "/claiming",
    "/claims-held", "/authorisations", "/payables", "/ledger", "/helpdesk",
    "/accounts", "/marketing", "/reminders", "/branches", "/pharmacies",
    "/rfqs", "/samples", "/recall", "/compounding", "/remittances",
    "/money-owed", "/compliance", "/leads", "/to-follows", "/will-call",
    "/repeats", "/stock-take", "/periods", "/fiscal", "/shifts",
    "/settlements", "/head-office", "/reconciliation", "/stock-performance",
    "/seasons", "/crm-reports", "/pipeline",
]

PROBE = r"""
(slack) => {
  const out = [];
  for (const bar of document.querySelectorAll(
      "main .filter-bar, main .dt-filters, main .toolbar," +
      "main .pill-tabs, main .section-nav")) {
    const r = bar.getBoundingClientRect();
    if (r.width < 100 || !bar.offsetParent) continue;
    const kids = [...bar.children]
      .map((c) => {
        const k = c.getBoundingClientRect();
        return {
          cls: (c.className || c.tagName).toString().slice(0, 26),
          right: Math.round(k.right - r.left),
          w: Math.round(k.width),
          said: (c.textContent || c.getAttribute("placeholder") || "")
                  .trim().slice(0, 24),
        };
      })
      .filter((k) => k.w > 0);
    if (!kids.length) continue;
    const used = Math.max(...kids.map((k) => k.right));
    const spare = Math.round(r.width) - used;
    if (spare <= slack) continue;
    const last = kids.reduce((a, b) => (b.right > a.right ? b : a));
    out.push({
      cls: (bar.className || "").toString().slice(0, 22),
      w: Math.round(r.width), used, spare,
      last: last.cls, said: last.said, n: kids.length,
    });
  }
  return out;
}
"""


def token() -> str:
    req = urllib.request.Request(API + "/api/auth/login", method="POST")
    req.add_header("Content-Type", "application/json")
    body = json.dumps({"username": "admin", "password": "admin123"}).encode()
    with urllib.request.urlopen(req, body, timeout=60) as f:
        return json.loads(f.read())["access_token"]


def look(routes):
    from playwright.sync_api import sync_playwright
    found, read = [], set()
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
        p.goto(BASE, wait_until="networkidle")
        p.fill("#lg-user", "admin")
        p.fill("#lg-pass", "admin123")
        p.get_by_role("button", name="Sign in").click()
        p.wait_for_timeout(3000)
        for route in routes:
            try:
                p.goto(BASE + route, wait_until="networkidle")
                p.wait_for_timeout(1700)
                rows = p.evaluate(PROBE, SLACK)
                read.add(route)
            except Exception as e:
                print(f"  ..  {route}: could not be read ({repr(e)[:45]})")
                continue
            for r in rows:
                found.append((route, r))
        b.close()
    return found, read


def report(routes) -> int:
    found, read = look(routes)
    missed = [r for r in routes if r not in read]
    if len(missed) > len(routes) // 3:
        print(f"\nFAIL  only {len(read)} of {len(routes)} screen(s) could be read. "
              f"That is not a pass, it is a sweep that did not run.")
        return 1
    if not found:
        print(f"\nok  {len(read)} screen(s): every rail and tab strip reaches "
              f"its own right edge")
        return 0
    print(f"\nFAIL  {len(found)} strip(s) drawing a border around empty space\n")
    for route, r in sorted(found, key=lambda x: -x[1]["spare"]):
        print(f"  {route:<22} [{r['cls']}] {r['w']}px wide, {r['used']}px used, "
              f"{r['spare']}px of it empty")
        print(f"      {r['n']} control(s); the last one ends at {r['used']}px: "
              f"{r['last']} {r['said']!r}")
    print("\n  Either a control grows into the gap, or the rail stops where its")
    print("  controls do. A bordered box with a third of it empty reads as")
    print("  something that was dropped in rather than placed.")
    return 1


#: Each is (what it breaks, the CSS that breaks it, where to look for it).
PLANTS = [
    ("the 340px cap on a rail search is back",
     '.toolbar input[type="search"] { max-width: 340px; }',
     ["/suppliers", "/patients"]),
    ("a tab strip is the width of the page again",
     ".pill-tabs, .section-nav { width: auto; }",
     ["/laybys", "/compliance"]),
]


def plant() -> int:
    """Prove it by putting each fault back, one at a time."""
    import time
    sheet = ROOT / "frontend" / "src" / "styles.css"
    original = sheet.read_text(encoding="utf-8")
    bad = 0
    try:
        for said, css, where in PLANTS:
            sheet.write_text(
                original + "\n/* planted by a-rail-uses-the-width-it-takes.py "
                           "--plant */\n" + css + "\n", encoding="utf-8")
            # Long enough for vite to notice a 14,000-line stylesheet changed
            # and re-transform it. Nine seconds reported a false all-clear
            # once, on a machine that had just finished a full sweep; the same
            # plant measured by hand a minute later was plainly there.
            # Fourteen is the margin.
            time.sleep(14)
            found, _ = look(where)
            if not found:
                print(f"FAIL  {said} and this said nothing")
                bad += 1
                continue
            route, r = max(found, key=lambda x: x[1]["spare"])
            print(f"ok  caught: {said}. {route} strip {r['w']}px wide with "
                  f"{r['spare']}px of it empty")
        return 1 if bad else 0
    finally:
        sheet.write_text(original, encoding="utf-8")
        time.sleep(3)


def alive() -> bool:
    try:
        urllib.request.urlopen(BASE, timeout=5).read(1)
        token()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    if not alive():
        print("The dev server and API have to be up for this one.")
        print(f"  {BASE} and {API}")
        sys.exit(2)
    sys.exit(plant() if "--plant" in sys.argv else report(ROUTES))
