# -*- coding: utf-8 -*-
"""Two things stacked on a screen have air between them.

WHAT WAS REPORTED, THREE TIMES IN ONE MESSAGE

"The top filter for the page is too coupled with the bottom component. There's
no space between it and the component that comes after it below."
"In Recall, the label of the field that is on top is too close to the search
field."
"In Claiming the thing that contains Batches, Calendar, Authorisations is too
close to the thing that contains Batches, Fee models, Formularies."
"I hope you can find all other instances where that is happening and solve
them. We don't want to come back to this again."

So this is the not-coming-back-to-it.

WHAT IS CHECKED

Two shapes, because the two reported faults had different causes.

A. TWO PAGE BLOCKS WITH NOTHING BETWEEN THEM.

   The convention here is that each block in a page's vertical flow declares
   its own bottom margin: the head 20px, a tab strip 20px, a card 16px. Three
   kinds of block never got the memo — a row of stat tiles, the wrapper that
   `Refreshable` puts around a table, and the section nav — so on eight screens
   one block sat directly on the next. The section nav was the worst of them: a
   navigation strip resting on the very thing it navigates, with the branch
   register on Licences landing on the table the moment somebody clicked a row.

B. A LABEL SITTING ON THE CONTROL IT WRAPS.

   `label { margin-bottom }` spaces the label from what follows it, which is
   right for `<label>Caption</label><input>`. For `<label>Caption <input></label>`
   the control is INSIDE, so that margin goes on the outside and the caption
   ends up directly on the box. One pixel, on Recall — a screen somebody opens
   with a recall notice in their hand.

WHAT IS NOT CHECKED

Whether the gap is the right size. 12px against 20px is a judgement about
rhythm; nought is a bug. Only nought is mechanical, so only nought is here.

Widths are not checked either, though two blocks of the same kind at different
widths was part of the same report — the section nav was 412px above a tab
strip of 1,190, both with the same ground, border and radius, which read as one
control that had failed to render. That is now one shape at one width, but
"these two should be the same width" is not a rule a machine can tell from
"these two are deliberately different".
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "http://localhost:5173"
API = "http://127.0.0.1:8000"

# Anything under this is touching. Not a rhythm judgement — a gap of nought,
# one or two pixels is a block that was never given a margin.
FLUSH = 2

ROUTES = [
    "/", "/patients", "/scripts", "/dispensing-history", "/to-follows",
    "/will-call", "/repeats", "/stock", "/stock-categories", "/orders",
    "/suppliers", "/deliveries", "/drivers", "/register", "/laybys",
    "/claiming", "/claims-held", "/authorisations", "/payables", "/ledger",
    "/periods", "/fiscal", "/shifts", "/helpdesk", "/accounts", "/pipeline",
    "/marketing", "/reminders", "/branches", "/pharmacies", "/head-office",
    "/admin", "/stock-take", "/rfqs", "/samples", "/recall", "/compounding",
    "/remittances", "/money-owed", "/compliance", "/leads", "/scorecard",
    "/reconciliation", "/reconciliation/bank", "/reconciliation/settlements",
    "/stock-performance", "/seasons", "/crm-reports", "/system",
    "/dispensary/operations",
]

PROBE = r"""
(flush) => {
  const blocks = [], labels = [];
  const page = document.querySelector("main .page") || document.querySelector("main");
  if (page) {
    let prev = null, prevCls = null;
    for (const el of page.children) {
      const r = el.getBoundingClientRect();
      if (!r.height || !r.width) continue;
      const cls = (el.className || el.tagName).toString().slice(0, 30);
      if (prev !== null && Math.round(r.top - prev) <= flush) {
        blocks.push({ after: prevCls, before: cls, gap: Math.round(r.top - prev) });
      }
      prev = r.bottom; prevCls = cls;
    }
  }
  for (const lab of document.querySelectorAll("main label")) {
    const caption = [...lab.childNodes].find(
      (n) => n.nodeType === 3 && n.textContent.trim());
    if (!caption) continue;
    const ctl = lab.querySelector(
      "input:not([type=checkbox]):not([type=radio]), select, textarea, "
      + ".sel-trigger, .rc-search");
    if (!ctl) continue;
    const range = document.createRange();
    range.selectNode(caption);
    const tr = range.getBoundingClientRect();
    const cr = ctl.getBoundingClientRect();
    if (!tr.height || !cr.height) continue;
    if (cr.top < tr.bottom - 2) continue;          // side by side, not stacked
    const gap = Math.round(cr.top - tr.bottom);
    if (gap > 4) continue;
    labels.push({ text: caption.textContent.trim().slice(0, 34), gap });
  }
  return { blocks, labels };
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
    touching, hugging = {}, {}
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
                p.wait_for_timeout(1900)
                r = p.evaluate(PROBE, FLUSH)
            except Exception as e:
                print(f"  ..  {route}: could not be read ({repr(e)[:45]})")
                continue
            for x in r["blocks"]:
                touching.setdefault((x["after"], x["before"], x["gap"]), set()).add(route)
            for x in r["labels"]:
                hugging.setdefault((x["text"], x["gap"]), set()).add(route)
        b.close()
    return touching, hugging


def report(routes) -> int:
    touching, hugging = look(routes)
    if not touching and not hugging:
        print(f"\nok  {len(routes)} screen(s): nothing is sitting on the thing "
              f"below it, and no caption is sitting on its own control")
        return 0
    if touching:
        print(f"\nFAIL  {len(touching)} pair(s) of blocks with no air between them:\n")
        for (a, b, gap), where in sorted(touching.items(), key=lambda kv: -len(kv[1])):
            print(f"  {a:<30} sits on  {b:<26} ({gap}px)")
            print(f"      {', '.join(sorted(where)[:6])}"
                  + (f"  (+{len(where) - 6} more)" if len(where) > 6 else ""))
        print("\n  A block in a page's flow declares its own bottom margin. The")
        print("  page rhythm is 20px between kinds and 16px between cards.")
    if hugging:
        print(f"\nFAIL  {len(hugging)} caption(s) sitting on the control they wrap:\n")
        for (txt, gap), where in sorted(hugging.items(), key=lambda kv: -len(kv[1])):
            print(f"  {gap}px  {txt!r}")
            print(f"      {', '.join(sorted(where))}")
    return 1


def plant() -> int:
    """Prove it by taking a block's margin away."""
    sheet = ROOT / "frontend" / "src" / "styles.css"
    original = sheet.read_text(encoding="utf-8")
    fault = original + (
        "\n/* planted by nothing-sits-on-what-it-is-not-part-of.py --plant */\n"
        ".section-nav { margin-bottom: 0; }\n")
    import time
    try:
        sheet.write_text(fault, encoding="utf-8")
        # Long enough for vite to rebuild a 14,000-line stylesheet on a
        # machine that is already busy. At four seconds this plant passed
        # on a quiet machine and reported a false all-clear on a loaded one.
        time.sleep(9)
        touching, _ = look(["/claiming", "/compliance", "/branches"])
        if not touching:
            print("FAIL  a block's margin was removed and this said nothing")
            return 1
        (a, b, gap), where = next(iter(touching.items()))
        print(f"ok  planted fault caught: {a} sits on {b} ({gap}px) "
              f"on {sorted(where)[0]}")
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
