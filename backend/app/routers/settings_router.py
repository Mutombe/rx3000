"""One place the pharmacy configures how the system behaves.

Settings were reachable only by editing rows, which meant the figures a pharmacy
adjusts most — its own name on a receipt, the deposit it takes on a lay-by, the
dates a scheme pays on — were the figures it could not adjust.

Two decisions worth stating:

**Every setting is declared, not free-form.** The store underneath is key/value,
which would happily accept `compnay.name` and silently do nothing. A declared
list means an unknown key is refused, the type is checked, and the screen can be
generated from the declaration rather than hand-built and drifting.

**Every setting says what it affects.** A field called `layby.minimum_deposit_pct`
with no explanation gets set to zero by somebody who wanted fewer arguments at
the counter, and nobody connects it to the stock sitting in the back nine months
later.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_role
from ..database import get_db
from ..models import Setting, User
from .periods_router import require_step_up

router = APIRouter(prefix="/api/settings", tags=["settings"],
                   dependencies=[Depends(get_current_user)])

Kind = Literal["text", "number", "percent", "money", "bool", "day_of_month"]


@dataclass(frozen=True)
class Declared:
    key: str
    label: str
    kind: Kind
    default: str
    group: str
    # What changing it actually does. Not a restatement of the label.
    effect: str
    unit: str = ""


DECLARED: tuple[Declared, ...] = (
    # ---- the pharmacy itself
    Declared("company.trading_name", "Trading name", "text", "", "Pharmacy",
             "Prints on every receipt, label, statement and report header."),
    Declared("company.city", "City", "text", "", "Pharmacy",
             "Appears on documents and on the patient portal."),
    Declared("company.phone", "Telephone", "text", "", "Pharmacy",
             "Printed on labels so a patient with a question can ring the "
             "dispensary rather than guess."),
    Declared("company.registration_no", "Registration number", "text", "", "Pharmacy",
             "The pharmacy's regulatory number, printed where a document has to "
             "carry it."),
    Declared("company.responsible_pharmacist", "Responsible pharmacist", "text", "",
             "Pharmacy",
             "Named on controlled-substance records and regulatory reports."),

    # ---- counter behaviour
    Declared("layby.minimum_deposit_pct", "Minimum lay-by deposit", "percent", "20",
             "Counter",
             "Below this a lay-by is refused. Set it low and the pharmacy stores "
             "stock for free that it could have sold from the shelf.", "%"),
    Declared("layby.max_weeks", "Lay-by term", "number", "12", "Counter",
             "How long a lay-by may run before it is chased. Goods held longer "
             "than this are stock that earned nothing.", "weeks"),
    Declared("cashup.variance_threshold", "Cash-up variance needing approval", "money",
             "20", "Counter",
             "A drawer out by more than this needs a manager before the shift can "
             "close, rather than being noted and forgotten."),
    Declared("pos.require_customer_over", "Require a customer above", "money", "0",
             "Counter",
             "Sales above this must be attached to a named customer. Zero means "
             "never. This is what stops large sales becoming untraceable."),

    # ---- dispensing
    Declared("dispensing.default_icd10", "Default diagnosis code", "text", "", "Dispensing",
             "Pre-filled on a new script line so a dispenser corrects one field "
             "rather than typing it every time. Left blank if the pharmacy would "
             "rather it were always deliberate."),
    Declared("dispensing.repeat_reminder_days", "Remind before a repeat is due", "number",
             "7", "Dispensing",
             "How far ahead a due repeat appears on the worklist and in reminders.",
             "days"),
    Declared("dispensing.require_pharmacist_initial", "Require a pharmacist initial",
             "bool", "true", "Dispensing",
             "Dispensing cannot be completed without initials. This is the record "
             "that somebody checked it."),

    # ---- claims
    Declared("claims.chase_after_days", "Chase a claim after", "number", "30", "Claims",
             "How long an unsettled claim waits before it appears on the chase "
             "list. Too short annoys the scheme, too long writes the money off.",
             "days"),
    Declared("claims.mou_reminder_days", "Warn before an MOU date", "number", "3",
             "Claims",
             "How many days before a submission or payment date the reminder "
             "appears.", "days"),

    # ---- backups
    Declared("backup.keep", "Backups to keep", "number", "20", "Backups",
             "Older backups are deleted, verified ones kept in preference to "
             "unverified. Below about seven this stops covering a long weekend."),
    Declared("backup.destination", "Where backups go", "text", "local", "Backups",
             "local, cloud, or both. Cloud is unavailable until a destination is "
             "configured, and an offline till always writes locally regardless."),
)

BY_KEY = {d.key: d for d in DECLARED}


def _typed(declared: Declared, raw: str):
    """Return the value in the shape a caller expects, not always a string."""
    if declared.kind == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if declared.kind in ("number", "percent", "money", "day_of_month"):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return float(declared.default or 0)
        return int(value) if value == int(value) else value
    return raw


def get_value(db: Session, key: str):
    """Read one setting, typed, falling back to its declared default."""
    declared = BY_KEY.get(key)
    if not declared:
        raise KeyError(key)
    row = db.query(Setting).filter(Setting.key == key).first()
    return _typed(declared, row.value if row and row.value != "" else declared.default)


@router.get("")
def listing(db: Session = Depends(get_db)):
    """Every setting, grouped, with its current value and what it affects."""
    stored = {s.key: s.value for s in db.query(Setting).all()}
    groups: dict[str, list[dict]] = {}
    for declared in DECLARED:
        raw = stored.get(declared.key, "")
        groups.setdefault(declared.group, []).append({
            "key": declared.key,
            "label": declared.label,
            "kind": declared.kind,
            "unit": declared.unit,
            "effect": declared.effect,
            "value": _typed(declared, raw if raw != "" else declared.default),
            "default": _typed(declared, declared.default),
            # Whether anybody has ever set it. A value that matches the default
            # is not the same as one somebody chose, and on a settings screen the
            # difference is what tells you whether it has been reviewed.
            "is_set": declared.key in stored and stored[declared.key] != "",
        })
    # Anything in the store that is not declared. Surfaced rather than hidden,
    # because a stray key is usually a typo that has been silently doing nothing.
    unknown = sorted(k for k in stored if k not in BY_KEY)
    return {"groups": groups, "unrecognised": unknown}


@router.put("/{key:path}")
def update(key: str, value: str = Body(..., embed=True),
           db: Session = Depends(get_db),
           user: User = Depends(require_role("admin")),
           _grant=Depends(require_step_up("settings.global"))):
    """Change one setting.

    Behind a password because these decide how everything else behaves. One wrong
    figure here is wrong on every transaction afterwards, and silently — nothing
    on a receipt says which VAT rate produced it.
    """
    declared = BY_KEY.get(key)
    if not declared:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{key}' is not a setting this system has. The store underneath "
                "would accept it and quietly do nothing, which is why it is "
                "refused here."
            ),
        )

    text = str(value).strip()
    if declared.kind in ("number", "percent", "money", "day_of_month"):
        try:
            number = float(text)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"{declared.label} is a number. '{text}' is not one.",
            )
        if number < 0:
            raise HTTPException(status_code=422,
                                detail=f"{declared.label} cannot be negative.")
        if declared.kind == "percent" and number > 100:
            raise HTTPException(status_code=422,
                                detail=f"{declared.label} is a percentage and cannot exceed 100.")
        if declared.kind == "day_of_month" and not 1 <= number <= 31:
            raise HTTPException(status_code=422,
                                detail=f"{declared.label} must be a day between 1 and 31.")
    if declared.kind == "bool" and text.lower() not in ("true", "false", "1", "0", "yes", "no"):
        raise HTTPException(status_code=422,
                            detail=f"{declared.label} is a yes or no setting.")

    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = text
        row.updated_at = datetime.utcnow()
    else:
        db.add(Setting(key=key, value=text, updated_at=datetime.utcnow()))
    db.commit()
    return {
        "key": key,
        "value": _typed(declared, text),
        "message": f"{declared.label} saved. {declared.effect}",
    }
