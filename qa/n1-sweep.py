"""Count the queries behind every endpoint the front end actually calls.

The last sweep measured a list of endpoints I wrote out by hand, so
`/api/dispensary/worklist` was not in it, and that was the one doing 2,698
queries and timing out in production. A list of endpoints somebody remembered
is not a list of endpoints the application uses.

So this reads the front end for every `api.get("/api/…")` it contains, drops
the ones that need an id or a body, and asks the running application how many
queries each costs. The arrow is a hint, not a verdict: an aggregate screen
legitimately runs seven queries to return three rows. Read the number.

    python qa/n1-sweep.py            # every GET the front end makes
    python qa/n1-sweep.py --top 20   # the worst twenty only
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from sqlalchemy import event                      # noqa: E402
from sqlalchemy.engine import Engine              # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402

from app.main import app                          # noqa: E402

counter = {"n": 0}


@event.listens_for(Engine, "before_cursor_execute")
def _count(conn, cursor, statement, params, context, executemany):
    counter["n"] += 1


def wanted_paths() -> list[str]:
    """Every literal GET path in the front end that needs no id."""
    src = ROOT / "frontend" / "src"
    found: set[str] = set()
    call = re.compile(r'api\.get<[^>]*>\(\s*[`"\']([^`"\']+)[`"\']')
    for path in list(src.rglob("*.ts")) + list(src.rglob("*.tsx")):
        for raw in call.findall(path.read_text(encoding="utf-8", errors="replace")):
            # `${...}` means it needs a record that may not exist; a sweep that
            # invents ids measures 404s, which cost one query and look wonderful.
            if "${" in raw or not raw.startswith("/api/"):
                continue
            found.add(raw.split("#")[0])
    return sorted(found)


def main() -> int:
    top = 0
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])

    client = TestClient(app)
    token = client.post("/api/auth/login",
                        json={"username": "admin", "password": "admin123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    rows = []
    for path in wanted_paths():
        counter["n"] = 0
        started = time.time()
        try:
            response = client.get(path, headers=headers)
        except Exception as exc:                              # noqa: BLE001
            rows.append((0, 0, 0, path, type(exc).__name__))
            continue
        took = round((time.time() - started) * 1000)
        if response.status_code != 200:
            rows.append((0, took, counter["n"], path, f"HTTP {response.status_code}"))
            continue
        body = response.json()
        count = (len(body) if isinstance(body, list)
                 else len(body.get("items", body.get("queue", body.get("lines", []))))
                 if isinstance(body, dict) else 0)
        rows.append((counter["n"], took, count, path, ""))

    rows.sort(reverse=True)
    shown = rows[:top] if top else rows
    print(f"{'queries':>8} {'ms':>7} {'rows':>6}  endpoint")
    for queries, took, count, path, note in shown:
        flag = ""
        if not note and queries > 40:
            flag = "   <-- look"
        elif not note and count > 4 and queries > count:
            flag = "   <-- look"
        print(f"{queries:8} {took:7} {count:6}  {path}{flag}{('  ' + note) if note else ''}")

    heavy = [r for r in rows if r[0] > 40 and not r[4]]
    print(f"\n{len(rows)} endpoints the front end calls; "
          f"{len(heavy)} cost more than 40 queries")
    for queries, took, count, path, _ in heavy:
        print(f"   {queries:5} queries, {count:4} rows   {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
