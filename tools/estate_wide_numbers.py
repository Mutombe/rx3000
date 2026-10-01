"""Take the estate-wide uniqueness off document numbers in a SQLite file.

    python tools/estate_wide_numbers.py              # what it would do
    python tools/estate_wide_numbers.py --apply      # do it, after a backup

WHAT THIS IS FOR

A document number belongs to a pharmacy, not to a database. `uq_<table>_tenant_<column>`
says so, and `migrate.py` creates it everywhere. What it cannot always do is get
rid of the older estate-wide constraint underneath: on Postgres it drops it, and
on SQLite it cannot, because SQLite has no way to drop a table constraint
without rebuilding the table.

On a file holding one pharmacy that costs nothing — unique across the file and
unique within the pharmacy are the same sentence. On a file holding several it
is a live fault, and this is what it looks like:

    sqlite3.IntegrityError: UNIQUE constraint failed: claims.claim_number

reaching a pharmacist as "Something went wrong at our end" in the middle of
dispensing to a medical aid, because the next claim number for THIS pharmacy is
already held by a different one. Nothing in the message points at the cause.

A developer's file accumulates pharmacies: every demonstration sign-up makes
one. The file this was written against held thirty.

WHY A TOOL AND NOT A MIGRATION

Migrations run at start-up, on every deployment, for every pharmacy, with
nobody present, and the API does not boot if one fails. Rebuilding a table is
destructive if it is wrong. The combination is the one thing that should never
happen automatically, which is why `migrate.py` warns here instead of acting —
and the same reasoning `tools/pack_sizes.py` sets out for the same kind of job.

Postgres needs none of this. It is already fixed there, by the migration.

WHAT IT PRESERVES

Everything except the constraint being removed. The new table is the old
table's own CREATE statement with the one clause cut out, so column types,
defaults, primary keys and foreign keys are not retyped by hand and cannot
drift. Indexes are read before and recreated after. Rows are counted on both
sides and the old table is kept if the counts disagree.

The whole database file is copied first, so the way back is a file copy.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "backend" / "rx3000.db"


def tenant_pairs(con: sqlite3.Connection) -> list[tuple[str, str]]:
    """(table, column) for every number already made unique per pharmacy.

    Read from the composite indexes themselves rather than from a list copied
    out of migrate.py, which would be a second list to keep in step.
    """
    out = []
    rows = con.execute(
        "SELECT name, tbl_name FROM sqlite_master "
        "WHERE type='index' AND name LIKE 'uq_%_tenant_%'").fetchall()
    for name, table in rows:
        prefix = f"uq_{table}_tenant_"
        if name.startswith(prefix):
            out.append((table, name[len(prefix):]))
    return sorted(out)


def estate_wide(con: sqlite3.Connection, table: str, column: str) -> bool:
    """Whether a single-column UNIQUE still sits on this column."""
    sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone()
    if sql and sql[0] and _unique_clause(sql[0], column):
        return True
    # Or as a standalone unique index, which migrate.py can and does drop, but
    # an old file may still carry.
    for (name,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,)).fetchall():
        info = con.execute(f"PRAGMA index_info({_q(name)})").fetchall()
        unique = con.execute(f"PRAGMA index_list({_q(table)})").fetchall()
        is_unique = any(r[1] == name and r[2] for r in unique)
        if is_unique and len(info) == 1 and info[0][2] == column:
            if not name.startswith(f"uq_{table}_tenant_"):
                return True
    return False


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _unique_clause(create_sql: str, column: str) -> str | None:
    """The `UNIQUE (col)` table clause for this column, exactly as written.

    Matched on the clause rather than parsed, because the point is to cut it
    out of the original statement and leave every other character alone.
    """
    pattern = re.compile(
        r",?\s*UNIQUE\s*\(\s*[\"`\[]?" + re.escape(column) + r"[\"`\]]?\s*\)",
        re.IGNORECASE)
    found = pattern.search(create_sql)
    return found.group(0) if found else None


def rebuild(con: sqlite3.Connection, table: str, column: str) -> int:
    """Rebuild one table without its estate-wide UNIQUE. Returns rows copied."""
    create = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone()[0]
    clause = _unique_clause(create, column)
    if not clause:
        raise RuntimeError(f"{table}: no UNIQUE({column}) clause to remove")
    fresh = create.replace(clause, "", 1)

    indexes = [r[0] for r in con.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? "
        "AND sql IS NOT NULL", (table,)).fetchall()]

    cols = [r[1] for r in con.execute(f"PRAGMA table_info({_q(table)})").fetchall()]
    joined = ", ".join(_q(c) for c in cols)
    before = con.execute(f"SELECT COUNT(*) FROM {_q(table)}").fetchone()[0]

    # Without legacy_alter_table, SQLite rewrites every foreign key in every
    # OTHER table to follow the rename, so the children end up pointing at
    # <table>__old and dropping it orphans them. Same reasoning, and the same
    # pragmas, as the rebuild in migrate.py.
    con.execute("PRAGMA legacy_alter_table=ON")
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute(f"ALTER TABLE {_q(table)} RENAME TO {_q(table + '__old')}")
    con.execute(fresh)
    con.execute(f"INSERT INTO {_q(table)} ({joined}) "
                f"SELECT {joined} FROM {_q(table + '__old')}")
    after = con.execute(f"SELECT COUNT(*) FROM {_q(table)}").fetchone()[0]
    if after != before:
        raise RuntimeError(
            f"{table}: copied {after} of {before} rows. "
            f"{table}__old has been kept; do not drop it.")
    con.execute(f"DROP TABLE {_q(table + '__old')}")
    for ddl in indexes:
        con.execute(ddl)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA legacy_alter_table=OFF")
    return after


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DB), help="the SQLite file")
    ap.add_argument("--apply", action="store_true",
                    help="actually rebuild. Without this it only reports.")
    args = ap.parse_args()

    path = Path(args.db)
    if not path.exists():
        print(f"No such database: {path}")
        return 2

    con = sqlite3.connect(path)
    shops = con.execute("SELECT COUNT(*) FROM pharmacies").fetchone()[0]
    pairs = tenant_pairs(con)
    stuck = [(t, c) for t, c in pairs if estate_wide(con, t, c)]

    print(f"{path}")
    print(f"  {shops} pharmacies, {len(pairs)} numbers made unique per pharmacy")
    if not stuck:
        print("\nok  none of them is still unique across the whole file. "
              "Nothing to do.")
        return 0

    print(f"\n  {len(stuck)} still unique across the WHOLE file:\n")
    for table, column in stuck:
        n = con.execute(f"SELECT COUNT(*) FROM {_q(table)}").fetchone()[0]
        clashes = con.execute(
            f"SELECT COUNT(*) FROM (SELECT {_q(column)} FROM {_q(table)} "
            f"WHERE {_q(column)} IS NOT NULL GROUP BY {_q(column)} "
            f"HAVING COUNT(DISTINCT pharmacy_id) > 1) d").fetchone()[0]
        print(f"    {table + '.' + column:<34} {n:>7} rows"
              + (f", {clashes} number(s) already held by more than one pharmacy"
                 if clashes else ""))

    if shops <= 1:
        print("\n  This file holds one pharmacy, so unique across the file and "
              "unique\n  within the pharmacy are the same thing. There is "
              "nothing to fix.")
        return 0

    if not args.apply:
        print(f"\nThis was a dry run. Nothing has been changed.")
        print(f"  python tools/estate_wide_numbers.py --apply")
        return 0

    backup = path.with_name(
        f"{path.stem}.before-estate-fix-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
    con.close()
    shutil.copy2(path, backup)
    print(f"\n  copied the file to {backup.name}")

    con = sqlite3.connect(path)
    con.isolation_level = None
    done = 0
    for table, column in stuck:
        try:
            rows = rebuild(con, table, column)
            print(f"  rebuilt {table} ({rows} rows), {column} is now unique "
                  f"within each pharmacy only")
            done += 1
        except Exception as exc:
            print(f"  FAILED on {table}: {exc}")
            print(f"  Stopping. The file is as it was before this table, and "
                  f"{backup.name} is the way back.")
            con.close()
            return 1
    con.close()
    print(f"\nDone. {done} table(s) rebuilt. The way back is {backup.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
