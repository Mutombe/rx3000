"""One place that bounds how much a single request may ask for.

Fifty-two endpoints take a bare `limit`, and none of them clamped it. That is
not fifty-two oversights, it is a missing guard: a rule that has to be
remembered in every new endpoint will be forgotten in some of them, and the one
that is forgotten is the one a client uses to ask for a hundred thousand rows.
The offline catalogue was doing exactly that — `/api/products?limit=100000` in a
single request.

So the clamp lives in middleware, above the handlers, where it cannot be left
out of a new route. Endpoints keep their own smaller defaults; this only says
what the ceiling is.

Clamped rather than refused, deliberately. A stale bookmark asking for 500 rows
should get 200 rows, not a 400 and an empty screen — and anything that genuinely
needs the whole table asks for it a page at a time, which is what the paged
endpoints are for.
"""
import logging

from starlette.datastructures import QueryParams
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("rx3000.limits")

# Same ceiling as the paged endpoints, so there is one number to reason about.
from .services.paging import MAX_PER_PAGE  # noqa: E402

BOUNDED = ("limit", "per_page", "page_size")


class RequestSizeLimit(BaseHTTPMiddleware):
    """Clamp any size parameter on the way in."""

    async def dispatch(self, request, call_next):
        params = request.query_params
        if any(p in params for p in BOUNDED):
            changed = {}
            for name in BOUNDED:
                raw = params.get(name)
                if raw is None:
                    continue
                try:
                    asked = int(raw)
                except (TypeError, ValueError):
                    continue
                if asked > MAX_PER_PAGE:
                    changed[name] = str(MAX_PER_PAGE)
            if changed:
                merged = [(k, v) for k, v in params.multi_items() if k not in changed]
                merged += list(changed.items())
                # Rewriting the scope's query string is what makes the handler
                # see the clamped value; changing request.query_params alone does
                # nothing, because it is derived from the scope each time.
                request.scope["query_string"] = str(
                    QueryParams(merged)).encode("latin-1")
                log.info(
                    "Clamped %s on %s to %s",
                    ", ".join(changed), request.url.path, MAX_PER_PAGE,
                )
        return await call_next(request)
