"""The Finish dialog never scrolls — on every route, every way of paying, at a
laptop size and a till size.

For Prescription and Dangerous Drugs, with a real patient, prescriber and
medicine, it opens Finish, proceeds past the settling stage when it can, and
for each of Send to till, Take payment now and Out for delivery asserts that
the dialog's content fits its box. The settling stage is measured too.

The controlled route is the hard case: its compliance record used to stack
under the bill. It needs a schedule 5 or 6 medicine in stock; the first of a
few common names that finds one is used, and if none does the route is
reported as not exercised rather than passed.

Run against a local preview on :4177 and API on :8099:
  python finish_never_scrolls.py [screenshot-dir]
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
FITS = ("(() => { const m = document.querySelector('.disp-finish');"
        " return m ? [m.scrollHeight, m.clientHeight] : null; })()")
fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def build_script(page, route_tab, terms):
    page.goto(BASE + "/dispense", wait_until="networkidle")
    page.wait_for_timeout(1400)
    if route_tab:
        tab = page.query_selector(f".disp-routes button:has-text('{route_tab}')")
        if not tab:
            return False
        tab.click()
        page.wait_for_timeout(800)
    page.fill("[data-hk='patient']", "Andela")
    page.wait_for_timeout(1500)
    picks = page.query_selector_all("#step-patient .product-pick")
    if not picks:
        return False
    picks[0].click()
    page.wait_for_timeout(1300)
    page.fill("#disp-doctor", "Dr")
    page.wait_for_timeout(500)
    docs = page.query_selector_all("#step-patient .doc-pick")
    if not docs:
        return False
    docs[0].click()
    page.wait_for_timeout(400)
    for term in terms:
        page.fill("[data-hk='product']", term)
        page.wait_for_timeout(1400)
        hits = [h for h in page.query_selector_all("#step-items .product-pick")
                if " 0 in stock" not in (h.inner_text() or "")]
        if hits:
            hits[0].click()
            page.wait_for_timeout(900)
            if page.query_selector(".disp-edit"):
                page.click(".disp-edit .disp-edit-actions .btn.primary")
                page.wait_for_timeout(1200)
            return True
    return False


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

        for label, tab, terms in (
            ("Prescription", None, ("metfor", "cipro")),
            ("Dangerous Drugs", "Dangerous Drugs", ("tramad", "diazep", "morph", "codein", "pethid", "methylphen")),
        ):
            if not build_script(page, tab, terms):
                print(f"  --    {label}: no patient, prescriber or in-stock medicine found; not exercised")
                continue
            page.click(".disp-bar .disp-go")
            page.wait_for_timeout(900)
            if page.query_selector(".disp-finish.is-settle"):
                sizes = page.evaluate(FITS)
                check(f"{label}: the settling stage fits", sizes and sizes[0] <= sizes[1] + 1, str(sizes))
                proceed = page.query_selector(".disp-finish .fin-proceed")
                if proceed and proceed.is_disabled():
                    for ack in page.query_selector_all(".disp-finish .fin-item-act .btn"):
                        ack.click()
                        page.wait_for_timeout(250)
                proceed = page.query_selector(".disp-finish .fin-proceed")
                if proceed and not proceed.is_disabled():
                    proceed.click()
                    page.wait_for_timeout(700)
            if not page.query_selector(".disp-finish.is-pay"):
                check(f"{label}: reaches payment", False, "still settling")
                page.keyboard.press("Escape")
                continue
            for i, choice in enumerate(("Send to till", "Take payment now", "Out for delivery")):
                page.click(f".disp-finish .fin-seg button:has-text('{choice}')")
                page.wait_for_timeout(700)
                sizes = page.evaluate(FITS)
                check(f"{label} · {choice}: fits without scrolling",
                      sizes and sizes[0] <= sizes[1] + 1, str(sizes))
                wide = page.evaluate("(() => { const m = document.querySelector('.disp-finish');"
                                     " return [m.scrollWidth, m.clientWidth]; })()")
                check(f"{label} · {choice}: nothing runs off the side", wide[0] <= wide[1] + 1, str(wide))
                cut = page.evaluate("[...document.querySelectorAll('.disp-finish .fin-print-name')]"
                                    ".filter((e) => e.scrollWidth > e.clientWidth + 1).map((e) => e.textContent)")
                check(f"{label} · {choice}: every print is named in full", not cut, str(cut))
                if SHOT is not None:
                    page.screenshot(path=str(SHOT / f"never-{label.split()[0].lower()}-{i}-{w}.png"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        page.close()
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
