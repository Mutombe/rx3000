"""A cell with nothing in it says so in words, not with a dash.

WHY THIS GUARD EXISTS

319 cells across 101 files rendered an em dash when they had no value: a
price that had never been set, a date nobody recorded, a stock code the line
was never given. A dash is a typographic mark standing in for a sentence
nobody wrote, and it makes three different situations look identical --
"nothing here", "not applicable", and "we failed to load it". On a printed
report it reads as a redaction.

The product says "none", or "no date" in a date column. Two words, because a
vocabulary of nine is how a product ends up saying the same thing nine ways.

WHAT IS NOT CHECKED

Em dashes in doc comments and code comments. Those are source, read by
whoever maintains the file, and there are 577 of them doing their proper job
as punctuation. This looks only at dashes that reach a screen.
"""
import pathlib
import re
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src"
DASH = "—"

#: The shapes a placeholder takes. Each one is a value standing in for
#: something absent, never punctuation inside a sentence.
SHAPES = [
    re.compile(r':\s*"' + DASH + r'"'),
    re.compile(r'\|\|\s*"' + DASH + r'"'),
    re.compile(r'\?\?\s*"' + DASH + r'"'),
    re.compile(r'>' + DASH + r'<'),
    re.compile(r'\{\s*"' + DASH + r'"\s*\}'),
]

passed = failed = 0


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


print("\n  a blank cell says what is missing\n")

found = []
scanned = 0
for f in sorted(SRC.rglob("*.tsx")):
    scanned += 1
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if DASH not in line:
            continue
        if line.lstrip().startswith(("*", "//", "/*")):
            continue          # a comment, which is source and not a screen
        if any(s.search(line) for s in SHAPES):
            found.append(f"{f.relative_to(SRC)}:{n}")

check(f"there are screens to check ({scanned})", scanned > 50)
check("no cell stands in for a missing value with a dash", not found,
      f"{len(found)} place(s): " + ", ".join(found[:8])
      + (" ..." if len(found) > 8 else ""))

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
