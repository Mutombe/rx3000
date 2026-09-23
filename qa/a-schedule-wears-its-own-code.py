"""A medicine wears the code this country writes, never another country's.

WHY THIS GUARD EXISTS, AND WHY IT IS BIGGER THAN IT WAS

The schedule number in the database is an internal ordinal. What a pharmacist
reads, says out loud and writes on a label is a code, and the codes differ by
country: schedule 5 is S5 in South Africa and PP10 in Zimbabwe, schedule 6 is
S6 and N.

The first version of this guard caught `S{product.schedule}` built at render
time and passed everything clean. It was checking the one form of the bug it
had just been written against, and the pharmacy still saw "Schedule 5 and 6"
on the controlled register, "Prescription (S3, S4)" on a dispensary tab, and
"PP10 and N" nowhere, because those are not interpolations. They are typed
literals, and there were more of them than there were interpolations.

So this checks both forms, on both sides of the wire:

  built      `S{n}`, `f"S{n}"`, `"S" + str(n)` — a code assembled from the
             ordinal, which is right in exactly one country.
  typed      "S5", "Schedule 6", "S5 / S6", "(S3, S4)" — a code somebody wrote
             out, which is right in exactly one country and cannot be fixed by
             changing the jurisdiction pack.

WHAT IS NOT A BUG

Comments and docstrings. They explain the history, most of them explain THIS
history, and rewriting them would delete the explanation of why the rule
exists. Only text a user or an inspector can read is checked, which on the
Python side means the string constants an `ast` walk finds after the
docstrings are removed, rather than whatever a regex thinks a string is.

    python qa/a-schedule-wears-its-own-code.py
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "src"
API = ROOT / "backend" / "app"

#: Files that name the South African scale on purpose.
ALLOWED = {
    # Owns the mapping, and owns the fallback.
    "schedules.ts",
    # The jurisdiction packs. The ZA pack's own labels ARE "Schedule 0" and so
    # on; that is the definition, not a leak of it.
    "jurisdictions.py",
    "schedule_policy.py",
    # The printed wall sheet says "not the South African S0 to S6 scale" in
    # order to warn against it. Stripping that sentence would remove the
    # warning and leave the mistake.
    "schedule_sheet.py",
    # A one-off operator CLI, never read by a pharmacy.
    "classify_schedules.py",
    # Embedded font data. Base64 contains every two-character pair there is.
    "docFont.ts",
    # This guard.
    pathlib.Path(__file__).name,
}

#: A code assembled from the ordinal at run time.
BUILT = re.compile(
    r"S\{[A-Za-z_][\w.?\[\]]*schedule"      # JSX  S{product.schedule}
    r"|`S\$\{"                               # TS   `S${n}`
    r"|f\"S\{"                               # py   f"S{n}"
    r"|'S'\s*\+\s*str\(|\"S\"\s*\+\s*str\("  # py   "S" + str(n)
)

#: A code somebody typed out.
#:
#: Case SENSITIVE for the letter form, which is the whole difference between
#: the schedule "S3" and the AWS bucket "s3", the sig shorthand "s1" and a SQL
#: alias "s2". Only the prose form takes either case, because both "Schedule 5"
#: and "schedule 5" shipped.
TYPED = re.compile(r"\bS[0-6]\b|\b[Ss]chedule\s+[0-6]\b")

#: `var(--s4)` is a spacing token, not a schedule.
CSS_TOKEN = re.compile(r"--s[0-9]")

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


def shipped_strings(path: pathlib.Path):
    """Every string constant in a Python file that is not a docstring.

    An `ast` walk rather than a regex, because the whole difficulty here is
    telling a sentence a pharmacist reads from a sentence explaining why the
    sentence a pharmacist reads had to change, and the second kind outnumbers
    the first.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docs.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docs):
            yield node.lineno, node.value


print("\n  a schedule wears its own code\n")

# ---- the frontend: comments stripped by line, which is enough for TSX -------
web_files = [f for f in sorted(list(WEB.rglob("*.tsx")) + list(WEB.rglob("*.ts")))
             if f.name not in ALLOWED]
for f in web_files:
    # Block comments tracked rather than guessed. The misses that mattered
    # were CONTINUATION lines: the second line of a `/* ... */` explaining why
    # the code below no longer says "Schedule 5" does not begin with a marker,
    # and reads exactly like the bug it describes.
    in_block = False
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        opens = "/*" in line
        closes = "*/" in line
        was_in_block = in_block
        if opens and not closes:
            in_block = True
        elif closes:
            in_block = False
        if was_in_block or opens:
            continue
        if stripped.startswith(("*", "//")):
            continue
        if CSS_TOKEN.search(line):
            continue
        # The documented fallback: a label carries the country's code and drops
        # back to the ordinal only when that code is absent.
        if "schedule_code ||" in line or "?? `S$" in line:
            continue
        if BUILT.search(line) or TYPED.search(line):
            hits.append(f"{f.relative_to(ROOT)}:{n}  {stripped[:88]}")

# ---- the backend: only the strings a user can actually receive --------------
api_files = [f for f in sorted(API.rglob("*.py")) if f.name not in ALLOWED]
for f in api_files:
    for n, text in shipped_strings(f):
        if BUILT.search(text) or TYPED.search(text):
            hits.append(f"{f.relative_to(ROOT)}:{n}  {text.strip()[:88]}")
    # f-strings are not plain constants, so the assembled form is caught on the
    # raw line as well.
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if BUILT.search(line):
            hits.append(f"{f.relative_to(ROOT)}:{n}  {stripped[:88]}")

check(f"there are files to check ({len(web_files)} screens, {len(api_files)} modules)",
      len(web_files) > 50 and len(api_files) > 50)
check("nothing shipped names another country's schedule scale",
      not hits,
      f"{len(hits)} place(s):\n       "
      + "\n       ".join(sorted(set(hits))[:40]) if hits else "")

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
