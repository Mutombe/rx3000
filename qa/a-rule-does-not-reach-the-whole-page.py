"""No stylesheet rule applies to everything by accident.

WHAT HAPPENED.

A list of selectors was edited by string replacement to drop one container
from it. `.wc-bands > *` became `*`, and the rule that followed it set
`padding: 12px 16px`, `border: none` and `background: none` — on every element
in the product.

It shipped. Two screenshots were taken afterwards and neither looked wrong.
That is the whole danger of a rule this broad: it does not break a page, it
slightly deforms every page, and nothing on screen says which rule did it. It
surfaced only because something small and precise was drawn next to it — a
seven pixel node that measured thirty-three by twenty-four.

WHAT THIS CHECKS.

A rule whose selector list contains a bare `*`, or a lone pseudo-class with
nothing in front of it like `:first-child` or `:nth-child(odd)`. Both are what
a half-finished edit to a selector list leaves behind, and both reach the
whole document.

The four legitimate universal rules in this sheet are allowed by name, with
the line they sit on. They are resets: box-sizing, margin, the focus ring and
the reduced-motion rule. A reset is universal on purpose and says so.

Run by exit code. Nought is a pass.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / "frontend" / "src" / "styles.css"

#: Selectors that are meant to reach everything. Matched exactly, so a rule
#: that grows extra properties still has to be re-approved by a human editing
#: this list.
RESETS = {
    "*",
    "*, *::before, *::after",
    "*::before",
    "*::after",
}

#: A selector that is only a pseudo-class or pseudo-element: what a botched
#: edit to a list leaves when the thing in front of it is deleted.
LONE_PSEUDO = re.compile(r"^::?[a-z-]+(\([^)]*\))?$")

#: Pseudo-classes that ARE the document and are meant to be written alone.
#: `:root` is where every token in this sheet lives.
WHOLE_DOCUMENT = {":root", ":host", ":before", ":after"}


def main() -> int:
    css = SHEET.read_text(encoding="utf-8")
    faults = []

    # Strip comments so a selector quoted in prose is not read as a rule.
    plain = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                   css, flags=re.S)

    for match in re.finditer(r"([^{}]+)\{", plain):
        head = match.group(1)
        line = plain.count("\n", 0, match.start()) + 1
        selectors = [s.strip() for s in head.split(",")]
        selectors = [s.splitlines()[-1].strip() if s else "" for s in selectors]
        if any(s.startswith("@") for s in selectors):
            continue
        whole = ", ".join(s for s in selectors if s)
        for selector in selectors:
            if not selector:
                continue
            if selector == "*" and whole in RESETS:
                continue
            if selector == "*":
                faults.append((line, selector, "reaches every element"))
            elif selector in WHOLE_DOCUMENT:
                continue
            elif LONE_PSEUDO.match(selector):
                faults.append((line, selector,
                               "reaches every element that matches it"))

    if not faults:
        print("Every rule names what it applies to.")
        return 0

    print("\nA rule reaches the whole page.\n")
    for line, selector, why in faults:
        print(f"    styles.css:{line}   `{selector}`   {why}")
    print("\n  This is what a half-finished edit to a list of selectors leaves "
          "behind:\n  removing one selector by hand turns `.thing > *` into "
          "`*`.")
    print("  It will not break a page. It will slightly deform every page, and "
          "nothing\n  on screen will say which rule did it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
