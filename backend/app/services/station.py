"""Which till this is, and whether it is licensed to be running.

A product sold to many pharmacies has to answer two questions the incumbent
answers on a panel it never hides: *which machine am I looking at*, and *is this
installation entitled to run*. Both are support questions before they are
commercial ones — "it does not work" is unanswerable without knowing which of
four tills, on what version, against which database.

The licence deliberately **warns rather than locks**. A pharmacy whose licence
lapsed on a Sunday must still be able to dispense on the Monday: refusing to
open a till over a billing matter puts patients between a vendor and its
invoice, which is not a place they belong. It nags, it is visible on every
screen, and it is recorded, but it does not stop medicine.
"""
import os
import platform
import socket
import uuid
from datetime import date, datetime

from ..config import settings, env

VERSION = "1.0.0"
BUILD = env("BUILD", "dev")

# Grace after expiry during which the product complains but behaves normally.
GRACE_DAYS = 30


def station_id() -> str:
    """A stable identifier for this machine.

    Derived from the host rather than stored, so restoring a backup onto a new
    machine does not silently inherit the old one's identity, which is exactly
    how two tills end up claiming to be the same station and a support call goes
    round in circles.
    """
    explicit = env("STATION_ID", "").strip()
    if explicit:
        return explicit
    host = socket.gethostname()
    return f"{host}-{uuid.getnode():x}"[:40]


def _parse(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None


def licence() -> dict:
    """What this installation is entitled to, and for how much longer."""
    expires = _parse(env("LICENCE_EXPIRES", ""))
    key = env("LICENCE_KEY", "").strip()
    licensed_to = env("LICENSED_TO", "").strip() or settings.PHARMACY_NAME
    tills = int(env("LICENCE_TILLS", "0") or 0)

    if not key:
        return {
            "state": "unlicensed",
            "licensed_to": licensed_to,
            "expires_on": None,
            "days_remaining": None,
            "tills_licensed": tills or None,
            "blocking": False,
            "message": "This installation has no licence key. It will run, and it "
                       "will keep saying this.",
        }

    today = date.today()
    if expires is None:
        state, remaining = "perpetual", None
        message = ""
    else:
        remaining = (expires - today).days
        if remaining >= 30:
            state, message = "active", ""
        elif remaining >= 0:
            state = "expiring"
            message = (f"The licence expires on {expires:%d %b %Y}, "
                       f"{remaining} day{'s' if remaining != 1 else ''} left.")
        elif remaining >= -GRACE_DAYS:
            state = "grace"
            message = (f"The licence expired on {expires:%d %b %Y}. The product "
                       f"keeps working for {GRACE_DAYS + remaining} more day"
                       f"{'s' if GRACE_DAYS + remaining != 1 else ''}, then keeps "
                       "working and keeps saying so.")
        else:
            state = "expired"
            message = (f"The licence expired on {expires:%d %b %Y}. Nothing has "
                       "been switched off. A lapsed invoice is not a reason to "
                       "stop a pharmacy dispensing, but this needs settling.")

    return {
        "state": state,
        "licensed_to": licensed_to,
        "key_fingerprint": (key[:4] + "…" + key[-4:]) if len(key) > 8 else "set",
        "expires_on": expires,
        "days_remaining": remaining,
        "tills_licensed": tills or None,
        # Never true. Recorded as a field so the answer is explicit rather than
        # merely absent, and so nobody later assumes the opposite by default.
        "blocking": False,
        "message": message,
    }


def info(db=None) -> dict:
    """The panel the incumbent keeps on screen, and the support call it saves."""
    from ..models import Prescription, Sale

    next_rx = next_sale = None
    period = None
    if db is not None:
        from . import periods
        next_rx = db.query(Prescription).count() + 1
        next_sale = db.query(Sale).count() + 1
        period = periods.current(db).code

    return {
        "product": "RX5000",
        "version": VERSION,
        "build": BUILD,
        "station_id": station_id(),
        "computer_name": socket.gethostname(),
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "environment": settings.ENVIRONMENT,
        "is_production": settings.is_production,
        "jurisdiction": settings.jurisdiction.code,
        "pharmacy": settings.PHARMACY_NAME,
        "registration_no": settings.PHARMACY_REG_NO,
        "database": settings.DATABASE_URL.split("///")[-1],
        "trading_period": period,
        "next_rx_number": next_rx,
        "next_sale_number": next_sale,
        "server_time": datetime.now(),
        "licence": licence(),
    }
