"""Values longer than the column that holds them.

SQLite does not enforce a VARCHAR length. PostgreSQL does. So a string that is
two characters too long is written without complaint on every developer's
machine and rejected the first time it reaches production, with
`StringDataRightTruncation` and nothing about which field.

That is not hypothetical. The CareXpress script importer sliced a dispenser's
name to ten characters for a column that is eight. It loaded 53,205 rows
locally without a murmur and failed on the first batch against the hosted
database — after committing part of the run, because the failure came at the
INSERT rather than at the point somebody could have caught it.

This reads the models for every declared length and asks the database whether
anything already exceeds it. Run it against SQLite, where the offending rows
can exist; against Postgres they cannot, which is the whole problem.

    python qa/column-widths.py
    python qa/column-widths.py --fix     # trim the offenders, saying what it cut
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from sqlalchemy import String, inspect, text        # noqa: E402

from app.database import Base, engine               # noqa: E402
from app import models                              # noqa: E402  (registers them)


def main() -> int:
    fix = "--fix" in sys.argv
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    findings: list[tuple[str, str, int, int, int]] = []

    with engine.begin() as conn:
        for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
            if table.name not in tables:
                continue
            live = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if not isinstance(column.type, String) or not column.type.length:
                    continue
                if column.name not in live:
                    continue
                limit = column.type.length
                over = conn.execute(text(
                    f"SELECT COUNT(*), MAX(LENGTH({column.name})) "
                    f"FROM {table.name} WHERE LENGTH({column.name}) > :n"
                ), {"n": limit}).first()
                count, longest = (over[0] or 0), (over[1] or 0)
                if not count:
                    continue
                findings.append((table.name, column.name, limit, count, longest))
                if fix:
                    conn.execute(text(
                        f"UPDATE {table.name} "
                        f"SET {column.name} = SUBSTR({column.name}, 1, :n) "
                        f"WHERE LENGTH({column.name}) > :n"), {"n": limit})

    if not findings:
        print("nothing is longer than the column that holds it")
        return 0

    print("Longer than the column allows — Postgres will refuse these\n")
    for table, column, limit, count, longest in findings:
        print(f"  {table}.{column}")
        print(f"      declared {limit}, longest {longest}, {count:,} row(s) over")
    print()
    if fix:
        print(f"trimmed {sum(f[3] for f in findings):,} value(s) to fit")
        return 0
    print(f"{len(findings)} column(s) hold values they could not on Postgres."
          f"  --fix trims them.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
