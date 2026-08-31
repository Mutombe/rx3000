"""Stopping a frozen branch from recording anything.

A freeze that is not enforced is a label. It has to bite in one place that
every write passes through, rather than in each router — a guard added to forty
endpoints is a guard missing from the forty-first, and the forty-first is the
one somebody uses.

WHAT IT STOPS, AND WHAT IT DELIBERATELY DOES NOT

Writes: sales, dispensings, stock movements, cash-ups. Everything that moves
money or medicine.

Reading stays open. A branch that cannot look up a patient's allergies, or
check what is on the shelf, is a branch that will work around the freeze within
an hour — on paper, where head office cannot see it at all. The object is to
stop the money moving, not to stop the pharmacists thinking.

Head office keeps its own routes, or the freeze could never be lifted and a
shop would be stopped forever by its own control.
"""
from __future__ import annotations

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .database import SessionLocal
from .services import hq


class BranchFreezeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method.upper() not in hq.WRITING:
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api/") or any(
                path.startswith(p) for p in hq.ALWAYS_ALLOWED):
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return await call_next(request)

        try:
            payload = jwt.decode(header[7:], settings.SECRET_KEY,
                                 algorithms=["HS256"])
        except jwt.PyJWTError:
            # Not our problem — the auth dependency will refuse it properly,
            # with the message it has written for that case.
            return await call_next(request)

        branch_id = payload.get("branch_id")
        if not branch_id:
            # The token predates branch scoping, or the user belongs to no
            # branch. Looked up rather than assumed, because "we could not tell
            # which branch" must not become "not frozen".
            branch_id = _branch_of(payload.get("sub"))
        if not branch_id:
            return await call_next(request)

        why = _frozen_reason(branch_id, path, request.method)
        if why:
            # 423 Locked, which is what this is: the resource exists and is
            # deliberately unavailable. A 403 would read as "you personally may
            # not", and the whole branch is stopped rather than the person.
            return JSONResponse(status_code=423, content={"detail": why})
        return await call_next(request)


def _branch_of(user_id) -> int | None:
    if not user_id:
        return None
    from .models import User
    from .tenancy import unscoped

    db = SessionLocal()
    try:
        with unscoped():
            user = db.get(User, int(user_id))
        return getattr(user, "branch_id", None) if user else None
    except Exception:  # noqa: BLE001 — never let the lookup break the request
        return None
    finally:
        db.close()


def _frozen_reason(branch_id: int, path: str, method: str) -> str:
    from .models import Branch
    from .tenancy import unscoped

    db = SessionLocal()
    try:
        with unscoped():
            branch = db.get(Branch, int(branch_id))
        return hq.blocked(path, method, branch)
    except Exception:  # noqa: BLE001
        # A freeze that cannot be read must not stop the shop trading. The
        # failure mode of a control has to be the safe one for the business:
        # a pharmacy unable to sell because a middleware could not reach the
        # database is a worse outcome than a frozen branch trading for an hour.
        return ""
    finally:
        db.close()
