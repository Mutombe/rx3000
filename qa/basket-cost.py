"""Does a basket cost a query per line?

The dispensing screen recomputes the scheme's coverage and the script's totals
on every basket change. Both fetched their products one at a time, so a
ten-item script cost thirteen round trips instead of four — about a second of
nothing happening on a hosted database, repeated on every keystroke that
changes the basket, on the screen a pharmacy spends its day on.

The measurement here is deliberately not "how many queries" but "how many MORE
queries for nine more lines". An endpoint that costs six queries flat is fine
however big the script; one that costs four plus one a line is the defect, and
on a small demo database the two look almost identical.

Nothing here writes anything: these are the read paths that run while somebody
is typing. The create paths (a sale, a script, a lay-by) had the same shape and
were fixed with the same one-query change; they are not exercised here because
doing so would leave records behind on whatever database this is pointed at.

    python qa/basket-cost.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from sqlalchemy import event                      # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402

from app.main import app                          # noqa: E402
from app.database import engine                   # noqa: E402

#: More than half a query per extra line means it is fetching them one by one.
#: Not zero: a legitimate endpoint may do one extra query for a *set* of lines
#: — an `IN` over the batch — and rounding that to a per-line cost would be
#: wrong.
PER_LINE_BUDGET = 0.5

client = TestClient(app)
counted = {"n": 0}


@event.listens_for(engine, "before_cursor_execute")
def _tick(*_a, **_k):
    counted["n"] += 1


def main() -> int:
    login = client.post("/api/auth/login",
                        json={"username": "admin", "password": "admin123"})
    if login.status_code != 200:
        print(f"FAIL: could not sign in ({login.status_code})")
        return 2
    head = {"Authorization": f"Bearer {login.json()['access_token']}"}

    products = client.get("/api/products?limit=12", headers=head).json()
    ids = [p["id"] for p in (products if isinstance(products, list)
                             else products.get("items", []))]
    if len(ids) < 10:
        print(f"FAIL: only {len(ids)} products — the difference between one "
              f"line and ten is the whole measurement")
        return 2
    aids = client.get("/api/medical-aids", headers=head).json()
    aid = aids[0]["id"] if aids else None

    def basket(k: int) -> dict:
        return {"medical_aid_id": aid,
                "items": [{"product_id": i, "quantity": 1} for i in ids[:k]]}

    checks = [
        ("/api/claiming/coverage", basket,
         "the scheme's formulary, on every basket change"),
        ("/api/script-totals", basket,
         "the figures along the foot of a script"),
    ]

    worst = 0.0
    failed = False
    for path, make, why in checks:
        results = []
        for k in (1, 10):
            counted["n"] = 0
            r = client.post(path, headers=head, json=make(k))
            results.append((counted["n"], r.status_code))
        (q1, s1), (q10, s10) = results
        if s1 != 200 or s10 != 200:
            print(f"  FAIL {path} answered {s1}/{s10}, so nothing was measured")
            failed = True
            continue
        per = (q10 - q1) / 9
        worst = max(worst, per)
        ok = per <= PER_LINE_BUDGET
        failed = failed or not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {q1:>3} queries at one line, "
              f"{q10:>3} at ten ({per:+.2f} a line)  {path}")
        print(f"       {why}")

    print(f"\n{'a basket costs the same whatever its size' if not failed else 'a basket still costs a query per line'}"
          f" (worst {worst:+.2f} a line, budget {PER_LINE_BUDGET:+.2f})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
