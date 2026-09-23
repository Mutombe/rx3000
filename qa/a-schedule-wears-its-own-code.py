"""A medicine wears the code this country writes, never the ordinal.

WHY THIS GUARD EXISTS

The schedule number in the database is an internal ordinal. What a pharmacist
reads, says out loud, and writes on a label is a code, and the codes differ by
country: schedule 5 is S5 in South Africa and PP10 in Zimbabwe, schedule 6 is
S6 and N.

`schedules.ts` has said so since it was written, and its own docstring records
that every screen rendered `S{schedule}` anyway. It happened again: fifteen
files were still printing the South African form, including the CONTROLLED
REGISTER'S PRINTED DOCUMENT — so a pharmacy in Harare handed an inspector a
legal register labelled with another country's codes.

It is wrong in the way that is hardest to notice. "S5" is a plausible thing to
see, it sorts correctly, and it is only wrong about the one thing the badge
exists to say.
"""
import pathlib
import re
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src"

#: `schedules.ts` itself documents the mapping and owns the fallback.
ALLOWED = {"schedules.ts"}

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


print("\n  a schedule wears its own code\n")

# `S{...schedule}` in JSX, and `` `S${...}` `` in a string.
RAW = re.compile(r"S\{[A-Za-z_][A-Za-z0-9_.?\[\]]*schedule|`S\$\{")

found = []
scanned = 0
for f in sorted(list(SRC.rglob("*.tsx")) + list(SRC.rglob("*.ts"))):
    if f.name in ALLOWED:
        continue
    scanned += 1
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith(("*", "//", "/*")):
            continue
        # `schedule_code || \`S${n}\`` is the documented fallback, not the bug:
        # the label carries the country's own code and drops back to the
        # ordinal only for a label built before that code existed. A line that
        # mentions schedule_code has already preferred the right thing.
        if "schedule_code" in line:
            continue
        if RAW.search(line):
            found.append(f"{f.relative_to(SRC)}:{n}")

check(f"there are screens to check ({scanned})", scanned > 100)
check("no screen prints a raw schedule ordinal", not found,
      f"{len(found)} place(s) showing S<n> instead of the country's code: "
      + ", ".join(found[:8]) + (" ..." if len(found) > 8 else ""))

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
