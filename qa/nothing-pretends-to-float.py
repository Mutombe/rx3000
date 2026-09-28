# -*- coding: utf-8 -*-
"""Nothing in this product is drawn as though it were above the page.

WHAT WAS ASKED FOR

"Remove every shadow from every component. We don't want any shadow. Have you
ever seen good software that has shadows? This is not a website. It's a
platform that people are going to rely on... If you put shadows, what is their
function?"

The answer to the last question, honestly, is nothing. A drop shadow claims a
piece of a flat screen is floating above another piece. On a dashboard it is a
decoration; on a dispensary screen read for nine hours a day it is nine hours
of a claim that is not true.

WHAT COUNTS AS A SHADOW

An offset or a blur. `box-shadow: rgba(0,0,0,.1) 0 1px 2px` puts the thing
above the page and is what this fails on.

`0 0 0 Npx` is not a shadow. It has no offset and no blur: it is a ring drawn
exactly on the element's own edge, which is how focus is shown, how a selected
thing is marked, and how one avatar is separated from the one behind it in a
stack. Taking those away would not make the product more serious, it would make
it unusable by keyboard — so this guard is careful to tell the two apart rather
than banning the property.

WHAT WAS FOUND WHEN IT WAS FIRST WRITTEN

One. `.st-progress`, a tenth of a per cent of black pressed into a 6px bar to
suggest a groove. The elevation tokens had been flattened by an earlier pass —
`--e1: none`, and `--e2`/`--e3` were already 1px hairlines rather than blurs —
so what was left reading as shadow was two other things this does not measure
and which were fixed alongside it:

  the coloured slab   thirty components carried a 3px bar of status colour down
                      their left edge, painted with `box-shadow: inset`. The
                      reported one was yellow, inside the medical-aid dialog.
                      The worklist pass had already decided against these and
                      written down why: urgency is said in a badge and a
                      figure, where somebody reads it, not in a coloured slab.

  the doubled edge    a 1px border and a 1px ring of the same colour in the
                      same place, on the toast and on the assistant dock. Two
                      hairlines a pixel apart are the soft edge that reads as a
                      shadow even when nothing is blurred.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "http://localhost:5173"
API = "http://127.0.0.1:8000"

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
() => {
  const out = [], seen = new Set();
  for (const el of document.querySelectorAll("body *")) {
    const s = getComputedStyle(el);
    const sh = s.boxShadow;
    if (!sh || sh === "none") continue;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    if (s.visibility === "hidden" || s.display === "none") continue;
    const cls = (el.className || el.tagName).toString().slice(0, 36);
    const key = cls + "|" + sh;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ cls, shadow: sh.slice(0, 90) });
  }
  return out;
}
"""

PX = re.compile(r"(-?[\d.]+)px")


def is_shadow(value: str) -> bool:
    """An offset or a blur. A spread on its own is a ring, not a shadow."""
    for part in value.split("), "):
        nums = [float(x) for x in PX.findall(part)]
        if len(nums) < 3:
            continue
        x, y, blur = nums[0], nums[1], nums[2]
        if x or y or blur:
            return True
    return False


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
                p.wait_for_timeout(1600)
                rows = p.evaluate(PROBE)
                read.add(route)
            except Exception as e:
                print(f"  ..  {route}: could not be read ({repr(e)[:45]})")
                continue
            for r in rows:
                if not is_shadow(r["shadow"]):
                    continue
                found.setdefault((r["cls"], r["shadow"]), set()).add(route)
        b.close()
    return found, read


def report(routes) -> int:
    found, read = look(routes)
    if len(routes) - len(read) > len(routes) // 3:
        print(f"\nFAIL  only {len(read)} of {len(routes)} screen(s) could be read. "
              f"That is not a pass, it is a sweep that did not run.")
        return 1
    if not found:
        print(f"\nok  {len(read)} screen(s): nothing is drawn as though it were "
              f"floating above the page")
        return 0
    print(f"\nFAIL  {len(found)} element(s) paint a shadow\n")
    for (cls, sh), where in sorted(found.items(), key=lambda kv: -len(kv[1])):
        print(f"  {cls:<38} {sh}")
        print(f"      on {len(where)} screen(s): {', '.join(sorted(where)[:5])}"
              + (f" (+{len(where) - 5})" if len(where) > 5 else ""))
    print("\n  A ring on the edge — `0 0 0 Npx` — is allowed and is how focus and")
    print("  selection are shown. An offset or a blur is not.")
    return 1


def plant() -> int:
    """Prove it by putting a shadow back."""
    sheet = ROOT / "frontend" / "src" / "styles.css"
    original = sheet.read_text(encoding="utf-8")
    fault = original + (
        "\n/* planted by nothing-pretends-to-float.py --plant */\n"
        ".card { box-shadow: 0 2px 8px rgba(0, 0, 0, .12); }\n")
    import time
    try:
        sheet.write_text(fault, encoding="utf-8")
        # Long enough for vite to rebuild a 14,000-line stylesheet on a
        # machine that is already busy. At four seconds this plant passed
        # on a quiet machine and reported a false all-clear on a loaded one.
        time.sleep(9)
        found, _ = look(["/patients", "/suppliers"])
        if not found:
            print("FAIL  a shadow was put on every card and this said nothing")
            return 1
        (cls, sh), where = next(iter(found.items()))
        print(f"ok  planted fault caught: {cls} — {sh}")
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
