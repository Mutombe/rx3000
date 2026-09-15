"""The operations dashboard, in a browser, checked against the API it reads.

  - Operations is in the Dispensary section of the sidebar and opens the page
  - the queue and on-hold tiles carry the server's figures
  - the scripts tile is today's distinct scripts, counted in local time
  - the hour chart and the dispenser table render once anything has gone out
  - the on-hold list is the server's list
  - the holds report link opens that report, not the catalogue

Run against a local dev server on :4177 and API on :8099:
  python dispensary_operations.py [screenshot-dir]
"""
import json
import pathlib
import sys
import urllib.request
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
API = "http://127.0.0.1:8099"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def api(path, data=None, token=None):
    req = urllib.request.Request(API + path, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, json.dumps(data).encode() if data else None, timeout=60) as f:
        return json.loads(f.read() or b"null")


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 900}, color_scheme="dark",
                            timezone_id="Africa/Harare")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)

    link = page.locator("nav a[href='/dispensary/operations'], aside a[href='/dispensary/operations']")
    check("Operations is in the sidebar", link.count() >= 1)
    if link.count():
        link.first.click()
    else:
        page.goto(BASE + "/dispensary/operations")
    page.wait_for_timeout(3500)
    check("…and opens the page", "Dispensary operations" in page.inner_text("h1"), page.inner_text("h1"))

    ops = api("/api/dispensary/operations", token=token)
    tiles = page.evaluate("""() => [...document.querySelectorAll('.ops-tiles .stat')]
      .map((t) => ({ label: t.querySelector('.label')?.innerText.trim(),
                     value: t.querySelector('.value')?.innerText.trim() }))""")
    by = {t["label"].lower(): t["value"] for t in tiles if t["label"]}
    check("five headline figures", len(tiles) == 5, str(tiles))
    check("the queue tile is the server's queue depth",
          by.get("lines waiting") == str(ops["queue_lines"]), f"{by.get('lines waiting')} vs {ops['queue_lines']}")
    check("the on-hold tile is the server's open holds",
          by.get("on hold now") == str(len(ops["open_holds"])),
          f"{by.get('on hold now')} vs {len(ops['open_holds'])}")

    # Today in Harare (UTC+2, no daylight saving), computed independently of the page.
    from datetime import timedelta
    offset = timedelta(hours=2)
    today_local = (datetime.now(timezone.utc) + offset).date()
    scripts = {d["prescription_id"] for d in ops["dispensings"]
               if (datetime.fromisoformat(d["at"].replace("Z", "+00:00")) + offset).date() == today_local}
    check("the scripts tile is today's distinct scripts, in local time",
          by.get("scripts dispensed today") == str(len(scripts)),
          f"{by.get('scripts dispensed today')} vs {len(scripts)}")

    if scripts:
        check("the hour chart renders", page.locator(".chart svg").count() >= 1)
        check("the dispenser table lists who dispensed",
              page.locator(".ops-table tbody tr").count() >= 1)
    else:
        print("  --    nothing dispensed today in this database; the chart and table were not exercised")

    held_rows = page.locator(".card", has_text="Longest held first").locator("tbody tr").count()
    check("the on-hold list is the server's list", held_rows == len(ops["open_holds"]),
          f"{held_rows} vs {len(ops['open_holds'])}")
    if SHOT:
        page.screenshot(path=str(SHOT / "operations.png"), full_page=True)

    page.get_by_role("link", name="The holds report").click()
    page.wait_for_timeout(3000)
    # Opened, not merely listed: its own title and purpose, and the runner's
    # Table/Chart tabs, which the catalogue does not have. (Column headings wait
    # for the rows, so they are not what proves it opened.)
    body = page.inner_text("body")
    runner_tabs = page.evaluate("[...document.querySelectorAll('[role=tab]')].map(t => t.innerText.trim())")
    check("the holds report link opens that report",
          "Dispensing holds" in body and "Every script put on hold" in body and "Table" in runner_tabs,
          str(runner_tabs))
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
