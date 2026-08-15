"""Proving a backup is restorable, rather than assuming a file is a backup.

The system we are replacing lists its archives with a name, a date and a size.
One of the entries in the photograph of that screen reads:

    D20260809.ZIP    09 Aug 2026    0.00 MBytes

That is a backup which failed, sitting in the list looking exactly like the ones
that worked. Nothing about the screen distinguishes them. A pharmacy finds out
which is which on the one day it matters, and by then the answer is fixed.

So a backup here is not "a file was written". It is:

1. The file exists and is not empty.
2. SQLite can open it and its own integrity check passes — this catches a
   truncated or half-flushed copy, which is the usual way a backup taken while
   the machine is busy goes wrong.
3. The tables that matter are present and hold roughly what the live database
   holds. An openable database with no patients in it is not a backup of this
   pharmacy.

Only when all three pass is it recorded as good. The verdict is written beside
the file, so the listing can show it without re-checking every archive on every
page load, and so a backup copied to a memory stick carries its verdict with it.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

# The tables whose emptiness would mean the backup is not of this pharmacy.
# Deliberately short: this is a smoke test, not a reconciliation.
WITNESS_TABLES = ["users", "products", "patients", "sales"]

# How far a count may drift from the live database and still be believed. A
# backup is taken while trading continues, so an exact match is the wrong test —
# but half the rows missing is not drift, it is a truncated copy.
TOLERANCE = 0.05


def _counts(path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        present = {
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for table in WITNESS_TABLES:
            if table in present:
                out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()
    return out


def verify(backup_path: Path, live_path: Path | None = None) -> dict:
    """Open the backup and decide whether it could actually be restored."""
    result: dict = {
        "verified_at": datetime.utcnow().isoformat(),
        "ok": False,
        "size_bytes": 0,
        "problems": [],
        "counts": {},
    }

    if not backup_path.exists():
        result["problems"].append("The backup file is not there.")
        return result

    result["size_bytes"] = backup_path.stat().st_size
    if result["size_bytes"] == 0:
        # The exact failure their screen cannot distinguish from success.
        result["problems"].append(
            "The backup is empty. Nothing was written, and the disk may be full."
        )
        return result

    try:
        conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
        try:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        result["problems"].append(
            f"The backup cannot be opened as a database ({exc}). It is corrupt "
            "or was copied while being written."
        )
        return result

    if check != "ok":
        result["problems"].append(f"The database inside the backup is damaged: {check}")
        return result

    try:
        result["counts"] = _counts(backup_path)
    except sqlite3.DatabaseError as exc:
        result["problems"].append(f"The backup opened but could not be read: {exc}")
        return result

    missing = [t for t in WITNESS_TABLES if t not in result["counts"]]
    if missing:
        result["problems"].append(
            "The backup is missing " + ", ".join(missing)
            + ". It opened, but it is not a backup of this system."
        )
        return result

    if live_path and live_path.exists():
        try:
            live = _counts(live_path)
        except sqlite3.DatabaseError:
            live = {}
        for table, live_count in live.items():
            backed = result["counts"].get(table, 0)
            # Only a shortfall matters. More rows than live simply means trading
            # continued after the copy started, which is expected.
            if live_count and backed < live_count * (1 - TOLERANCE):
                result["problems"].append(
                    f"{table}: the backup holds {backed:,} rows against {live_count:,} "
                    "live. That is too large a gap to be ordinary trading."
                )

    result["ok"] = not result["problems"]
    return result


def sidecar_for(backup_path: Path) -> Path:
    return backup_path.with_suffix(backup_path.suffix + ".verify.json")


def record(backup_path: Path, result: dict) -> None:
    """Write the verdict beside the file.

    Beside it rather than in a database, for the obvious reason: the thing this
    protects against is the database being gone.
    """
    try:
        sidecar_for(backup_path).write_text(json.dumps(result, indent=1), encoding="utf-8")
    except OSError:
        # Failing to record the verdict must not fail the backup itself.
        pass


def read_verdict(backup_path: Path) -> dict | None:
    path = sidecar_for(backup_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def verify_and_record(backup_path: Path, live_path: Path | None = None) -> dict:
    result = verify(backup_path, live_path)
    record(backup_path, result)
    return result
