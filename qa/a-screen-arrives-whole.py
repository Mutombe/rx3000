# -*- coding: utf-8 -*-
"""A screen's frame is there before its figures are.

WHAT WAS REPORTED

"If you go to the operations page right now, the only things that load in
skeleton mode are the top cards. Essentially the whole page loads as well...
Only the dynamic spots, the spots where the numbers or the result should be.
The frame of the page should already be there to the bottom. Stop making the
headers load. These are original components that will always be there whether
the data loads or not."

THE RULE, AND WHY IT IS MEASURABLE

Every word on a screen is one of two things. Either it came from the server, or
it is written in the source and is the same on every visit: a card's heading, a
stat's label, a column head, the sentence under a panel title, a tab's name.
The second kind is known before the request is sent, so withholding it is not
loading. It is the screen pretending not to know something it knows.

That makes the rule testable without judging anything. Photograph the chrome
while the API is held back, photograph it again once the answers land, and
compare. Anything in the second photograph that is missing from the first was
being withheld. Numbers are masked to `#` first, because a count in a tab label
genuinely does arrive with the data and is not what this is about.

The second half of the rule is height. A frame that is all there does not grow
when the figures land: the dispensary operations screen used to arrive twice,
the second time about 800px taller, because two panels and a table did not
exist until the request came back.

HOW THE API IS HELD BACK

Every `/api/` request made after the page is opened is parked rather than
answered, so the first paint is genuinely the loading state, with no race and
no arbitrary timeout. They are released together afterwards. Signing in happens
before the parking starts, because a screen nobody is signed in to has no frame
to measure.

WHAT IT DOES NOT COVER

A section that exists only when the data says so — a banner counting expired
lines, a panel that appears when a scheme is in arrears — is a conditional
section rather than withheld chrome, and this cannot tell the two apart. Those
are listed in ALLOWED below, each with the reason, rather than being quietly
skipped.
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
import urllib.request

# Screens are full of characters the Windows console codepage has never heard
# of, and a guard that dies partway through its own report is a guard that
# looks like a pass to whatever is reading its exit code.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "http://localhost:5173"
API = "http://127.0.0.1:8000"

#: Growth under this is a scrollbar or a row of rounding, not a withheld panel.
GROW = 24

ROUTES = [
    "/", "/dispensary/operations", "/patients", "/scripts",
    "/dispensing-history", "/to-follows", "/will-call", "/repeats", "/stock",
    "/orders", "/suppliers", "/deliveries", "/drivers", "/register", "/laybys",
    "/claiming", "/claims-held", "/authorisations", "/payables", "/ledger",
    "/periods", "/fiscal", "/shifts", "/helpdesk", "/accounts", "/pipeline",
    "/marketing", "/reminders", "/branches", "/pharmacies", "/head-office",
    "/admin", "/stock-take", "/rfqs", "/samples", "/recall", "/compounding",
    "/remittances", "/money-owed", "/compliance", "/leads", "/scorecard",
    "/reconciliation", "/stock-performance", "/seasons", "/crm-reports",
    "/system", "/stock-categories", "/insights", "/pos",
]

#: RECORD PAGES, WHICH IS WHERE THIS WAS REPORTED WORST.
#:
#: A record page is the shape most likely to swap itself for a grey stand-in,
#: because it genuinely does not know the record's name until the answer comes
#: back, and it is tempting to conclude it knows nothing. It knows the panel
#: titles, the identifier labels and every column head.
#:
#: The ids are read from the API at startup rather than written down, because
#: a route that 404s falls through to the dashboard and this would compare a
#: screen with itself and call it a pass. Resolved in `record_routes()`.
RECORD_PATHS = [
    ("/api/patients?limit=1", "/patients/{id}"),
    ("/api/products?limit=1", "/products/{id}"),
    ("/api/suppliers?limit=1", "/suppliers/{id}"),
    ("/api/prescriptions?limit=1", "/scripts/{id}"),
]


def record_routes() -> list[str]:
    """One real record of each kind, or none rather than a guess."""
    out = []
    try:
        tok = token()
    except Exception:
        return out
    for path, shape in RECORD_PATHS:
        try:
            req = urllib.request.Request(API + path)
            req.add_header("Authorization", "Bearer " + tok)
            with urllib.request.urlopen(req, timeout=60) as f:
                body = json.loads(f.read())
            rows = body if isinstance(body, list) else (
                body.get("items") or body.get("rows") or [])
            if rows and isinstance(rows[0], dict) and rows[0].get("id"):
                out.append(shape.format(id=rows[0]["id"]))
        except Exception:
            continue
    return out

#: Chrome that genuinely arrives with the answer, per screen, with the reason.
#:
#: EVERY LINE HERE IS A CLAIM, AND A WRONG ONE HIDES A REAL FAULT FOREVER.
#: So it is keyed by route rather than global: "When" and "Category" are
#: ordinary column names that must keep being checked everywhere else, and a
#: flat list would have excused them on all fifty screens.
#:
#: Three things belong here and nothing else. A value the SERVER names, where
#: writing it into the front end would be a second copy of a back end rule that
#: can silently disagree with it. A panel whose very existence is the answer.
#: And a phrase whose wording is decided by the figure inside it.
ALLOWED: dict[str, set[str]] = {
    "/claiming": {
        # "No batch open" against "3 batches open": the negation and the
        # plural are both the answer, so the chip cannot be written in advance.
        "ClaimingNo batch open",
    },
    "/payables": {
        # The ageing columns are named by AGE_BANDS in
        # backend/app/services/payables.py. A pharmacy that changes its bands
        # changes these, and a copy here would go stale without saying so.
        "Not due", "# to #", "Over #",
    },
    "/shifts": {
        # The chip is the answer to "is a till open".
        "Cash OfficeA shift is open",
        # The pharmacy's own base currency, out of its settings.
        "In USD",
        # The whole cash-up panel exists only while a shift is open, which is
        # a fetched fact. Drawing its frame would promise a drawer to count on
        # a day nobody opened one.
        "Count the drawer", "Notes and coins", "Other tenders",
        "When", "Category", "What for", "Amount", "Receipt", "By",
    },
    "/stock-take": {
        # The open count's own reference.
        "ST#",
        # "1 line across one shelf" against "9 lines across 3 shelves": both
        # nouns are pluralised by the figures beside them, so the words are
        # part of the figures rather than part of the frame.
        "Still to count# lines across # shelves",
    },
    "/reconciliation": {
        # The six areas are named by backend/app/services/recon_overview.py.
        # A pharmacy that does not take cards has no card line, so even the
        # number of them is the answer.
        "Cash. Tills", "Claims. Remittances", "Deliveries. Cash with drivers",
        "Stock. Count against batches", "Card. Acquirer settlement",
        "Bank. Statement against ledger",
    },
    "/system": {
        # The verdict badge beside the heading. The heading itself is drawn.
        "What is connectedNot ready to trade",
    },
    "/products/{id}": {
        # "None yet" against "3 scanned or entered": which sentence belongs
        # there is decided by the answer, and saying "none yet" before the
        # answer is in is how a till gets taught a code it already knows. The
        # heading above it is drawn at once, which is the part that was wrong.
        "Codes that find thisNone yet. The till learns them as they are scanned",
    },
    "/stock-categories": {
        # The panel offering to file untagged lines exists only when there are
        # untagged lines, which is a finding rather than a fixture.
        "File the untagged lines",
    },
}


def allowed_on(route: str) -> set[str]:
    """The exemptions for this screen, by its shape rather than its id.

    A record route carries a real id resolved at startup, so "/products/577"
    is a different string every time the catalogue changes and an exemption
    written against it would quietly stop applying. Keyed on the shape as well:
    "/products/577" also reads the entry for "/products/{id}".
    """
    out = set(ALLOWED.get(route, ()))
    bits = route.rsplit("/", 1)
    if len(bits) == 2 and bits[1].isdigit():
        out |= set(ALLOWED.get(f"{bits[0]}/{{id}}", ()))
    return out


CHROME = r"""
() => {
  const pick = "main h1, main h2, main h3, main h4, main th,"
             + " main .label, main .eyebrow, main legend, main .card-head";
  // A LABEL OFTEN CONTAINS A FIGURE, AND THAT IS ALLOWED.
  //
  // "Taken over 14 days" is a label with a number in the middle of it. While
  // the answer is on its way the label is there and the number is a ghost, so
  // reading the element's text gives "Taken over days" before and "Taken over
  // 14 days" after, and a naive comparison calls the label withheld when it
  // was on the screen the whole time.
  //
  // So a ghosted figure is read as the figure it stands for: the node is
  // cloned, every `.sk-val` in it becomes a `#`, and the digits elsewhere are
  // masked to `#` too. What is left is the wording, which is the thing this
  // is actually about.
  const words = (el) => {
    const copy = el.cloneNode(true);
    for (const ghost of copy.querySelectorAll(".sk-val")) {
      ghost.replaceWith(document.createTextNode("#"));
    }
    // A CHIP HOLDING NOTHING BUT A NUMBER IS A FIGURE, NOT WORDING.
    //
    // A panel titled "What they supply" wears a badge saying how many, and a
    // page title wears one saying how many are on file. Those counts are
    // fetched, so they arrive late by definition and this rule was never
    // about them: it is about the words around them. Read by text alone they
    // made every such heading look withheld.
    //
    // Recognised by content rather than by class, so it holds for a chip
    // nobody has named yet: an element whose whole text is digits and
    // separators. A badge that says a WORD ("Overdue", "Held") is wording and
    // stays, which is the distinction that matters.
    for (const el2 of copy.querySelectorAll("span, b, em, small")) {
      const said = (el2.textContent || "").trim();
      if (said && /^[\d.,\s ]+$/.test(said)) el2.remove();
    }
    return (copy.textContent || "").trim().replace(/\s+/g, " ")
      .replace(/\d[\d,. ]*/g, "#")
      // The currency mark belongs to the figure, not to the wording. `money()`
      // formats "$1,240" as one string, so it sits inside the ghost and comes
      // back as "$#" once the answer lands but as "#" before it.
      .replace(/[$£€]\s*#/g, "#")
      // "# #" is one masked figure beside another with only a space between,
      // which happens when a ghost sits next to a real number.
      .replace(/#(\s*#)+/g, "#");
  };
  const said = [...document.querySelectorAll(pick)]
    .map(words)
    .filter((s) => s.length > 0 && s.length < 120);
  return {
    said,
    height: Math.round(document.documentElement.scrollHeight),
  };
}
"""


def token() -> str:
    req = urllib.request.Request(API + "/api/auth/login", method="POST")
    req.add_header("Content-Type", "application/json")
    body = json.dumps({"username": "admin", "password": "admin123"}).encode()
    with urllib.request.urlopen(req, body, timeout=60) as f:
        return json.loads(f.read())["access_token"]


def look(routes):
    from playwright.sync_api import sync_playwright
    found, read = {}, set()
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page(viewport={"width": 1440, "height": 900},
                       color_scheme="light")
        p.goto(BASE, wait_until="networkidle")
        p.fill("#lg-user", "admin")
        p.fill("#lg-pass", "admin123")
        p.get_by_role("button", name="Sign in").click()
        p.wait_for_timeout(3000)

        parked = []
        holding = {"on": False}

        def park(route):
            # Answers are held, not refused: a refusal puts the screen into
            # its error state, which is a different screen. Installed once for
            # the whole sweep and switched with a flag, rather than routed and
            # unrouted around each screen: unrouting while a handler is in
            # flight cancels it, and the guard spent its report printing
            # asyncio tracebacks at somebody who only wanted the list.
            if holding["on"]:
                parked.append(route)
            else:
                route.continue_()

        p.route("**/api/**", park)

        for route in routes:
            parked.clear()
            try:
                holding["on"] = True
                p.goto(BASE + route, wait_until="domcontentloaded")
                # Long enough for the route's chunk to load and paint, short
                # enough that this is still the waiting state: nothing has
                # been answered, so there is no race to lose.
                p.wait_for_timeout(2500)
                before = p.evaluate(CHROME)

                holding["on"] = False
                for r in list(parked):
                    try:
                        r.continue_()
                    except Exception:
                        pass
                parked.clear()
                p.wait_for_load_state("networkidle")
                p.wait_for_timeout(2200)
                after = p.evaluate(CHROME)
                read.add(route)
            except Exception as e:
                holding["on"] = False
                print(f"  ..  {route}: could not be read ({repr(e)[:50]})")
                continue

            had = list(before["said"])
            withheld = []
            for s in after["said"]:
                if s in had:
                    had.remove(s)
                elif "#" in had:
                    # A chrome element that was NOTHING BUT a ghost has
                    # declared itself dynamic, and is allowed to become
                    # anything. A record page's `<h1>` is the case that
                    # matters: the patient's name is fetched, so ghosting the
                    # whole heading is right, and "#" is what this reads it as.
                    # An element that was absent entirely, like a panel title,
                    # leaves no "#" behind and is still caught.
                    had.remove("#")
                elif s not in allowed_on(route):
                    withheld.append(s)
            grew = after["height"] - before["height"]
            if withheld or grew > GROW:
                found[route] = {
                    "withheld": withheld[:8],
                    "more": max(0, len(withheld) - 8),
                    "grew": grew,
                    "before": before["height"], "after": after["height"],
                }
        b.close()
    return found, read


def report(routes) -> int:
    found, read = look(routes)
    if len(read) < len(routes) - len(routes) // 3:
        print(f"\nFAIL  only {len(read)} of {len(routes)} screen(s) could be "
              f"read. That is not a pass, it is a sweep that did not run.")
        return 1
    if not found:
        print(f"\nok  {len(read)} screen(s): every frame is there before the "
              f"figures are")
        return 0
    print(f"\nFAIL  {len(found)} of {len(read)} screen(s) withhold their own "
          f"frame while they wait\n")
    for route, r in sorted(found.items(), key=lambda kv: -kv[1]["grew"]):
        print(f"  {route:<26} {r['before']}px while waiting, {r['after']}px "
              f"after: {r['grew']:+}px")
        for s in r["withheld"]:
            print(f"        withheld: {s!r}")
        if r["more"]:
            print(f"        and {r['more']} more")
    print("\n  A label, a heading or a column head is written in the source and")
    print("  is the same on every visit. Draw it at once and pulse only the")
    print("  figure: `<Figure ready={…}>` for a value, `<GhostRows>` under a")
    print("  real table head.")
    return 1


def plant() -> int:
    """Prove it by making one label wait for the answer it labels."""
    import time
    comp = ROOT / "frontend" / "src" / "pages" / "DispensaryOperations.tsx"
    original = comp.read_text(encoding="utf-8")
    marker = '<div className="label">Lines waiting</div>'
    if marker not in original:
        print("FAIL  the label this plants against is not on the operations "
              "screen any more, so the plant would prove nothing.")
        return 1
    # One label made to wait for the answer, which is the whole fault in
    # miniature and a single balanced expression, so it cannot leave the file
    # in a state that will not compile.
    fault = original.replace(
        marker, '<div className="label">{day ? "Lines waiting" : ""}</div>', 1)
    try:
        comp.write_text(fault, encoding="utf-8")
        # Vite needs a while to re-transform on a busy machine.
        time.sleep(14)
        found, _ = look(["/dispensary/operations"])
        if not found:
            print("FAIL  a stat label was made to wait for the answer and this "
                  "said nothing")
            return 1
        route, r = next(iter(found.items()))
        print(f"ok  planted fault caught: {route} grew {r['grew']:+}px and "
              f"withheld {len(r['withheld']) + r['more']} piece(s) of chrome")
        return 0
    finally:
        comp.write_text(original, encoding="utf-8")
        time.sleep(3)


def alive() -> bool:
    try:
        urllib.request.urlopen(BASE, timeout=5).read(1)
        token()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    if not alive():
        print("The dev server and API have to be up for this one.")
        print(f"  {BASE} and {API}")
        sys.exit(2)
    if "--plant" in sys.argv:
        sys.exit(plant())
    only = [a for a in sys.argv[1:] if a.startswith("/")]
    sys.exit(report(only or (ROUTES + record_routes())))
