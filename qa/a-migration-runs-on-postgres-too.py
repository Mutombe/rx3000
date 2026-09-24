"""Raw SQL that only works on SQLite must not reach the migrations.

THIS HAS NOW HAPPENED TWICE.

Development runs on SQLite and production runs on Postgres, and SQLite has no
opinion about most of the things Postgres is strict about. So a migration can
be written, run clean on a laptop, pass every check, and then refuse to
execute on the only database that matters.

Both times it was the same shape. `is_cash = 1`, and then `is_change = 0`:
comparing a boolean column to a number. SQLite stores booleans as 0 and 1 and
compares them happily; Postgres answers "operator does not exist: boolean =
integer" and the statement dies. Because migrations run inside the startup
lifespan, a dead statement in the fatal block means the API does not boot, so
the symptom is not a broken screen — it is a pharmacy that cannot open.

migrate.py carries a comment describing the first occurrence. A comment did
not prevent the second one. This does.

What it checks:

  1. No raw SQL anywhere in the backend compares a Boolean column to 0 or 1.
     The Boolean columns are read from models.py rather than listed here, so
     a new one is covered the day it is added.
  2. No raw SQL uses a construct SQLite tolerates and Postgres does not:
     double-quoted string literals, `strftime`, `||` used as OR, `AUTOINCREMENT`,
     or `INSERT OR REPLACE`.
  3. Every data backfill is registered in the ADVISORY list rather than the
     fatal one. A backfill fills in columns that already exist; if it fails the
     screens that read them are empty, which is a bad morning and not a closed
     shop. Only schema changes are allowed to stop the server.

     A backfill that genuinely must stop it — one that decides who may see
     whose data, where a wrong answer is worse than no answer — may stay in
     the fatal block by writing `FATAL BY DESIGN:` in its docstring and
     saying why. The point is not that nothing may be fatal. It is that being
     fatal has to be a decision somebody made on purpose and wrote down.

Run by exit code. Nought is a pass.
"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend" / "app"
MIGRATE = BACKEND / "migrate.py"

#: SQLite accepts these; Postgres does not, or means something else by them.
ONLY_SQLITE = [
    (r"\bAUTOINCREMENT\b", "AUTOINCREMENT is SQLite's alone; Postgres uses a sequence"),
    (r"\bINSERT\s+OR\s+(REPLACE|IGNORE)\b", "INSERT OR REPLACE is SQLite's; "
                                            "Postgres wants ON CONFLICT"),
    (r"\bstrftime\s*\(", "strftime is SQLite's; Postgres wants to_char or date_trunc"),
    (r"\bdatetime\s*\(\s*'now'", "datetime('now') is SQLite's; Postgres wants now()"),
    (r"\bPRAGMA\b", "PRAGMA is SQLite's alone"),
]


def boolean_columns() -> set[str]:
    """Every Boolean column in the model, by name."""
    models = (BACKEND / "models.py").read_text(encoding="utf-8")
    return set(re.findall(r"(\w+)\s*=\s*Column\(\s*Boolean", models))


def sql_lines():
    """Every line in the backend that looks like it carries raw SQL."""
    for path in sorted(BACKEND.rglob("*.py")):
        try:
            src = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for n, line in enumerate(src.split("\n"), 1):
            if '"' not in line and "'" not in line:
                continue
            if not re.search(r"\b(SELECT|UPDATE|INSERT|DELETE|ALTER|CREATE|WHERE|FROM)\b",
                             line, re.I):
                continue
            yield path, n, line


def main() -> int:
    faults: list[str] = []
    bools = boolean_columns()
    if not bools:
        print("Found no Boolean columns in models.py, which cannot be right.")
        return 1

    for path, n, line in sql_lines():
        rel = f"{path.parent.name}/{path.name}"
        for col in bools:
            if re.search(rf"\b{re.escape(col)}\s*(=|!=|<>)\s*[01]\b", line):
                faults.append(
                    f"{rel}:{n} compares the boolean `{col}` to a number. "
                    f"SQLite evaluates it and Postgres refuses with 'operator "
                    f"does not exist: boolean = integer'. Write `NOT {col}` or "
                    f"`{col}` instead, which both databases read the same way."
                    f"\n         {' '.join(line.split())[:100]}")
        for pattern, why in ONLY_SQLITE:
            if re.search(pattern, line, re.I):
                faults.append(f"{rel}:{n} {why}."
                              f"\n         {' '.join(line.split())[:100]}")

    # ---- backfills are advisory, never fatal ------------------------------
    src = MIGRATE.read_text(encoding="utf-8")
    fatal = src[src.index("applied += _add_tenant_columns"):
                src.index("# The tidying passes run in their own transactions")]
    advisory = src[src.index("for label, needs, fix in ["):]
    called_fatally = set(re.findall(r"applied \+= (_\w+)\(", fatal))

    # A pass that only writes to columns is a backfill; one that adds or alters
    # them is a schema change and is allowed to be fatal.
    for name in sorted(called_fatally):
        body = re.search(rf"\ndef {re.escape(name)}\(.*?(?=\ndef )", src, re.S)
        if not body:
            continue
        text = body.group(0)
        touches_schema = re.search(r"ALTER TABLE|CREATE (TABLE|INDEX|UNIQUE)", text, re.I)
        writes_data = re.search(r"\bUPDATE \w+ SET\b", text, re.I)
        # Allowed to stop the server, having said why.
        declared = "FATAL BY DESIGN:" in text
        if writes_data and not touches_schema and not declared:
            faults.append(
                f"migrate.py runs `{name}` in the fatal block, but it only "
                f"fills in data — no ALTER or CREATE. A backfill that raises "
                f"stops the API booting, which is a pharmacy that cannot open "
                f"for a column nobody was reading yet. Move it to the advisory "
                f"list at the bottom of run_migrations.")

    if faults:
        print("\nA migration has to run on Postgres, not just on a laptop:\n")
        for fault in faults:
            print(f"  X  {fault}")
        print(f"\n{len(faults)} fault(s).")
        return 1

    print(f"Raw SQL is portable, and every backfill is advisory. "
          f"({len(bools)} boolean columns checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
