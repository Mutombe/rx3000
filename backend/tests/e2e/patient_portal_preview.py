"""What the patient sees, seen from behind the counter.

The preview rendered the portal's markup with none of the portal's rules: raw
browser defaults inside a phone frame, headings running into text, no cards, no
spacing. It looked broken because it was.

  - the preview opens from the patient's page
  - it is the portal's own page: its cards, its type, its colours
  - the phone frame holds it at the width a patient reads it at
  - it says plainly that this is a record read through a staff session
  - nothing in it is unstyled: every block has the portal's own styling

Run against a local dev server on :4177 and API on :8099:
  python patient_portal_preview.py [screenshot-dir]
"""
import json
import pathlib
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
API = "http://127.0.0.1:8099"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def api(path, token=None):
    req = urllib.request.Request(API + path)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=60) as f:
        return json.loads(f.read() or b"null")


token = json.loads(urllib.request.urlopen(urllib.request.Request(
    API + "/api/auth/login", data=json.dumps(
        {"username": "admin", "password": "admin123"}).encode(),
    headers={"Content-Type": "application/json"}), timeout=60).read())["access_token"]

# Somebody with medicine waiting, so the preview has something in it.
shelf = api("/api/dispensing/will-call?limit=50", token)
rows = shelf["items"] if isinstance(shelf, dict) else shelf
patient_id = next((b["patient_id"] for b in rows if b.get("patient_id")), None)
assert patient_id, "no patient with a bag waiting to preview"

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)
    page.goto(f"{BASE}/patients/{patient_id}", wait_until="networkidle")
    page.wait_for_timeout(2500)

    opener = page.get_by_role("button", name="See it as they do")
    if not opener.count():
        opener = page.locator("button", has_text="sees").first
    check("the patient's page offers the preview", opener.count() > 0)
    opener.first.click()
    page.wait_for_timeout(1800)

    shell = page.locator(".preview-shell")
    check("it opens", shell.count() > 0)
    check("…saying it is their record read through a staff session",
          "portal session" in shell.first.inner_text(), shell.first.inner_text()[:160])

    phone = page.locator(".preview-phone")
    check("…inside a phone-width frame", phone.count() > 0
          and 300 <= (phone.first.bounding_box() or {}).get("width", 0) <= 400,
          str((phone.first.bounding_box() or {}).get("width")))

    # The portal's own rules are loaded: its card has a background of its own
    # and its heading is not the browser's default 32px black.
    styled = page.evaluate("""() => {
      const card = document.querySelector('.preview-phone .pp-card');
      const page_ = document.querySelector('.preview-phone .pp');
      if (!card || !page_) return null;
      const c = getComputedStyle(card), p = getComputedStyle(page_);
      return {
        cardBg: c.backgroundColor, cardRadius: c.borderRadius, cardPad: c.padding,
        pageBg: p.backgroundImage !== 'none' ? 'washed' : p.backgroundColor,
      };
    }""")
    check("the portal's own stylesheet is applied", styled is not None, "no .pp-card in the frame")
    if styled:
        check("…its cards have a surface of their own",
              styled["cardBg"] not in ("rgba(0, 0, 0, 0)", "transparent"), str(styled))
        check("…rounded and padded, not raw browser defaults",
              styled["cardRadius"] != "0px" and styled["cardPad"] != "0px", str(styled))

    rows_seen = page.locator(".preview-phone .pp-row").count()
    pills = page.locator(".preview-phone .pp-pill").count()
    check("…and the waiting medicines are laid out as rows with their state",
          rows_seen > 0 and pills > 0, f"{rows_seen} rows, {pills} pills")
    # Nothing inside is wider than the phone: a line that runs off the side is
    # the failure a preview exists to catch.
    widest = page.evaluate("""() => {
      const f = document.querySelector('.preview-phone');
      const room = f.getBoundingClientRect().width;
      let worst = 0, what = '';
      for (const el of f.querySelectorAll('*')) {
        const w = el.getBoundingClientRect().width;
        if (w > worst) { worst = w; what = el.className || el.tagName; }
      }
      return { room, worst, what };
    }""")
    check("nothing inside is wider than the phone",
          widest["worst"] <= widest["room"] + 1, str(widest))
    if SHOT:
        page.screenshot(path=str(SHOT / "portal-preview.png"))
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
