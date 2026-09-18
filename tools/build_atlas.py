"""The map RX-Assistant reads: every screen, what it is called, and how to reach it.

    python tools/build_atlas.py            # writes backend/app/assets/atlas.json

An assistant is only as good as the map it is given. Asked "where do I set a
price on a script", a model with no map can only guess, and a guess about your
own software is worse than silence.

RX5000 already knows all of this. It is simply scattered across the code as
facts nobody ever collected: the routes in App.tsx, the sidebar in Layout.tsx
with the capability each entry needs, the function keys in keymap.ts, and on
every page a heading and a subtitle written for a person to read.

GENERATED, NEVER WRITTEN BY HAND.

That is the whole point. A help page drifts from the software the week after it
is written, and nobody notices until a pharmacist follows it into a screen that
was renamed six months ago. This is rebuilt from the source, so a screen that is
renamed is renamed in the atlas, and a screen that is deleted leaves.

WHAT IS DELIBERATELY NOT HERE.

Anything about the pharmacy's own data. The atlas describes the software, not
the shop: no patients, no products, no figures. It is the same file for every
customer, it can be read by anybody signed in, and nothing in it is a secret.
The tools that read live data are separate, and they run as the person asking.
"""
from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend" / "src"
OUT = ROOT / "backend" / "app" / "assets" / "atlas.json"


#: How a screen says you may not open it, which is never what the screen is.
REFUSAL = re.compile(
    r"nothing on this screen|not yours|your account does not|no access|"
    r"you do not have|ask an administrator", re.I)


def _read(rel: str) -> str:
    path = FRONT / rel
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


# --------------------------------------------------------------- the sidebar
def nav_entries() -> list[dict]:
    """Sections, labels and the capability each screen needs.

    The sidebar is the pharmacy's own vocabulary for its software: whatever a
    screen is called here is what somebody will ask for by name.
    """
    src = _read("components/Layout.tsx")
    block = re.search(r"const NAV[^=]*=\s*\[(.*?)\n\];", src, re.S)
    if not block:
        return []
    out: list[dict] = []
    section = ""
    # The comment above an entry, where somebody has written one. These are the
    # best descriptions in the codebase: a sentence explaining why a screen
    # exists, written by the person who decided it should. Pages whose heading
    # is built at runtime, the dispensary among them, have nothing else.
    said: list[str] = []
    for line in block.group(1).splitlines():
        note = re.match(r"\s*//\s?(.*)", line)
        if note:
            said.append(note.group(1).strip())
            continue
        got = re.search(r'section:\s*"([^"]+)"', line)
        if got:
            section = got.group(1)
            said = []
            continue
        entry = re.search(r'\{\s*to:\s*"([^"]+)",\s*label:\s*"([^"]+)"', line)
        if not entry:
            said = []
            continue
        needs = re.search(r'needs:\s*"([^"]+)"', line)
        tier = re.search(r"tier:\s*(\d+)", line)
        out.append({
            "route": entry.group(1),
            "label": entry.group(2),
            "section": section,
            "needs": needs.group(1) if needs else None,
            "tier": int(tier.group(1)) if tier else None,
            "group_wide": "groupWide" in line,
            "note": re.sub(r"\s+", " ", " ".join(said)).strip(),
        })
        said = []
    return out


# ---------------------------------------------------------------- the routes
def routes() -> dict[str, str]:
    """Every path the application answers, and the component behind it.

    Includes the ones the sidebar never shows: a patient, a script, an invoice.
    Somebody asking "how do I get to a supplier's account" is asking about one
    of those.
    """
    src = _read("App.tsx")
    # The lazy imports say which file each page lives in. Resolved first,
    # because it is also how the page is picked out of its wrappers below.
    files = dict(re.findall(r'const (\w+) = lazy\(\(\) => import\("\./([^"]+)"\)\)', src))

    found: dict[str, str] = {}
    # The whole element expression, not the first tag in it. Several routes
    # wrap the page in a guard, and taking the first component name gave
    # `RequiresConnection` for the dispensary, which is the one screen this
    # feature is most about. The page is whichever component in there is a
    # lazily imported one.
    # The element must not itself contain a route. `path="/*"` wraps the whole
    # signed-in application, and a plain lazy match ran from there to the first
    # closing brace, swallowing the dashboard that sits directly inside it.
    for path, element in re.findall(
            r'<Route\s+path="([^"]+)"\s+element=\{((?:(?!<Route).)*?)\}\s*/>',
            src, re.S):
        page = next((n for n in re.findall(r"<(\w+)", element) if n in files), "")
        if page:
            found.setdefault(path, page)
    return {p: files[c] for p, c in found.items()}


# ------------------------------------------------------------ what a page is
def page_words(rel: str) -> tuple[str, str]:
    """The heading and the line under it, as written for a person to read.

    Better than any description I could invent, and better than the comments in
    the code: this is the text the person asking is looking at.
    """
    if not rel:
        return "", ""
    src = _read(rel if rel.endswith(".tsx") else rel + ".tsx")
    tidy = lambda s: re.sub(r"\s+", " ", s).strip() if s else ""
    h1 = re.search(r"<h1[^>]*>([^<{]+)</h1>", src)
    if not h1:
        return "", ""
    # The subtitle that belongs to THIS heading, not the first one anywhere in
    # the file. Searched forward from the heading and only a little way: the
    # dispensary's first `.sub` further down is a permission notice reading
    # "Nothing on this screen is yours to use", which described the busiest
    # screen in the product as exactly the wrong thing.
    near = src[h1.end(): h1.end() + 400]
    sub = re.search(r'className="(?:page-)?sub"[^>]*>\s*([^<{][^<]*)</div>', near)
    said = tidy(sub.group(1) if sub else "")
    # Some pages carry a heading inside their REFUSAL, shown to somebody who
    # may not open them. The dispensary is one, and taking its words verbatim
    # described the busiest screen in the product as "Nothing on this screen is
    # yours to use". A refusal is not a description of a screen.
    if REFUSAL.search(said):
        return "", ""
    return tidy(h1.group(1)), said


def opening_words(rel: str) -> str:
    """The first sentences of the file's own docstring.

    Nearly every page in this codebase opens by explaining what it is for and
    why it exists. That is a better description than anything generated, and
    for the dispensary it is the only one: its heading is the script number, so
    there is no static title or subtitle anywhere in the file.
    """
    if not rel:
        return ""
    src = _read(rel if rel.endswith(".tsx") else rel + ".tsx")
    doc = re.match(r"\s*/\*\*(.*?)\*/", src, re.S)
    if not doc:
        return ""
    lines = []
    for line in doc.group(1).splitlines():
        line = re.sub(r"^\s*\*\s?", "", line).strip()
        if not line:
            if lines:
                break            # the first paragraph is the summary
            continue
        lines.append(line)
    said = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return said[:300]


def anchors(rel: str) -> list[dict]:
    """The controls on a page that can actually be pointed at.

    A route that says "the Medicine field" is worth little; one that can light
    the field up is worth the whole feature. These are the hooks already in the
    markup for the keyboard and the guided tour.
    """
    if not rel:
        return []
    src = _read(rel if rel.endswith(".tsx") else rel + ".tsx")
    out: list[dict] = []
    for hk in sorted(set(re.findall(r'data-hk="([^"]+)"', src))):
        out.append({"selector": f'[data-hk="{hk}"]', "name": hk})
    for step in sorted(set(re.findall(r'id="(step-[^"]+)"', src))):
        out.append({"selector": f"#{step}", "name": step.replace("step-", "")})
    return out


def tabs(rel: str) -> list[str]:
    """The tabs on a page, which are screens in their own right to whoever is
    looking for one."""
    if not rel:
        return []
    src = _read(rel if rel.endswith(".tsx") else rel + ".tsx")
    got = re.findall(r'\{\s*key:\s*"[^"]+",\s*label:\s*"([^"]+)"', src)
    seen, out = set(), []
    for label in got:
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out[:14]


# ------------------------------------------------------------------ the keys
def keys() -> list[dict]:
    """The function keys, which are how the dispensary is actually driven.

    Copied from the incumbent on purpose, so a dispenser who has used that for
    years does not have to be retrained. That makes them the most likely thing
    anybody asks about.
    """
    src = _read("keymap.ts")
    out: list[dict] = []
    for name, body in re.findall(r"export const (\w+_KEYS)[^=]*=\s*\[(.*?)\n\];", src, re.S):
        where = name.replace("_KEYS", "").lower()
        for line in body.splitlines():
            combo = re.search(r'combo:\s*"([^"]+)"', line)
            label = re.search(r'label:\s*"([^"]+)"', line)
            if not (combo and label):
                continue
            group = re.search(r'group:\s*"([^"]+)"', line)
            out.append({
                "combo": combo.group(1), "label": label.group(1),
                "group": group.group(1) if group else "",
                "where": where,
            })
    return out


def build() -> dict:
    by_route = routes()
    nav = {n["route"]: n for n in nav_entries()}
    screens: list[dict] = []
    for route, file in sorted(by_route.items()):
        if route in ("/*", "*", "/login") or route.startswith("/portal"):
            continue
        title, sub = page_words(file)
        entry = nav.get(route, {})
        # A record page takes its heading from the record, so there is no
        # heading in the source to find. What it is can still be said honestly
        # from the list it belongs to: /patients/:id is one of Patients.
        one_of = ""
        if not title and "/:" in route:
            parent = nav.get(route.rsplit("/", 1)[0])
            if parent:
                one_of = parent["label"]
        screens.append({
            "route": route,
            "label": entry.get("label") or title
                     or (f"{one_of}, one record" if one_of else
                         route.strip("/").replace("-", " ").replace("/:id", "").title()),
            "section": entry.get("section") or (nav.get(route.rsplit("/", 1)[0], {}).get("section", "")),
            "in_sidebar": route in nav,
            "title": title,
            "about": sub or entry.get("note", "") or opening_words(file)
                     or (f"One record from {one_of}." if one_of else ""),
            "opens_from": route.rsplit("/", 1)[0] if one_of else "",
            "needs": entry.get("needs"),
            "group_wide": entry.get("group_wide", False),
            "file": file,
            "tabs": tabs(file),
            "anchors": anchors(file),
        })
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "note": "Generated by tools/build_atlas.py. Describes the software, never a "
                "pharmacy's own data. Do not edit by hand.",
        "screens": screens,
        "keys": keys(),
    }


if __name__ == "__main__":
    atlas = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(atlas, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    listed = sum(1 for s in atlas["screens"] if s["in_sidebar"])
    described = sum(1 for s in atlas["screens"] if s["about"])
    anchored = sum(len(s["anchors"]) for s in atlas["screens"])
    print(f"{len(atlas['screens'])} screens, {listed} of them in the sidebar")
    print(f"{described} carry a description of their own")
    print(f"{anchored} controls can be pointed at")
    print(f"{len(atlas['keys'])} keys")
    print(f"\n{OUT.relative_to(ROOT)}: {OUT.stat().st_size:,} bytes")
    missing = [s["route"] for s in atlas["screens"] if not s["title"]][:8]
    if missing:
        print(f"\nno heading found on: {', '.join(missing)}")
