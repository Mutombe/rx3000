"""Lending a phone to a counter, for as long as a shift lasts.

A pharmacy that has not bought a scanner for every station still has a camera
in everybody's pocket. This pairs one of those with one workstation, so a scan
taken in somebody's hand appears on the screen they are standing at.

THE SHAPE OF IT

    desktop asks for a code   ->  draws it as a Code 128
    phone scans that code     ->  claims the pairing, gets a scoped token
    phone scans a pack        ->  posts the string, is told "sent"
    desktop is watching       ->  the string arrives and it resolves it

The phone never learns what it scanned. It sends a string and gets an
acknowledgement, and the desktop — which is signed in, which knows whether it
is dispensing or receiving, and which has a pharmacist in front of it — is
what turns that string into a patient or a pack. A phone left on a counter can
put a code onto one screen somebody is looking at. It cannot read a record.

WHY THE CODE IS A BARCODE AND NOT A QR

This product can already draw a Code 128 and the phone can already read one. A
QR would have meant writing a second encoder for no gain, since the phone is
about to use that same camera for everything else anyway.

WHY THE QUEUE IS A TABLE

Nothing guarantees the phone's POST and the desktop's stream are served by the
same worker, and a scan delivered into the wrong process is one that silently
never arrives. A row is visible to every worker and survives a restart
mid-shift. It costs a poll of a small indexed table and under half a second,
against a person moving a phone to the next box.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import ScannerLink, ScannerScan, User
from . import portal_tokens

#: How long an unclaimed code is worth offering. It is on a screen in a
#: dispensary, not in an email, so this is minutes rather than hours.
PAIRING_SECONDS = 180

#: How long a claimed pairing lasts without being used. A pairing that lives
#: until somebody remembers to end it outlives the shift, the member of staff
#: and the phone.
IDLE_SECONDS = 4 * 60 * 60

#: The token kind, so a scanner token cannot be presented as a patient link or
#: the other way round. `portal_tokens` puts this inside the signature.
TOKEN_KIND = "scanner"

#: Unambiguous to read off a screen and to hear read aloud. No O/0, no I/1.
ALPHABET = "ACDEFGHJKLMNPQRTUVWXY2345679"


def _fresh_code(db: Session) -> str:
    for _ in range(24):
        code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        clash = (db.query(ScannerLink)
                 .filter(ScannerLink.code == code,
                         ScannerLink.status != "closed").first())
        if clash is None:
            return code
    raise HTTPException(503, "Could not allocate a pairing code. Try again.")


def offer(db: Session, *, user: User, station: str = "",
          branch_id: int | None = None) -> ScannerLink:
    """A code for a desktop to show. Nothing is paired until it is claimed."""
    # One live offer per person per station. Somebody who presses the button
    # twice should see the same code, not collect abandoned pairings.
    now = datetime.utcnow()
    existing = (db.query(ScannerLink)
                .filter(ScannerLink.user_id == user.id,
                        ScannerLink.station == (station or "")[:60],
                        ScannerLink.status == "pending",
                        ScannerLink.expires_at > now)
                .order_by(ScannerLink.id.desc()).first())
    if existing is not None:
        return existing

    link = ScannerLink(
        code=_fresh_code(db),
        status="pending",
        user_id=user.id,
        branch_id=branch_id,
        station=(station or "")[:60],
        created_at=now,
        expires_at=now + timedelta(seconds=PAIRING_SECONDS),
    )
    db.add(link)
    db.flush()
    return link


def claim(db: Session, *, code: str, device: str = "") -> tuple[ScannerLink, str]:
    """A phone takes the pairing. Returns the link and the phone's own token.

    Unscoped by the caller, deliberately: the phone is not signed in to
    anything yet, so there is no tenant in force and this is looked up across
    the estate. The code is what proves the claim, it is single use, and it
    dies in three minutes — so the window in which a guess would be worth
    anything is a few minutes against 28^6 possibilities.
    """
    wanted = (code or "").strip().upper()
    if not wanted:
        raise HTTPException(400, "Enter the code shown on the screen.")
    link = (db.query(ScannerLink)
            .filter(ScannerLink.code == wanted).first())
    if link is None:
        raise HTTPException(
            404, "That code is not one this pharmacy is showing. Check the "
                 "screen and try again.")
    if link.status == "closed":
        raise HTTPException(400, "That pairing has been ended.")
    if link.status == "live":
        raise HTTPException(
            409, "That code has already been used by another phone. Ask the "
                 "counter for a new one.")
    if link.expires_at and link.expires_at < datetime.utcnow():
        raise HTTPException(
            410, "That code has expired. Ask the counter for a new one.")

    now = datetime.utcnow()
    link.status = "live"
    link.claimed_at = now
    link.last_seen_at = now
    link.device = (device or "")[:80]
    db.commit()
    token = portal_tokens.issue(kind=TOKEN_KIND, subject_id=link.id,
                                ttl=IDLE_SECONDS)
    return link, token


def holder(db: Session, token: str) -> ScannerLink:
    """The link a phone's token names, if it is still live.

    The token carries the link id inside its own signature, so it cannot be
    edited to point at somebody else's pairing — which is the property the
    whole design rests on.
    """
    try:
        link_id = portal_tokens.read(token, expect=TOKEN_KIND)
    except Exception:
        raise HTTPException(401, "This scanner is no longer paired.")
    # LOOKED UP UNSCOPED, BECAUSE NOBODY IS SIGNED IN ON THIS SIDE.
    #
    # A phone holding a scanner token has no session and no pharmacy in force,
    # and tenancy narrows a query with no pharmacy to rows that have none — of
    # which there are none. So the ordinary lookup found nothing and every
    # scan a paired phone sent came back "no longer paired", for a pairing
    # that was live.
    #
    # Safe because the id is not taken from the request: it is inside the
    # token's own signature, so this cannot be pointed at another pairing.
    # The caller sets the pharmacy from the link it gets back.
    from ..tenancy import unscoped

    with unscoped():
        link = db.get(ScannerLink, link_id)
    if link is None or link.status != "live":
        raise HTTPException(401, "This scanner is no longer paired.")
    if link.last_seen_at and (datetime.utcnow() - link.last_seen_at
                              > timedelta(seconds=IDLE_SECONDS)):
        link.status = "closed"
        link.closed_at = datetime.utcnow()
        db.commit()
        raise HTTPException(401, "This scanner was idle too long and has been "
                                 "unpaired. Scan the code again.")
    return link


def push(db: Session, link: ScannerLink, code: str) -> ScannerScan:
    """A phone sends what it read. It is told nothing about what it was."""
    text = (code or "").strip()
    if not text:
        raise HTTPException(400, "Nothing was scanned.")
    row = ScannerScan(link_id=link.id, code=text[:200],
                      pharmacy_id=link.pharmacy_id)
    db.add(row)
    link.last_seen_at = datetime.utcnow()
    db.commit()
    return row


def waiting(db: Session, link: ScannerLink, after_id: int = 0) -> list[ScannerScan]:
    """Scans this desktop has not been handed yet, oldest first."""
    return (db.query(ScannerScan)
            .filter(ScannerScan.link_id == link.id,
                    ScannerScan.id > after_id)
            .order_by(ScannerScan.id.asc()).limit(20).all())


def close(db: Session, link: ScannerLink) -> ScannerLink:
    """End the pairing. The phone's next scan is refused."""
    link.status = "closed"
    link.closed_at = datetime.utcnow()
    db.commit()
    return link


def shape(link: ScannerLink) -> dict:
    """One pairing, as either end needs to see it."""
    return {
        "id": link.id,
        "code": link.code if link.status == "pending" else "",
        "status": link.status,
        "station": link.station or "",
        "device": link.device or "",
        "expires_at": link.expires_at.isoformat() if link.expires_at else "",
        "claimed_at": link.claimed_at.isoformat() if link.claimed_at else "",
    }
