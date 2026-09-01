"""Listing sales must not cost a query per row.

`/api/pos/sales?status=paid&limit=50` ran 266 queries to return 50 rows. On
SQLite that is invisible, which is why it survived: the whole list came back in
under two hundred milliseconds locally. Against a hosted Postgres at roughly
ninety milliseconds a round trip it is the better part of half a minute, and
the front shop's billing history simply appeared to hang.

The cause is worth stating because it is the trap in every ORM: eager loading
has to reach as deep as the *schema* does, not as deep as the query looks like
it needs. SaleOut carries the tenders, the lines, the claim and the patient;
SaleItemOut carries the batch allocations; AllocationOut carries the batch;
PatientOut carries the medical aid. Serialisation walks all of it, so every
level not named in the loader is a round trip per row.

This asserts a budget rather than an exact number — a legitimate change may add
a query, but a budget low enough that a reintroduced lazy load fails it
immediately rather than in production three weeks later.
"""
import os
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import event                           # noqa: E402
from fastapi.testclient import TestClient              # noqa: E402
from app.database import engine                        # noqa: E402
from app.main import app                               # noqa: E402

# Per endpoint: the path, how many rows it should be asked for, and the most
# queries it may take. Deliberately generous — the point is the shape, not a
# golden number.
BUDGETS = [
    ("/api/pos/sales?status=paid&limit=50", 15),
    ("/api/pos/sales?status=pending&limit=20", 10),
    ("/api/pos/owed", 15),
    ("/api/dispensary/worklist", 15),
    ("/api/dispensing/will-call?limit=400", 15),
]

client = TestClient(app)
token = client.post("/api/auth/login",
                    json={"username": "admin", "password": "admin123"}).json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

count = {"n": 0}


@event.listens_for(engine, "before_cursor_execute")
def _tick(conn, cursor, statement, params, context, executemany):
    count["n"] += 1


failures = []
for path, budget in BUDGETS:
    count["n"] = 0
    response = client.get(path, headers=headers)
    queries = count["n"]
    body = response.json() if response.status_code == 200 else None
    rows = len(body) if isinstance(body, list) else (
        len(body.get("items", [])) if isinstance(body, dict) else 0)
    ok = response.status_code == 200 and queries <= budget
    print(f"  {'ok  ' if ok else 'FAIL'} {queries:4} queries for {rows:4} rows "
          f"(budget {budget})  {path}")
    if not ok:
        failures.append(f"{path}: {queries} queries, budget {budget}")

print()
if failures:
    print(f"{len(failures)} over budget")
    for f in failures:
        print(f"  {f}")
    sys.exit(1)
print("listing rows does not cost a query per row")
