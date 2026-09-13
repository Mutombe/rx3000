"""The lane, the Initials field and the script number — measured.

  1  Checked by. The field says what it is while nobody is typing, what to
     type once somebody is, carries the whole sentence for anyone who hovers,
     and signs itself when it holds something. No separate label: the field is
     the label.

  2  The lane is containered like the route tabs — a sunken ground, a hairline
     edge, 3px of padding — with one difference. The tabs' well shrinks to fit
     what is in it; this band keeps its width and the three fields grow to
     meet it, so the patient is the biggest target on the row rather than a
     30px chip in a 38px slot.

  3  The script number is on screen when the dispensary opens, matches what
     the server would issue, and moves to the next one after a dispensing.

Run against a local dev server on :4177 and API on :8099:
  python dispensary_lane_and_number.py [screenshot-dir]
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
LINES = ".disp-grid > .rx-item:not(.rx-item-waiting)"
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
    body = json.dumps(data).encode() if data else None
    with urllib.request.urlopen(req, body, timeout=30) as f:
        return json.loads(f.read() or b"null")


token = api("/api/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
server_says = api("/api/prescriptions/next-number", token=token)["number"]
print(f"  the server would issue: {server_says}")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 900}, color_scheme="dark")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(2200)

    # ---- 3 · the number is there on open ---------------------------------------
    shown = page.inner_text(".disp-scriptid-no").strip()
    check("the script number is on screen when the dispensary opens",
          bool(re.fullmatch(r"RX\d{6,}", shown)), f"reads {shown!r}")
    check("…and it is the number the server would issue", shown == server_says,
          f"screen {shown!r}, server {server_says!r}")
    check("…shown as a number, not as the words it replaced",
          "is-number" in (page.get_attribute(".disp-scriptid-no", "class") or ""))

    # ---- 2 · the lane, containered like the route tabs --------------------------
    well = page.evaluate("""() => {
      const band = document.querySelector('.card.sec-patient');
      const tabs = document.querySelector('.disp-head .disp-routes');
      const b = getComputedStyle(band), t = getComputedStyle(tabs);
      return {
        ground: b.backgroundColor === t.backgroundColor,
        padding: b.padding,
        tabsPadding: t.padding,
        corners: b.borderTopLeftRadius === t.borderTopLeftRadius,
        edged: parseFloat(b.borderTopWidth) >= 1,
      };
    }""")
    check("the lane sits on the same sunken ground as the route tabs", well["ground"], str(well))
    check("…with the tabs' tight padding", well["padding"] == well["tabsPadding"],
          f"lane {well['padding']}, tabs {well['tabsPadding']}")
    check("…the same corners and a hairline edge", well["corners"] and well["edged"], str(well))

    def lane_boxes():
        return page.evaluate("""() => {
          const band = document.querySelector('.card.sec-patient');
          const bb = band.getBoundingClientRect();
          const pad = parseFloat(getComputedStyle(band).paddingRight);
          const f = [...band.children].filter((e) => e.classList.contains('lane-field'));
          return {
            heights: f.map((e) => Math.round(e.getBoundingClientRect().height)),
            names: f.map((e) => e.className.split(' ').filter((c) => c.startsWith('disp-')).join('')),
            // The rightmost field, not the last one written: the prescriber is
            // last in the document and sits in the middle column, so measuring
            // document order reports a third of the band as a shortfall.
            rightGap: f.length
              ? Math.round(bb.right - pad
                           - Math.max(...f.map((e) => e.getBoundingClientRect().right)))
              : null,
          };
        }""")

    b = lane_boxes()
    check("the three fields on the lane are one height", len(set(b["heights"])) == 1, str(b))
    check("…and it is a big one — bigger than the 30px chip it replaces",
          b["heights"] and b["heights"][0] >= 38, str(b["heights"]))
    check("…the fields grow out to the band's own border",
          b["rightGap"] is not None and abs(b["rightGap"]) <= 2,
          f"{b['rightGap']}px short of the edge")

    widest = page.evaluate("""() => {
      const band = document.querySelector('.card.sec-patient');
      const f = [...band.children].filter((e) => e.classList.contains('lane-field'));
      const w = (part) => {
        const e = f.find((x) => x.className.includes(part));
        return e ? Math.round(e.getBoundingClientRect().width) : null;
      };
      return { patient: w('disp-patient'), prescriber: w('disp-doctor'),
               medicine: w('disp-medicine') };
    }""")
    check("the patient is the widest thing on the lane — it is what a dispenser "
          "checks first and last",
          bool(widest["patient"] and widest["prescriber"])
          and widest["patient"] > widest["prescriber"]
          and widest["patient"] > (widest["medicine"] or 0), str(widest))

    # ---- 1 · Checked by --------------------------------------------------------
    init = page.query_selector("#disp-initials")
    check("the Initials field is on the bar", init is not None)
    if init:
        check("at rest the field says what it is",
              init.get_attribute("placeholder") == "Checked by",
              repr(init.get_attribute("placeholder")))
        check("…and carries the whole sentence for anyone who hovers",
              "checked this dispensing" in (init.get_attribute("title") or ""),
              repr(init.get_attribute("title")))
        check("…with no separate label repeating it", page.evaluate(
            "!document.querySelector('label[for=\\'disp-initials\\']')"))
        init.click()
        page.wait_for_timeout(300)
        check("with the cursor in it, it says what to type",
              init.get_attribute("placeholder") == "Your initials, e.g. TM",
              repr(init.get_attribute("placeholder")))
        if SHOT:
            page.screenshot(path=str(SHOT / "lane-initials-focus.png"))
        init.fill("tm")
        page.wait_for_timeout(300)
        signed = page.evaluate("""() => {
          const f = document.querySelector('.disp-initials');
          const i = f.querySelector('input');
          const ic = f.querySelector('.lane-icon');
          return { value: i.value, signed: f.classList.contains('is-signed'),
                   mono: getComputedStyle(i).fontFamily,
                   tick: ic ? getComputedStyle(ic).color : null,
                   ok: getComputedStyle(document.documentElement).getPropertyValue('--ok').trim() };
        }""")
        check("what is typed is kept as initials", signed["value"] == "TM", str(signed["value"]))
        check("…and the field signs itself once it holds something", signed["signed"], str(signed))
        page.evaluate("document.querySelector('#disp-initials').blur()")
        page.wait_for_timeout(200)
        check("…and says what it is again once the cursor leaves",
              page.get_attribute("#disp-initials", "placeholder") == "Checked by")

    if SHOT:
        page.screenshot(path=str(SHOT / "lane-empty.png"))

    # ---- the lane with a patient on it, and a dispensing ------------------------
    page.fill("[data-hk='patient']", "Andela")
    page.wait_for_timeout(1600)
    picks = page.query_selector_all("#step-patient .product-pick")
    check("a patient to put on the lane", bool(picks))
    if picks:
        picks[0].click()
        page.wait_for_timeout(1600)
        picked = page.evaluate("""() => {
          const band = document.querySelector('.card.sec-patient');
          const who = band.querySelector('.disp-patient-picked');
          const med = band.querySelector('.disp-medicine');
          const r = (e) => e ? Math.round(e.getBoundingClientRect().height) : null;
          return { patient: r(who), medicine: r(med),
                   name: who ? getComputedStyle(who.querySelector('.dpp-who')).fontSize : null };
        }""")
        check("the chosen patient fills the same height as the medicine search",
              picked["patient"] is not None and picked["patient"] == picked["medicine"],
              str(picked))
        check("…and reads larger than the rest of the lane",
              picked["name"] and float(picked["name"].replace("px", "")) >= 14, str(picked))

        # The chip drops the ID first when it runs out of room — it wraps to a
        # second line the 20px chip then clips. That is the right behaviour and
        # the wrong outcome here: the ID is what a dispenser checks a patient
        # by, and this band exists to make the patient bigger, not to squeeze
        # the identifying half of it off the row.
        idline = page.evaluate("""() => {
          const chip = document.querySelector('.disp-patient-picked');
          const name = chip.querySelector('.cell-text > b');
          const id = chip.querySelector('.cell-text > .muted');
          if (!name || !id) return null;
          const n = name.getBoundingClientRect(), i = id.getBoundingClientRect();
          return { name: name.innerText.trim(), id: id.innerText.trim(),
                   sameLine: Math.abs(n.top - i.top) <= 2,
                   idWidth: Math.round(i.width) };
        }""")
        check("the patient's ID stays beside the name rather than wrapping out of sight",
              bool(idline) and idline["sameLine"] and idline["idWidth"] > 0, str(idline))
        if SHOT:
            page.screenshot(path=str(SHOT / "lane-picked.png"))

        page.fill("#disp-doctor", "Dr")
        page.wait_for_timeout(800)
        docs = page.query_selector_all("#step-patient .doc-pick")
        if docs:
            docs[0].click()
            page.wait_for_timeout(500)
        page.fill("[data-hk='product']", "amlo")
        page.wait_for_timeout(1600)
        hits = page.query_selector_all("#step-items .product-pick")
        if hits:
            hits[0].click()
            page.wait_for_timeout(900)
            add = page.query_selector(".disp-edit .disp-edit-actions .btn.primary")
            if add:
                add.click()
                page.wait_for_timeout(1500)

        before = page.inner_text(".disp-scriptid-no").strip()
        go = page.query_selector(".disp-bar .disp-go")
        if go and not go.is_disabled() and len(page.query_selector_all(LINES)) > 0:
            go.click()
            page.wait_for_timeout(1400)
            proceed = page.query_selector(".disp-finish .fin-proceed")
            if proceed and not proceed.is_disabled():
                proceed.click()
                page.wait_for_timeout(1000)
            fi = page.query_selector("#finish-initials")
            if fi:
                check("the Finish dialog's Initials field says the same thing",
                      fi.get_attribute("placeholder") == "Checked by",
                      repr(fi.get_attribute("placeholder")))
                fi.fill("TM")
                page.wait_for_timeout(300)
            dispense = page.query_selector(".disp-finish .fin-dispense")
            if dispense and not dispense.is_disabled():
                dispense.click()
                page.wait_for_timeout(6000)
                # Dispensing leaves for the till, which is where the patient
                # settles. Coming back to the dispensary is the moment the next
                # number has to be waiting — which is the whole ask.
                page.goto(BASE + "/dispense", wait_until="networkidle")
                page.wait_for_timeout(2400)
                after = page.inner_text(".disp-scriptid-no").strip()
                server_now = api("/api/prescriptions/next-number", token=token)["number"]
                check("dispensing moves the header to the next number", after != before,
                      f"{before} -> {after}")
                check("…which is the one the server would now issue", after == server_now,
                      f"screen {after!r}, server {server_now!r}")
                if SHOT:
                    page.screenshot(path=str(SHOT / "lane-after-dispense.png"))
            else:
                print("  --    could not reach the dispense button; the number was not exercised")

    page.close()
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
