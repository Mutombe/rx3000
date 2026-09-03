"""Does a server error reach the browser as a server error?

Twice now a fault has been reported as this:

    Access to fetch at '…' from origin '…' has been blocked by CORS policy:
    No 'Access-Control-Allow-Origin' header is present on the requested
    resource.

Twice, nothing was wrong with CORS. The handler had raised, and an unhandled
exception returns a response the CORS middleware never decorated. The browser
can only see that the header is absent, so it reports the one thing it can see:
the wrong cause, on a different layer, in a different subsystem. The first cost
an afternoon in the deployment configuration for a query filtering on a column
that did not exist; the second was a draft that would not finalise.

THE FIX THAT DID NOT WORK, AND WHY

`@app.exception_handler(Exception)` was already registered, with a docstring
saying it existed to solve exactly this. It does not. Starlette installs a
handler for `Exception` into `ServerErrorMiddleware`, which is the OUTERMOST
layer of the stack — outside CORS — so its response never passes back through
the CORS middleware either. The comment was right about the problem and wrong
about the remedy, which is worse than no comment, because it stops anybody
looking again.

The remedy is a middleware added BEFORE `CORSMiddleware`, which with
`add_middleware` means it sits inside it, since the last middleware added is
the outermost. An exception becomes an ordinary response there and is
decorated on the way out like any other.

This check asserts the property rather than the implementation: raise inside a
route, and require the response to carry the header. Any future rearrangement
of the middleware stack that loses it fails here rather than in somebody's
browser three weeks later.

    python qa/errors-keep-cors.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import logging                                      # noqa: E402
logging.disable(logging.CRITICAL)

from fastapi import APIRouter                       # noqa: E402
from fastapi.testclient import TestClient           # noqa: E402
from app.main import app                            # noqa: E402

#: An origin the application is configured to allow. If this ever stops being
#: allowed the check reports that instead, rather than silently passing.
ORIGIN = "http://localhost:5180"


def main() -> int:
    probe = APIRouter()

    @probe.get("/api/__qa_raises")
    def raises():
        raise RuntimeError("deliberate, raised by qa/errors-keep-cors.py")

    @probe.get("/api/__qa_refuses")
    def refuses():
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="deliberate refusal")

    app.include_router(probe)
    client = TestClient(app, raise_server_exceptions=False)
    failures: list[str] = []

    def check(ok: bool, said: str, why: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {said}")
        if not ok:
            failures.append(why or said)

    fine = client.get("/api/health", headers={"Origin": ORIGIN})
    allowed = fine.headers.get("access-control-allow-origin")
    check(allowed == ORIGIN,
          f"a route that works carries the header ({allowed})",
          f"{ORIGIN} is not an allowed origin here, so this check cannot tell "
          f"a missing header from a rejected origin")
    if failures:
        print("\n  " + failures[0])
        return 2

    for path, expect, what in (
        ("/api/__qa_raises", 500, "an unhandled exception"),
        ("/api/__qa_refuses", 400, "a deliberate refusal"),
    ):
        res = client.get(path, headers={"Origin": ORIGIN})
        header = res.headers.get("access-control-allow-origin")
        check(res.status_code == expect and header == ORIGIN,
              f"{what} answers {res.status_code} and keeps the header",
              f"{what} answered {res.status_code} with "
              f"Access-Control-Allow-Origin={header!r}. The browser will "
              f"report this as a CORS failure and nobody will look at the "
              f"server log, which is where the real cause is.")

    body = client.get("/api/__qa_raises", headers={"Origin": ORIGIN}).json()
    check("detail" in body,
          f"and says something a person can read: {str(body.get('detail'))[:60]}…",
          "a 500 with no body tells the operator nothing at all")
    check("where" in body,
          f"and names the request, for finding it in the log: {body.get('where')}",
          "nothing in the response identifies which request failed")

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("an error arrives as an error, not as a cross-origin mystery")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
