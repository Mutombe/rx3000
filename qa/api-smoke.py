"""Ask every parameterless GET endpoint whether it still answers.

Cheap, and it catches the class of fault that is invisible to a typecheck, a
build and the test suite: a response schema that cannot serialise the rows
actually in the database. Nothing in the code is wrong in that case — the data
simply grew a NULL the schema does not allow, so only a real request finds it.

    python qa/api-smoke.py            # needs the backend running (RX5000_API to point elsewhere)

What it found the first time it was run:

    GET /api/products -> 500, for all 545 products.

`bin_location` and `manufacturer` had been added as `VARCHAR` with no DEFAULT,
so every existing row was NULL, while the API declared them as plain `str`.
`field: str = ""` supplies the default only when the key is *missing*, and
reading from an ORM object the attribute is always present, so one unfilled
column returned 500 for the entire catalogue, the stock screens, and the offline
catalogue sync. The friendly error worked exactly as designed and told nobody
which two columns.

Two failures of my own to record, because both made a test pass while proving
nothing:

  * The first version enumerated `app.routes` and read `r.path`. The app wraps
    routers in `_IncludedRouter`, which has no `.path`, so the guard
    `getattr(r, "methods", None)` skipped nearly everything in silence. It
    reported "checked 2 endpoints, failures none" against an app with 129, and
    the 500 above was in the part it never looked at. It now enumerates from the
    OpenAPI schema and asserts the count is plausible before believing a pass.

  * 400 is not in the acceptable list, and one endpoint returns it deliberately
    ("Specify a record to build a timeline for"). Verify a 400 is a refusal you
    meant before adding it to the allowed set — silencing it wholesale would
    hide genuine bad-request bugs.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

# Overridable, because a stale server holding the default port makes this check
# describe code from days ago while reporting "0 failing", which is worse than
# not running it. RX3000_API points it at whichever backend is current.
BASE = os.environ.get("RX5000_API") or os.environ.get("RX3000_API") or "http://localhost:8177"
# 401/403 mean the route is alive and guarded; 404/422 mean it wants arguments
# this script does not invent. 5xx is the only thing being hunted.
OK = {200, 204, 400, 401, 403, 404, 422, 428}


def token() -> str:
    body = json.dumps({"username": "admin", "password": "admin123"}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/auth/login", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["access_token"]


def main() -> int:
    from app.main import app

    paths = sorted(
        p for p, ops in app.openapi()["paths"].items()
        if "get" in ops and "{" not in p and p.startswith("/api")
    )
    # A silent under-count is how this script passed while missing an outage.
    if len(paths) < 50:
        print(f"FAIL: only {len(paths)} endpoints enumerated — the enumeration "
              f"is broken, not the API")
        return 2

    tok = token()
    failures = []
    for path in paths:
        req = urllib.request.Request(
            f"{BASE}{path}", headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:                     # noqa: BLE001
            code = type(e).__name__
        if code not in OK:
            failures.append((path, code))
            print(f"  {code}  {path}")

    print(f"checked {len(paths)} GET endpoints, {len(failures)} failing")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
