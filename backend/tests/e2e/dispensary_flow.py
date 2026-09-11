"""The dispensary flow, end to end, in a real browser.

Measures what the change claims, not what it renders:

  the columns are single unbroken rules, from the headings to the floor;
  deleting the last line takes the totals row with it;
  the shield checks on the first press and opens the detail on the second;
  the pencil opens the editor, the bin deletes;
  Escape closes a dialog without clearing the script behind it;
  Escape on the direction-code list does not close the editor it is in;
  Finish opens with payment in it and Dispense on screen;
  and nothing on the page scrolls, at a laptop size and a till size.

Run against a local preview: python dispensary_flow.py [screenshot-dir]
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


# A column is unbroken when, for every pair of consecutive rows, its cell in the
# lower row starts where the one above ends (allowing the 1–2px of the row rule
# between them) at the same x, with a solid left border.
RULES_JS = """() => {
  const grid = document.querySelector('.disp-grid');
  const g = grid.getBoundingClientRect();
  const foot = grid.querySelector('.st-foot');
  const floor = foot ? foot.getBoundingClientRect().top : g.bottom - 1;
  // Only what is on show: the waiting rows past the floor are clipped by design.
  const rows = [...grid.querySelectorAll('.rx-item-cols, .rx-item > .rx-item-head')]
    .filter((r) => r.getBoundingClientRect().top < floor - 1);
  const broken = [];
  for (let c = 1; c < 6; c++) {
    for (let r = 0; r + 1 < rows.length; r++) {
      const a = rows[r].children[c], b = rows[r + 1].children[c];
      if (!a || !b) { broken.push(`row ${r} col ${c} missing`); continue; }
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const gap = rb.top - ra.bottom;
      if (gap > 2.5 || Math.abs(ra.left - rb.left) > 1)
        broken.push(`col ${c} rows ${r}/${r + 1}: gap ${gap.toFixed(1)} dx ${(rb.left - ra.left).toFixed(1)}`);
      const st = getComputedStyle(a);
      if (st.borderLeftStyle !== 'solid' || parseFloat(st.borderLeftWidth) < 1)
        broken.push(`col ${c} row ${r}: border ${st.borderLeftStyle} ${st.borderLeftWidth}`);
    }
  }
  const last = rows[rows.length - 1].getBoundingClientRect();
  // Reaching the floor, or running under it and being clipped there, both count.
  // A table that has to scroll to show rows with nothing in them does not.
  const scrolls = grid.scrollHeight > grid.clientHeight + 1;
  return { rows: rows.length, broken: broken.slice(0, 6),
           toFloor: Math.round(Math.max(0, floor - last.bottom)) + (scrolls ? 999 : 0) };
}"""

SCROLLS_JS = "() => document.documentElement.scrollHeight > window.innerHeight + 2"
LINES = ".disp-grid > .rx-item:not(.rx-item-waiting)"


def line_count(page):
    return len(page.query_selector_all(LINES))


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for w, h in ((1512, 900), (1366, 768)):
        print(f"\n  {w}x{h}")
        page = browser.new_page(viewport={"width": w, "height": h}, color_scheme="dark")
        page.goto(BASE, wait_until="networkidle")
        page.fill("#lg-user", "admin")
        page.fill("#lg-pass", "admin123")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_timeout(2200)
        page.goto(BASE + "/dispense", wait_until="networkidle")
        page.wait_for_timeout(1500)
        shots = SHOT is not None and w == 1512

        # ---- empty ----------------------------------------------------------
        m = page.evaluate(RULES_JS)
        check("empty: columns are unbroken rules", not m["broken"], "; ".join(m["broken"]))
        check("empty: the rules reach the floor of the table", abs(m["toFloor"]) <= 2,
              f"{m['toFloor']}px short")
        check("empty: no totals row", page.query_selector(".st-foot") is None)
        heads = page.evaluate(
            "[...document.querySelectorAll('.rx-item-cols > *')].map(e => e.textContent.trim()).join('|')")
        check("empty: the headings end in Action",
              heads == "Medicine|Qty|Directions|Amount|Margin|Action", heads)
        check("empty: the page does not scroll", not page.evaluate(SCROLLS_JS))
        lane0 = page.evaluate("""() => {
          const top = (s) => Math.round(document.querySelector('.sec-patient ' + s).getBoundingClientRect().top);
          return { tops: [top('.disp-patient-field'), top('.disp-doctor'), top('.disp-medicine')],
                   lane: Math.round(document.querySelector('.sec-patient').getBoundingClientRect().height) };
        }""")
        check("empty: patient, prescriber and medicine share one row",
              max(lane0["tops"]) - min(lane0["tops"]) <= 2, str(lane0["tops"]))
        check("empty: the lane is one row high", lane0["lane"] <= 64, f"{lane0['lane']}px")
        check("no line joins the lane to the worklist", page.evaluate(
            "parseFloat(getComputedStyle(document.querySelector('.disp-head')).borderBottomWidth) === 0"))
        kb = page.evaluate("""() => {
          const k = document.querySelector('.keybar'), b = document.querySelector('.disp-bar');
          const ks = getComputedStyle(k), kr = k.getBoundingClientRect(), br = b.getBoundingClientRect();
          return { top: parseFloat(ks.borderTopWidth), bottom: parseFloat(ks.borderBottomWidth),
                   gap: Math.round(kr.top - br.bottom), below: Math.round(window.innerHeight - kr.bottom) };
        }""")
        check("the key strip has its own border above and below", kb["top"] >= 1 and kb["bottom"] >= 1, str(kb))
        check("…a clean gap from the bar above it", kb["gap"] >= 6, str(kb))
        check("…and sits fully on screen", kb["below"] >= 0, str(kb))
        slabs = page.evaluate(
            "['.sec-patient', '.disp-grid', '.disp-bar', '.wl', '.wl-row']"
            ".map((s) => { const e = document.querySelector(s);"
            " return e ? parseFloat(getComputedStyle(e).borderLeftWidth) : 0; })")
        check("no coloured slab down the left of any section or worklist card",
              all(x <= 1.01 for x in slabs), str(slabs))
        tints = page.evaluate(
            "['.sec-patient', '.disp-bar', '.wl']"
            ".map((s) => getComputedStyle(document.querySelector(s)).backgroundImage)")
        check("the lane, the bar and the worklist keep their own tint", len(set(tints)) == 3, str(tints))

        # The field's name inside the field, an icon at its right end, widths that
        # follow the data, and every name and hint measured against its room.
        FIT = """(sel) => {
          const el = document.querySelector(sel); const cs = getComputedStyle(el);
          const c = document.createElement('canvas').getContext('2d');
          c.font = `500 ${cs.fontSize} ${cs.fontFamily}`;
          const room = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
          return { text: el.placeholder, need: Math.ceil(c.measureText(el.placeholder).width), room: Math.floor(room) };
        }"""
        ui = page.evaluate("""() => {
          const q = (s) => document.querySelector(s);
          const w = (s) => Math.round(q(s).getBoundingClientRect().width);
          return {
            labels: document.querySelectorAll('.sec-patient > .lane-field label').length,
            icons: ['.disp-patient-field', '.disp-doctor', '.disp-medicine'].map((s) => !!q(s + ' .lane-icon')),
            widths: [w('.disp-patient-field'), w('.disp-doctor'), w('.disp-medicine')],
          };
        }""")
        check("lane: no label beside the fields", ui["labels"] == 0, str(ui["labels"]))
        check("lane: each field has its icon at the right end", all(ui["icons"]), str(ui["icons"]))
        check("lane: widths follow the data (patient > prescriber > medicine)",
              ui["widths"][0] > ui["widths"][1] > ui["widths"][2], str(ui["widths"]))
        for sel, label in (("#disp-patient", "Patient"), ("#disp-doctor", "Prescriber"), ("#disp-product", "Medicine")):
            name_fit = page.evaluate(FIT, sel)
            check(f"lane: {label} is named inside its field", name_fit["text"] == label, name_fit["text"])
            check(f"lane: the name '{label}' fits", name_fit["need"] <= name_fit["room"] + 2,
                  f"{name_fit['need']} > {name_fit['room']}")
            page.focus(sel)
            page.wait_for_timeout(200)
            hint = page.evaluate(FIT, sel)
            check(f"lane: clicking {label} shows what to type", hint["text"] not in ("", label), hint["text"])
            check(f"lane: the {label} hint fits the field", hint["need"] <= hint["room"] + 2,
                  f"{hint['need']} > {hint['room']}: {hint['text']!r}")
            page.evaluate("document.activeElement && document.activeElement.blur()")
            page.wait_for_timeout(150)
            check(f"lane: leaving {label} puts its name back", page.evaluate(FIT, sel)["text"] == label)
        if SHOT is not None:
            page.screenshot(path=str(SHOT / f"lane-empty-{w}.png"),
                            clip={"x": 270, "y": 120, "width": (880 if w == 1512 else 730), "height": 70})
        if shots:
            page.screenshot(path=str(SHOT / "flow-empty.png"))

        # ---- a patient, a prescriber, two medicines ---------------------------
        page.fill("[data-hk='patient']", "Andela")   # the box searches from two letters
        page.wait_for_timeout(1500)
        picks = page.query_selector_all("#step-patient .product-pick")
        if picks:
            picks[0].click()
            page.wait_for_timeout(1200)
        # The prescriber is searched like the patient and the medicine, and its
        # matches list full width under the lane, the same as theirs.
        page.fill("#disp-doctor", "Dr")
        page.wait_for_timeout(500)
        opts = page.query_selector_all("#step-patient .doc-pick")
        check("prescriber matches list full width under the lane", bool(opts) and page.evaluate(
            "(() => { const r = document.querySelector('#step-patient .doc-pick').getBoundingClientRect();"
            " const l = document.querySelector('.sec-patient').getBoundingClientRect();"
            " return r.width > l.width * 0.8; })()"))
        if opts:
            opts[0].click()
            page.wait_for_timeout(400)
        check("the picked prescriber sits in the lane like the patient",
              page.query_selector(".lane-field.is-picked.disp-doctor") is not None)
        check("a patient and a prescriber are chosen", bool(picks) and bool(opts),
              f"patients {len(picks)}, doctors {len(opts)}")

        # Picking a patient must not take the screen from the table.
        lane = page.evaluate("""() => {
          const lane = document.querySelector('.sec-patient').getBoundingClientRect();
          const who = document.querySelector('.disp-patient-picked')?.getBoundingClientRect();
          const doc = document.querySelector('.disp-doctor').getBoundingClientRect();
          return { lane: Math.round(lane.height),
                   overlap: !!who && who.right > doc.left + 1,
                   grid: Math.round(document.querySelector('.disp-grid').getBoundingClientRect().height) };
        }""")
        check("with a patient: the lane stays slim", lane["lane"] <= 110, f"{lane['lane']}px")
        check("with a patient: the name does not run into the prescriber", not lane["overlap"])
        check("with a patient: the table keeps the screen",
              lane["grid"] >= (320 if w == 1512 else 220), f"{lane['grid']}px")
        chip = page.query_selector(".disp-patient-picked .lane-tool.is-repeats:not([disabled])")
        if chip:
            chip.click()
            page.wait_for_timeout(900)
            check("the repeats chip opens the list", page.query_selector(".disp-lane-modal .rd-list") is not None)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            check("Escape closes it", page.query_selector(".disp-lane-modal") is None)
        else:
            print("  --    no repeats due for this patient; chip not exercised")

        # The patient box as a toolbar.
        tools = page.evaluate(
            "[...document.querySelectorAll('.disp-patient-picked .lane-tool')].map((b) => b.className)")
        check("the patient box carries its five tools", len(tools) == 5, str(tools))
        check("no chip row under the lane any more", page.query_selector(".disp-context") is None)
        check("the patient box is one field high", page.evaluate(
            "Math.round(document.querySelector('.disp-patient-picked').getBoundingClientRect().height) <= 32"))
        check("the patient's name is not cut off by the tools", page.evaluate(
            "(() => { const b = document.querySelector('.disp-patient-picked .dpp-who b');"
            " return !!b && b.scrollWidth <= b.clientWidth + 1; })()"))
        page.click(".disp-patient-picked .lane-tool.is-history")
        page.wait_for_timeout(1200)
        check("History opens the patient's record of scripts and dispensings",
              page.query_selector(".pt-history .fin-stats") is not None)
        if page.query_selector(".pt-history"):
            page.click(".pt-history .pt-tabs button:has-text('Scripts')")
            page.wait_for_timeout(300)
            check("…and switches to the scripts", page.query_selector(".pt-history .pt-tabs button.on:has-text('Scripts')") is not None)
            if shots:
                page.screenshot(path=str(SHOT / "patient-history.png"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        check("Escape closes History", page.query_selector(".pt-history") is None)
        page.click(".disp-patient-picked .lane-tool.is-details")
        page.wait_for_timeout(500)
        card = page.query_selector(".pt-card")
        check("Details shows who the patient is, with their allergies",
              card is not None and "Andela" in (card.inner_text() or "")
              and page.query_selector(".pt-card .ctx-chip.is-allergy") is not None)
        if card and shots:
            page.screenshot(path=str(SHOT / "patient-card.png"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check("Escape closes Details", page.query_selector(".pt-card") is None)
        if shots:
            page.screenshot(path=str(SHOT / "patient-box.png"), clip={"x": 270, "y": 120, "width": 880, "height": 60})
        if shots:
            page.screenshot(path=str(SHOT / "flow-patient.png"))

        for term in ("amox", "metfor"):
            page.fill("[data-hk='product']", term)
            page.wait_for_timeout(1500)
            hits = page.query_selector_all("#step-items .product-pick")
            if not hits:
                continue
            hits[0].click()
            page.wait_for_timeout(900)
            check(f"adding {term} opens its editor", page.query_selector(".disp-edit .ed-body") is not None)
            page.click(".disp-edit .disp-edit-actions .btn.primary")
            page.wait_for_timeout(500)
        check("two lines on the script", line_count(page) == 2, str(line_count(page)))
        page.wait_for_timeout(1500)
        check("the totals row sits under the lines", page.query_selector(".disp-grid > .st-foot") is not None)
        m = page.evaluate(RULES_JS)
        check("with lines: columns are unbroken rules", not m["broken"], "; ".join(m["broken"]))
        check("with lines: every line carries three action icons", page.evaluate(
            f"[...document.querySelectorAll('{LINES}')].every(r => r.querySelectorAll('.rx-icon').length === 3)"))
        check("with lines: the page does not scroll", not page.evaluate(SCROLLS_JS))
        check("the bar's sentence is readable", page.evaluate(
            "(() => { const s = document.querySelector('.disp-status > p > span, .disp-status > .disp-say > span');"
            " return !s || s.getBoundingClientRect().width > 40; })()"))
        check("the bar's pieces do not overlap", page.evaluate(
            "(() => { const r = [...document.querySelectorAll('.disp-status > *')]"
            ".map((x) => x.getBoundingClientRect()).filter((b) => b.width > 0);"
            " for (let i = 1; i < r.length; i++) if (r[i].left < r[i - 1].right - 1) return false;"
            " return true; })()"))
        check("with a patient: the name is not cut off", page.evaluate(
            "(() => { const b = document.querySelector('.disp-patient-picked .dpp-who b'); if (!b) return true;"
            " return b.scrollWidth <= b.clientWidth + 1; })()"))
        if shots:
            page.screenshot(path=str(SHOT / "flow-lines.png"))

        # ---- the shield ---------------------------------------------------------
        shield = f"{LINES} .rx-icon:first-child"
        check("the shield starts unchecked", "chk-idle" in (page.get_attribute(shield, "class") or ""))
        page.click(shield)
        try:
            page.wait_for_selector(
                f"{LINES} .rx-icon:first-child:is(.chk-clean, .chk-minor, .chk-major, .chk-error)",
                timeout=8000)
        except Exception:
            pass
        cls = page.get_attribute(shield, "class") or ""
        check("pressed once, it checks and shows the answer",
              "chk-idle" not in cls and "chk-loading" not in cls, cls)
        check("…without opening anything", page.query_selector(".disp-check") is None)
        page.click(shield)
        page.wait_for_timeout(500)
        check("pressed on the answer, it opens the detail", page.query_selector(".disp-check") is not None)
        if shots:
            page.screenshot(path=str(SHOT / "flow-check.png"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check("Escape closes the check", page.query_selector(".disp-check") is None)
        check("…and leaves the script alone", line_count(page) == 2, str(line_count(page)))

        # ---- the pencil -----------------------------------------------------------
        page.click(f"{LINES} .rx-icon[title='Edit this line']")
        page.wait_for_timeout(500)
        check("the pencil opens the editor, with its side rail", page.query_selector(".disp-edit .ed-rail") is not None)
        check("the editor shows characters, not escape codes", not page.evaluate(
            r"document.querySelector('.disp-edit').innerText.includes('\\u')"))
        box = page.query_selector(".disp-edit .ed-main .ed-sec:nth-of-type(2) input")
        if box:
            box.click()
            box.type("1")
            page.wait_for_timeout(600)
            if page.query_selector(".disp-edit [role='listbox']"):
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                check("Escape on the code list keeps the editor open", page.query_selector(".disp-edit") is not None)
            else:
                print("  --    no code list appeared for '1'; Escape-on-list not exercised")
            if page.query_selector(".disp-edit"):
                page.fill(".disp-edit .ed-main .ed-sec:nth-of-type(2) input", "")
        if shots and page.query_selector(".disp-edit"):
            page.screenshot(path=str(SHOT / "flow-edit.png"))
        if page.query_selector(".disp-edit"):
            page.click(".disp-edit .disp-edit-actions .btn.primary")
            page.wait_for_timeout(300)
        check("Done closes the editor", page.query_selector(".disp-edit") is None)

        # ---- editing in the table --------------------------------------------------
        MET = f"{LINES}:has-text('Metformin')"
        page.dblclick(f"{MET} .rx-item-qty")
        page.wait_for_timeout(250)
        check("double-clicking Qty edits it in the table", page.query_selector(f"{MET} .rx-item-qty input") is not None)
        page.fill(f"{MET} .rx-item-qty input", "28")
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        check("…Enter keeps it", (page.text_content(f"{MET} .rx-item-qty") or "").strip() == "28",
              page.text_content(f"{MET} .rx-item-qty"))
        page.dblclick(f"{MET} .rx-item-qty")
        page.wait_for_timeout(250)
        page.fill(f"{MET} .rx-item-qty input", "99")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check("…Escape puts it back, and leaves the script alone",
              (page.text_content(f"{MET} .rx-item-qty") or "").strip() == "28" and line_count(page) == 2)

        page.dblclick(f"{MET} .rx-item-sig")
        page.wait_for_timeout(300)
        sig_box = f"{MET} .rx-item-sig input"
        check("double-clicking Directions edits it in the table", page.query_selector(sig_box) is not None)
        if page.query_selector(sig_box):
            page.fill(sig_box, "")
            page.type(sig_box, "1a")
            page.wait_for_timeout(500)
            if page.query_selector(".sig-suggest [role='option']"):
                check("…with the direction codes listed under it, unclipped", page.evaluate(
                    "(() => { const s = document.querySelector('.sig-suggest').getBoundingClientRect();"
                    " const hit = document.elementFromPoint(s.left + s.width / 2, s.top + Math.min(40, s.height / 2));"
                    " return !!hit && !!hit.closest('.sig-suggest'); })()"))
                page.keyboard.press("Escape")
                page.wait_for_timeout(200)
                check("…Escape closes the codes, not the cell", page.query_selector(sig_box) is not None)
            else:
                print("  --    no code suggestions for '1a'; the list was not exercised")
            page.fill(sig_box, "Take one tablet twice daily with food and review at the clinic in Zvimba")
            page.keyboard.press("Enter")
            page.wait_for_timeout(400)
            check("…Enter keeps the directions", "Zvimba" in (page.text_content(f"{MET} .rx-item-sig") or ""))
            page.hover(f"{MET} .rx-item-sig")
            page.wait_for_timeout(350)
            tip = page.text_content(".cell-tip") if page.query_selector(".cell-tip") else ""
            check("hovering a cut-off cell shows its full text", "Zvimba" in (tip or ""), tip or "no tooltip")
            if SHOT is not None and w == 1512:
                page.screenshot(path=str(SHOT / "cell-tip.png"), clip={"x": 270, "y": 180, "width": 880, "height": 160})
            page.mouse.move(5, 5)

        page.dblclick(f"{MET} .rx-item-name .cell-text")
        page.wait_for_timeout(300)
        swap_box = ".disp-grid .rx-item-name.is-editing input"
        check("double-clicking Medicine searches in the table", page.query_selector(swap_box) is not None)
        if page.query_selector(swap_box):
            page.type(swap_box, "cipro")
            page.wait_for_timeout(1300)
            hits = page.query_selector_all(".cell-menu [role='option']:not([aria-disabled='true'])")
            check("…with matches listed under the cell", bool(hits))
            if SHOT is not None and w == 1512:
                page.screenshot(path=str(SHOT / "cell-swap.png"), clip={"x": 270, "y": 180, "width": 880, "height": 330})
            if hits:
                hits[0].click()
                page.wait_for_timeout(700)
                CIP = f"{LINES}:has-text('Cipro')"
                swapped = page.query_selector(CIP)
                check("…and picking one swaps the medicine, keeping qty and directions",
                      swapped is not None
                      and (page.text_content(f"{CIP} .rx-item-qty") or "").strip() == "28"
                      and "Zvimba" in (page.text_content(f"{CIP} .rx-item-sig") or ""),
                      "no swapped row" if swapped is None else page.text_content(f"{CIP} .rx-item-qty"))
            else:
                page.keyboard.press("Escape")
        check("still two lines after editing in place", line_count(page) == 2, str(line_count(page)))

        # ---- Finish: the first stage, what must be settled ----------------------------
        FITS = ("(() => { const m = document.querySelector('.disp-finish');"
                " return !!m && m.scrollHeight <= m.clientHeight + 1; })()")
        page.click(".disp-bar .disp-go")
        page.wait_for_timeout(800)
        check("Finish opens", page.query_selector(".disp-finish") is not None)
        check("…at the settling stage, with the warnings",
              page.query_selector(".disp-finish.is-settle #finish-warnings") is not None)
        proceed = page.query_selector(".disp-finish .fin-proceed")
        check("…and Proceed held while a blocking warning stands", proceed is not None and proceed.is_disabled())
        check("the settling stage shows characters, not escape codes", not page.evaluate(
            r"document.querySelector('.disp-finish').innerText.includes('\\u')"))
        if SHOT is not None:
            page.screenshot(path=str(SHOT / f"flow-settle-{w}.png"))
        page.click(".finish-foot .btn.secondary")
        page.wait_for_timeout(300)
        check("Back to the script closes it", page.query_selector(".disp-finish") is None)
        page.keyboard.press("F12")
        page.wait_for_timeout(700)
        check("F12 opens Finish", page.query_selector(".disp-finish") is not None)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check("Escape closes Finish without clearing the script",
              page.query_selector(".disp-finish") is None and line_count(page) == 2,
              f"open={page.query_selector('.disp-finish') is not None} lines={line_count(page)}")

        # ---- Finish: payment, once the blocking line is off ---------------------------
        page.click(f"{LINES}:has-text('Amoxicillin') .rx-icon.is-remove")
        page.wait_for_timeout(1800)
        page.click(".disp-bar .disp-go")
        page.wait_for_timeout(800)
        if page.query_selector(".disp-finish.is-settle"):
            check("with only advisories left, Proceed goes",
                  not page.query_selector(".disp-finish .fin-proceed").is_disabled())
            page.click(".disp-finish .fin-proceed")
            page.wait_for_timeout(700)
        check("…to payment", page.query_selector(".disp-finish.is-pay #finish-pay") is not None)
        check("…with the bill beside it", page.query_selector(".disp-finish .fin-side .fin-due") is not None)
        check("…and Dispense in its foot", page.query_selector(".finish-foot .printmenu-main") is not None)
        for i, choice in enumerate(("Send to till", "Take payment now", "Out for delivery")):
            page.click(f".disp-finish .fin-seg button:has-text('{choice}')")
            page.wait_for_timeout(800)
            sizes = page.evaluate("(() => { const m = document.querySelector('.disp-finish');"
                                  " return [m.scrollHeight, m.clientHeight]; })()")
            check(f"'{choice}' fits without scrolling", page.evaluate(FITS), f"{sizes[0]} > {sizes[1]}")
            if SHOT is not None:
                page.screenshot(path=str(SHOT / f"flow-pay-{i}-{w}.png"))
        check("payment shows characters, not escape codes", not page.evaluate(
            r"document.querySelector('.disp-finish').innerText.includes('\\u')"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ---- the bin --------------------------------------------------------------
        for _ in range(2):
            if line_count(page):
                page.click(f"{LINES} .rx-icon.is-remove")
                page.wait_for_timeout(500)
        check("the bin deletes both lines", line_count(page) == 0, str(line_count(page)))
        page.wait_for_timeout(800)
        check("deleting the last line takes the totals row with it", page.query_selector(".st-foot") is None)
        m = page.evaluate(RULES_JS)
        check("after deleting: the rules are unbroken to the floor",
              not m["broken"] and abs(m["toFloor"]) <= 2, f"{m['broken']} {m['toFloor']}")
        check("after deleting: the page does not scroll", not page.evaluate(SCROLLS_JS))
        page.close()
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
for f in fails:
    print(f"    {f}")
sys.exit(1 if fails else 0)
