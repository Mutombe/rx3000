"""A table row is one line tall, and every row is the same height.

WHAT WENT WRONG.

A hundred and fifty-eight cells across sixty-seven files put a second line
under the value: a telephone number under a name, a payment state under an
invoice number, a prescriber under a patient, a schedule chip under a
medicine. Each was reasonable where it was written.

Together they made every table in the product ragged. A row was one line tall
or two depending on whether that particular record happened to have a
telephone number on it, so the eye cannot use row height to track across a
wide table — which is the one thing row height is for. On the dispensing
history it went further and stacked two DIFFERENT PEOPLE in the patient's own
column, the patient above and the prescriber below, both with a face.

There is a detail page for every row in this product. Somebody who wants the
rest clicks. The table shows what is needed to choose which row to click.

WHAT THIS CHECKS.

The two rules that decide it, because this is settled in the stylesheet rather
than at a hundred and fifty-eight call sites:

  * a muted block inside a cell is INLINE, so a text afterthought sits on the
    line rather than under it, and
  * a badge inside a cell is INLINE, so a chip sits beside the value it
    qualifies rather than taking a line of its own.

The badge one has to stay a flex container as well, or its status mark
disappears — `inline-flex` satisfies both, and a-status-mark-stays-in-its-badge
checks the other half.

Deliberately NOT a check on the markup. A `div` inside a cell holding a form
row, a list or a set of actions is real layout, and flattening those would
break the thing they arrange. The stylesheet targets `.muted` and `.badge` for
exactly that reason.

Run by exit code. Nought is a pass.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / "frontend" / "src" / "styles.css"

#: (what it is, the selector that decides it, what its display must contain)
RULES = [
    ("a muted block inside a cell", r"main td > \.muted", "inline"),
    ("a badge inside a cell", r"main td > \.badge", "inline"),
]

DISPLAY = re.compile(r"(?<![\w-])display\s*:\s*([\w-]+)")


def main() -> int:
    css = SHEET.read_text(encoding="utf-8")
    faults = []
    for said, selector, wanted in RULES:
        found = None
        for m in re.finditer(selector + r"[^{}]*\{([^{}]*)\}", css):
            display = DISPLAY.search(m.group(1))
            if display:
                found = (display.group(1), css.count("\n", 0, m.start()) + 1)
        if not found:
            faults.append(f"{said}: no rule sets its display, so it is whatever "
                          f"the element defaults to.")
        elif wanted not in found[0]:
            faults.append(f"{said}: styles.css:{found[1]} sets "
                          f"display: {found[0]}, which takes a line of its own.")

    if not faults:
        print("A table row is one line. Muted blocks and badges inside a cell "
              "both sit on it.")
        return 0

    print("\nSomething in a table cell takes a line of its own.\n")
    for fault in faults:
        print(f"    {fault}")
    print("\n  A row that is one line tall on some records and two on others "
          "cannot be\n  tracked across a wide table, and there is a detail "
          "page for every row\n  here: somebody who wants the rest clicks.")
    print("  A badge needs `inline-flex` rather than `inline`, because it is "
          "still a flex\n  container and its status mark is laid out as a flex "
          "child.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
