"""Reading a setting, from the code that has to obey it.

Settings were declared in one place and read in another, and several were
declared and read nowhere at all. `cashup.variance_threshold` is on the
settings screen, has a label, a default and a sentence explaining what
changing it does, and no line of code anywhere consults it. A pharmacy can
set it, save it, and watch it do nothing.

That happens because declaring a setting and obeying one were never the same
piece of work: the screen knows the whole list, and the module that should
care knows a module level constant instead. So this is the other half — the
accessor a service calls, with the default in the SAME place the screen's
default comes from, so the two cannot drift.

WHY IT FALLS BACK RATHER THAN RAISING

A pharmacy that has never opened the settings screen has no rows at all, and
a stock sweep that refuses to run until somebody configures it is a sweep
that never runs. Every reader here answers with the declared default, which
is the behaviour the software had before the setting existed.

WHY THE VALUES ARE TEXT

Because that is what the `settings` table holds: one `value` column, a string,
for a screen that writes free text into it. Parsing therefore has to assume
somebody typed "90 days" into a box meant for "90", and answer sensibly rather
than raise five hundred at whoever is standing at the counter.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import Setting

#: Digits, a decimal point and a leading minus. Anything a person adds around
#: the number ("90 days", "R 20.00", "20%") is thrown away rather than fatal.
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def text(db: Session, key: str, default: str = "") -> str:
    """A setting as it was typed, or the default where nobody has set it."""
    row = db.query(Setting).filter(Setting.key == key).first()
    value = (row.value if row else "") or ""
    return value.strip() or default


def number(db: Session, key: str, default: float) -> float:
    """A setting as a number, however it was typed.

    An empty box means "use the default", not "zero". Those are different
    answers and the difference matters: a threshold of zero makes every
    variance need approval, which is how a control gets switched off for being
    unworkable.
    """
    raw = text(db, key, "")
    if not raw:
        return default
    found = _NUMBER.search(raw)
    return float(found.group()) if found else default


def whole(db: Session, key: str, default: int) -> int:
    """The same, as a whole number of days, units or weeks."""
    return int(number(db, key, default))


def flag(db: Session, key: str, default: bool = False) -> bool:
    """A yes or no, in the several shapes a screen might have written one."""
    raw = text(db, key, "").lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "y")
