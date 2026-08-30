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

Two halves, because the bug has two halves.

**What is already stored.** Every String column with a declared length, against
what the database actually holds. This has to run against SQLite, because those
rows cannot exist on Postgres — which is exactly why nobody sees them until a
deploy.

**What the code will store.** Every `Model(field=value[:N])` where N is wider
than the column. That is the shape that produced this: a slice at ten into a
column of eight. It catches the next one before any data exists, which is the
only cheap moment to catch it.

    python qa/column-widths.py
    python qa/column-widths.py --fix     # trim the stored offenders
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import ast                                          # noqa: E402

from sqlalchemy import String, inspect, text        # noqa: E402

from app.database import Base, engine               # noqa: E402
from app import models                              # noqa: E402  (registers them)


def sliced_too_wide() -> list[tuple[str, int, str, str, int, int]]:
    """`Model(field=value[:N])` where N is wider than the column.

    Matched against the model being constructed, not against the column name
    alone. A first version took the narrowest column of that name anywhere in
    the schema and reported eight places; seven were `code` or `description`
    on some other table entirely, and an audit that is wrong seven times in
    eight is one nobody runs twice.
    """
    by_class: dict[str, dict[str, int]] = {}
    for mapper in Base.registry.mappers:
        by_class[mapper.class_.__name__] = {
            c.name: c.type.length for c in mapper.local_table.columns
            if isinstance(c.type, String) and c.type.length
        }

    out = []
    for path in sorted((ROOT / "backend" / "app").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (node.func.id if isinstance(node.func, ast.Name)
                    else getattr(node.func, "attr", ""))
            columns = by_class.get(name)
            if not columns:
                continue
            for kw in node.keywords:
                limit = columns.get(kw.arg)
                if limit is None:
                    continue
                v = kw.value
                if isinstance(v, ast.Subscript) and isinstance(v.slice, ast.Slice) \
                        and isinstance(v.slice.upper, ast.Constant) \
                        and isinstance(v.slice.upper.value, int) \
                        and v.slice.upper.value > limit:
                    out.append((path.relative_to(ROOT).as_posix(), v.lineno,
                                name, kw.arg, v.slice.upper.value, limit))
    return out


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

    slices = sliced_too_wide()

    if not findings and not slices:
        print("nothing is longer than the column that holds it, and nothing "
              "in the code would make it so")
        return 0

    if findings:
        print("Stored longer than the column allows — Postgres will refuse these\n")
        for table, column, limit, count, longest in findings:
            print(f"  {table}.{column}")
            print(f"      declared {limit}, longest {longest}, {count:,} row(s) over")
        print()

    if slices:
        print("Sliced wider than the column it is written to\n")
        for path, line, cls, column, n, limit in slices:
            print(f"  {path}:{line}")
            print(f"      {cls}.{column} = …[:{n}] into String({limit})")
        print()
    if fix and findings:
        print(f"trimmed {sum(f[3] for f in findings):,} stored value(s) to fit")
    if slices:
        print(f"{len(slices)} slice(s) wider than their column — no --fix for "
              f"these, the number in the source has to change.")
        return 1
    if findings and not fix:
        print(f"{len(findings)} column(s) hold values they could not on "
              f"Postgres.  --fix trims them.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
