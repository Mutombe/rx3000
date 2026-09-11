"""Dialogs keep their height while their data loads, and show its shape meanwhile.

For each dialog on the dispensary that loads something, the request is held at
the network, the dialog is measured while it shows its skeleton, the request is
released, and the dialog is measured again. It passes only if a skeleton was on
screen while loading and the height did not move by more than a pixel when the
data arrived.

  History         held: the history report and the patient's scripts
  Repeats due     held: the patient's repeats
  Line check      held: the interaction screen
  Details         nothing to load; the height is simply measured twice
  Edit line       held: substitutions, opened inside the dialog
  Finish          one height across settling, paying, and every way to pay

At a laptop size and a till size.

Run against a local preview on :4177 and API on :8099:
  python dialog_heights.py
"""
import re
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def height(page, sel):
    return page.evaluate(
        f"(() => {{ const e = document.querySelector('{sel}'); "
        f"return e ? Math.round(e.getBoundingClientRect().height) : null; }})()")


def skeletons(page, sel):
    return page.evaluate(f"document.querySelectorAll('{sel} .skel').length")


def held_while(page, patterns, open_it, sel, label):
    """Open a dialog with its requests held; measure; release; measure."""
    held = []
    for p in patterns:
        page.route(p, lambda route: held.append(route))
    open_it()
    page.wait_for_timeout(600)
    loading_h = height(page, sel)
    loading_skel = skeletons(page, sel)
    for p in patterns:
        page.unroute(p)
    for r in held:
        try:
            r.continue_()
        except Exception:
            pass
    page.wait_for_timeout(1500)
    loaded_h = height(page, sel)
    loaded_skel = skeletons(page, sel)
    check(f"{label}: shows the shape of its data while loading", loading_skel > 0,
          f"{loading_skel} placeholders, {len(held)} requests held")
    check(f"{label}: keeps its height when the data arrives",
          loading_h is not None and loaded_h is not None and abs(loading_h - loaded_h) <= 1,
          f"{loading_h}px -> {loaded_h}px")
    check(f"{label}: the placeholders are gone once it has", loaded_skel == 0, f"{loaded_skel} left")
    return loaded_h


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
        page.wait_for_timeout(1400)
        page.fill("[data-hk='patient']", "Andela")
        page.wait_for_timeout(1500)
        page.query_selector_all("#step-patient .product-pick")[0].click()
        page.wait_for_timeout(1600)
        page.fill("#disp-doctor", "Dr")
        page.wait_for_timeout(500)
        page.query_selector_all("#step-patient .doc-pick")[0].click()
        page.wait_for_timeout(400)
        page.fill("[data-hk='product']", "metfor")
        page.wait_for_timeout(1500)
        page.query_selector_all("#step-items .product-pick")[0].click()
        page.wait_for_timeout(900)
        page.click(".disp-edit .disp-edit-actions .btn.primary")
        page.wait_for_timeout(1500)

        # ---- History, with a tab switch after it loads
        hist = held_while(
            page,
            [re.compile(r".*/api/reports/patient/\d+/history.*"),
             re.compile(r".*/api/prescriptions\?patient_id=.*")],
            lambda: page.click(".disp-patient-picked .lane-tool.is-history"),
            ".pt-history", "History")
        page.click(".pt-history .pt-tabs button:has-text('Scripts')")
        page.wait_for_timeout(300)
        check("History: the same height on the other tab", abs((height(page, ".pt-history") or 0) - (hist or 0)) <= 1,
              f"{hist}px -> {height(page, '.pt-history')}px")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ---- Repeats due
        tool = page.query_selector(".disp-patient-picked .lane-tool.is-repeats:not([disabled])")
        if tool:
            held_while(page, [re.compile(r".*/api/patients/\d+/repeats.*")],
                       lambda: page.click(".disp-patient-picked .lane-tool.is-repeats"),
                       ".disp-lane-modal", "Repeats due")
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        else:
            print("  --    no repeats due for this patient; not exercised")

        # ---- Details: nothing loads; the height holds
        page.click(".disp-patient-picked .lane-tool.is-details")
        page.wait_for_timeout(200)
        first = height(page, ".pt-card")
        page.wait_for_timeout(900)
        check("Details: a height of its own", first is not None and abs(first - (height(page, ".pt-card") or 0)) <= 1,
              f"{first}px -> {height(page, '.pt-card')}px")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ---- Line check, opened from the row's dose triangle while it loads
        LINE = ".disp-grid > .rx-item:not(.rx-item-waiting)"
        if page.query_selector(f"{LINE} .rx-item-warn"):
            held_while(page, [re.compile(r".*/api/dispensing/interaction-screen.*")],
                       lambda: page.click(f"{LINE} .rx-item-warn"),
                       ".disp-check", "Line check")
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        else:
            print("  --    no dose triangle on the line; line check not exercised")

        # ---- Edit line, with substitutions opened inside it.
        # The substitutions list sits in a collapsed <details> and is mounted, and
        # so fetched, the moment the dialog opens — so the request is held from
        # before the dialog opens, or there is no loading state left to see.
        VARIANTS = re.compile(r".*/api/products/\d+/variants.*")
        held = []
        page.route(VARIANTS, lambda route: held.append(route))
        page.click(f"{LINE} .rx-icon[title='Edit this line']")
        page.wait_for_timeout(500)
        closed_h = height(page, ".disp-edit")
        page.click(".disp-edit summary:has-text('Substitutions')")
        page.wait_for_timeout(400)
        loading_h = height(page, ".disp-edit")
        loading_skel = skeletons(page, ".disp-edit .vr")
        page.unroute(VARIANTS)
        for r in held:
            try:
                r.continue_()
            except Exception:
                pass
        page.wait_for_timeout(1500)
        loaded_h = height(page, ".disp-edit")
        check("Edit line · substitutions: shows the shape of its data while loading", loading_skel > 0,
              f"{loading_skel} placeholders, {len(held)} requests held")
        check("Edit line: one height closed, loading and loaded",
              None not in (closed_h, loading_h, loaded_h)
              and max(closed_h, loading_h, loaded_h) - min(closed_h, loading_h, loaded_h) <= 1,
              f"{closed_h} / {loading_h} / {loaded_h}px")
        check("Edit line · substitutions: the placeholders are gone once it has",
              skeletons(page, ".disp-edit .vr") == 0)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ---- Finish: one height, whatever stage and way of paying
        page.click(".disp-bar .disp-go")
        page.wait_for_timeout(900)
        heights = []
        if page.query_selector(".disp-finish.is-settle"):
            heights.append(("settling", height(page, ".disp-finish")))
            proceed = page.query_selector(".disp-finish .fin-proceed")
            if proceed and not proceed.is_disabled():
                proceed.click()
                page.wait_for_timeout(600)
        for choice in ("Send to till", "Take payment now", "Out for delivery"):
            if page.query_selector(".disp-finish .fin-seg"):
                page.click(f".disp-finish .fin-seg button:has-text('{choice}')")
                page.wait_for_timeout(500)
                heights.append((choice, height(page, ".disp-finish")))
        values = [v for _, v in heights if v is not None]
        check("Finish: one height across settling and every way of paying",
              len(values) >= 3 and max(values) - min(values) <= 1, str(heights))
        page.keyboard.press("Escape")
        page.close()
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
