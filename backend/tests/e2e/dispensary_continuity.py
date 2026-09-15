"""Four things a dispenser hit, each measured rather than eyeballed.

  1  A controlled line is a controlled line whatever tab you are on.

     The server asks for the compliance record from the highest schedule on the
     script. The screen asked from the route tab. Those two disagree whenever a
     script holds a controlled line and is opened from a worklist row that does
     not — the row carries one line's schedule, `openQueued` loads all of them —
     and that is a real script in the queue, not a contrivance: the dispenser
     lands on Prescription with a Schedule 5 line on the table. The old build
     then showed no compliance section, stripped those fields from the payload,
     left the button enabled, and was refused by the server with

       "Prescription preparation - Tenth Schedule requires: patient identity
        verification, original prescription sighted, prescriber verification."

     naming three things there was nowhere on screen to give. Reproduced here
     through that exact path, then dispensed through to a sale.

  2  The button that dispenses is the height of the button beside it.

  3  Walking away and coming back: the capture is still there, and the
     compliance ticks are NOT — those are somebody's statement that they
     checked something, not typing.

  4  Double-clicking an empty row of the table starts the medicine search.

The mixed script it needs is created through the API first, so the test carries
its own fixture rather than hoping the queue holds one.

Run against a local dev server on :4177 and API on :8099:
  python dispensary_continuity.py [screenshot-dir]
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

LINES = ".disp-grid > .rx-item:not(.rx-item-waiting)"
NL = "String.fromCharCode(10)"


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def api(path, data=None, token=None):
    req = urllib.request.Request(API + path, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    body = json.dumps(data).encode() if data else None
    with urllib.request.urlopen(req, body, timeout=30) as f:
        return json.loads(f.read() or b"null")


def make_mixed_script():
    """A script holding an ordinary line and a controlled one, as the queue has."""
    token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
    patient = api("/api/patients?q=Andela&limit=3", token=token)[0]
    doctors = api("/api/doctors?limit=3", token=token)
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    ordinary = api("/api/dispensing/products?route=prescription&q=amlo", token=token)[0]
    controlled = [p for p in api("/api/dispensing/products?route=controlled&limit=10", token=token)
                  if (p.get("schedule") or 0) >= 5][0]
    line = {"quantity": 10, "dosage_instructions": "One twice a day", "repeats_allowed": 0,
            "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}
    rx = api("/api/prescriptions", {
        "patient_id": patient["id"], "doctor_id": doctor["id"],
        "notes": "mixed schedule; the worklist row is the ordinary line",
        "items": [{**line, "product_id": ordinary["id"]},
                  {**line, "product_id": controlled["id"], "quantity": 5}],
    }, token=token)
    return patient, ordinary, controlled, rx


def sign_in(page):
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)


def open_dispensary(page):
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(2000)


def script_state(page):
    return page.evaluate("""() => ({
      tab: (document.querySelector('.disp-routes button.active') || {}).innerText || '?',
      lines: [...document.querySelectorAll('""" + LINES + """ .rx-item-name')]
        .map((e) => e.innerText.split(""" + NL + """).join(' ').trim().slice(0, 40)),
      patient: (document.querySelector('.disp-patient-picked') || {}).innerText || '',
    })""")


patient, ordinary, controlled, rx = make_mixed_script()
print(f"  fixture: {rx.get('rx_number')} — {ordinary['name']} S{ordinary.get('schedule')} "
      f"+ {controlled['name']} S{controlled.get('schedule')} for "
      f"{patient.get('first_name')} {patient.get('last_name')}")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 900}, color_scheme="dark")
    sign_in(page)
    open_dispensary(page)

    # ---- 4 · double-clicking an empty row starts the work -----------------------
    check("the table starts empty", len(page.query_selector_all(LINES)) == 0)
    page.dblclick(".disp-grid > .rx-waiting")
    page.wait_for_timeout(400)
    check("double-clicking an empty row puts the cursor in the medicine search",
          page.evaluate("document.activeElement && document.activeElement.getAttribute('data-hk')")
          == "product")

    # ---- 1 · the worklist row that does not carry the controlled line -----------
    rows = page.evaluate("[...document.querySelectorAll('.wl-row')]"
                         ".map((e) => e.innerText.split(" + NL + ").join(' / '))")
    # This script's own row, found by its prescription id in the order the
    # worklist returns — the order the panel draws. Matching by patient and
    # medicine picked the first Andela + Amlodipine row in the queue, which once
    # other suites had left single-line Amlodipine scripts for the same patient
    # was one of theirs: it opened with one line, and the test blamed the
    # dispensary for a script it had not been given.
    token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
    queue = api("/api/dispensary/worklist", token=token)["queue"]
    wanted = [i for i, r in enumerate(queue)
              if r["prescription_id"] == rx["id"] and r["schedule"] < 5 and i < len(rows)]
    check("the queue offers the ordinary line of the mixed script", bool(wanted),
          f"{rx.get('rx_number')} not among the {len(rows)} rows on show")

    if wanted:
        page.query_selector_all(".wl-row")[wanted[0]].click()
        page.wait_for_timeout(3200)
        st = script_state(page)
        check("opening it loads every line on the script, controlled one included",
              len(st["lines"]) >= 2, str(st))
        check("…while the route tab reads Prescription — the state that was refused",
              st["tab"].strip().startswith("Prescription"), str(st["tab"]))
        if SHOT:
            page.screenshot(path=str(SHOT / "continuity-worklist.png"))

        go = page.query_selector(".disp-bar .disp-go")
        check("Finish is offered", bool(go) and not go.is_disabled())
        page.click(".disp-bar .disp-go")
        page.wait_for_timeout(1400)
        proceed = page.query_selector(".disp-finish .fin-proceed")
        if proceed and not proceed.is_disabled():
            proceed.click()
            page.wait_for_timeout(1000)

        check("on the Prescription tab, the controlled line still asks for its "
              "compliance record", page.query_selector("#finish-compliance") is not None)
        check("…and the dialog lays itself out as a controlled one",
              "is-controlled" in (page.evaluate(
                  "(document.querySelector('.disp-finish') || {}).className || ''")))
        if SHOT:
            page.screenshot(path=str(SHOT / "continuity-compliance.png"))

        # ---- 2 · the two buttons in the foot are one control tall --------------
        pair = page.evaluate("""() => {
          const foot = document.querySelector('.disp-finish .finish-foot');
          const back = foot.querySelector('.btn.secondary');
          const go = foot.querySelector('.fin-dispense');
          const r = (e) => Math.round(e.getBoundingClientRect().height);
          return { back: r(back), dispense: r(go),
                   control: getComputedStyle(document.documentElement)
                              .getPropertyValue('--control').trim(),
                   sameLine: Math.abs(back.getBoundingClientRect().top
                                      - go.getBoundingClientRect().top) <= 1,
                   sub: (go.querySelector('.fin-dispense-sub') || {}).textContent || '' };
        }""")
        check("the dispense button is the height of the button beside it",
              pair["back"] == pair["dispense"], f"back {pair['back']}px, "
              f"dispense {pair['dispense']}px")
        check("…which is the height every other control uses",
              f"{pair['dispense']}px" == pair["control"], str(pair))
        check("…they sit on one line", pair["sameLine"], str(pair))
        check("…and it still says what it will print", pair["sub"].strip() != "", str(pair))

        # Everything the record asks for, then dispense it for real.
        boxes = page.query_selector_all("#finish-compliance input[type=checkbox]")
        check("the record asks for the verifications the pack names", len(boxes) > 0,
              str(len(boxes)))
        for b in boxes:
            if not b.is_checked():
                b.click()
                page.wait_for_timeout(150)
        init = page.query_selector("#finish-initials")
        if init:
            init.fill("SM")
            page.wait_for_timeout(250)

        go = page.query_selector(".disp-finish .fin-dispense")
        check("with the record complete, the dispense button is live",
              bool(go) and not go.is_disabled())
        if go and not go.is_disabled():
            go.click()
            page.wait_for_timeout(6000)
            body = page.inner_text("body")
            check("the server does not refuse it for a missing compliance record",
                  "requires:" not in body, body[body.find("requires:") - 60:][:180]
                  if "requires:" in body else "")
            check("the script goes out and the table clears",
                  len(page.query_selector_all(LINES)) == 0,
                  f"{len(page.query_selector_all(LINES))} lines left")
            check("dispensing clears what was kept for coming back to",
                  page.evaluate("sessionStorage.getItem('rx5000_script_draft')") is None)
            if SHOT:
                page.screenshot(path=str(SHOT / "continuity-dispensed.png"))

    # ---- 3 · walking away and coming back ---------------------------------------
    open_dispensary(page)
    page.fill("[data-hk='patient']", "Andela")
    page.wait_for_timeout(1600)
    page.query_selector_all("#step-patient .product-pick")[0].click()
    page.wait_for_timeout(1600)
    page.fill("#disp-doctor", "Dr")
    page.wait_for_timeout(700)
    docs = page.query_selector_all("#step-patient .doc-pick")
    if docs:
        docs[0].click()
    page.wait_for_timeout(500)
    page.fill("[data-hk='product']", "amlo")
    page.wait_for_timeout(1600)
    hits = page.query_selector_all("#step-items .product-pick")
    check("a medicine to walk away from", bool(hits))
    if hits:
        hits[0].click()
        page.wait_for_timeout(900)
        add = page.query_selector(".disp-edit .disp-edit-actions .btn.primary")
        if add:
            add.click()
            page.wait_for_timeout(1500)

    before = script_state(page)
    check("there is a part-typed script to lose", bool(before["lines"]), str(before))

    page.goto(BASE + "/stock", wait_until="networkidle")
    page.wait_for_timeout(1800)
    check("it is kept while away from the screen",
          page.evaluate("sessionStorage.getItem('rx5000_script_draft')") is not None)

    open_dispensary(page)
    page.wait_for_timeout(2200)
    after = script_state(page)
    check("coming back, the lines are exactly as they were",
          after["lines"] == before["lines"] and after["lines"] != [],
          f"{before['lines']} -> {after['lines']}")
    check("coming back, the patient is still on the script",
          after["patient"].strip() == before["patient"].strip() and after["patient"].strip() != "",
          f"{before['patient']!r} -> {after['patient']!r}")
    if SHOT:
        page.screenshot(path=str(SHOT / "continuity-restored.png"))

    kept = page.evaluate("JSON.parse(sessionStorage.getItem('rx5000_script_draft') || '{}')")
    check("what is kept holds no compliance ticks and no initials",
          not any(k in kept for k in
                  ("idVerified", "scriptSighted", "prescriberVerified", "initials")),
          str(sorted(kept.keys())))

    page.keyboard.press("Escape")
    page.wait_for_timeout(800)
    check("clearing the script leaves nothing to come back to",
          page.evaluate("sessionStorage.getItem('rx5000_script_draft')") is None)

    page.close()
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
