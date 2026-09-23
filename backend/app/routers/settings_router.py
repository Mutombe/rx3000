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

from .. import schedule_policy

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


#: Settings this screen knows about but deliberately does not edit, because
#: the choice only makes sense beside something else. `rfqs.auto` is one: it
#: is a three-way choice shown next to the list of lines that WOULD be asked
#: about, which a generic text box cannot do. Listed here so the screen stops
#: calling them unrecognised and telling the pharmacy they are being ignored.
ELSEWHERE: dict[str, str] = {
    "rfqs.auto": "Quotes, under Asking by itself",
    "portal.base_url": "set by whoever configures the public web address",
}


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
    Declared("till.lock_everywhere", "Lock every screen when idle", "bool", "0",
             "Counter",
             "On, any screen left idle asks for a PIN, which suits a pharmacy "
             "where every machine is a shared counter. Off, only the screens "
             "where the keyboard actually changes hands lock, the till, the "
             "dispensary, the cash drawer, and a back-office machine stays "
             "signed in. Off by default: a manager who is asked for a PIN every "
             "five minutes while reading a report turns the lock off entirely, "
             "and then the till it was written for is unlocked all day too."),
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

    # ---- stock
    #
    # Every one of these was a constant in a module before it was a setting,
    # and the client's blueprint asks for each to be configurable. The default
    # in each line below is the constant it replaces, so a pharmacy that never
    # opens this screen behaves exactly as it did.
    Declared("stock.expiry_alert_days", "Warn about stock expiring within",
             "number", "90", "Stock",
             "How far ahead the nightly sweep looks. Shorter and short-dated "
             "stock is found too late to return or discount; longer and the "
             "list is too big to act on.", "days"),
    Declared("stock.variance_threshold", "Stock-take variance needing approval",
             "money", "0", "Stock",
             "A count whose variance is worth more than this needs a second "
             "person before it posts. Zero means every count does, which is "
             "the safest and the slowest."),
    Declared("stock.transfer_threshold", "Transfer needing approval",
             "money", "0", "Stock",
             "A transfer worth more than this is only requested, and somebody "
             "has to agree it before the stock leaves the shelf. Zero means "
             "none do, which is how transfers have always worked here."),
    # THE TWO THAT GUARD THE MONEY GOING OUT.
    #
    # Both were read by code and declared nowhere, so the pharmacy could not
    # set either of them: the only way to change one was for somebody to
    # write to the settings table by hand. A control the owner cannot reach
    # is not a control they have. See services/order_approval.
    Declared("orders.approve_over", "Purchase order needing a second signature",
             "money", "0", "Stock",
             "An order worth more than this cannot be sent until somebody "
             "else signs it off, and the person who raised it cannot be that "
             "somebody. Zero turns it off, which is how ordering worked "
             "before this existed. Set it at the figure you would want to be "
             "told about, not at the figure you order every week."),
    Declared("rfqs.approve_over", "Quotation award needing a second signature",
             "money", "0", "Stock",
             "Choosing which wholesaler wins is where the money is decided, "
             "so an award worth more than this needs a second person, and "
             "the buyer cannot approve their own choice. Kept separate from "
             "the order figure above because they guard different things: "
             "one guards what is spent, this guards where it goes. Zero "
             "turns it off."),
    Declared("stock.adjust_threshold", "Adjustment needing a password",
             "money", "0", "Stock",
             "An adjustment worth more than this asks for a second person's "
             "password. Zero means none do: small shelf corrections stay "
             "instant, and it is the large unexplained ones that cost "
             "somebody a moment."),

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
    Declared("dispensing.require_counselling", "Require a counselling record", "text",
             "never", "Dispensing",
             "never, controlled, or always. When required, a script cannot be "
             "dispensed until the points the patient was told are recorded. "
             f"Controlled means {schedule_policy.range_for(5, 6)} scripts only."),
    Declared("dispensing.after_till", "After sending a sale to the till", "text",
             "stay", "Dispensing",
             "stay, or go. A pharmacy with a cashier leaves the dispenser on the "
             "dispensary, the till is already showing what is waiting, and moving "
             "somebody's screen mid-script is how the next patient is kept waiting. "
             "Where one person does both, 'go' opens the till on that sale the "
             "moment it is raised. Either way the dispensing says where it went and "
             "offers to take you there."),
    Declared("dispensing.require_scan_check", "Require each pack to be scanned",
             "bool", "false", "Dispensing",
             "When on, a script cannot be dispensed until every pack has been "
             "scanned and matched to its line. Leave off on a till with no scanner."),

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
    # because a stray key is usually a typo that has been silently doing
    # nothing. Settings that belong to another screen are excluded: the
    # warning says they are "being ignored", and saying that about a key a
    # nightly job reads every morning is how it gets deleted.
    unknown = sorted(k for k in stored
                     if k not in BY_KEY and k not in ELSEWHERE)
    return {
        "groups": groups,
        "unrecognised": unknown,
        # Read by code, set somewhere better than here, and named so nobody
        # has to wonder whether they are live.
        "set_elsewhere": [
            {"key": k, "where": where, "value": stored.get(k, "")}
            for k, where in sorted(ELSEWHERE.items()) if k in stored
        ],
    }


@router.get("/{key:path}")
def one(key: str, db: Session = Depends(get_db)):
    """One setting, with its stored value or its declared default.

    A single-key read, because a screen that needs one flag should not fetch and
    filter the whole catalogue on every mount. Unknown keys 404 rather than
    answering empty: a typo that silently returns "" is a feature that quietly
    behaves as though it were switched off.
    """
    declared = next((d for d in DECLARED if d.key == key), None)
    if not declared:
        raise HTTPException(status_code=404, detail=f"No setting called '{key}'.")
    row = db.query(Setting).filter(Setting.key == key).first()
    return {
        "key": key,
        "value": row.value if row and row.value != "" else declared.default,
        "is_default": not (row and row.value != ""),
        "kind": declared.kind,
        "label": declared.label,
    }


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
