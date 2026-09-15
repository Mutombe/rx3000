"""What the patient was told when the medicine was handed over.

CareXpress To-Be blueprint §5 (Patient Counselling Capture) and §8: counselling
is captured as a structured record rather than the verbal-only process it
replaces. RX5000 recorded a yes/no for over-the-counter sales and nothing at
all for a prescription.

Structured as the points covered, not a free-text box alone. A box invites
"counselled" typed four hundred times a week, which records that somebody
pressed a key; the points record what was actually said, and are what an
inspector or a complaint asks about. A note is kept beside them for what the
points cannot hold.

When a record is required is §13's open decision, left to the pharmacy as a
setting until CareXpress confirms it: never, for controlled medicines, or
always. Anything unrecognised is treated as never — a misspelt setting must not
stop a pharmacy dispensing.
"""
from sqlalchemy.orm import Session

# Order is the order they are offered in, which is the order they are said.
POINTS: dict[str, str] = {
    "dose": "How and when to take it",
    "duration": "How long to take it for",
    "side_effects": "Side effects to watch for",
    "warnings": "Warnings and what to avoid",
    "missed_dose": "What to do about a missed dose",
    "storage": "How to store it",
}

SETTING = "dispensing.require_counselling"
RULES = ("never", "controlled", "always")


def clean(points: list[str]) -> list[str]:
    """The known points, each once, in the order they are offered."""
    wanted = {p.strip() for p in points or []}
    return [key for key in POINTS if key in wanted]


def rule(db: Session) -> str:
    from ..routers.settings_router import get_value

    value = str(get_value(db, SETTING) or "never").strip().lower()
    return value if value in RULES else "never"


def required(db: Session, *, controlled: bool) -> bool:
    r = rule(db)
    return r == "always" or (r == "controlled" and controlled)
