"""Cancelling a script that should never have been on the worklist.

A script saved and never dispensed stays on the worklist until it goes out.
Nothing could take it off: prescriptions had a cancelled status that the
worklist already ignored, and no way to reach it. So a script captured twice by
mistake, or one the patient no longer wants, or three identical copies left
behind by refused dispensings, sat in the queue for good, looking like three
patients waiting.

Cancelling is for a script with nothing dispensed — no line supplied, no repeat
used. A script that has gone out, even in part, is a dispensing record, and the
lines still to go are taken off with Alter script, where each change is kept.

It takes a pharmacist, a manager or an administrator, and a reason. It is
written to the script's change trail — who, when, and why — so a script that
disappeared from the queue can always be accounted for. An open hold is
released with it: there is nothing left to hold.
"""
from datetime import datetime

from sqlalchemy.orm import Session

#: The capability, not a list of roles: the same list lived here, in holds.py
#: and twice more in the browser, and only one of the four could see a grant
#: made to one named person.
CANCELLERS = "script.manage"


class CancelError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def cancel(db: Session, *, rx, reason: str, user):
    from ..models import ScriptChange
    from . import holds

    label = rx.rx_number or rx.draft_ref or f"#{rx.id}"
    from . import permissions
    if not permissions.can(db, user, CANCELLERS):
        raise CancelError("A pharmacist or a manager cancels a script. Ask one to take it off.", 403)
    if rx.status == "draft":
        raise CancelError(f"{label} is still being captured. Delete the draft instead.")
    if rx.status == "cancelled":
        raise CancelError(f"{label} is already cancelled.")
    why = (reason or "").strip()
    if len(why) < 3:
        raise CancelError("Say why the script is being cancelled.")
    if any(item.dispensings or (item.repeats_used or 0) > 0 for item in rx.items):
        raise CancelError(
            f"{label} has already been dispensed, at least in part, so it cannot be cancelled. "
            "Take off the lines that are not going out with Alter script.")

    now = datetime.utcnow()
    rx.status = "cancelled"
    rx.updated_at = now
    open_hold = holds.open_hold(db, rx.id)
    if open_hold:
        open_hold.cleared_at = now
        open_hold.cleared_by_id = user.id
        open_hold.clear_note = f"Script cancelled: {why}"[:500]
    db.add(ScriptChange(
        prescription_id=rx.id, prescription_item_id=None,
        field="status", old_value="active", new_value="cancelled",
        reason=why[:240], changed_at=now, changed_by_id=user.id,
    ))
    db.flush()
    return rx
