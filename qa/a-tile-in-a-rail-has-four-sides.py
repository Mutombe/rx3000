# -*- coding: utf-8 -*-
"""A tile drawn as its own box is drawn as a whole box.

WHAT WAS REPORTED, TWICE

The dispensary worklist's chosen tile, "Waiting", read as cut off down its left
edge against the rail. It was fixed once by giving the rail room to show the
tile had risen out of it, which was not the fault, and it came back.

WHAT IT ACTUALLY WAS

Everywhere in this product these figure tiles are one bordered strip divided by
hairlines, and the tiles inside it draw nothing of their own. The strip reset
says so, and ends with the rule that makes a strip a strip:

    .wl-stats.wl-stats > :first-child { border-left: none; }

Without it the first tile's left border doubles the container's. With it, in a
rail that has turned the container's border OFF and given each tile a box of
its own, the first tile is drawn with three sides. At one class each plus a
pseudo-class that rule outscored the rail's own, so it won.

The first tile is "Waiting", which is also the one chosen when the screen
opens. So the single tile carrying the accent ring was the one tile missing a
side of it.

WHAT THIS MEASURES

Not the selector, which is the cause. The effect, and as a question the markup
answers about itself: in a strip that draws no border of its own, every tile is
a box in its own right, so the tiles must agree with each other about how many
sides they have. A tile with three sides beside two tiles with four is the
fault however it got there, and on whichever screen it turns up next.

Where the strip DOES draw its own border the tiles are dividers rather than
boxes and the first one having no left rule is correct, so those are skipped
rather than reported.
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "http://localhost:5173"
API = "http://127.0.0.1:8000"

#: Screens carrying one of these strips. The dispensary is the one that was
#: reported; the rest are here because the rule that broke it is shared by
#: every strip in the file and would break them the same way.
ROUTES = ["/dispense", "/", "/stock-performance", "/patients", "/insights",
          "/will-call", "/orders"]

PROBE = r"""
() => {
  const out = [];
  const strips = document.querySelectorAll(
    ".wl-stats, .ins-figures, .fin-stats, .st-figures, .bp-figures");
  for (const strip of strips) {
    if (!strip.offsetParent) continue;
    const ss = getComputedStyle(strip);
    /* A strip that draws its own box: its tiles are dividers, and the first
       one having no left rule is the whole point. Not this guard's question. */
    const own = parseFloat(ss.borderLeftWidth) || 0;
    if (own > 0) continue;
    const tiles = [...strip.children].filter((t) => t.offsetParent);
    if (tiles.length < 2) continue;
    const sides = tiles.map((t) => {
      const s = getComputedStyle(t);
      return {
        l: Math.round(parseFloat(s.borderLeftWidth) || 0),
        r: Math.round(parseFloat(s.borderRightWidth) || 0),
        t: Math.round(parseFloat(s.borderTopWidth) || 0),
        b: Math.round(parseFloat(s.borderBottomWidth) || 0),
        cls: (t.className || "").toString().slice(0, 24),
        said: (t.textContent || "").trim().replace(/\s+/g, " ").slice(0, 18),
      };
    });
    /* The widest agreement among the tiles is what a tile is meant to look
       like. Anything narrower on any side is a missing side, not a style. */
    const most = { l: Math.max(...sides.map(s => s.l)),
                   r: Math.max(...sides.map(s => s.r)),
                   t: Math.max(...sides.map(s => s.t)),
                   b: Math.max(...sides.map(s => s.b)) };
    if (!(most.l || most.r || most.t || most.b)) continue;   // no tile boxes
    for (const s of sides) {
      const short = ["l", "r", "t", "b"].filter((k) => s[k] < most[k]);
      if (short.length) {
        out.push({ strip: (strip.className || "").toString().slice(0, 22),
                   tile: s.cls, said: s.said,
                   missing: short.join(" and "),
                   has: [s.l, s.t, s.r, s.b].join("/"),
                   want: [most.l, most.t, most.r, most.b].join("/") });
      }
    }
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


def look():
    from playwright.sync_api import sync_playwright
    found, read = {}, set()
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page(viewport={"width": 1512, "height": 950},
                       color_scheme="dark")
        p.goto(BASE, wait_until="networkidle")
        p.fill("#lg-user", "admin")
        p.fill("#lg-pass", "admin123")
        p.get_by_role("button", name="Sign in").click()
        p.wait_for_timeout(3000)
        for route in ROUTES:
            try:
                p.goto(BASE + route, wait_until="networkidle")
                p.wait_for_timeout(2500)
                rows = p.evaluate(PROBE)
                read.add(route)
            except Exception as e:
                print(f"  ..  {route}: could not be read ({repr(e)[:45]})")
                continue
            if rows:
                found[route] = rows
        b.close()
    return found, read


def report() -> int:
    found, read = look()
    if not found:
        print(f"\nok  {len(read)} screen(s): every tile drawn as its own box "
              f"is drawn with all four sides")
        return 0
    print(f"\nFAIL  {sum(len(v) for v in found.values())} tile(s) short of a "
          f"side\n")
    for route, rows in found.items():
        for r in rows:
            print(f"  {route:<20} {r['tile']}  {r['said']!r}")
            print(f"{'':22}no {r['missing']} border; has {r['has']} where its "
                  f"neighbours have {r['want']} (left/top/right/bottom)")
    print("\n  A strip that draws no border of its own is not a strip, and its")
    print("  tiles are boxes rather than dividers. Every one of them, equally.")
    return 1


def plant() -> int:
    """Let the strip's first-child reset reach the rail again."""
    import time
    sheet = ROOT / "frontend" / "src" / "styles.css"
    original = sheet.read_text(encoding="utf-8")
    fault = original + (
        "\n/* planted by a-tile-in-a-rail-has-four-sides.py */\n"
        ".wl-stats.wl-stats.wl-stats > :first-child { border-left: none; }\n")
    try:
        sheet.write_text(fault, encoding="utf-8")
        time.sleep(14)
        found, _ = look()
        if not found:
            print("FAIL  the first tile lost its left edge and this said "
                  "nothing")
            return 1
        route, rows = next(iter(found.items()))
        print(f"ok  planted fault caught: {route} draws {rows[0]['said']!r} "
              f"with no {rows[0]['missing']} border")
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
        sys.exit(2)
    sys.exit(plant() if "--plant" in sys.argv else report())
