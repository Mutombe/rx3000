"""A field with nothing in it says so in words, never with a dash.

WHY THIS GUARD EXISTS, AND WHY IT IS WIDER THAN IT WAS

319 cells across 101 files rendered an em dash where they had no value: a price
that had never been set, a date nobody recorded, a stock code the line was
never given. A dash is a typographic mark standing in for a sentence nobody
wrote, and it makes three different situations look identical: "nothing here",
"not applicable", and "we failed to load it". On a printed report it reads as a
redaction.

THE FIRST VERSION OF THIS GUARD PASSED WHILE DASHES WERE STILL ON SCREEN.

It looked for one character, the em dash, in five shapes, in `.tsx` files only.
It missed the commonest shape of all, `cond ? "—" : value`, which was every one
of the nine that survived. It missed the hyphen and the en dash. And it never
looked at the backend at all, where a further dozen were going into printed
reports and a purchase order emailed to a supplier.

So this checks every dash character, in both languages, on both sides of the
wire. The Python side is read through an `ast` walk rather than a regex,
because the two shapes that matter there are `value or "-"` and
`x if cond else "-"`, and a regex cannot tell either of them from a hyphen
inside a slug or a rule of dashes printed across a receipt.

WHAT THE REPLACEMENT SHOULD BE

The field's own words, not one phrase used everywhere: "no expiry recorded",
"not scanned", "no cap", "walk in", "balances". A screen that says "none" in
six columns has replaced one uninformative mark with another.

WHAT IS NOT CHECKED

Dashes in comments and docstrings, which are source and doing their proper job
as punctuation. Dashes inside a sentence. A rule of dashes printed across a
receipt, and a hyphen used to build a filename slug: those are drawings and
separators, not values.

    python qa/a-blank-cell-says-what-is-missing.py
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "src"
API = ROOT / "backend" / "app"

#: Every dash a keyboard or a paste can produce, plus the abbreviation that
#: does the same job with letters.
DASHES = "‐‑‒–—―-"
#: A whole value that is nothing but a dash.
JUST_A_DASH = re.compile(r'^\s*[' + DASHES + r']\s*$|^\s*N/?A\s*$', re.I)

#: The shapes a placeholder takes in JSX and TypeScript. Each is a value
#: standing where something absent should have been described.
SHAPES = [
    re.compile(r'\?\s*"[' + DASHES + r']"'),          # cond ? "—" : value
    re.compile(r':\s*"[' + DASHES + r']"'),           # value : "—", or key: "—"
    re.compile(r'\|\|\s*"[' + DASHES + r']"'),        # value || "—"
    re.compile(r'\?\?\s*"[' + DASHES + r']"'),        # value ?? "—"
    re.compile(r'>\s*[‐-―]\s*<'),           # >—<
    re.compile(r'\{\s*"[' + DASHES + r']"\s*\}'),     # {"—"}
    re.compile(r'["\'>]\s*N/?A\s*["\'<]', re.I),
]

#: Files where a dash is a drawing rather than a value.
ALLOWED_WEB = {
    # Builds a printed rule across a receipt: "-".repeat(width).
    "deviceAgent.ts",
    # A minus sign in front of a negative number.
    "ReportChart.tsx",
    # A compact day-of-week code, "M-W-F", where the dash is the gap.
    "HqPermissions.tsx",
    # Embedded font data.
    "docFont.ts",
}

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


def is_dash(node) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and bool(JUST_A_DASH.match(node.value)))


print("\n  a blank cell says what is missing\n")

web_hits: list[str] = []
web_files = [f for f in sorted(list(WEB.rglob("*.tsx")) + list(WEB.rglob("*.ts")))
             if f.name not in ALLOWED_WEB]
for f in web_files:
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
        if any(s.search(line) for s in SHAPES):
            web_hits.append(f"{f.relative_to(ROOT)}:{n}")

api_hits: list[str] = []
api_files = sorted(API.rglob("*.py"))
for f in api_files:
    try:
        tree = ast.parse(f.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        # `value or "-"`, the classic fallback.
        if (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
                and is_dash(node.values[-1])):
            api_hits.append(f"{f.relative_to(ROOT)}:{node.lineno}")
        # `a if cond else "-"`, and its mirror.
        elif isinstance(node, ast.IfExp) and (is_dash(node.body)
                                              or is_dash(node.orelse)):
            # A filename slug replaces unsafe characters WITH a hyphen, which
            # is the one place this shape is a separator rather than a value.
            line = f.read_text(encoding="utf-8").split("\n")[node.lineno - 1]
            if "isalnum" in line:
                continue
            api_hits.append(f"{f.relative_to(ROOT)}:{node.lineno}")

check(f"there is something to check ({len(web_files)} screens, "
      f"{len(api_files)} modules)",
      len(web_files) > 50 and len(api_files) > 50)
check("no screen stands in for a missing value with a dash", not web_hits,
      f"{len(web_hits)} place(s): " + ", ".join(web_hits[:10])
      + (" ..." if len(web_hits) > 10 else ""))
check("nor any report, document or export the server writes", not api_hits,
      f"{len(api_hits)} place(s): " + ", ".join(api_hits[:10])
      + (" ..." if len(api_hits) > 10 else ""))

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
