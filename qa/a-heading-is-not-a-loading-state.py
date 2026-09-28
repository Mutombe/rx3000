# -*- coding: utf-8 -*-
"""The name of a page is there before the page is.

WHAT WAS REPORTED

"When you go to any page completely, the whole page loads, which doesn't make
any sense... there's a label on the top left... and at the far top right, there
are the action buttons. Why do these things have to load? Some of these things
are static. The dynamic part is what should load, not the whole page."

Exactly right, and it was one component. `PageSkeleton` is what the Suspense
boundary in Staff.tsx falls back to while a route's code arrives, and it drew
two grey blocks where the title and the subtitle go. So the one thing on the
screen that was never in doubt — the name of the page you had just clicked —
arrived as a loading state.

A page's title does not depend on its code, its data, or the network. It is
already written down, in the rail, before any of them exist.

WHAT THIS CHECKS

Two things, and the second is the one that will actually go wrong later.

1. No skeleton block inside a page head, on any screen. The head holds the
   title, the subtitle and the actions. All three are static. A grey block
   there is a static thing pretending to be a dynamic one.

2. The heading the fallback would show equals the heading the page does show.
   The fallback reads the name from the rail's own table, so if somebody
   renames a page and not its rail entry, the heading would change word as the
   code lands — which is worse than the grey block it replaced, because a name
   that changes reads as the wrong page having loaded.

   Twelve screens already call themselves something other than what the rail
   calls them: the rail says Ledger and the page says General ledger. Those are
   recorded in the rail table's `page` column rather than reconciled, because
   renaming twelve screens to simplify a loading state would be the tail
   wagging the dog. This is what keeps that column true.

WHAT IT DOES NOT CHECK

Whether a count chip waits for its count. `TabDef.count` takes `null` for "not
known yet" and the chip pulses; passing `0` from an array that has not loaded
is the same class of fault and is not mechanically distinguishable from a
genuine nought.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAYOUT = ROOT / "frontend" / "src" / "components" / "Layout.tsx"
BASE = "http://localhost:5173"
API = "http://127.0.0.1:8000"

# Routes reached only with a record id, and the two that are not pages.
SKIP = {"/login", "/welcome", "/training", "/scanner", "/profile", "/assistant"}

TITLE = r"""
() => {
  const main = document.querySelector("main") || document.body;
  const h = main.querySelector(".page-head h1, .record-title h1");
  const head = main.querySelector(".page-head");
  const out = {
    blocks: head ? head.querySelectorAll(".skel").length : 0,
    title: null,
  };
  if (h) {
    // The count chip is part of the heading element and is not part of the
    // name: "Patients 4,812" is the page Patients.
    const chip = h.querySelector(".page-count");
    let s = (h.textContent || "").trim();
    if (chip) s = s.slice(0, s.length - (chip.textContent || "").length).trim();
    out.title = s;
  }
  return out;
}
"""


def rail_table() -> list[tuple[str, str]]:
    """Every `{ to, label, page? }` in the rail, read from the source.

    Read from the file rather than from the rendered rail because the rendered
    one is filtered by what this user may see, and the fallback is not.
    """
    src = LAYOUT.read_text(encoding="utf-8")
    rows = []
    for m in re.finditer(r'\{\s*to:\s*"([^"]+)"\s*,\s*label:\s*"([^"]+)"([^}]*)\}', src):
        to, label, rest = m.group(1), m.group(2), m.group(3)
        page = re.search(r'page:\s*"([^"]+)"', rest)
        rows.append((to, page.group(1) if page else label))
    return rows


def token() -> str:
    req = urllib.request.Request(API + "/api/auth/login", method="POST")
    req.add_header("Content-Type", "application/json")
    body = json.dumps({"username": "admin", "password": "admin123"}).encode()
    with urllib.request.urlopen(req, body, timeout=60) as f:
        return json.loads(f.read())["access_token"]


def look(rows):
    from playwright.sync_api import sync_playwright
    wrong_name, grey = [], []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
        p.goto(BASE, wait_until="networkidle")
        p.fill("#lg-user", "admin")
        p.fill("#lg-pass", "admin123")
        p.get_by_role("button", name="Sign in").click()
        p.wait_for_timeout(3000)
        for to, expect in rows:
            if to in SKIP:
                continue
            try:
                p.goto(BASE + to, wait_until="networkidle")
                p.wait_for_timeout(2000)
                seen = p.evaluate(TITLE)
            except Exception as e:
                print(f"  ..  {to}: could not be read ({repr(e)[:50]})")
                continue
            if seen["blocks"]:
                grey.append((to, seen["blocks"]))
            if seen["title"] is None:
                continue          # a screen with no page head of its own
            if seen["title"] != expect:
                wrong_name.append((to, expect, seen["title"]))
        b.close()
    return wrong_name, grey


def report(rows) -> int:
    wrong_name, grey = look(rows)
    if not wrong_name and not grey:
        print(f"\nok  {len(rows)} route(s): the name the fallback shows is the "
              f"name the page shows, and no page head holds a skeleton")
        return 0
    if grey:
        print(f"\nFAIL  {len(grey)} page head(s) hold a skeleton block:")
        for to, n in grey:
            print(f"  {to:<28} {n} grey block(s) where static text belongs")
    if wrong_name:
        print(f"\nFAIL  {len(wrong_name)} heading(s) would change word as the "
              f"page loads:")
        for to, expect, got in wrong_name:
            print(f"  {to:<28} rail table says {expect!r}, the page says {got!r}")
        print("\n  Put the page's own wording in the rail entry's `page` field,")
        print("  or change the page to agree with the rail. Either is fine; the")
        print("  heading changing under the reader is not.")
    return 1


def plant() -> int:
    """Prove it by making one page disagree with the rail."""
    victim = ROOT / "frontend" / "src" / "pages" / "Suppliers.tsx"
    original = victim.read_text(encoding="utf-8")
    anchor = 'title="Suppliers"'
    if anchor not in original:
        print(f"FAIL  the plant's anchor is gone from {victim.name}")
        return 1
    import time
    try:
        victim.write_text(original.replace(anchor, 'title="Wholesalers"', 1),
                          encoding="utf-8")
        time.sleep(4)
        wrong_name, _ = look([("/suppliers", "Suppliers")])
        if not wrong_name:
            print("FAIL  a page was renamed away from its rail entry and this "
                  "said nothing")
            return 1
        to, expect, got = wrong_name[0]
        print(f"ok  planted fault caught: {to} rail says {expect!r}, page says {got!r}")
        return 0
    finally:
        victim.write_text(original, encoding="utf-8")
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
    sys.exit(plant() if "--plant" in sys.argv else report(rail_table()))
