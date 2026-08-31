"""Are we still calling things what the trade calls them?

A pharmacist moving off Proppharm has twenty years of vocabulary and no reason
to learn ours. Where this software invented a word for something the trade
already names, the trade wins — a dispenser should be able to read a screen
they have never seen and know what every figure is.

THE ONE THAT PROMPTED THIS

When a medical aid does not cover the full price and the patient makes up the
difference at the counter, that difference is a **shortfall**. Every pharmacy
in Zimbabwe says so; the inspecting pharmacist said so. This software called it
"patient portion" and "patient pays" — accurate descriptions of the number that
nobody would say out loud, in a ledger line, on a printed receipt and on the
dispensing screen, so the same money had three names and none of them the right
one.

WHAT THIS CHECKS, AND WHAT IT DELIBERATELY DOES NOT

It looks for the replaced wording in text that reaches a person: a JSX string,
a printed receipt template, a ledger description, an API note. It does not
touch field names. `patient_portion` is a perfectly good column and renaming it
would be a migration, a schema change and a week of nothing improving for
anybody standing at a counter. The name a person reads is the thing that has to
be right.

Nor does it object to "patient pays" everywhere. A private patient paying cash
is paying the price, not a shortfall — a shortfall exists only where a scheme
was billed and did not cover it all. So the phrase survives where the code can
be seen choosing between them, and is reported where it is hard-coded next to a
claim, which is where it is wrong.

    python qa/trade-terms.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"
BACKEND = ROOT / "backend" / "app"

#: The wording that was replaced, and what it should now say. Matched only in
#: text a person reads — see the note above about field names.
REPLACED: list[tuple[str, str, str]] = [
    (r"Patient portion",
     "Shortfall",
     "the part of the price the scheme did not cover"),
    (r"\bPatient pays\b(?![^<]{0,40}\{)",
     "Shortfall, where a scheme was billed",
     "hard-coded beside a claim, where it is always a shortfall"),
]

#: Files whose strings are read by a person. A ledger description and a receipt
#: template count; a test fixture and this file do not.
def sources() -> list[Path]:
    out: list[Path] = []
    out += sorted(FRONTEND.rglob("*.tsx"))
    out += [FRONTEND / "print.ts", FRONTEND / "terms.ts"]
    out += sorted(BACKEND.rglob("*.py"))
    return [p for p in out if p.exists()]


def main() -> int:
    findings: list[str] = []
    scanned = 0

    for file in sources():
        # terms.ts is where the old wording is quoted on purpose, to explain
        # what it replaced. A check that fails on its own documentation is a
        # check that gets deleted.
        if file.name == "terms.ts":
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        scanned += 1
        for pattern, should, why in REPLACED:
            for match in re.finditer(pattern, text):
                line_no = text.count("\n", 0, match.start()) + 1
                line = text.splitlines()[line_no - 1].strip()
                # A comment explaining the change is not the change coming back.
                if line.lstrip().startswith(("#", "*", "//", "/*")):
                    continue
                findings.append(
                    f"{file.relative_to(ROOT).as_posix()}:{line_no}\n"
                    f"       {line[:96]}\n"
                    f"       say \"{should}\" — {why}")

    for finding in findings:
        print(f"  X    {finding}\n")

    print(f"  {scanned} file(s) read; {len(findings)} still use the old wording")
    if findings:
        print("\nthe same money under three names is three names too many. "
              "frontend/src/terms.ts holds the vocabulary.")
        return 1
    print("\nthe counter, the receipt and the ledger all call a shortfall a "
          "shortfall")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
