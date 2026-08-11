"""Signed links for people who do not have accounts.

A patient will not create an account to find out whether their repeat is ready.
Asking them to is how a portal ends up unused. So the link *is* the credential:
signed, scoped to one person, and expiring.

Three properties make that safe enough for what it carries:

* **Signed, not guessable.** The token is an HMAC over its own contents using
  the application secret. Nothing is looked up by a number a stranger could
  increment.

* **Scoped.** A token names exactly one subject — this patient, this doctor —
  and one purpose. A patient link cannot be pointed at another patient by
  editing it, because the subject is inside the signed payload.

* **Expiring.** WhatsApp links get forwarded, screenshotted and left in group
  chats. A permanent link is a permanent leak, so these die and are re-issued on
  request, which costs the pharmacy nothing.

What a signed link deliberately does **not** do is authorise writing. A link
that can submit a prescription is a prescription pad that anyone in the
forwarding chain now holds. Prescribing is gated on a real account with a
prescriber identity behind it — see `portal_router`.
"""
import base64
import hashlib
import hmac
import json
import time

from ..config import settings

# Long enough that a patient can read a WhatsApp message the next morning,
# short enough that a link left in a group chat stops working.
DEFAULT_TTL = 7 * 24 * 3600


class TokenError(ValueError):
    """Raised when a link is malformed, tampered with, or past its date."""


def _b64(raw: bytes) -> str:
    # URL-safe and unpadded: these travel in links, and '=' gets mangled by
    # every second messaging client that tries to be helpful.
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> str:
    return _b64(hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).digest())


def issue(*, kind: str, subject_id: int, ttl: int = DEFAULT_TTL) -> str:
    """Mint a link token for one subject.

    `kind` separates patient links from doctor links so that a patient token can
    never be replayed against a prescriber endpoint, even though both are signed
    by the same key.
    """
    body = {"k": kind, "s": subject_id, "e": int(time.time()) + ttl}
    payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    return f"{_b64(payload)}.{_sign(payload)}"


def read(token: str, *, expect: str) -> int:
    """Verify a token and return the subject id it names.

    The signature is checked *before* the contents are trusted, and compared
    with a constant-time comparison so the check cannot be timed open.
    """
    try:
        encoded, signature = token.split(".", 1)
        payload = _unb64(encoded)
    except (ValueError, TypeError):
        raise TokenError("This link is not valid. Ask the pharmacy for a new one.")

    if not hmac.compare_digest(_sign(payload), signature):
        raise TokenError("This link is not valid. Ask the pharmacy for a new one.")

    body = json.loads(payload)
    if body.get("k") != expect:
        # A real mismatch is either a bug or someone trying a patient link
        # against a prescriber route. Neither deserves a detailed explanation.
        raise TokenError("This link is not valid. Ask the pharmacy for a new one.")
    if body.get("e", 0) < time.time():
        raise TokenError("This link has expired. Ask the pharmacy to send a new one.")
    return int(body["s"])
