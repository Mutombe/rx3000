"""Per-user action audit log.

A middleware records every state-changing API call (method, path, user, status)
so a pharmacy manager can answer "who did what, when" — required for
controlled-substance compliance and dispute resolution.
"""
import logging

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import settings
from .database import SessionLocal
from .models import AuditLog

log = logging.getLogger("rx5000.audit")

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
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                payload = jwt.decode(auth[7:], settings.SECRET_KEY, algorithms=["HS256"])
                username = payload.get("username", "")
                user_id = int(payload["sub"])
            except jwt.PyJWTError:
                username = "(invalid token)"

        db = SessionLocal()
        try:
            db.add(AuditLog(
                user_id=user_id,
                username=username,
                action=method,
                path=path,
                summary=_describe(method, path),
                status_code=response.status_code,
                ip_address=request.client.host if request.client else "",
            ))
            db.commit()
        except Exception as exc:  # noqa: BLE001 — auditing must never break a request
            log.warning("Audit write failed: %s", exc)
            db.rollback()
        finally:
            db.close()

        return response
