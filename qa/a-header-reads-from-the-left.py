# -*- coding: utf-8 -*-
"""A page's name starts at the left edge of its header, like every other page.

WHAT WAS REPORTED

"On some detail pages the information in the header is displayed to the far
right instead of normally. Some stuff goes left and some right, like in other
headers, but this one is just picking header information and putting it far
right. It is happening in claims, in creditor detail pages, and I think
remittances as well."

WHAT IT WAS

One selector, and a precise one:

    .page-head .page-actions,
    .page-head > div:last-child { justify-content: flex-end; ... }

The second arm is a fallback for headers written by hand, which put their
buttons in a bare `<div>` rather than in `.page-actions`. On a record page with
NO buttons there is only the identity block, so it was both the first child and
the last, and the rule meant for the buttons turned the record's type, its name
and its subtitle into a right justified flex ROW. "MESSAGE Repeat due Munashe
Musarurwa" ran along one line and finished hard against the right edge.

That is why it appeared on exactly those pages and no others: they are the
record pages that carry no header buttons. Nothing was wrong with any of them.

WHAT THIS CHECKS

Not the selector, which is the cause and will be rewritten one day. The effect:
the first block in a header begins at its left edge, and is not laid out as a
row pushed to the end. A header whose identity half is a flex row justified to
the end is the fault however it got there.

The ids are resolved from the API at startup rather than written down, because
a record page that 404s falls through to the dashboard, and a dashboard header
is perfectly left aligned.
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

#: More than this from the left edge and the name is not where a reader looks
#: for it. Eight pixels covers a border and a rounding.
SLACK = 8

#: (list endpoint, the record route it fills in). Every record kind whose list
#: can be read in one call, so the sweep covers the shapes rather than a
#: hand-picked few.
KINDS = [
    ("/api/patients?limit=1", "/patients/{id}"),
    ("/api/products?limit=1", "/inventory/{id}"),
    ("/api/suppliers?limit=1", "/suppliers/{id}"),
    ("/api/prescriptions?limit=1", "/scripts/{id}"),
    ("/api/messages?limit=1", "/messages/{id}"),
    ("/api/payables/invoices?limit=1", "/payables/invoices/{id}"),
    ("/api/orders/list?limit=1", "/orders/{id}"),
    ("/api/waybills?limit=1", "/deliveries/{id}"),
    ("/api/staff?limit=1", "/staff/{id}"),
    ("/api/doctors?limit=1", "/prescribers/{id}"),
]

PROBE = r"""
(slack) => {
  const out = [];
  for (const head of document.querySelectorAll("main .page-head")) {
    const r = head.getBoundingClientRect();
    if (r.width < 200) continue;
    const first = head.firstElementChild;
    if (!first) continue;
    const k = first.getBoundingClientRect();
    const s = getComputedStyle(first);
    const pushed = s.display.includes("flex")
      && (s.justifyContent === "flex-end" || s.justifyContent === "right");
    const off = Math.round(k.left - r.left);
    if (off <= slack && !pushed) continue;
    out.push({
      cls: (first.className || first.tagName).toString().slice(0, 30),
      off, justify: s.justifyContent, display: s.display,
      said: (first.textContent || "").trim().replace(/\s+/g, " ").slice(0, 44),
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


def routes() -> list[str]:
    out, tok = [], token()
    for path, shape in KINDS:
        try:
            req = urllib.request.Request(API + path)
            req.add_header("Authorization", "Bearer " + tok)
            with urllib.request.urlopen(req, timeout=60) as f:
                body = json.loads(f.read())
            rows = body if isinstance(body, list) else (
                body.get("items") or body.get("rows") or [])
            if rows and isinstance(rows[0], dict) and rows[0].get("id"):
                out.append(shape.format(id=rows[0]["id"]))
        except Exception:
            continue
    return out


def look(paths):
    from playwright.sync_api import sync_playwright
    found, read = {}, set()
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page(viewport={"width": 1440, "height": 900},
                       color_scheme="light")
        p.goto(BASE, wait_until="networkidle")
        p.fill("#lg-user", "admin")
        p.fill("#lg-pass", "admin123")
        p.get_by_role("button", name="Sign in").click()
        p.wait_for_timeout(3000)
        for route in paths:
            try:
                p.goto(BASE + route, wait_until="networkidle")
                p.wait_for_timeout(1800)
                rows = p.evaluate(PROBE, SLACK)
                read.add(route)
            except Exception as e:
                print(f"  ..  {route}: could not be read ({repr(e)[:45]})")
                continue
            if rows:
                found[route] = rows
        b.close()
    return found, read


def report() -> int:
    paths = routes()
    if len(paths) < 4:
        print(f"FAIL  only {len(paths)} record route(s) could be resolved, so "
              f"this would be checking almost nothing.")
        return 1
    found, read = look(paths)
    if not found:
        print(f"\nok  {len(read)} record page(s): the name starts at the left "
              f"edge of the header")
        return 0
    print(f"\nFAIL  {len(found)} header(s) whose first block is not at the "
          f"left\n")
    for route, rows in found.items():
        for r in rows:
            print(f"  {route:<28} {r['cls']} at {r['off']}px, "
                  f"{r['display']} / {r['justify']}")
            print(f"        {r['said']!r}")
    print("\n  The identity half of a header is not an actions group. Only the")
    print("  buttons are pushed to the right edge.")
    return 1


def plant() -> int:
    """Prove it by letting a lone block be treated as an actions group again."""
    import time
    sheet = ROOT / "frontend" / "src" / "styles.css"
    original = sheet.read_text(encoding="utf-8")
    fault = original + (
        "\n/* planted by a-header-reads-from-the-left.py --plant */\n"
        ".page-head > div:last-child {\n"
        "  display: flex; justify-content: flex-end;\n}\n")
    try:
        sheet.write_text(fault, encoding="utf-8")
        time.sleep(14)
        # Against a record page with NO header buttons, which is the only
        # shape this fault can appear on: where there ARE buttons the last
        # child is the button group and pushing it right is correct, so
        # planting there proves nothing. The first attempt at this plant used
        # the first four routes, all of which have buttons, and reported that
        # the guard had missed a fault it was never shown.
        where = [r for r in routes()
                 if "/messages/" in r or "/payables/" in r] or routes()
        found, _ = look(where)
        if not found:
            print("FAIL  a header's name was pushed to the right edge and this "
                  "said nothing")
            return 1
        route, rows = next(iter(found.items()))
        print(f"ok  planted fault caught: {route} puts {rows[0]['cls']} at "
              f"{rows[0]['off']}px with justify {rows[0]['justify']}")
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
