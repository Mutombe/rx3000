# -*- coding: utf-8 -*-
"""Every column in every table starts on one line, and the heading is on it too.

WHAT THIS IS FOR, IN THE WORDS IT WAS ASKED FOR IN

"Data should be starting from a specific vertical line... and that line should
be very aligned. The table header topic should be aligned as well with the data
that comes after. When someone looks at a table, they should know exactly what
is happening by just looking at it."

A reader does not read a column, they run their eye down its edge. Every pixel
a row is out by is a step the eye has to take, and it only takes them on the
rows that are out — so the raggedness reads as meaning, and there is none.

WHAT AN EDGE IS

A left-aligned column aligns on the left edge of its text. A right-aligned one
aligns on the right edge, because that is where the units are and a column of
figures is read by its ones column. The heading sits on the same edge as the
data it names, or it is naming something that is not underneath it.

So for every column: measure the heading's edge and every body row's edge, and
they must be the same number.

THE TWO FAULTS IT WAS WRITTEN AGAINST, BOTH FOUND BY MEASURING

`main td > .muted { margin-left: 8px }`. Right air between a value and the note
after it, and an 8px indent on a cell whose only content is muted — which is
most of them, because this product never prints a dash and an unknown value is
a sentence in its own words. Every "Not on file" and "None recorded" in the
product sat 8px right of the rows above it and of its own heading.

`main td > .muted { display: inline }` in a numeric column. Flattening the note
onto the value's line keeps the value first, so a left column is unmoved. In a
right column the LAST thing on the line is on the edge, so the note landed
there and shoved the number left by the note's own width — different on every
row. Measured on Stock: `2,075` ended at x=570 and `397` at x=644 in the same
column. Seventy-four pixels, on the one kind of column whose whole purpose is
that the digits line up.

WHAT IS NOT MEASURED, AND WHY

A column of buttons. Its heading is blank by design and its cells hold controls
rather than text, so there is no text edge to align and the width machinery in
`.actions` governs it instead. Measuring it produced nothing but noise: rows
with two buttons against rows with none, reported as a 206px spread.

Truncation is a separate question with its own guard, `a-cell-is-not-cut-off`.
A column can be perfectly aligned and still too narrow.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "http://localhost:5173"
API = "http://127.0.0.1:8000"

# A laptop, which is what the shops this is sold to are using.
WIDTH, HEIGHT = 1366, 768

# Taken from the router rather than from memory. The first list was written
# from memory and four of its names did not exist — `/staff`, `/sales`,
# `/settlements`, `/deferred-claims` — so React Router fell through to the
# dashboard and the same table was reported as a fault on five screens.
ROUTES = [
    "/", "/accounts", "/authorisations", "/branches", "/claiming",
    "/claims-held", "/compliance", "/compounding", "/crm-reports",
    "/deliveries", "/dispensary/operations", "/dispensing-history", "/drivers",
    "/fiscal", "/head-office", "/helpdesk", "/laybys", "/leads", "/ledger",
    "/marketing", "/money-owed", "/orders", "/patients", "/payables",
    "/periods", "/pharmacies", "/pipeline", "/recall", "/reconciliation",
    "/reconciliation/bank", "/reconciliation/card",
    "/reconciliation/settlements", "/register", "/reminders", "/remittances",
    "/repeats", "/rfqs", "/samples", "/scorecard", "/scripts", "/seasons",
    "/shifts", "/stock", "/stock-categories", "/stock-performance",
    "/stock-take", "/suppliers", "/system", "/to-follows", "/will-call",
]

# Under this and it is a rounding difference, not a kink anybody can see.
SLACK = 1

PROBE = r"""
() => {
  /* The edge of the TEXT, not of the box. A range over the cell's contents
     gives where the ink actually starts and stops, which is what an eye
     follows — padding and margins are only interesting insofar as they move
     it. */
  const edge = (el) => {
    try {
      const r = document.createRange();
      r.selectNodeContents(el);
      const b = r.getBoundingClientRect();
      if (!b.width) return null;
      /* Clamped to what is on the screen. A Range reports where text WOULD be,
         and a cell clips with `overflow: hidden`, so a heading too wide for its
         column reports an edge 22px outside the column it is drawn in. That is
         a real fault and it is the other guard's — `a-cell-is-not-cut-off`
         measures what is cut, this one measures where what is left begins. Both
         had to be separate or every clipped heading is reported twice, under a
         name that does not describe it. */
      const box = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      const lo = box.left + parseFloat(cs.paddingLeft || 0)
                 + parseFloat(cs.borderLeftWidth || 0);
      const hi = box.right - parseFloat(cs.paddingRight || 0)
                 - parseFloat(cs.borderRightWidth || 0);
      return {
        l: Math.round(Math.max(b.left, lo)),
        r: Math.round(Math.min(b.right, hi)),
      };
    } catch (e) { return null; }
  };
  /* A cell holding only controls has no text edge to align. */
  const controlsOnly = (c) => {
    const txt = (c.innerText || "").trim();
    if (!txt) return true;
    const ctl = c.querySelector("button, a.btn, input, select, textarea");
    return !!ctl && ctl.innerText.trim() === txt;
  };
  const out = [];
  for (const table of document.querySelectorAll("main table")) {
    const hrow = (table.tHead || table).querySelector("tr");
    const body = table.tBodies[0];
    if (!hrow || !body || body.rows.length < 2) continue;
    /* A table in a tab nobody is looking at is still in the document and still
       has geometry — geometry of a box 0px wide, where every edge is wherever
       the collapse left it. Measured, that reported a heading 37px out of line
       on a column that is perfectly aligned when the tab is open. Only what is
       on the screen is a question about the screen. */
    const box = table.getBoundingClientRect();
    if (!table.offsetParent || box.width < 200) continue;
    const heads = [...hrow.children];
    for (let i = 0; i < heads.length; i++) {
      const h = heads[i];
      const name = (h.innerText || "").trim();
      if (!name) continue;                       // an action or avatar column
      if (h.classList.contains("actions")) continue;
      const right = ["right", "end"].includes(getComputedStyle(h).textAlign);
      const key = right ? "r" : "l";
      const he = edge(h);
      if (!he) continue;
      const seen = [];
      let digits = false, tabular = true;
      for (const row of [...body.rows].slice(0, 15)) {
        /* A row holding a colspan is not a row of this table's columns. The
           trial balance's totals row spans its first three into one "Totals",
           so the fourth cell of that row sits under the second heading and
           positional indexing quietly compares a money figure against the
           account-name column: reported as a 415px kink that does not exist. */
        if ([...row.children].some((x) => x.colSpan > 1)) continue;
        const c = row.children[i];
        if (!c) continue;
        if (c.classList.contains("actions")) continue;
        if (controlsOnly(c)) continue;
        /* A wrapping cell is several lines and its range spans all of them,
           so the right edge belongs to whichever line is longest. Only the
           first line's start is an alignment question. */
        const cs = getComputedStyle(c);
        if (right && cs.whiteSpace === "normal") continue;
        const e = edge(c);
        if (!e) continue;
        seen.push({ at: e[key], text: (c.innerText || "").trim().slice(0, 24) });
        if (/[0-9]/.test(c.innerText || "")) {
          digits = true;
          if (cs.fontVariantNumeric.indexOf("tabular-nums") < 0) tabular = false;
        }
      }
      if (seen.length < 2) continue;
      const at = seen.map((s) => s.at);
      out.push({
        table: table.className || "(no class)",
        col: name.slice(0, 18),
        side: key,
        head: he[key],
        lo: Math.min(...at), hi: Math.max(...at),
        worst: seen.reduce((a, b) =>
          Math.abs(b.at - he[key]) > Math.abs(a.at - he[key]) ? b : a).text,
        right, digits, tabular,
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
    found = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT},
                                color_scheme="light")
        page.goto(BASE, wait_until="networkidle")
        page.fill("#lg-user", "admin")
        page.fill("#lg-pass", "admin123")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_timeout(3000)
        # Every route once before anything is measured. A screen read while its
        # chunk is still compiling reports a skeleton, and a skeleton's columns
        # are all the same width — which is to say, perfectly aligned.
        for route in routes:
            try:
                page.goto(BASE + route, wait_until="networkidle")
                page.wait_for_timeout(900)
            except Exception:
                pass
        for route in routes:
            try:
                page.goto(BASE + route, wait_until="networkidle")
                # Wait for the rows, not for a guess at how long they take. A
                # fixed pause was measuring 36 screens on a quiet machine and 13
                # on a busy one, reporting "ok" either way — this guard's own
                # hundred navigations are enough to make the machine busy.
                try:
                    page.wait_for_selector("main table tbody tr",
                                           timeout=12000, state="attached")
                    # A beat after the first row, so the rest of the page has
                    # settled and column widths have stopped moving.
                    page.wait_for_timeout(700)
                except Exception:
                    # Genuinely no table here, or it never arrived. Either way
                    # there is nothing to measure; the count in `report` is what
                    # notices if that happens too often.
                    continue
                for row in page.evaluate(PROBE):
                    row["route"] = route
                    found.append(row)
            except Exception as e:
                print(f"  ..  {route}: could not be read ({repr(e)[:60]})")
        browser.close()
    return found


def judge(rows):
    bad = []
    for r in rows:
        spread = r["hi"] - r["lo"]
        off = (r["lo"] if abs(r["lo"] - r["head"]) > abs(r["hi"] - r["head"])
               else r["hi"]) - r["head"]
        why = []
        if spread > SLACK:
            why.append(f"rows {spread}px apart")
        if abs(off) > SLACK:
            why.append(f"heading {abs(off)}px "
                       + ("left of" if off > 0 else "right of") + " its data")
        if r["right"] and r["digits"] and not r["tabular"]:
            why.append("figures are not tabular, so they cannot line up")
        if why:
            bad.append((r, "; ".join(why)))
    return bad


def report(rows) -> int:
    bad = judge(rows)
    cols = len(rows)
    seen = {r["route"] for r in rows}
    # A guard that quietly measures less is a guard that quietly stops
    # guarding. On a loaded machine the per-route wait expired before the rows
    # arrived and the sweep fell from 36 screens to 11 — still reporting "ok",
    # because every column it did manage to read was straight.
    missed = [r for r in ROUTES if r not in seen]
    if len(missed) > len(ROUTES) // 3:
        print(f"\nFAIL  only {len(seen)} of {len(ROUTES)} screen(s) had a table "
              f"to measure. That is not a pass, it is a sweep that did not run.")
        print(f"  nothing read on: {', '.join(missed[:12])}"
              + (f" (+{len(missed) - 12} more)" if len(missed) > 12 else ""))
        print("  Usually the dev server is still warming or the machine is "
              "loaded. Run it again on a quiet machine.")
        return 1
    if not bad:
        note = f"; {len(missed)} screen(s) had no table" if missed else ""
        print(f"\nok  {cols} column(s) across {len(seen)} screen(s): every one "
              f"has a single edge, and its heading is on it{note}")
        return 0
    last = None
    for r, why in bad:
        if r["route"] != last:
            print(f"  {r['route']}")
            last = r["route"]
        side = "left" if r["side"] == "l" else "right"
        print(f"      {r['col']:<20} [{r['table'][:18]}] {side} edge: {why}")
        print(f"        worst row: {r['worst']!r}")
    print("\n  An edge moves for a reason. The two found so far were both one CSS")
    print("  rule: a margin on the muted span that is most cells' whole content,")
    print("  and that span going inline inside a right-aligned column.")
    return 1


def plant() -> int:
    """Prove it by knocking one column out of line."""
    sheet = ROOT / "frontend" / "src" / "styles.css"
    original = sheet.read_text(encoding="utf-8")
    fault = original + (
        "\n/* planted by a-column-has-one-edge.py --plant */\n"
        "main td > .muted { margin-left: 9px; }\n")
    try:
        sheet.write_text(fault, encoding="utf-8")
        # Vite serves the stylesheet; give it a moment to rebuild.
        import time
        time.sleep(4)
        bad = judge(look(["/patients", "/scripts", "/deliveries"]))
        if not bad:
            print("FAIL  a column was knocked 9px out of line and this said nothing")
            return 1
        r, why = bad[0]
        print(f"ok  planted fault caught: {r['route']} {r['col']} — {why}")
        return 0
    finally:
        sheet.write_text(original, encoding="utf-8")
        import time
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
    sys.exit(plant() if "--plant" in sys.argv else report(look(ROUTES)))
