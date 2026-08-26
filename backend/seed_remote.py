"""Seed the hosted database, from a machine whose own database is SQLite.

Local development runs on a SQLite file: it is fast, it is offline, and a
mistake at a keyboard is not a mistake in production. The hosted database is
Postgres and needs the same data in it, so this is the one script that talks to
it — given the URL explicitly, in its own process, rather than by pointing the
whole application at production and hoping nobody forgets.

    python seed_remote.py            # fill whatever is missing
    python seed_remote.py --status   # say what is there, change nothing

The URL comes from `SEED_TARGET_URL` in backend/.env, which is gitignored. It is
read and set into the environment *before* anything imports `app.config`, since
that module reads `DATABASE_URL` once at import and never looks again.

It is safe to run repeatedly and safe to interrupt. Trading skips any day that
already has sales, and every other stage checks whether its own rows exist, so a
run cut off by a dropped connection resumes rather than doubling what is there —
which matters here, because the connection does drop.
"""
from __future__ import annotations

import os
import pathlib
import sys
import time


def _target() -> str:
    env = pathlib.Path(__file__).with_name(".env")
    if not env.exists():
        sys.exit("backend/.env not found; nothing to read the target from.")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SEED_TARGET_URL="):
            url = line.split("=", 1)[1].strip()
            if url:
                return url
    sys.exit("SEED_TARGET_URL is not set in backend/.env.")


# Before any app import: config reads DATABASE_URL once, at import time.
os.environ["DATABASE_URL"] = _target()

from sqlalchemy import text  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app import models  # noqa: E402,F401 - create_all only makes what is imported
from app.migrate import run_migrations  # noqa: E402

TABLES = ["patients", "products", "medical_aids", "sales", "prescriptions",
          "dispensings", "claims", "messages", "stock_batches", "laybys",
          "shifts", "leads", "deals", "sample_receipts", "consent_events"]


def status() -> dict:
    db = SessionLocal()
    try:
        out = {}
        for t in TABLES:
            try:
                out[t] = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            except Exception:
                db.rollback()
                out[t] = "—"
        out["days of trade"] = db.execute(
            text("SELECT COUNT(DISTINCT DATE(created_at)) FROM sales")).scalar()
        out["on the shelf"] = db.execute(
            text("SELECT COUNT(*) FROM dispensings WHERE collected_at IS NULL")).scalar()
        return out
    finally:
        db.close()


def main() -> None:
    host = os.environ["DATABASE_URL"].split("@")[-1].split("/")[0]
    print(f"target: {host}\n")

    if "--status" in sys.argv:
        for k, v in status().items():
            print(f"  {k:16s} {v}")
        return

    print("bringing the schema up to date…")
    Base.metadata.create_all(bind=engine)
    print(f"  {run_migrations(engine)} migration(s) applied")

    from app.realseed import run
    # Retried rather than abandoned. The connection to a hosted database drops,
    # and a seed that gives up on the first dropped packet leaves half a dataset
    # behind — which is worse than none, because it looks like the whole thing.
    for attempt in range(1, 9):
        try:
            run(days=60)
            break
        except Exception as exc:  # noqa: BLE001 - resumable by design
            print(f"\n  attempt {attempt} stopped: {str(exc).splitlines()[0][:90]}")
            if attempt == 8:
                print("  giving up; run again and it will carry on from here")
                break
            time.sleep(min(30, attempt * 5))
            print("  retrying…")

    print("\nfinal state:")
    for k, v in status().items():
        print(f"  {k:16s} {v}")


if __name__ == "__main__":
    main()
