"""Per-user action audit log.

A middleware records every state-changing API call (method, path, user, status)
so a pharmacy manager can answer "who did what, when" — required for
controlled-substance compliance and dispute resolution.
"""
import asyncio
import logging

import jwt
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import settings
from .database import SessionLocal
from .models import AuditLog

log = logging.getLogger("rx5000.audit")

#: Audit writes still in flight.
#:
#: Held so the event loop keeps a reference to each one. A task nobody is
#: holding can be collected before it runs, which would lose rows silently and
#: at random — the worst possible failure for a log whose entire job is to be
#: complete.
#:
#: Drained on shutdown by `settle()`, so a deploy or a restart does not drop
#: the calls that were in flight when it began.
_in_flight: set[asyncio.Task] = set()


async def settle(timeout: float = 5.0) -> int:
    """Wait for outstanding audit writes. Called on shutdown."""
    if not _in_flight:
        return 0
    waiting = list(_in_flight)
    done, _ = await asyncio.wait(waiting, timeout=timeout)
    return len(done)

# Never log these (credentials in body, or pure noise)
SKIP_PATHS = {"/api/auth/login"}

# Friendly descriptions keyed by (method, path prefix)
DESCRIPTIONS: list[tuple[str, str, str]] = [
    ("POST", "/api/prescriptions", "Captured or dispensed a prescription"),
    ("POST", "/api/pos/sales", "Processed a sale"),
    ("POST", "/api/stock/adjust", "Adjusted stock"),
    ("POST", "/api/stock/batches", "Wrote off a stock batch"),
    ("POST", "/api/orders", "Created or updated a purchase order"),
    ("POST", "/api/messages", "Sent a patient message"),
    ("POST", "/api/patients", "Created a patient"),
    ("PUT", "/api/patients", "Updated a patient"),
    ("POST", "/api/products", "Created a product"),
    ("PUT", "/api/products", "Updated a product"),
    ("POST", "/api/shifts", "Shift operation"),
    ("POST", "/api/admin/price-import", "Imported a supplier price file"),
    ("POST", "/api/admin/backup", "Created a database backup"),
    ("POST", "/api/auth/users", "Created a user account"),
]


def _describe(method: str, path: str) -> str:
    for m, prefix, text_ in DESCRIPTIONS:
        if method == m and path.startswith(prefix):
            return text_
    return f"{method} {path}"


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        path = request.url.path
        method = request.method
        if method in ("GET", "HEAD", "OPTIONS") or not path.startswith("/api") or path in SKIP_PATHS:
            return response

        username, user_id = "", None
        # Who was REALLY doing it. An impersonated token carries both, and
        # without recording the second the trail says a cashier in Bulawayo
        # voided a sale at two in the morning when it was head office.
        acted_as_id, acted_as = None, ""
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                payload = jwt.decode(auth[7:], settings.SECRET_KEY, algorithms=["HS256"])
                username = payload.get("username", "")
                user_id = int(payload["sub"])
                if payload.get("imp"):
                    acted_as_id = int(payload["imp"])
                    acted_as = str(payload.get("imp_name", ""))[:50]
            except jwt.PyJWTError:
                username = "(invalid token)"

        # Written in a worker thread, not on the event loop. This is a blocking
        # database write inside an async middleware: under load it waited for a
        # pooled connection, or for SQLite's write lock, with the event loop
        # stopped behind it — every other request in the building frozen until
        # it got one. Three counters dispensing at once was enough.
        row = AuditLog(
            user_id=user_id,
            username=username,
            acted_as_id=acted_as_id,
            acted_as=acted_as,
            action=method,
            path=path,
            summary=_describe(method, path),
            status_code=response.status_code,
            ip_address=request.client.host if request.client else "",
        )
        # NOT AWAITED, DELIBERATELY.
        #
        # The response is already built by this point: `call_next` returned
        # above and nothing below can change what the caller gets. Awaiting
        # the write meant every state-changing request also waited for a
        # connection, an INSERT and a COMMIT before the client saw a byte —
        # three database round trips, which against the hosted database is
        # about three hundred milliseconds added to every sale, every
        # dispensing and every stock movement.
        #
        # The row is still written, and still written from a worker thread so
        # it cannot block the event loop. What changed is who waits for it: the
        # server rather than the person at the counter.
        #
        # It is tracked rather than fired and forgotten, because an audit log
        # that loses rows when a deploy lands is not one anybody can rely on.
        # See `_in_flight` and `settle`.
        task = asyncio.create_task(run_in_threadpool(_write, row))
        _in_flight.add(task)
        task.add_done_callback(_in_flight.discard)
        return response


def _write(row: AuditLog) -> None:
    db = SessionLocal()
    try:
        db.add(row)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — auditing must never break a request
        log.warning("Audit write failed: %s", exc)
        db.rollback()
    finally:
        db.close()


def note(db, actor, summary: str, path: str = "") -> None:
    """Record something the middleware cannot see from the outside.

    The middleware knows the route, the session and the status, which for most
    actions is the whole story. It is not the whole story when the interesting
    fact is not in the URL: "POST /api/auth/pin, 200, signed in as the cashier"
    does not say whose code was changed, and on a shared till that is the only
    part anybody will want later.

    Written on the request's own session and transaction rather than a separate
    one, so a note about a change cannot survive that change being rolled back.
    Failure is swallowed, as everywhere else in here: a trail that can refuse a
    dispensing is a trail that gets switched off.
    """
    try:
        db.add(AuditLog(
            user_id=getattr(actor, "id", None),
            username=(getattr(actor, "username", "") or "")[:50],
            action="NOTE",
            path=path or "(recorded by the action itself)",
            summary=summary[:200],
            status_code=200,
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("Audit note failed: %s", exc)
        db.rollback()
