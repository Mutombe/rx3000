# -*- coding: utf-8 -*-
"""Nothing paints a square corner inside a round one.

WHAT WAS REPORTED

"When you are in an activated state of the RX-Assistant page, there's an inner
design that has sharp corners, and then there's a design behind it that has
rounded corners... Our design system right now should be supporting rounded
corners because that's the overall system. Find every other instance."

It was right, and it was two elements deep. The assistant's own ground painted
four square corners inside the card's 12px ones; rounding that exposed its
composer bar doing the same thing one level down, on all forty-eight screens
the dock appears on. Both are `border-radius: inherit` now — the corner is
taken from whatever box it sits in, so it follows the page card at 12px and the
dock at 14px without either being restated.

WHAT COUNTS AS A MISMATCH

Only a corner somebody can see. An element qualifies if it PAINTS — a
background, a border, a shadow — and sits within three pixels of a corner of a
parent that also paints, with a smaller radius there than the parent has. An
element with no ground of its own has no corner to be square.

Two exemptions, both sound:

  the parent clips    `overflow: hidden` rounds every child for free, so the
                      child's own radius is not what anybody sees.
  the parent is bare  a transparent parent draws no curve for a child to
                      disagree with.

WHAT IT DOES NOT COVER

Overlays that only exist once something is clicked. Two were opened by hand
while this was written and both were clean, but a modal nobody opens is a modal
this does not measure. The chrome — rail, top bar, toasts — is excluded because
it is not a component anybody composes with.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "http://localhost:5173"
API = "http://127.0.0.1:8000"

# Under this and it is a rounding difference rather than a square inside a
# curve. Three pixels is below what an eye picks up at a corner.
SLACK = 3

ROUTES = [
    "/", "/assistant", "/patients", "/scripts", "/dispensing-history",
    "/to-follows", "/will-call", "/repeats", "/stock", "/orders", "/suppliers",
    "/deliveries", "/drivers", "/register", "/laybys", "/claiming",
    "/claims-held", "/authorisations", "/payables", "/ledger", "/periods",
    "/fiscal", "/shifts", "/helpdesk", "/accounts", "/pipeline", "/marketing",
    "/reminders", "/branches", "/pharmacies", "/head-office", "/admin",
    "/stock-take", "/rfqs", "/samples", "/recall", "/compounding",
    "/remittances", "/money-owed", "/compliance", "/leads", "/scorecard",
    "/reconciliation", "/stock-performance", "/seasons", "/crm-reports",
    "/system", "/dispensary/operations", "/stock-categories", "/pos",
]

PROBE = r"""
(slack) => {
  const CORNERS = [
    ["borderTopLeftRadius", "top-left"],
    ["borderTopRightRadius", "top-right"],
    ["borderBottomRightRadius", "bottom-right"],
    ["borderBottomLeftRadius", "bottom-left"],
  ];
  const paints = (s) => {
    const bg = s.backgroundColor;
    const solid = bg && bg !== "transparent"
      && !/rgba\(\s*0,\s*0,\s*0,\s*0\s*\)/.test(bg);
    const bordered = ["borderTopWidth", "borderRightWidth",
                      "borderBottomWidth", "borderLeftWidth"]
      .some((k) => parseFloat(s[k]) > 0);
    return solid || bordered || (s.boxShadow && s.boxShadow !== "none");
  };
  const out = [], seen = new Set();
  for (const el of document.querySelectorAll("body *")) {
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none") continue;
    if (!paints(s)) continue;
    if (el.closest(".rail, .sidebar, .topbar, .toasts")) continue;
    const par = el.parentElement;
    if (!par) continue;
    const ps = getComputedStyle(par);
    if (ps.overflow === "hidden" || ps.overflowX === "hidden") continue;
    if (!paints(ps)) continue;
    const pr = par.getBoundingClientRect();
    const NEAR = 3;
    const at = [
      Math.abs(r.left - pr.left) < NEAR && Math.abs(r.top - pr.top) < NEAR,
      Math.abs(r.right - pr.right) < NEAR && Math.abs(r.top - pr.top) < NEAR,
      Math.abs(r.right - pr.right) < NEAR && Math.abs(r.bottom - pr.bottom) < NEAR,
      Math.abs(r.left - pr.left) < NEAR && Math.abs(r.bottom - pr.bottom) < NEAR,
    ];
    for (let i = 0; i < 4; i++) {
      if (!at[i]) continue;
      const [key, name] = CORNERS[i];
      const mine = parseFloat(s[key]) || 0;
      const theirs = parseFloat(ps[key]) || 0;
      if (theirs - mine < slack) continue;
      const id = (el.className || el.tagName) + "|"
               + (par.className || par.tagName) + "|" + name;
      if (seen.has(id)) continue;
      seen.add(id);
      out.push({
        el: (el.className || el.tagName).toString().slice(0, 36),
        parent: (par.className || par.tagName).toString().slice(0, 28),
        corner: name, mine, theirs,
      });
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


def look(routes):
    from playwright.sync_api import sync_playwright
    found, read = {}, set()
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
                key = (r["el"], r["parent"], r["corner"], r["mine"], r["theirs"])
                found.setdefault(key, set()).add(route)
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
        print(f"\nok  {len(read)} screen(s): nothing paints a square corner "
              f"inside a rounded one")
        return 0
    print(f"\nFAIL  {len(found)} square corner(s) inside a rounded one\n")
    for (el, parent, corner, mine, theirs), where in sorted(
            found.items(), key=lambda kv: -len(kv[1])):
        print(f"  {el:<36} in {parent:<26} {corner:<13} "
              f"{mine:.0f}px inside {theirs:.0f}px")
        print(f"      on {len(where)} screen(s): {', '.join(sorted(where)[:5])}"
              + (f" (+{len(where) - 5})" if len(where) > 5 else ""))
    print("\n  `border-radius: inherit` takes the corner from the box it sits")
    print("  in, which is usually what was meant and never goes stale.")
    return 1


def plant() -> int:
    """Prove it by squaring a corner off."""
    sheet = ROOT / "frontend" / "src" / "styles.css"
    original = sheet.read_text(encoding="utf-8")
    fault = original + (
        "\n/* planted by a-corner-follows-the-corner-it-sits-in.py --plant */\n"
        ".ax-ask { border-bottom-left-radius: 0; border-bottom-right-radius: 0; }\n")
    import time
    try:
        sheet.write_text(fault, encoding="utf-8")
        # Long enough for vite to rebuild a 14,000-line stylesheet on a
        # machine that is already busy. At four seconds this plant passed
        # on a quiet machine and reported a false all-clear on a loaded one.
        time.sleep(9)
        found, _ = look(["/assistant", "/patients"])
        if not found:
            print("FAIL  a corner was squared off and this said nothing")
            return 1
        (el, parent, corner, mine, theirs), where = next(iter(found.items()))
        print(f"ok  planted fault caught: {el} in {parent}, {corner}, "
              f"{mine:.0f}px inside {theirs:.0f}px")
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
