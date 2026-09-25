"""A badge that carries a status mark stays a flex container.

WHAT HAPPENED.

A badge says its state twice: in colour, and in a shape, so that the one man in
twelve who cannot tell green from amber still reads it. The shape is drawn as
the badge's own ::before and laid out as a FLEX CHILD, which is what `.badge`
is: `display: inline-flex`.

One rule then set `display: block` on a badge inside a table cell, to break the
line so a chip sits under the value rather than beside it. That is a reasonable
thing to want and it quietly destroyed the marks on every table in the system,
because a mark inside a block box is no longer a flex child. It becomes an
inline box, and an inline box IGNORES width and height. So:

  * the disc and the square collapsed to nothing and vanished, and
  * the triangle, which is drawn with borders and borders do apply to inline
    boxes, survived, sat on the text baseline, and hung out below the pill.

Which is why it read as "the amber badges are broken": the other two were not
misplaced, they were gone. Scripts, To follows, Deliveries and Patient
Adherence all showed it, and no test failed.

WHAT THIS CHECKS.

Every rule in the stylesheet whose subject is a badge and which sets `display`
must set it to a flex. `flex` and `inline-flex` both keep the mark a flex
child; `flex` is block level, so a rule wanting the line to break can still
have it.

Read from the stylesheet rather than from a rendered page on purpose: this is a
property of the rules, it takes no browser, and it names the offending line
rather than a symptom three screens away.

Run by exit code. Nought is a pass.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "frontend" / "src" / "styles.css"

#: A selector whose SUBJECT is a badge: the last thing it targets, so
#: `.badge`, `main td > .badge` and `.hq-code .badge` all count, while
#: `.badge .icon` does not — that rule is about the icon.
SUBJECT = re.compile(r"\.badge(?:[.:][\w-]+(?:\([^)]*\))?)*\s*$")
DISPLAY = re.compile(r"(?<![\w-])display\s*:\s*([\w-]+)")


def rules(css: str):
    """Every (line, selector, body) in the sheet, ignoring at-rule wrappers."""
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        body = match.group(2)
        for selector in match.group(1).split(","):
            selector = selector.strip().splitlines()[-1].strip() if selector.strip() else ""
            if not selector or selector.startswith("@"):
                continue
            yield css.count("\n", 0, match.start()) + 1, selector, body


def main() -> int:
    css = SHEET.read_text(encoding="utf-8")
    faults = []
    checked = 0
    for line, selector, body in rules(css):
        if "::" in selector or not SUBJECT.search(selector):
            continue
        said = DISPLAY.search(body)
        if not said:
            continue
        checked += 1
        if "flex" not in said.group(1):
            faults.append((line, selector, said.group(1)))

    if not faults:
        print(f"Every badge keeps its mark: {checked} rule(s) set a badge's "
              f"display, and all of them keep it a flex container.")
        return 0

    print("\nA badge has been taken out of flex layout, which silently "
          "destroys its status mark.\n")
    for line, selector, value in faults:
        print(f"    styles.css:{line}  {selector}  ->  display: {value}")
    print("\n  The mark is the badge's ::before and is laid out as a flex "
          "child. Outside\n  flex it becomes an inline box: the disc and the "
          "square disappear entirely\n  because inline boxes ignore width and "
          "height, and the triangle drops out\n  below the pill because "
          "borders still apply.")
    print("  Use `display: flex` where the line has to break; it is block "
          "level too, so\n  it breaks the line and keeps the mark where it "
          "belongs.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
