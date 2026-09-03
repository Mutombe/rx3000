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
from . import branch_scope, tenancy


class TenancyMiddleware(BaseHTTPMiddleware):
    """Establish both scopes for the request: the pharmacy, then the shops.

    Both are read from the same token in the same pass, because the argument
    for doing it here rather than in a dependency applies identically to each:
    a context variable set inside a worker thread is not reliably visible to
    the next one, and by the time a dependency runs the first query may already
    have gone out.
    """

    async def dispatch(self, request, call_next):
        pharmacy_id = None
        branches: frozenset[int] | None = None
        header = request.headers.get("authorization") or ""
        if header.lower().startswith("bearer "):
            try:
                payload = jwt.decode(header[7:], settings.SECRET_KEY,
                                     algorithms=["HS256"])
                raw = payload.get("pharmacy_id")
                pharmacy_id = int(raw) if raw is not None else None
                # Absent (an older token) and null (sees everything) are the
                # same answer here, and both are the safe one: a token issued
                # before this shipped must not narrow its holder to nothing.
                claim = payload.get("branches")
                if claim:
                    branches = frozenset(int(b) for b in claim)
            except Exception:
                # A bad or expired token is not this middleware's problem — the
                # authentication dependency will refuse it with a proper 401.
                # What matters here is that it does not become an *unscoped*
                # request on the way past.
                pharmacy_id = None
                branches = None

        token = tenancy.set_current_pharmacy(pharmacy_id)
        branch_token = branch_scope.set_visible_branches(branches)
        try:
            return await call_next(request)
        finally:
            branch_scope.reset_visible_branches(branch_token)
            tenancy.reset_current_pharmacy(token)
