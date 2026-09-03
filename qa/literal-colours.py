"""Is a colour written into an element, where the theme cannot reach it?

The chosen medicine in the counter-sale search carried

    style={{ background: "#fff", borderColor: "var(--accent)" }}

so on the dark dispensary the selected row became near-white text on a white
block. The one row meant to stand out was the one row nobody could read.

Half of that line is right: `var(--accent)` follows the theme. The other half
is a literal, and a literal cannot. Every colour in this product is a token for
that reason, and the tokens are redefined under `:root[data-theme="dark"]`.

WHY THE OTHER TWO COLOUR CHECKS MISSED IT

`button-contrast.py` reads what a CLASS declares. `inherited-colour.py` reads
what a STYLESHEET declares. This colour was in neither: it was written into the
element, which is the one place both of them are blind. Five faults of this
family have now shipped and this is the first that hid there.

WHAT IS ALLOWED

`transparent`, `inherit`, `currentColor`, `none` — none of them is a colour, so
none of them can be the wrong one in a theme.

A literal on something that has no theme: an SVG chart series painted from the
chart palette, a printed sheet, a canvas. Those are listed by file, with the
reason, rather than pattern-matched, so adding one is a decision somebody makes
rather than a rule somebody satisfies.

    python qa/literal-colours.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

#: Properties whose value is a colour.
COLOUR_PROPS = (
    "background", "backgroundColor", "color", "borderColor", "borderTopColor",
    "borderRightColor", "borderBottomColor", "borderLeftColor", "outlineColor",
    "fill", "stroke", "caretColor", "textDecorationColor",
)

#: Values that are not a colour and so cannot be the wrong one.
NOT_A_COLOUR = {"transparent", "inherit", "currentcolor", "none", "unset",
                "initial", "revert", "auto"}

#: Files that paint something the theme does not reach. Each is a decision,
#: with its reason, rather than a pattern that lets anything through.
EXEMPT = {
    "print.ts": "a printed sheet is ink on paper and has no dark mode",
    "letterhead.ts": "same: this is printed",
    "escpos.ts": "a thermal till roll, which is monochrome",
    "chartPalette.ts": "the chart palette itself, which is where the literals live",
    "charts.tsx": "series colours come from the chart palette by design",
    "PatientPortalPreview.tsx": "renders the portal's own sheet, not this one",
}

STYLE_BLOCK = re.compile(r'style=\{\{(.*?)\}\}', re.S)
LITERAL = re.compile(
    r'\b(' + "|".join(COLOUR_PROPS) + r')\s*:\s*["\']([^"\']+)["\']')


def is_literal_colour(value: str) -> bool:
    v = value.strip().lower()
    if v in NOT_A_COLOUR or v.startswith("var(") or not v:
        return False
    if v.startswith("#"):
        return True
    if re.match(r'^(rgb|rgba|hsl|hsla|color|oklch|oklab)\(', v):
        return True
    # A bare colour keyword: white, black, red…
    return bool(re.fullmatch(r'[a-z]+', v)) and v not in NOT_A_COLOUR


def main() -> int:
    findings: list[str] = []
    blocks = 0

    for file in sorted(SRC.rglob("*.ts*")):
        if file.name in EXEMPT:
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        for block in STYLE_BLOCK.finditer(text):
            blocks += 1
            for prop, value in LITERAL.findall(block.group(1)):
                if not is_literal_colour(value):
                    continue
                line = text.count("\n", 0, block.start()) + 1
                findings.append(
                    f"frontend/src/{file.relative_to(SRC).as_posix()}:{line}\n"
                    f"       {prop}: \"{value}\"\n"
                    f"       written into the element, so it is the same colour "
                    f"in both themes.\n"
                    f"       Use a token: the sheet redefines every one of them "
                    f"under dark.")

    for finding in findings:
        print(f"  X    {finding}\n")

    print(f"  {blocks} inline style block(s) read; {len(findings)} paint a "
          f"literal colour")
    if findings:
        print("\na literal cannot follow the theme. Neither the class check nor "
              "the stylesheet check can see one, because it is in neither.")
        return 1
    print("\nevery colour in an inline style is a token, so it follows the theme")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
