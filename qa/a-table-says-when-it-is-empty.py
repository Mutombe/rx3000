"""A table that has nothing in it says so.

WHAT GOES WRONG WHEN IT DOES NOT.

A table with no rows and no empty state renders as a header row above a void.
From the counter that is indistinguishable from a screen that failed to load,
and the reader cannot tell whether the shop has no deliveries today or whether
something is broken. They refresh, and it is still blank, and now they do not
trust the screen.

WHAT COUNTS AS SAYING SO.

Four mechanisms exist in this product and all four are legitimate:

  * `<EmptyRow>` — the shared one, inside the table, spanning the columns.
  * a `colSpan` row written by hand, which is the same idea.
  * `empty=` on DataTable or RecordPage's Panel, which render one.
  * a `.empty` block beside the table, for a card that replaces the whole
    table rather than filling it.

This checks that a file holding a table has at least one of them. It is a file
level check on purpose: a page with four tables and one empty state is not
something a regular expression can judge, and a check that guesses at that
would report faults that are not there.

AN EARLIER COUNT WAS WRONG AND THIS IS WHY IT EXISTS.

An audit reported thirty-six table files with no empty state. It had looked
for three of the four mechanisms and missed the hand-rolled colSpan row, which
several of those files use. Counting by hand is how a number like that gets
repeated; this counts the same way every time.

Run by exit code. Nought is a pass.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

#: Files that render a table for a reason other than showing data.
NOT_DATA = {"DataTable.tsx", "Skeleton.tsx", "Markdown.tsx", "Empty.tsx"}

SAYS = (
    re.compile(r"<EmptyRow\b"),
    re.compile(r"\bcolSpan\b"),
    re.compile(r"\bempty=\{?"),
    re.compile(r'className="[^"]*\bempty\b'),
)


def main() -> int:
    silent = []
    checked = 0
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name in NOT_DATA:
            continue
        text = path.read_text(encoding="utf-8")
        # A real table, not one built inside a printed document's template.
        if "<table" not in text:
            continue
        checked += 1
        if any(p.search(text) for p in SAYS):
            continue
        silent.append(path.relative_to(SRC).as_posix())

    if not silent:
        print(f"Every table says when it is empty. {checked} file(s) hold one.")
        return 0

    print(f"\n{len(silent)} of {checked} files with a table never say when it "
          f"is empty.\n")
    for name in silent:
        print(f"    {name}")
    print("\n  A header row above a void reads as a screen that failed to "
          "load, not as\n  a shop with nothing to show. Say which empty it "
          "is: nothing yet, and\n  what the thing is for, or nothing matched, "
          "and offer to clear the filters.")
    print("  <EmptyRow cols={n}> from components/Empty.tsx goes inside the "
          "table, so the\n  header stays above it and the reader can still "
          "see what the columns were.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
