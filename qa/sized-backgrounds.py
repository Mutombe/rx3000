"""Can an element that is only a background actually be seen?

The logo vanished from the login page. The rule was right, the file was served,
the element was in the DOM — and it was fifty-two pixels tall and nothing wide.

An empty element carrying a `background-image` has no content, so it has no
content size. In normal flow `width: auto` then fills the line box and it looks
fine; inside a flex row it resolves the main size from the content, finds
nothing, and collapses. `aspect-ratio` was supposed to supply the width from
the definite height and did not, and `background-size: contain` painted into a
box of zero width.

That failure is silent in every way that matters. Nothing errors, nothing warns,
the stylesheet reads correctly, and the only symptom is an image somebody
notices is missing — which on a login page is the brand.

WHAT THIS CHECKS

Every class that sets a `background-image` and is not a child of a rule that
gives it size must state BOTH dimensions itself, or be positioned absolutely,
or be an actual `<img>`. Stated rather than inferred, because inferring is the
thing that broke.

    python qa/sized-backgrounds.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "frontend" / "src" / "styles.css"

#: Classes whose size comes from somewhere this check cannot see: a sprite on a
#: sized parent, a decorative wash on an element with content of its own, a
#: gradient that is painting a surface rather than showing a picture. Each is a
#: decision with its reason.
EXEMPT: dict[str, str] = {}


#: A size that resolves without asking the content. Everything else — `auto`,
#: `fit-content`, `max-content`, `min-content` — is a way of saying "ask", and
#: asking an empty element returns nothing.
DEFINITE = re.compile(r'^-?[\d.]+(px|rem|em|vh|vw|ch|%|pt)$')


def _definite(props: dict[str, str], axis: str) -> bool:
    for name in (axis, f"min-{axis}"):
        value = props.get(name, "").strip()
        if value and DEFINITE.match(value):
            return True
    return False


def rules(css: str):
    """(selector, body) for every rule, comments stripped."""
    css = re.sub(r'/\*.*?\*/', "", css, flags=re.S)
    for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
        yield match.group(1).strip(), match.group(2)


def main() -> int:
    css = SHEET.read_text(encoding="utf-8")

    # What each selector declares, across every rule that mentions it —
    # property AND value. The first version of this check kept only the names,
    # so `width: auto` counted as having a width, and `width: auto` is exactly
    # what collapses. It passed on the stylesheet as shipped.
    declares: dict[str, dict[str, str]] = {}
    picture: set[str] = set()

    for selector, body in rules(css):
        props = {m.group(1): m.group(2).strip()
                 for m in re.finditer(r'(?:^|;)\s*([a-z-]+)\s*:([^;]*)', body)}
        for one in selector.split(","):
            one = one.strip()
            if not one:
                continue
            # The last class in the selector is the element being sized.
            classes = re.findall(r'\.([\w-]+)', one)
            if not classes:
                continue
            target = classes[-1]
            declares.setdefault(target, {}).update(props)
            # A url() background is a picture; a gradient is a surface, and a
            # surface with no size is simply not painted rather than missing.
            if re.search(r'background(-image)?\s*:[^;]*url\(', body):
                picture.add(target)

    findings = []
    for name in sorted(picture):
        if name in EXEMPT:
            continue
        props = declares.get(name, set())
        if "position" in props and "absolute" in css:
            # Absolutely positioned things are sized by their insets.
            pass
        has_width = _definite(props, "width")
        has_height = _definite(props, "height") or "padding" in props
        if has_width and has_height:
            continue
        missing = []
        if not has_width:
            missing.append("width")
        if not has_height:
            missing.append("height")
        findings.append(
            f".{name} paints a picture and never states its "
            f"{' or '.join(missing)}.\n"
            f"       In a flex row an element with no content collapses on that "
            f"axis, and a background has nothing to paint into. That is how the "
            f"logo disappeared from the login card.")

    for finding in findings:
        print(f"  X    {finding}\n")

    print(f"  {len(picture)} class(es) paint an image; "
          f"{len(findings)} could collapse")
    for name, why in sorted(EXEMPT.items()):
        print(f"       {name} is exempt: {why}")
    if not picture:
        print("       nothing paints a background image, which is either true "
              "or means this check has stopped finding them")

    if findings:
        print("\nnothing errors when this happens. The rule reads correctly, "
              "the file is served, and the picture is simply not there.")
        return 1
    print("\nevery element that is only a picture states how big it is")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
