"""SQL written by hand has to mean the same thing on both databases.

The server runs on PostgreSQL and the desktop install runs on SQLite, from one
codebase, and the dialect that accepts more is the one development runs against.
So a comparison like

    WHERE dispensable = 0

passes every local check — SQLite has no boolean type and compares it to an
integer happily — and PostgreSQL refuses it outright: "operator does not exist:
boolean = integer". Because migrations run inside the startup lifespan, that
refusal is not a failed migration. It is a service that will not boot, and every
deploy after it crash-looping.

That has now happened twice: `is_cash = 1`, and `dispensable = 0`. Column
definitions are already translated by `_portable`; hand-written SQL is not, so
this reads the boolean columns out of the models and the migration table and
looks for any of them compared to a number in raw SQL.

    python qa/sql-speaks-both-dialects.py
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1] / "backend" / "app"

# Every column the models declare as a boolean, plus the ones the migration file
# adds as one. Those are the names that must never meet a 0 or a 1 in SQL.
def boolean_columns() -> set[str]:
    names: set[str] = set()
    models = (ROOT / "models.py").read_text(encoding="utf-8")
    for match in re.finditer(r"^\s*(\w+)\s*=\s*Column\(\s*Boolean", models, re.M):
        names.add(match.group(1))
    migrate = (ROOT / "migrate.py").read_text(encoding="utf-8")
    for match in re.finditer(r'"(\w+)":\s*"BOOLEAN', migrate):
        names.add(match.group(1))
    return names


def offences(text: str, columns: set[str]) -> list[tuple[int, str]]:
    """Lines where a boolean column is compared to a number, inside SQL."""
    found = []
    for n, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Only SQL: a Python comparison against a boolean column name is fine,
        # and `dispensable=False` as a keyword argument is how it should be done.
        if not re.search(r"\b(SELECT|UPDATE|DELETE|WHERE|SET|AND|OR)\b", line, re.I):
            continue
        for column in columns:
            if re.search(rf"\b{re.escape(column)}\s*(=|<>|!=)\s*[01]\b", line):
                found.append((n, stripped[:110]))
                break
    return found


columns = boolean_columns()
print(f"{len(columns)} boolean column name(s) known\n")

bad: list[str] = []
for path in sorted(ROOT.rglob("*.py")):
    for n, line in offences(path.read_text(encoding="utf-8"), columns):
        rel = path.relative_to(ROOT.parent.parent)
        bad.append(f"  {rel}:{n}\n      {line}")

if bad:
    print(f"{len(bad)} comparison(s) PostgreSQL will refuse:\n")
    print("\n".join(bad))
    print("\nBind the value instead — `= :off` with {\"off\": False} — so the driver\n"
          "adapts it: True/False on PostgreSQL, 1/0 on SQLite.")
    sys.exit(1)

print("no boolean column is compared to a number in hand-written SQL")
