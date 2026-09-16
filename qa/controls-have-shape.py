"""Controls a person can press should look pressable before they are touched.

A button drawn with no border and no fill until the pointer finds it reads as a
run of text. The eye has to work out, on every glance, which words are controls
— and on a rail of four filters that is four decisions per look, all day.

This walks the screens a dispensary lives in and reports every interactive
element that, at rest, has:

    no visible border, and no fill of its own, and no group box around it

The last clause matters. A segmented control whose container carries the border
is properly shaped: its buttons are inside a box, and only the chosen one needs
to stand out. What this catches is a control floating on a panel with nothing to
hold it — which is what the worklist's filters were.

    python qa/controls-have-shape.py            # needs the dev server on :4177
"""
import json
import pathlib
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4177"
API = "http://127.0.0.1:8099"
SHOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None

SCREENS = [
    ("the dispensary", "/dispense"),
    ("the till", "/pos"),
    ("the worklist rail", "/dispense"),
    ("will call", "/will-call"),
    ("stock", "/stock"),
    ("departments", "/stock-categories"),
    ("patients", "/patients"),
    ("repeats", "/repeats"),
]

# Things that are meant to read as text: a link in a sentence, a nav item, a
# row that happens to be clickable. The question here is about controls that sit
# in a group of their own.
IGNORE = (".linkish", ".nav a", ".section-nav a", "a.entity", ".wl-row", ".product-pick",
          ".doc-pick", ".toast", ".doing-act", "th", "td", ".sel-opt", ".sig-suggest li",
          ".tab-link", ".crumb", ".skip", ".pagination a")

PROBE = """() => {
  const ignore = %s;
  const transparent = (c) => !c || c === 'transparent' || /rgba\\(0, 0, 0, 0\\)/.test(c)
    || /, 0\\)$/.test(c);
  const out = [];
  for (const el of document.querySelectorAll('button, [role=button], [role=tab], [role=radio]')) {
    if (el.disabled) continue;
    if (ignore.some((sel) => el.closest(sel))) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 14) continue;          // icons carry their own meaning
    const s = getComputedStyle(el);
    const noEdge = ['Top', 'Right', 'Bottom', 'Left']
      .every((side) => transparent(s['border' + side + 'Color'])
        || parseFloat(s['border' + side + 'Width']) === 0);
    const noFill = transparent(s.backgroundColor) && s.backgroundImage === 'none';
    if (!noEdge || !noFill) continue;
    // A group box around it counts as shape: the control is inside a container
    // that is itself drawn.
    let held = false;
    for (let p = el.parentElement, hops = 0; p && hops < 3; p = p.parentElement, hops++) {
      const ps = getComputedStyle(p);
      const edged = ['Top', 'Right', 'Bottom', 'Left']
        .some((side) => !transparent(ps['border' + side + 'Color'])
          && parseFloat(ps['border' + side + 'Width']) > 0);
      if (edged || !transparent(ps.backgroundColor)) { held = true; break; }
    }
    if (held) continue;
    out.push({
      text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 40),
      cls: (el.className || '').toString().slice(0, 60),
    });
  }
  return out;
}""" % json.dumps(list(IGNORE))


def token():
    req = urllib.request.Request(API + "/api/auth/login", method="POST")
    req.add_header("Content-Type", "application/json")
    body = json.dumps({"username": "admin", "password": "admin123"}).encode()
    with urllib.request.urlopen(req, body, timeout=60) as f:
        return json.loads(f.read())["access_token"]


token()
found = {}
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1512, "height": 950}, color_scheme="light")
    page.goto(BASE, wait_until="networkidle")
    page.fill("#lg-user", "admin")
    page.fill("#lg-pass", "admin123")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_timeout(2500)
    for label, path in SCREENS:
        page.goto(BASE + path, wait_until="networkidle")
        page.wait_for_timeout(2600)
        for row in page.evaluate(PROBE):
            key = (row["cls"] or row["text"])
            found.setdefault(key, {"where": set(), "text": row["text"], "cls": row["cls"]})
            found[key]["where"].add(label)
    browser.close()

print(f"\n{len(found)} kind(s) of control are invisible until touched\n")
for key, row in sorted(found.items(), key=lambda kv: -len(kv[1]["where"])):
    where = ", ".join(sorted(row["where"]))
    print(f"  {row['text'][:34]:<36} {row['cls'][:44]:<46} {where}")
sys.exit(0)
