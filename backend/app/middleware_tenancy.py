"""Put the request's pharmacy in force before anything reads.

The scoping in `tenancy` needs to know which pharmacy is asking. Setting that
inside a dependency is too late and too narrow: dependencies for a synchronous
endpoint run in a worker thread, and a context variable set in one thread is not
reliably visible in the next. A middleware wraps the whole request in one
context, so the tenant is established before the first query and released after
the last one, whichever threads the work touches.

It reads the tenant from the token rather than the database, because looking it
up would itself be a scoped query with no scope yet in force.
"""
from __future__ import annotations

import jwt
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from . import tenancy


class TenancyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        pharmacy_id = None
        header = request.headers.get("authorization") or ""
        if header.lower().startswith("bearer "):
            try:
                payload = jwt.decode(header[7:], settings.SECRET_KEY,
                                     algorithms=["HS256"])
                raw = payload.get("pharmacy_id")
                pharmacy_id = int(raw) if raw is not None else None
            except Exception:
                # A bad or expired token is not this middleware's problem — the
                # authentication dependency will refuse it with a proper 401.
                # What matters here is that it does not become an *unscoped*
                # request on the way past.
                pharmacy_id = None

        token = tenancy.set_current_pharmacy(pharmacy_id)
        try:
            return await call_next(request)
        finally:
            tenancy.reset_current_pharmacy(token)
