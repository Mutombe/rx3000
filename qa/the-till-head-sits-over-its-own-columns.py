# -*- coding: utf-8 -*-
"""The till's column heads sit over the columns they name, and are divided.

WHY THIS IS NOT COVERED BY a-column-has-one-edge

That guard asks `main table` for its columns, and the till basket is not a
table. It is a stack of `.till-row` grids of bare `<span>`, drawn that way so a
row can be a line, a waiting placeholder or a filler without three sets of
table markup. So the one screen a pharmacy stares at for eight hours is the one
screen that guard has never measured, and it said nothing about it either way.

WHAT WAS REPORTED

Four arrows on a screenshot of the till, one at each boundary between the
columns, on the head band. The body rows drew a rule at every boundary and the
head drew none, so the labels floated over a divided grid and the eye had
nothing joining "PRICE" to the column of prices.

The rules were in fact there and had always been: `--line`, 13% white, over a
head washed with the money section's tint, which in the dark theme comes out as
rgba(180,120,80,0.15) over near black. Invisible rather than absent.

WHAT THIS MEASURES

Two things, because either alone passes while the screen is wrong.

  WHERE.  Every boundary the body draws a rule at, the head draws one at the
          same x. A head whose grid drifts from the body's is the fault the
          arrows were actually pointing at, whatever the cause.

  WHETHER. The head's rules are drawn at all, and in a colour that is not the
          body's quietest. A rule nobody can see is the same screen as no rule,
          and that is how this was shipped in the first place.

And the text edges, which is the ordinary column question: a right aligned head
label ends where its column's figures end.

WHAT IT DOES NOT MEASURE

The Item column's own left edge against the head, because the placeholder line
is italic and set in a different face, and the two disagree by a pixel that no
reader has ever noticed. The boundaries are the question.
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

#: Under this and it is a rounding difference, not a kink anybody can see.
SLACK = 1

PROBE = r"""
(slack) => {
  const head = document.querySelector(".till-row-head");
  const body = document.querySelector(".till-lines .till-row")
            || document.querySelector(".till-row-empty");
  if (!head || !body) return { missing: true };

  const rules = (row) => [...row.children].map((c) => {
    const s = getComputedStyle(c);
    const w = parseFloat(s.borderLeftWidth) || 0;
    return { at: Math.round(c.getBoundingClientRect().left), w,
             colour: s.borderLeftColor,
             said: (c.textContent || "").trim().slice(0, 10) };
  });

  const h = rules(head), b = rules(body);
  const faults = [];

  if (h.length !== b.length) {
    faults.push({ what: "the head has " + h.length + " cells and a row has "
                        + b.length });
    return { faults };
  }

  /* The first cell of a row has no rule to its left by design: that edge is
     the card's. Every boundary after it is a boundary. */
  for (let i = 1; i < b.length; i++) {
    if (Math.abs(h[i].at - b[i].at) > slack) {
      faults.push({ what: "boundary " + i + " is at " + h[i].at
                          + " in the head and " + b[i].at + " in the rows",
                    col: h[i].said });
    }
    if (b[i].w > 0 && h[i].w === 0) {
      faults.push({ what: "the rows draw a rule at boundary " + i
                          + " and the head draws none", col: h[i].said });
    }
    if (b[i].w > 0 && h[i].colour === b[i].colour) {
      /* Same ink, different ground. The head is washed with the section tint
         and the rows are not, so a rule that reads on one does not on the
         other. This is the fault that was shipped. */
      faults.push({ what: "boundary " + i + " uses the rows' own ink ("
                          + h[i].colour + ") on the head's tinted ground, "
                          + "where it does not read", col: h[i].said });
    }
  }

  /* And the text edges, for the columns that are read as figures. */
  const edge = (el) => {
    const r = document.createRange();
    r.selectNodeContents(el);
    const bb = r.getBoundingClientRect();
    return bb.width ? Math.round(bb.right) : null;
  };
  const rows = [...document.querySelectorAll(".till-lines .till-row")];
  for (let i = 1; i < h.length; i++) {
    if (getComputedStyle(head.children[i]).textAlign !== "right") continue;
    const he = edge(head.children[i]);
    if (he === null) continue;
    for (const row of rows.slice(0, 8)) {
      const c = row.children[i];
      if (!c) continue;
      if (c.querySelector("input, button, select")) continue;
      const ce = edge(c);
      if (ce === null) continue;
      if (Math.abs(ce - he) > slack) {
        faults.push({ what: "'" + h[i].said + "' ends at " + he
                            + " and a figure under it at " + ce,
                      col: h[i].said });
        break;
      }
    }
  }
  return { faults, cols: h.length,
           grid: getComputedStyle(head).gridTemplateColumns,
           rowGrid: getComputedStyle(body).gridTemplateColumns };
}
"""


def token() -> str:
    req = urllib.request.Request(API + "/api/auth/login", method="POST")
    req.add_header("Content-Type", "application/json")
    body = json.dumps({"username": "admin", "password": "admin123"}).encode()
    with urllib.request.urlopen(req, body, timeout=60) as f:
        return json.loads(f.read())["access_token"]


def look(words=("Para", "Amoxi")):
    """Open the till, put real lines in the basket, and measure.

    With an empty basket the only body row is a placeholder, whose cells are
    empty, so every text edge question answers itself. A till with nothing on
    it is not the screen anybody is complaining about.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page(viewport={"width": 1512, "height": 950},
                       color_scheme="dark")
        p.goto(BASE, wait_until="networkidle")
        p.fill("#lg-user", "admin")
        p.fill("#lg-pass", "admin123")
        p.get_by_role("button", name="Sign in").click()
        p.wait_for_timeout(3000)
        p.goto(BASE + "/pos", wait_until="networkidle")
        p.wait_for_selector(".till-row-head", timeout=30000)
        p.wait_for_timeout(2000)
        for word in words:
            try:
                box = p.locator("input[placeholder*='Scan a barcode']")
                box.click()
                box.fill("")
                box.type(word, delay=55)
                p.wait_for_timeout(2200)
                if p.locator(".product-pick").count():
                    p.locator(".product-pick").first.click()
                    p.wait_for_timeout(1000)
            except Exception:
                continue
        out = p.evaluate(PROBE, SLACK)
        b.close()
    return out


def report() -> int:
    d = look()
    if d.get("missing"):
        print("FAIL  the till drew no basket, so nothing was measured.")
        return 1
    faults = d.get("faults") or []
    if not faults:
        print(f"ok  the till's {d['cols']} column heads sit over their own "
              f"columns, every boundary is ruled on both, and the figures "
              f"line up with their labels")
        return 0
    print(f"\nFAIL  {len(faults)} thing(s) wrong with the till's columns\n")
    for f in faults:
        print(f"  {f['what']}")
    print(f"\n  head {d.get('grid')}")
    print(f"  rows {d.get('rowGrid')}")
    return 1


def plant() -> int:
    """Put the reported fault back: a head with no rules on it."""
    import time
    sheet = ROOT / "frontend" / "src" / "styles.css"
    original = sheet.read_text(encoding="utf-8")
    fault = original + (
        "\n/* planted by the-till-head-sits-over-its-own-columns.py */\n"
        ".till-row-head > span + span { border-left-width: 0; }\n")
    try:
        sheet.write_text(fault, encoding="utf-8")
        time.sleep(14)
        d = look()
        faults = d.get("faults") or []
        if not faults:
            print("FAIL  the head was stripped of its rules and this said "
                  "nothing")
            return 1
        print(f"ok  planted fault caught: {faults[0]['what']}")
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
