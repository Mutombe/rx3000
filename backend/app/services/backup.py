"""Backups, from inside the product.

A pharmacy will not run its own database backups. If the software does not do
it, nobody does — and one disk failure ends the business, because the stock
ledger, the controlled-substances register and every claim live in one file.

Three things here are deliberate:

* **A backup is verified before it is called a backup.** Copying a file proves
  nothing: the copy is opened, integrity-checked and its table counts compared
  against the source. An unverified backup is worse than none, because somebody
  is relying on it.

* **SQLite is copied with its own backup API, not with the filesystem.** A
  `cp` of a live database can capture a half-written page or miss the
  write-ahead log entirely, producing a file that opens fine and is subtly
  wrong. The engine's own routine takes a consistent snapshot of a database
  being written to.

* **Old backups are pruned, and the newest is never pruned.** A disk that fills
  stops the pharmacy trading; a retention rule that could delete the only good
  copy is worse than no retention rule.
"""
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import settings

log = logging.getLogger("rx3000.backup")

BACKUP_DIR = Path(os.getenv("RX3000_BACKUP_DIR", "backups"))
KEEP = int(os.getenv("RX3000_BACKUP_KEEP", "14"))


class BackupError(RuntimeError):
    """Raised when a backup could not be taken or could not be trusted."""


def _database_path() -> Path:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        raise BackupError(
            "Only SQLite is backed up from inside the product. A server database "
            "is backed up by whoever runs the server.")
    return Path(url.split("///")[-1]).resolve()


@dataclass
class BackupFile:
    name: str
    path: str
    size_bytes: int
    taken_at: datetime
    verified: bool


def _counts(path: Path) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")]
        return {t: con.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
                for t in tables}
    finally:
        con.close()


def take(note: str = "") -> dict:
    """Take a verified backup. Raises rather than returning a file nobody checked."""
    source = _database_path()
    if not source.exists():
        raise BackupError(f"No database at {source}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"rx3000-{stamp}.db"

    # SQLite's own backup API rather than a file copy: a copy of a live database
    # can catch a half-written page or miss the WAL, giving a file that opens
    # cleanly and is quietly wrong.
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    # --- verify, or it is not a backup ---
    problems = []
    try:
        check = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
        check.close()
        if result != "ok":
            problems.append(f"integrity check said '{result}'")
    except sqlite3.Error as exc:
        problems.append(f"the copy would not open: {exc}")

    if not problems:
        before, after = _counts(source), _counts(target)
        missing = [t for t in before if t not in after]
        short = [f"{t} {after[t]} of {before[t]}" for t in before
                 if t in after and after[t] < before[t]]
        if missing:
            problems.append("tables missing: " + ", ".join(missing))
        if short:
            problems.append("rows missing: " + "; ".join(short[:5]))

    if problems:
        target.unlink(missing_ok=True)
        raise BackupError(
            "The backup was taken and then failed verification, so it has been "
            "deleted rather than left to be relied on: " + "; ".join(problems))

    if note:
        (BACKUP_DIR / f"{target.stem}.txt").write_text(note, encoding="utf-8")

    pruned = prune()
    size = target.stat().st_size
    return {
        "name": target.name,
        "path": str(target),
        "size_bytes": size,
        "size_mb": round(size / 1_048_576, 2),
        "verified": True,
        "tables": len(_counts(target)),
        "pruned": pruned,
        "taken_at": datetime.now(),
        "note": note,
    }


def listing() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    files = sorted(BACKUP_DIR.glob("rx3000-*.db"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for path in files:
        note_file = path.with_suffix(".txt")
        out.append({
            "name": path.name,
            "size_mb": round(path.stat().st_size / 1_048_576, 2),
            "taken_at": datetime.fromtimestamp(path.stat().st_mtime),
            "note": note_file.read_text(encoding="utf-8") if note_file.exists() else "",
        })
    return out


def prune(keep: int = KEEP) -> list[str]:
    """Delete the oldest beyond `keep`. The newest is never deleted."""
    files = sorted(BACKUP_DIR.glob("rx3000-*.db"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    # max(1, keep) — a retention setting of zero must not be read as an
    # instruction to delete the only copy there is.
    for path in files[max(1, keep):]:
        path.with_suffix(".txt").unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        removed.append(path.name)
    return removed


def status() -> dict:
    """Whether this pharmacy is actually protected, said plainly."""
    files = listing()
    latest = files[0] if files else None
    age_hours = (round((datetime.now() - latest["taken_at"]).total_seconds() / 3600, 1)
                 if latest else None)
    stale = age_hours is None or age_hours > 24
    return {
        "directory": str(BACKUP_DIR.resolve()),
        "count": len(files),
        "keep": KEEP,
        "latest": latest,
        "age_hours": age_hours,
        "protected": bool(latest) and not stale,
        "message": ("No backup has ever been taken. One disk failure ends this "
                    "business." if not latest else
                    f"Last backup {age_hours} hours ago." if not stale else
                    f"The last backup was {age_hours} hours ago. A day's "
                    "dispensing is not recoverable."),
    }
