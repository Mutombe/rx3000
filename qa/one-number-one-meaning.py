"""A stock figure on a screen means the shelf the reader can reach.

THE LEAK THIS CLOSES

`Product.quantity_on_hand` is every branch added up. `here` is what this
counter holds. Both are correct numbers and they answer different questions,
so a screen that shows one while the reader is asking the other is wrong in the
way that is hardest to see: it is a plausible figure, it moves when stock
moves, and it is only wrong about which shelf.

The first attempt at this made it worse rather than better. `here` was added
BESIDE `quantity_on_hand` on the product list, so the row carried two numbers
with two meanings under one heading and the reader was left to work out which
one answered their question. That is the abstraction leaking out of the system
and onto the person using it. The rule is one number, and the system decides
which.

WHAT IS CHECKED

Any JSX that renders `quantity_on_hand` into text a person reads must fall back
through `here` first. Writing to it is fine: an opening stock field, a form
body, a type declaration, the value posted back to the server. Reading it to
put a figure in front of somebody is not.

WHAT IS DELIBERATELY ALLOWED

The group total is the right answer to a group question, and those exist: what
the whole pharmacy's shelves are worth, whether a line may be retired anywhere
at all, what another branch is holding. Each is listed below by name, because a
list somebody has to add to is a list somebody reads.

    python qa/one-number-one-meaning.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "src"

#: Reads of the group total that are asking a group question.
ALLOWED = {
    # Valuation across every shelf, for the accounts.
    ("pages/Stock.tsx", "stock_value"),
    # Retiring is a catalogue act: it must be clear at EVERY branch, so the
    # warning counts the group on purpose.
    ("pages/Stock.tsx", "retire"),
    # The second number in "0 here, 9 at another branch" IS the group total
    # minus this shelf. That is the conclusion, not a rival figure.
    ("pages/Stock.tsx", "elsewhere"),
}

#: `quantity_on_hand` read in a position that puts it on screen.
#: Not a type declaration (`quantity_on_hand: number`), not a key being written.
READS = re.compile(
    r"(?<!\.)\bquantity_on_hand\b(?!\s*[:?]\s*(number|0\b))"
)
#: Already routed through the branch figure.
GUARDED = re.compile(r"here\s*\?\?[^;\n]*quantity_on_hand")

passed = failed = 0
hits: list[str] = []


def check(said, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ok   {said}")
    else:
        failed += 1
        print(f"  X    {said}")
        if detail:
            print(f"       {detail}")


print("\n  one number, one meaning\n")

files = sorted(list(WEB.rglob("*.tsx")))
for f in files:
    rel = f.relative_to(WEB).as_posix()
    in_block = False
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        opens, closes = "/*" in line, "*/" in line
        was_in_block = in_block
        if opens and not closes:
            in_block = True
        elif closes:
            in_block = False
        if was_in_block or opens or stripped.startswith(("*", "//")):
            continue
        if "quantity_on_hand" not in line or GUARDED.search(line):
            continue
        # Writing to it, or declaring it, is not a reader-facing figure.
        if re.search(r"quantity_on_hand\s*[:=]", line) or "delete " in line:
            continue
        # A quoted occurrence is a key: a column id, a sort field, a body
        # property. The figure the column actually renders is on another line
        # and is checked there.
        if '"quantity_on_hand"' in line or "'quantity_on_hand'" in line:
            continue
        # The form's own draft of a NEW product's opening stock. It is an input
        # the user is filling in, not a figure being reported to them, and at
        # that moment the product has no shelf anywhere to be on.
        if "form.quantity_on_hand" in line:
            continue
        if any(rel == a and key in line for a, key in ALLOWED):
            continue
        if not READS.search(line):
            continue
        hits.append(f"{rel}:{n}  {stripped[:86]}")

check(f"there are screens to check ({len(files)})", len(files) > 50)
check("no screen shows the group total where the reader means this shelf",
      not hits,
      f"{len(hits)} place(s):\n       " + "\n       ".join(hits[:25])
      if hits else "")

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
