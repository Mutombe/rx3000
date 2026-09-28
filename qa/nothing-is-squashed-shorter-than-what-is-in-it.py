# -*- coding: utf-8 -*-
"""Nothing is cut off because a flex row decided it was the part that gives way.

WHAT WAS REPORTED

"Why are these buttons sunk in like that", with a photograph of the dispensary
worklist: three rounded tops peeking out from under the WORKLIST heading and
nothing else of them.

They were not sunk in. They were SEVEN PIXELS TALL. `.wl-stats` is a strip of
three figures that wants forty six pixels, sitting in a flex column with a
height limit, and it had been shrunk to seven to make the list below it fit.
What showed was the top seven pixels of three forty six pixel tiles.

WHY IT COULD HAPPEN AT ALL, AND WHY IT IS SILENT

A flex item will not normally shrink below its own content: `min-height: auto`
is the default and it holds the floor. But `overflow` set to anything other
than `visible` replaces that floor with zero. The strip carried
`overflow: hidden` for an honest reason, to clip its children's corners to its
own radius, and in doing so it signed away its right to a minimum height.

Nothing about that produces an error, a scrollbar or a console line. The
element simply becomes shorter than the thing inside it and clips it, and the
only way to find it is to measure.

WHAT COUNTS

An element that clips vertically, whose content is meaningfully taller than the
box, and that offers no way to reach the rest: `overflow-y: hidden`, not
`auto` or `scroll`. A deliberate scroller is not this fault; a deliberate
one-line truncation (`text-overflow: ellipsis`, or `-webkit-line-clamp`) is not
either, and both are excluded by name rather than by guesswork.

Two more exclusions, both found by running this and reading what it caught.
Anything inside `aria-hidden="true"` is excluded, because an element that
declares it carries nothing a person needs loses nothing by being cut: the
dispensary draws twenty four ruled empty rows so the grid always reaches the
floor of the table, and the ones past the floor are supposed to go. And a
Leaflet map is excluded, because a map's tile pane is larger than the window
onto it by design and always will be.

Twelve pixels of slack. Below that it is a rounding difference or a descender,
not a control somebody cannot see.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "http://localhost:5173"
API = "http://127.0.0.1:8000"

#: Under this it is a descender or a rounded half pixel.
SLACK = 12

ROUTES = [
    "/", "/dispense", "/dispensary/operations", "/patients", "/scripts",
    "/dispensing-history", "/to-follows", "/will-call", "/repeats", "/stock",
    "/orders", "/suppliers", "/deliveries", "/drivers", "/register", "/laybys",
    "/claiming", "/claims-held", "/authorisations", "/payables", "/ledger",
    "/periods", "/fiscal", "/shifts", "/helpdesk", "/accounts", "/pipeline",
    "/marketing", "/reminders", "/branches", "/pharmacies", "/head-office",
    "/admin", "/stock-take", "/rfqs", "/samples", "/recall", "/compounding",
    "/remittances", "/money-owed", "/compliance", "/leads", "/scorecard",
    "/reconciliation", "/stock-performance", "/seasons", "/crm-reports",
    "/system", "/stock-categories", "/pos",
]

PROBE = r"""
(slack) => {
  const out = [], seen = new Set();
  for (const el of document.querySelectorAll("body *")) {
    const s = getComputedStyle(el);
    // Only a box that clips with no way to reach the rest. `auto` and
    // `scroll` are scrollers, and a scroller is doing its job.
    if (s.overflowY !== "hidden" && s.overflow !== "hidden") continue;
    if (s.display === "none" || s.visibility === "hidden") continue;
    // Truncation somebody asked for, on purpose, in one line.
    if (s.textOverflow === "ellipsis") continue;
    if (s.webkitLineClamp && s.webkitLineClamp !== "none") continue;
    // Decoration, by its own declaration. `aria-hidden` says this carries
    // nothing a person needs, so clipping it loses nothing. The dispensary's
    // ruled empty rows are exactly this: twenty four of them are drawn so the
    // grid always reaches the floor of the table, and the ones past the floor
    // are meant to be cut off.
    if (el.closest("[aria-hidden=true]")) continue;
    // A map pans. Its tile pane is deliberately larger than the window onto
    // it, and always will be.
    if (el.closest(".leaflet-container")) continue;
    const r = el.getBoundingClientRect();
    if (r.height < 4 || r.width < 4) continue;
    const over = el.scrollHeight - el.clientHeight;
    if (over <= slack) continue;
    // What is actually being cut, so the report names something findable.
    const tall = [...el.children]
      .map((c) => ({ c, h: Math.round(c.getBoundingClientRect().height) }))
      .sort((a, b) => b.h - a.h)[0];
    const id = (el.className || el.tagName).toString().slice(0, 40);
    if (seen.has(id)) continue;
    seen.add(id);
    out.push({
      el: id,
      h: Math.round(r.height), wants: el.scrollHeight, over,
      flex: s.flex,
      holds: tall
        ? ((tall.c.className || tall.c.tagName).toString().slice(0, 26)
           + " at " + tall.h + "px")
        : "text",
      said: (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 34),
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
    found, read = {}, set()
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        # The window a till opens at, which is where this was reported.
        p = b.new_page(viewport={"width": 1440, "height": 860},
                       color_scheme="light")
        p.goto(BASE, wait_until="networkidle")
        p.fill("#lg-user", "admin")
        p.fill("#lg-pass", "admin123")
        p.get_by_role("button", name="Sign in").click()
        p.wait_for_timeout(3000)
        for route in routes:
            try:
                p.goto(BASE + route, wait_until="networkidle")
                p.wait_for_timeout(1800)
                rows = p.evaluate(PROBE, SLACK)
                read.add(route)
            except Exception as e:
                print(f"  ..  {route}: could not be read ({repr(e)[:45]})")
                continue
            for r in rows:
                found.setdefault((r["el"], r["h"], r["wants"]), set()).add(route)
        b.close()
    return found, read


def report(routes) -> int:
    found, read = look(routes)
    if len(read) < len(routes) - len(routes) // 3:
        print(f"\nFAIL  only {len(read)} of {len(routes)} screen(s) could be "
              f"read. That is not a pass, it is a sweep that did not run.")
        return 1
    if not found:
        print(f"\nok  {len(read)} screen(s): nothing is clipping something "
              f"taller than itself")
        return 0
    print(f"\nFAIL  {len(found)} box(es) shorter than what is inside them\n")
    for (el, h, wants), where in sorted(found.items(),
                                        key=lambda kv: -(kv[0][2] - kv[0][1])):
        print(f"  {el:<40} {h}px tall around {wants}px of content")
        print(f"      on {len(where)} screen(s): {', '.join(sorted(where)[:4])}")
    print("\n  A flex item with `overflow` other than visible has no minimum")
    print("  height of its own, so the row is free to shrink it to nothing.")
    print("  If it is furniture rather than the scrolling part, say so with")
    print("  `flex: 0 0 auto`.")
    return 1


def plant() -> int:
    """Prove it by letting the worklist's figures give way again."""
    import time
    sheet = ROOT / "frontend" / "src" / "styles.css"
    original = sheet.read_text(encoding="utf-8")
    fault = original + (
        "\n/* planted by nothing-is-squashed-shorter-than-what-is-in-it.py */\n"
        ".disp-with-worklist .wl-stats {\n"
        "  overflow: hidden; flex: 0 1 auto; min-height: 0;\n}\n")
    try:
        sheet.write_text(fault, encoding="utf-8")
        # Vite needs a while to re-transform a stylesheet this size on a busy
        # machine; nine seconds has given a false all-clear before.
        time.sleep(14)
        found, _ = look(["/dispense"])
        if not found:
            print("FAIL  the worklist figures were allowed to collapse again "
                  "and this said nothing")
            return 1
        (el, h, wants), _ = next(iter(found.items()))
        print(f"ok  planted fault caught: {el} is {h}px around {wants}px")
        return 0
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
