"""Pairing a phone to a counter, and carrying its scans across.

Four endpoints and one stream. The desktop asks for a code and watches; the
phone claims the code and sends. See `services/scanner_link` for why the phone
is deliberately a dumb input device and why the queue is a table.

SERVER-SENT EVENTS RATHER THAN A WEBSOCKET

The same call this codebase already made for the assistant, for the same
reasons stated there: this is one way, it is long lived rather than
conversational, and it survives a proxy that would drop an upgrade. The phone
talks to the server with ordinary POSTs; only the desktop needs to be told
things it did not ask for, and that is exactly the shape SSE has.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import SessionLocal, get_db
from ..models import ScannerLink, User
from ..services import branches as branch_svc
from ..services import scanner_link
from ..tenancy import set_current_pharmacy, unscoped

router = APIRouter(prefix="/api/scanner", tags=["scanner"])

#: How often the stream looks for new scans. Under half a second, which is
#: imperceptible beside a person moving a phone to the next box, and cheap: it
#: is one indexed lookup per open counter.
POLL_SECONDS = 0.4

#: How often the stream says something even when nothing has happened. Proxies
#: and phones close a connection that has gone quiet, and a scanner that looks
#: connected and is not is worse than one that plainly dropped.
HEARTBEAT_SECONDS = 20


# ---------- the desktop ----------

@router.post("/pair")
def pair(body: dict = Body(default={}), db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    """Ask for a code to show. Nothing is paired until a phone claims it."""
    branch_id = branch_svc.branch_of(db, user.id)
    link = scanner_link.offer(db, user=user,
                              station=str(body.get("station") or "")[:60],
                              branch_id=branch_id)
    db.commit()
    said = scanner_link.shape(link)
    said["message"] = ("Scan this code with the phone's camera to use it as a "
                       "scanner at this counter.")
    return said


@router.get("/links")
def my_links(db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """What this person currently has paired, so a stale one can be ended."""
    rows = (db.query(ScannerLink)
            .filter(ScannerLink.user_id == user.id,
                    ScannerLink.status == "live")
            .order_by(ScannerLink.id.desc()).limit(10).all())
    return {"links": [scanner_link.shape(r) for r in rows]}


@router.post("/close/{link_id}")
def close(link_id: int, db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    link = db.get(ScannerLink, link_id)
    if link is None or link.user_id != user.id:
        raise HTTPException(404, "That pairing is not one of yours.")
    scanner_link.close(db, link)
    return {"ok": True, "message": "That phone is no longer paired."}


@router.get("/stream/{link_id}")
async def stream(link_id: int, request: Request,
                 user: User = Depends(get_current_user)):
    """What the paired phone has scanned, as it arrives.

    Its own session, opened per connection and closed with it. The request
    scoped session from `get_db` is returned to the pool when the handler
    returns, and this handler returns a generator that outlives it — holding
    that session open for a whole shift would take a connection out of the
    pool for the same length of time.

    Tenancy is set on that session by hand for the same reason: nothing else
    is doing it here, and a stream that is not scoped is a stream that could
    hand one pharmacy's scans to another.
    """
    # Read once, on the caller's own authority, before anything is streamed.
    with SessionLocal() as check:
        set_current_pharmacy(user.pharmacy_id)
        link = check.get(ScannerLink, link_id)
        if link is None or link.user_id != user.id:
            raise HTTPException(404, "That pairing is not one of yours.")
        pharmacy_id = link.pharmacy_id

    async def frames():
        seen = 0
        quiet = 0.0
        said_paired = False
        db = SessionLocal()
        try:
            # The link, belonging to THIS session.
            #
            # It was carried over from the one that authorised the request,
            # which is closed by then, so every use of it here was a detached
            # instance: `expire` refused it outright and killed the generator
            # on the first quiet poll. The stream then looked perfect from
            # outside — connection open, no error, silence — which is exactly
            # what a phone nobody is scanning with looks like.
            set_current_pharmacy(pharmacy_id)
            link = db.get(ScannerLink, link_id)
            if link is None:
                yield "event: closed\ndata: {}\n\n"
                return
            yield ("event: open\ndata: "
                   + json.dumps({"link_id": link_id}) + "\n\n")
            while True:
                if await request.is_disconnected():
                    break
                # SET EVERY TIME ROUND, NOT ONCE BEFORE THE LOOP.
                #
                # The pharmacy in force is a context variable, and an async
                # generator is not guaranteed to be resumed in the context it
                # was suspended in: the server may hand each step a fresh copy
                # taken from before the assignment. Setting it once worked
                # until the first yield and then silently stopped, so every
                # query after it was narrowed to rows with no pharmacy — of
                # which there are none. The stream stayed open, said nothing,
                # and looked exactly like a phone nobody was scanning with.
                set_current_pharmacy(pharmacy_id)
                rows = scanner_link.waiting(db, link, after_id=seen)
                if rows:
                    quiet = 0.0
                    for row in rows:
                        seen = row.id
                        row.delivered_at = datetime.utcnow()
                        yield ("event: scan\ndata: "
                               + json.dumps({"id": row.id, "code": row.code})
                               + "\n\n")
                    db.commit()
                else:
                    quiet += POLL_SECONDS
                    if quiet >= HEARTBEAT_SECONDS:
                        quiet = 0.0
                        # A comment frame: it keeps the connection and the
                        # proxies in front of it awake without the client
                        # having to know about a message type that means
                        # nothing.
                        yield ": still here\n\n"
                    # The pairing can be ended from the other side, or time
                    # out. The stream has to notice, or the screen goes on
                    # saying "scanner connected" over a phone that is not.
                    db.expire(link)
                    # A PHONE HAS ACTUALLY TAKEN IT.
                    #
                    # Said once, when the pairing flips from pending to live.
                    # The `open` frame above means only that this stream is
                    # open, which is true while the code is still sitting
                    # unclaimed on the screen — treating the two as one thing
                    # made the counter announce "phone scanning" the instant
                    # it displayed a code nobody had picked up.
                    if link.status == "live" and not said_paired:
                        said_paired = True
                        quiet = 0.0
                        yield ("event: paired\ndata: "
                               + json.dumps({"station": link.station or "",
                                             "device": link.device or ""})
                               + "\n\n")
                    # Pending is a pairing still waiting to be claimed, which
                    # is not a reason to hang up on the counter showing it.
                    if link.status not in ("pending", "live"):
                        yield "event: closed\ndata: {}\n\n"
                        break
                await asyncio.sleep(POLL_SECONDS)
        finally:
            db.close()

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Nginx and friends buffer a response until it is "big enough",
            # which for a stream means the first scan arrives with the tenth.
            "X-Accel-Buffering": "no",
        },
    )


# ---------- the phone ----------

@router.post("/claim")
def claim(body: dict = Body(...), db: Session = Depends(get_db)):
    """A phone takes a pairing. This is the one endpoint with no account.

    The code is the credential: single use, three minutes, and worth nothing
    after it is claimed. What it buys is a token that can do exactly one
    thing, which is post a string to this one pairing.
    """
    with unscoped():
        link, token = scanner_link.claim(
            db, code=str(body.get("code") or ""),
            device=str(body.get("device") or "")[:80])
        said = scanner_link.shape(link)
    said["token"] = token
    said["message"] = (f"Paired to {link.station or 'the counter'}. "
                       "Scans will appear on that screen.")
    return said


def _paired(db: Session = Depends(get_db),
            x_scanner: str = Header(default="")) -> ScannerLink:
    """The pairing a phone's token names. Its only way in."""
    if not x_scanner:
        raise HTTPException(401, "This scanner is not paired.")
    link = scanner_link.holder(db, x_scanner)
    # Scoped to the pairing's own pharmacy, not to a signed-in user, because
    # there is no signed-in user on this side.
    set_current_pharmacy(link.pharmacy_id)
    return link


@router.post("/scan")
def scan(body: dict = Body(...), db: Session = Depends(get_db),
         link: ScannerLink = Depends(_paired)):
    """A phone sends what it read, and is told only that it arrived.

    Deliberately not resolved here. The phone does not learn the patient, the
    medicine or the script: it is an input device, and the desktop is what
    knows whether this is a dispensing or a delivery and has a pharmacist in
    front of it.
    """
    row = scanner_link.push(db, link, str(body.get("code") or ""))
    return {"ok": True, "id": row.id,
            "station": link.station or "the counter",
            "message": "Sent."}


@router.get("/paired")
def paired(link: ScannerLink = Depends(_paired)):
    """What this phone is attached to, for the screen it is showing."""
    return scanner_link.shape(link)
