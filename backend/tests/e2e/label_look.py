"""What a dispensing label actually looks like, as a picture.

Renders the label sheet the dispensary prints, for a real dispensing, so the
sticker can be looked at rather than described.

  python label_look.py <screenshot-dir> [rx_id]
"""
import json
import pathlib
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
API = "http://127.0.0.1:8099"
SHOT = pathlib.Path(sys.argv[1])


def api(path, data=None, token=None):
    req = urllib.request.Request(API + path, method=("POST" if data is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None,
                                timeout=60) as f:
        return json.loads(f.read() or b"null")


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
shelf = api("/api/dispensing/will-call?limit=40", token=token)
rows = shelf["items"] if isinstance(shelf, dict) else shelf
rx_id = int(sys.argv[2]) if len(sys.argv) > 2 else next(
    b["prescription_id"] for b in rows if b.get("prescription_id"))
labels = api(f"/api/prescriptions/{rx_id}/labels", token=token)
print(json.dumps(labels[0], indent=2, default=str)[:900])

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 900, "height": 700}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)
    page.goto(f"{BASE}/dispense?reprint={rx_id}", wait_until="networkidle")
    page.wait_for_timeout(3500)
    sheet = page.query_selector(".label-sheet, .modal")
    if sheet:
        sheet.screenshot(path=str(SHOT / "label-now.png"))
        print("\nshot of the label preview taken")
    else:
        page.screenshot(path=str(SHOT / "label-now.png"))
        print("\nno label preview found; whole page shot instead")
    browser.close()
