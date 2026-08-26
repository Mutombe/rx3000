"""Consent as a record of what happened, not a checkbox.

`marketing_opt_in = True` answers "may we message them" and nothing else. It
cannot answer when they agreed, what they were told, through which channel, who
recorded it, or whether they have since said stop. Those are the questions asked
when somebody complains, which is the only occasion the answer matters.

So the boolean stays — it is the fast read every campaign query does — and this
is the record behind it. Three rules:

* **A withdrawal never deletes the grant.** Somebody agreeing and later changing
  their mind is two facts. Erasing the first leaves a pharmacy unable to say why
  it ever sent anything, which is exactly what it is being asked.
* **Consent is per channel.** Agreeing to a repeat reminder by SMS is not
  agreeing to marketing on WhatsApp, and a system that cannot tell them apart
  ends up treating one as the other — always in the direction of sending more.
* **"Imported" is not consent.** Where a flag arrived from a spreadsheet or a
  previous system, it is recorded as imported and says so. Dressing an unknown
  provenance up as a grant is the failure this module exists to prevent.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Contact, ConsentEvent, Lead, Patient

SUBJECTS = {"patient": Patient, "lead": Lead, "contact": Contact}

#: Channels consent is held per. `all` is a blanket answer and is used when
#: somebody says "stop everything", which people do say.
CHANNELS = ("all", "sms", "whatsapp", "email", "phone", "post")

#: How it was taken. Ordered by how much evidence each actually constitutes.
CAPTURE = {
    "form": "Signed form",
    "portal": "Given through the patient portal",
    "counter": "Given verbally at the counter",
    "phone": "Given verbally on the telephone",
    "reply": "Replied to a message",
    "imported": "Imported from a previous system, provenance unknown",
}

#: The default wording, kept with the grant so that consent is to something
#: specific rather than to a checkbox nobody can reconstruct.
DEFAULT_WORDING = (
    "May we send you reminders about your repeat prescriptions and occasional "
    "notices about services at this pharmacy? You can stop them at any time by "
    "telling us or replying STOP."
)


class ConsentError(ValueError):
    """Raised when consent cannot be recorded as asked."""


def _subject(db: Session, subject_type: str, subject_id: int):
    model = SUBJECTS.get(subject_type)
    if not model:
        raise ConsentError(f"'{subject_type}' is not something consent is held for.")
    row = db.get(model, subject_id)
    if not row:
        raise ConsentError("That record is not on file.")
    return row


def record(db: Session, *, subject_type: str, subject_id: int, state: str,
           channel: str = "all", captured_via: str = "counter",
           wording: str = "", note: str = "", user_id: int | None = None) -> ConsentEvent:
    """Write a grant or a withdrawal, and update the flag it stands behind."""
    if state not in ("granted", "withdrawn"):
        raise ConsentError("Consent is either granted or withdrawn.")
    if channel not in CHANNELS:
        raise ConsentError(f"'{channel}' is not a channel this pharmacy sends on.")
    if captured_via not in CAPTURE:
        raise ConsentError(f"'{captured_via}' is not a way consent is taken.")

    row = _subject(db, subject_type, subject_id)
    event = ConsentEvent(
        subject_type=subject_type, subject_id=subject_id,
        channel=channel, state=state, captured_via=captured_via,
        wording=(wording or (DEFAULT_WORDING if state == "granted" else "")).strip(),
        note=note.strip(), user_id=user_id,
    )
    db.add(event)

    # The flag follows the blanket answer and any single-channel change, because
    # every campaign query in the product reads the flag and none of them reads
    # this table. A record nothing consults protects nobody.
    if hasattr(row, "marketing_opt_in"):
        row.marketing_opt_in = (state == "granted")
    db.commit()
    db.refresh(event)
    return event


def state_for(db: Session, subject_type: str, subject_id: int) -> dict:
    """What is currently permitted, per channel, and the evidence for it.

    Derived from the newest event per channel rather than stored, so the answer
    and its audit trail cannot disagree. A blanket `all` event sets every channel
    that has no more specific answer of its own after it.
    """
    events = (db.query(ConsentEvent)
                .filter(ConsentEvent.subject_type == subject_type,
                        ConsentEvent.subject_id == subject_id)
                .order_by(ConsentEvent.created_at.asc())
                .all())

    per_channel: dict[str, ConsentEvent] = {}
    for e in events:
        if e.channel == "all":
            # A blanket answer applies to every channel, and to any channel that
            # has not been answered separately since.
            for c in CHANNELS:
                if c != "all":
                    per_channel[c] = e
        else:
            per_channel[e.channel] = e

    channels = {}
    for c in CHANNELS:
        if c == "all":
            continue
        e = per_channel.get(c)
        channels[c] = {
            "allowed": bool(e and e.state == "granted"),
            "since": e.created_at if e else None,
            "captured_via": e.captured_via if e else "",
            "how": CAPTURE.get(e.captured_via, "") if e else "",
            # Said plainly rather than shown as a tick. An imported flag and a
            # signed form are not the same evidence and should not read the same.
            "evidence": ("no record" if not e else
                         "imported, provenance unknown" if e.captured_via == "imported"
                         else CAPTURE.get(e.captured_via, e.captured_via)),
        }

    row = _subject(db, subject_type, subject_id)
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "flag": bool(getattr(row, "marketing_opt_in", False)),
        "channels": channels,
        "any_allowed": any(c["allowed"] for c in channels.values()),
        "events": [{
            "id": e.id, "state": e.state, "channel": e.channel,
            "captured_via": e.captured_via,
            "how": CAPTURE.get(e.captured_via, e.captured_via),
            "wording": e.wording, "note": e.note,
            "by": e.user.full_name if e.user else "",
            "created_at": e.created_at,
        } for e in reversed(events)],
    }


def may_send(db: Session, subject_type: str, subject_id: int, channel: str) -> bool:
    """The one question a campaign asks. Defaults to no."""
    if channel not in CHANNELS or channel == "all":
        return False
    return state_for(db, subject_type, subject_id)["channels"][channel]["allowed"]


def backfill_from_flags(db: Session) -> int:
    """Give every existing flag an event that says where it came from.

    Run once. Everybody carrying `marketing_opt_in` today got it from a seed, a
    spreadsheet or a checkbox nobody kept the wording for, and the honest record
    of that is an imported event — not a grant. Writing it as a grant would put a
    provenance on it that does not exist, which is the one thing this module is
    written to prevent.
    """
    made = 0
    for subject_type, model in SUBJECTS.items():
        existing = {
            sid for (sid,) in db.query(ConsentEvent.subject_id)
                                .filter(ConsentEvent.subject_type == subject_type).all()
        }
        for row in db.query(model).all():
            if row.id in existing or not hasattr(row, "marketing_opt_in"):
                continue
            db.add(ConsentEvent(
                subject_type=subject_type, subject_id=row.id, channel="all",
                state="granted" if row.marketing_opt_in else "withdrawn",
                captured_via="imported",
                note="Carried over from the opt-in flag when the consent register "
                     "was introduced. No wording or date was kept at the time.",
                created_at=datetime.utcnow(),
            ))
            made += 1
        db.commit()
    return made
