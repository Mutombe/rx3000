# -*- coding: utf-8 -*-
"""What a screen actually spends its wait on.

BEFORE BUILDING PROGRESSIVE LOADING, MEASURE WHAT IS SLOW.

"Progressive priority loading" is a family of techniques and only some of them
pay in this product. Rendering rows one at a time is worth real milliseconds
when committing a list blocks the main thread for a tenth of a second; it is
theatre, and a net loss, when the rows are already on screen in 20ms and the
drip is pure delay. Prefetching the next page is worth it when there is a next
page. Deferring what is below the fold is worth it when something below the
fold is expensive.

So this measures, per screen:

  requests      how many calls go out on arrival, and whether they are fired
                together or in a chain. A chain is the one shape that is
                always worth breaking: three 200ms calls in series is 600ms of
                waiting for no reason.
  bytes         the largest response, because that is what has to be parsed.
  rows          how many rows land in the biggest table.
  longest task  the longest uninterrupted block of main thread work after the
                answers arrive. This is the number that says whether
                incremental rendering would help: under 50ms nobody can feel
                it, over 200ms it is a visible stall.
  below         how much of the page is below the fold on arrival, which is
                what viewport priority would defer.

It reports rather than passes or fails. It is a measuring instrument, and the
decisions it informs are written up beside it.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

#: MEASURE A PRODUCTION BUILD, NOT THE DEV SERVER.
#:
#: Run against vite's dev server this counted 35 calls on the dispensary and
#: long tasks of 300ms and more. Half those calls were React StrictMode
#: double-invoking effects, which happens in development and nowhere else, and
#: much of the main thread work was vite serving several hundred unbundled
#: modules. Building progressive loading against those figures would have been
#: optimising a phantom.
#:
#: So `RX5000_MEASURE` points this at a preview of a real build. Without it, it
#: still runs against the dev server and says plainly that the numbers are not
#: the ones to decide anything on.
import os
BASE = os.environ.get("RX5000_MEASURE", "http://localhost:5173")
DEV = "RX5000_MEASURE" not in os.environ
API = "http://127.0.0.1:8000"

#: The screens worth measuring: the ones a pharmacy is on all day, plus the
#: ones with the longest lists in the product.
ROUTES = [
    "/dispense", "/patients", "/scripts", "/dispensing-history", "/will-call",
    "/stock", "/repeats", "/to-follows", "/insights", "/orders",
    "/dispensary/operations", "/claims-held", "/money-owed", "/ledger",
]

WATCH = r"""
() => {
  window.__rx = { tasks: [], calls: [] };
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) window.__rx.tasks.push(Math.round(e.duration));
    }).observe({ entryTypes: ["longtask"] });
  } catch (e) { /* not supported: the task figures stay empty and say so */ }
}
"""

REPORT = r"""
() => {
  const api = performance.getEntriesByType("resource")
    .filter((r) => r.name.includes("/api/"))
    .map((r) => ({
      path: r.name.replace(/^https?:\/\/[^/]+/, "").split("?")[0],
      start: Math.round(r.startTime),
      end: Math.round(r.responseEnd),
      ms: Math.round(r.duration),
      kb: Math.round((r.transferSize || r.decodedBodySize || 0) / 1024),
    }))
    .sort((a, b) => a.start - b.start);

  // A chain: a call that only STARTED after an earlier one had finished.
  let chained = 0;
  for (let i = 1; i < api.length; i++) {
    if (api[i].start >= api[i - 1].end - 5) chained++;
  }

  const tables = [...document.querySelectorAll("main table")]
    .map((t) => t.querySelectorAll("tbody tr").length);
  const doc = document.documentElement;
  return {
    calls: api.length,
    chained,
    spread: api.length ? api[api.length - 1].end - api[0].start : 0,
    slowest: api.slice().sort((a, b) => b.ms - a.ms)[0] || null,
    biggest: api.slice().sort((a, b) => b.kb - a.kb)[0] || null,
    rows: tables.length ? Math.max(...tables) : 0,
    tasks: (window.__rx?.tasks || []).sort((a, b) => b - a).slice(0, 3),
    pageH: doc.scrollHeight,
    viewH: window.innerHeight,
  };
}
"""


def token() -> str:
    req = urllib.request.Request(API + "/api/auth/login", method="POST")
    req.add_header("Content-Type", "application/json")
    body = json.dumps({"username": "admin", "password": "admin123"}).encode()
    with urllib.request.urlopen(req, body, timeout=60) as f:
        return json.loads(f.read())["access_token"]


def main() -> int:
    from playwright.sync_api import sync_playwright
    rows = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page(viewport={"width": 1440, "height": 900},
                       color_scheme="light")
        p.goto(BASE, wait_until="networkidle")
        p.fill("#lg-user", "admin")
        p.fill("#lg-pass", "admin123")
        p.get_by_role("button", name="Sign in").click()
        p.wait_for_timeout(3000)
        for route in ROUTES:
            try:
                p.add_init_script(WATCH)
                p.goto(BASE + route, wait_until="domcontentloaded")
                p.evaluate(WATCH)
                p.wait_for_load_state("networkidle")
                p.wait_for_timeout(2500)
                rows.append((route, p.evaluate(REPORT)))
            except Exception as e:
                print(f"  ..  {route}: {repr(e)[:50]}")
        b.close()

    print(f"\n  {'screen':<24} {'calls':>5} {'chain':>5} {'spread':>7} "
          f"{'slowest':>9} {'biggest':>9} {'rows':>5} {'longest task':>13} "
          f"{'below fold':>11}")
    print("  " + "-" * 104)
    for route, r in rows:
        slow = f"{r['slowest']['ms']}ms" if r["slowest"] else "none"
        big = f"{r['biggest']['kb']}kb" if r["biggest"] else "none"
        task = f"{r['tasks'][0]}ms" if r["tasks"] else "under 50ms"
        below = max(0, r["pageH"] - r["viewH"])
        print(f"  {route:<24} {r['calls']:>5} {r['chained']:>5} "
              f"{r['spread']:>6}ms {slow:>9} {big:>9} {r['rows']:>5} "
              f"{task:>13} {below:>10}px")

    if DEV:
        print("\n  THESE ARE DEV SERVER FIGURES AND NOTHING SHOULD BE DECIDED "
              "ON THEM.")
        print("  React StrictMode fires every effect twice here, so the call "
              "counts are")
        print("  roughly double, and vite serves several hundred unbundled "
              "modules, so the")
        print("  task figures are its own. Build the front end, preview it, "
              "and set")
        print("  RX5000_MEASURE to that address.")
    print("\n  chain        calls that only started once an earlier one had "
          "finished.")
    print("  spread       first request out to last request back.")
    print("  longest task the longest unbroken block of main thread work. "
          "Under 50ms")
    print("               nobody can feel; over 200ms is a visible stall and "
          "is what")
    print("               incremental rendering exists to break up.")
    return 0


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
    sys.exit(main())
