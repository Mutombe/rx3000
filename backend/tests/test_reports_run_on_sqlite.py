"""The reporting screens answer on SQLite, which is what the desktop runs.

`func.greatest` is PostgreSQL's spelling and SQLite has never heard of it, so
three reporting queries that divide a pack price by the pack size answered
"no such function: greatest" — a 500 on the dashboard of every desktop install,
while the hosted server was fine.

Against a snapshot of the local database (SQLite), each screen that does that
arithmetic is asked for its figures:

  python tests/test_reports_run_on_sqlite.py
"""
import sys

from snapshot_app import client

SCREENS = [
    ("the dashboard", "/api/reports/command-centre?days=14"),
    ("repeats, weekly", "/api/repeats/weekly"),
    ("repeats, daily", "/api/repeats/daily"),
    ("repeats due", "/api/repeats/due"),
    ("repeat performance", "/api/repeats/performance"),
    ("the call sheet", "/api/repeats/call-sheet"),
    ("the dispensary worklist", "/api/dispensary/worklist"),
    ("dispensary operations", "/api/dispensary/operations"),
]


def run():
    c = client()
    from app.database import engine
    assert engine.dialect.name == "sqlite", engine.dialect.name

    for label, path in SCREENS:
        r = c.get(path)
        assert r.status_code == 200, f"{label} ({path}) answered {r.status_code}: {r.text[:200]}"
        print(f"ok    {label} answers")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:                  # noqa: BLE001
        import os
        import traceback
        traceback.print_exc()
        print("FAIL", exc)
        sys.stdout.flush()
        os._exit(1)
    print("\nall passed")
