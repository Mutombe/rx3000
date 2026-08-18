"""Count the queries an endpoint issues, and how long it takes.

    python qa/query-count.py "/api/products/paged?per_page=25"

A page of 25 rows should be a handful of queries. If it is 28, the serialiser is
walking a relationship per row, and the endpoint gets slower in proportion to the
data — the failure that never shows on a demo database and always shows on a real
one.

What it found when first run, all since fixed by eager loading:

    /api/authorisations/paged   28 queries for 25 rows   (auth.uses per row)
    /api/remittances/paged      28 queries for 25 rows   (advice.lines per row)
    /api/remittances/outstanding 18 queries for 25 rows  (line.remittance per row)
    /api/crm/reports/by-owner   14 queries for 3 rows    (a query per rep, then
                                                          summed in Python)

The "<-- N+1?" flag is queries > rows, which is a hint and not a verdict: an
aggregate endpoint legitimately runs seven queries to return three rows, and a
one-row endpoint that runs two is fine. Read the number, not the arrow.
"""
import os
import sys
import time
from pathlib import Path

# Runnable from anywhere: the app is imported from backend/, and its SQLite path
# is relative to that directory.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from sqlalchemy import event
from sqlalchemy.engine import Engine
from fastapi.testclient import TestClient

from app.main import app

counter = {"n": 0}


@event.listens_for(Engine, "before_cursor_execute")
def _count(conn, cursor, statement, params, context, executemany):
    counter["n"] += 1


def main(urls):
    c = TestClient(app)
    tok = c.post("/api/auth/login",
                 json={"username": "admin", "password": "admin123"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    for url in urls:
        counter["n"] = 0
        t0 = time.time()
        try:
            r = c.get(url, headers=h, timeout=120)
        except Exception as e:                                  # noqa: BLE001
            print(f"{url}\n    FAILED {type(e).__name__}")
            continue
        ms = round((time.time() - t0) * 1000)
        if r.status_code != 200:
            print(f"{url}\n    HTTP {r.status_code}")
            continue
        d = r.json()
        rows = (len(d) if isinstance(d, list)
                else len(d.get("items", d.get("laybys", d.get("lines", [])))))
        # A hint, not a verdict — see the note above.
        flag = "  <-- look" if rows > 4 and counter["n"] > rows else ""
        print(f"{url}\n    {counter['n']} queries, {ms}ms, {rows} rows{flag}")


if __name__ == "__main__":
    main(sys.argv[1:])
