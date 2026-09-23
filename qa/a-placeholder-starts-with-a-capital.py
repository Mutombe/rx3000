"""A word standing in for data starts like a sentence.

WHY

Where a record has no value the screen says so in words rather than with a
dash, which is the rule the sister guard holds. Those words were being written
the way a variable is named: "no date", "not recorded", "none". Beside a column
of proper nouns and figures they read as something the software forgot to
finish, and next to a status printed straight from the database, "draft", the
whole cell looks like a column dump rather than a sentence.

SENTENCE CASE, NOT TITLE CASE

"No date", never "No Date". Capitalising every word is how a form reads when it
was generated from field names. The one job of the capital is to say this is
the start of something a person is meant to read.

WHAT IS CHECKED

The two positions where a string is certainly read as a VALUE: alone inside a
muted span, and alone inside a table cell. A lowercase phrase in either is a
placeholder that was written like an identifier.

WHAT IS NOT

Words inside a sentence, which are listed below and keep their case: a hint
reading "optional" after a label is not a value. Anything with an expression in
it, because that is not a literal. Comments.

    python qa/a-placeholder-starts-with-a-capital.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "src"

MUTED = re.compile(r'<span className="muted[^"]*">\s*([a-z][a-z0-9 \'/-]{1,30}?)\s*</span>')
CELL = re.compile(r'<td[^>]*>\s*([a-z][a-z0-9 \'/-]{1,30}?)\s*</td>')

#: Genuinely part of a sentence or a field hint, not a value standing in for
#: data. Each one earns its lowercase.
KEEP = {"to", "is", "of", "and", "or", "a", "an", "the", "this one", "optional",
        "required", "per", "each", "from", "at", "in", "on"}

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


print("\n  a placeholder starts with a capital\n")

hits: list[str] = []
files = sorted(WEB.rglob("*.tsx"))
for f in files:
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
        for pattern in (MUTED, CELL):
            for m in pattern.finditer(line):
                word = m.group(1)
                if word in KEEP:
                    continue
                hits.append(f"{f.relative_to(ROOT)}:{n}  {word!r}")

check(f"there are screens to check ({len(files)})", len(files) > 50)
check("no value is written in lower case", not hits,
      f"{len(hits)} place(s):\n       " + "\n       ".join(hits[:20])
      + (" ..." if len(hits) > 20 else "") if hits else "")

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
