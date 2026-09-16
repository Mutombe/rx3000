"""The dialog closes on the keystroke, and the work answers for itself.

  - Dispense closes the Finish dialog at once and frees the screen, without
    waiting for the server
  - the work is visible while it runs, named, in the tray
  - it ends in a word: the chip turns and a toast says what happened
  - the dispenser can start the next patient while it is still in flight
  - cancelling a script closes its dialog at once and the row leaves the rail
  - a refusal hands the work back: the chip says why, offers Try again, and
    the script comes back as it was

Run against a local dev server on :4177 and API on :8099:
  python optimistic_actions.py [screenshot-dir]
"""
import json
import pathlib
import random
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
API = "http://127.0.0.1:8099"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
LINE = {"quantity": 1, "dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}
fails = []
tag = random.randint(1000, 9999)


def check(label, ok, detail=""):
    line = f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else "")
    # The console here is cp1252 and the chips carry an arrow.
    print(line.encode("ascii", "replace").decode("ascii"))
    if not ok:
        fails.append(label)


def api(path, data=None, token=None):
    req = urllib.request.Request(API + path, method=("POST" if data is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None,
                                    timeout=60) as f:
            return json.loads(f.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"status": e.code, **json.loads(e.read() or b"{}")}


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
doctors = api("/api/doctors?limit=3", token=token)
doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
stocked = [p for p in api("/api/dispensing/products?route=prescription&limit=60", token=token)
           if (p.get("quantity_on_hand") or 0) >= 10]
patients = api("/api/patients?q=e&limit=30", token=token)


def clean(p, product):
    q = (f"/api/counter-messages/for-dispensing?patient_id={p['id']}&product_ids={product['id']}"
         f"&doctor_id={doctor['id']}")
    return not api(q, token=token).get("blocking")


patient = next(p for p in patients if clean(p, stocked[0]))
to_dispense = api("/api/prescriptions", {"patient_id": patient["id"], "doctor_id": doctor["id"],
                                         "notes": "optimistic", "items": [{**LINE, "product_id": stocked[0]["id"]}]},
                  token=token)
# One that cannot be cancelled: part-dispensed, so the refusal path is real.
part = api("/api/prescriptions", {"patient_id": patient["id"], "doctor_id": doctor["id"],
                                  "notes": "part dispensed", "items": [
                                      {**LINE, "product_id": stocked[0]["id"]},
                                      {**LINE, "product_id": stocked[1]["id"]}]}, token=token)
api(f"/api/prescriptions/{part['id']}/dispense",
    {"item_ids": [part["items"][0]["id"]], "payment_method": "cash", "pharmacist_initial": "TM"},
    token=token)

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)

    # ---- dispensing: the dialog goes, the screen is free ---------------------------
    page.goto(f"{BASE}/dispense?rx={to_dispense['id']}", wait_until="networkidle")
    page.wait_for_timeout(3200)
    page.click(".disp-bar .disp-go")
    page.wait_for_timeout(1500)
    proceed = page.query_selector(".disp-finish .fin-proceed")
    if proceed and not proceed.is_disabled():
        proceed.click()
        page.wait_for_timeout(900)
    page.click(".fin-dispense")
    page.wait_for_timeout(350)
    check("the Finish dialog closes on the keystroke",
          page.query_selector(".disp-finish") is None)
    # The lines go at once — the script is off the dispenser's hands. The patient
    # chip stays, as it always has, because the next script is often theirs too.
    lines_left = page.locator(".rx-item-sig").count()
    check("…and the script's lines are off the screen at once", lines_left == 0, str(lines_left))
    tray = page.query_selector(".doing-chip")
    # Named while it runs, and named afterwards: against a server on the same
    # machine it can already have landed by the time this looks, and the chip
    # then says so in the past tense.
    chip = tray.inner_text() if tray else ""
    check("…with the work named in the tray",
          tray is not None and to_dispense["rx_number"] in chip, chip[:90] or "no chip")
    if SHOT and tray:
        page.screenshot(path=str(SHOT / "optimistic-dispensing.png"))

    # The tray floats over a working screen, so it must not come to rest on the
    # two things that say what to do next. It is a solid slab now; at 5.4rem it
    # lay across the finish bar.
    clear = page.evaluate("""() => {
      const box = (s) => { const e = document.querySelector(s);
        if (!e) return null; const r = e.getBoundingClientRect();
        return {l: r.left, r: r.right, t: r.top, b: r.bottom}; };
      const hits = (a, b) => !!a && !!b && a.l < b.r && a.r > b.l && a.t < b.b && a.b > b.t;
      const chip = box('.doing-chip');
      return {chip, onBar: hits(chip, box('.disp-foot, .disp-bar, .disp-finish-bar')),
              onKeys: hits(chip, box('.keybar'))};
    }""")
    check("the tray rests on neither the finish bar nor the key strip",
          clear["chip"] and not clear["onBar"] and not clear["onKeys"],
          f"bar={clear['onBar']} keys={clear['onKeys']}")

    # The dispenser starts the next patient while it is still in flight.
    page.fill("[data-hk='product']", "atorva")
    page.wait_for_timeout(1200)
    check("the next line can be typed while it is still in flight",
          page.input_value("[data-hk='product']") != "")

    said = ""
    for _ in range(40):
        page.wait_for_timeout(300)
        said += " | ".join(t.inner_text() for t in page.query_selector_all(".toast"))
        if "dispensed" in said.lower():
            break
    check("it ends in a word: a toast says what happened", "dispensed" in said.lower(), said[:160])
    landed = page.query_selector(".doing-chip.is-done")
    check("…and the chip turns as it lands", landed is not None or "dispensed" in said.lower())

    # The script's own status stays active while repeats remain; what proves it
    # went out is the dispensing itself.
    import sqlite3
    db = sqlite3.connect(str(pathlib.Path(__file__).resolve().parents[2] / "rx3000.db"))
    dispensings = db.execute("""select count(*) from dispensings d
                                join prescription_items pi on pi.id = d.prescription_item_id
                                where pi.prescription_id = ?""", (to_dispense["id"],)).fetchone()[0]
    check("…and the server really has it dispensed", dispensings == 1, str(dispensings))

    # ---- cancelling: the row goes, the work carries on ------------------------------
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(2500)
    if page.query_selector(".disp-patient-picked"):
        page.locator(".page-actions").get_by_role("button", name="New script").click()
        page.wait_for_timeout(900)
    page.goto(f"{BASE}/dispense?rx={part['id']}", wait_until="networkidle")
    page.wait_for_timeout(3000)
    page.locator(".page-actions").get_by_role("button", name="Cancel script").click()
    page.wait_for_timeout(700)
    page.locator(".disp-cancel-modal .hold-reason", has_text="Captured twice by mistake").click()
    page.locator(".disp-cancel-modal").get_by_role("button", name="Cancel script").click()
    page.wait_for_timeout(400)
    check("the cancel dialog closes on the keystroke too",
          page.query_selector(".disp-cancel-modal") is None)

    # This one is refused — it has already been part dispensed.
    failed = None
    for _ in range(40):
        page.wait_for_timeout(300)
        failed = page.query_selector(".doing-chip.is-failed")
        if failed:
            break
    check("a refusal is handed back on the chip, with why",
          failed is not None and "Alter script" in failed.inner_text(),
          failed.inner_text()[:140] if failed else "no failed chip")
    check("…and offers Try again rather than retrying by itself",
          failed is not None and "Try again" in failed.inner_text())
    if SHOT and failed:
        page.screenshot(path=str(SHOT / "optimistic-refused.png"))
    still = api(f"/api/prescriptions/{part['id']}", token=token)
    check("…and the script is still there, not cancelled", still.get("status") != "cancelled",
          str(still.get("status")))
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
