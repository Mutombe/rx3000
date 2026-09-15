"""Registering a patient, in a browser: duplicates reviewed, numbers shown.

  - typing an existing patient's ID number (without its hyphens) into New
    Patient shows the review before anything is saved, naming who matched,
    their profile number and why
  - "Use this patient" saves nothing new
  - "They're a different person" registers them, with a profile number, and
    their page carries the notice pointing at the patient they matched
  - profile numbers show in the patient list and in the dispensary's search

Run against a local dev server on :4177 and API on :8099:
  python patient_registration.py [screenshot-dir]
"""
import json
import pathlib
import re
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
API = "http://127.0.0.1:8099"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
NUMBER = re.compile(r"PT\d{9}")
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
    with urllib.request.urlopen(req, json.dumps(data).encode() if data else None, timeout=30) as f:
        return json.loads(f.read() or b"null")


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
existing = next(p for p in api("/api/patients?q=a&limit=200", token=token)
                if p.get("id_number") and "-" in p["id_number"] and p.get("profile_number"))
count_before = len(api(f"/api/patients?q={existing['last_name']}&limit=200", token=token))
print(f"  matching against {existing['first_name']} {existing['last_name']} "
      f"{existing['profile_number']} · ID {existing['id_number']}")


def field(page, label):
    return page.locator(".modal .field", has_text=label).first.locator("input").first


def open_new(page):
    page.goto(BASE + "/patients", wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.get_by_role("button", name="+ New Patient").click()
    page.wait_for_timeout(600)
    field(page, "First name").fill("Nyasha")
    field(page, "Last name").fill(existing["last_name"])
    field(page, "ID number").fill(existing["id_number"].replace("-", "").lower())


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)

    # ---- the review appears before anything is saved -------------------------
    open_new(page)
    # As a dispenser who filled in the caregiver section would be: scrolled to
    # the bottom of the form when they press Add.
    page.evaluate("(() => { const m = document.querySelector('.modal'); if (m) m.scrollTop = m.scrollHeight; })()")
    page.wait_for_timeout(300)
    page.locator(".modal .modal-actions").get_by_role("button", name="Add patient").click()
    page.wait_for_timeout(1800)
    review = page.query_selector(".dup-review")
    check("the review appears instead of saving", review is not None)
    # Present is not enough. The first version rendered it below the caregiver
    # section, out of sight, and every check above still passed.
    in_view = page.evaluate("""() => {
      const e = document.querySelector('.dup-review'), m = document.querySelector('.modal');
      if (!e || !m) return null;
      const r = e.getBoundingClientRect(), box = m.getBoundingClientRect();
      const foot = m.querySelector('.modal-actions');
      const floor = foot ? foot.getBoundingClientRect().top : box.bottom;
      return { top: Math.round(r.top), boxTop: Math.round(box.top), floor: Math.round(floor),
               visible: r.top >= box.top - 1 && r.top + 40 <= floor };
    }""")
    check("…and it is in view, not below the fold, even from the bottom of the form",
          bool(in_view and in_view["visible"]), str(in_view))
    text = review.inner_text() if review else ""
    check("…naming the patient already on file",
          existing["last_name"] in text and existing["profile_number"] in text, text[:200])
    check("…and saying why they matched", "Same ID number" in text, text[:200])
    check("…with the choice to register made explicit",
          page.locator(".modal .modal-actions").get_by_role(
              "button", name=re.compile("different person")).count() == 1)
    if SHOT:
        page.screenshot(path=str(SHOT / "dup-review.png"))

    # ---- it is them: nothing new is saved ------------------------------------
    page.locator(".dup-item").first.get_by_role("button", name="Use this patient").click()
    page.wait_for_timeout(1500)
    check("\"Use this patient\" closes the form", page.query_selector(".dup-review") is None)
    after_use = len(api(f"/api/patients?q={existing['last_name']}&limit=200", token=token))
    check("…and saves nothing new", after_use == count_before, f"{count_before} -> {after_use}")

    # ---- a different person: registered, numbered, flagged -------------------
    open_new(page)
    page.locator(".modal .modal-actions").get_by_role("button", name="Add patient").click()
    page.wait_for_timeout(1500)
    page.locator(".modal .modal-actions").get_by_role(
        "button", name=re.compile("different person")).click()
    page.wait_for_timeout(2000)
    toast = page.locator(".toast").last.inner_text() if page.locator(".toast").count() else ""
    check("registering a different person says their new profile number",
          bool(NUMBER.search(toast)), toast)
    fresh = next((p for p in api(f"/api/patients?q={existing['last_name']}&limit=200", token=token)
                  if p["first_name"] == "Nyasha" and p.get("possible_duplicate_of_id") == existing["id"]),
                 None)
    check("…and they are saved, flagged against the patient they matched", fresh is not None)

    if fresh:
        page.goto(f"{BASE}/patients/{fresh['id']}", wait_until="networkidle")
        page.wait_for_timeout(1800)
        check("their page shows their profile number",
              fresh["profile_number"] in page.inner_text(".page-head"), fresh["profile_number"])
        flag = page.query_selector(".dup-flag")
        check("…and the notice that they matched somebody, with a link to that record",
              flag is not None and flag.query_selector(f"a[href='/patients/{existing['id']}']") is not None)
        if SHOT:
            page.screenshot(path=str(SHOT / "dup-flagged.png"))

    # ---- numbers where staff look -----------------------------------------
    page.goto(BASE + "/patients", wait_until="networkidle")
    page.wait_for_timeout(1800)
    list_text = page.inner_text("table")
    check("the patient list shows profile numbers", len(NUMBER.findall(list_text)) >= 5,
          f"{len(NUMBER.findall(list_text))} found")

    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(1800)
    page.fill("[data-hk='patient']", existing["last_name"])
    page.wait_for_timeout(1600)
    picks = page.inner_text("#step-patient") if page.query_selector("#step-patient") else ""
    check("the dispensary's patient search shows profile numbers",
          existing["profile_number"] in picks, picks[:200])
    if SHOT:
        page.screenshot(path=str(SHOT / "dup-dispensary-search.png"))

    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
