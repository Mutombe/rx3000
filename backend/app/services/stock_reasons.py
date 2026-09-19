"""Why a stock figure was changed, from a list rather than in a sentence.

The dialog that corrects a shelf has asked for a reason from five choices
since it was written. It then joined the answer onto the front of a free text
note, so the information was collected and immediately made unqueryable.
"How much did we write off to damage last quarter" could only be answered by
matching words, which finds "damaged", misses "broken", and counts "not
damaged" as damage.

The list lives here rather than in the screen because the server has to be
able to refuse one it does not know. A code the client invents would sail
through, and the column would be back to free text with fewer characters.

WHY WRITING OFF IS MARKED ON THE REASON

Damaged and expired are goods LEAVING the building; a miscount and an
unbooked delivery are the record being corrected. Those are different acts
with different money behind them and a different capability, and the
difference is a property of the reason rather than something each caller
should work out. `writes_off` says which, and the endpoint reads it instead
of matching on the word.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reason:
    code: str
    label: str
    #: Goods left the building, as against the count having been wrong.
    writes_off: bool = False
    #: What it means, for a screen that wants to explain the choice.
    means: str = ""


REASONS: tuple[Reason, ...] = (
    Reason("count", "Counted the shelf", False,
           "The shelf was counted and the system was wrong. Nothing moved."),
    Reason("damaged", "Damaged or broken", True,
           "Goods were destroyed or spoiled and have left the shelf."),
    Reason("expired", "Expired, taken off the shelf", True,
           "Goods reached their expiry date and may not be dispensed."),
    Reason("recalled", "Recalled by the supplier", True,
           "Goods were withdrawn by the manufacturer or the regulator."),
    Reason("theft", "Missing or stolen", True,
           "Stock that cannot be found and is not explained by a miscount."),
    Reason("received", "Delivery not booked in", False,
           "Goods arrived and the paperwork did not follow them."),
    Reason("returned", "Returned by a patient", False,
           "Goods came back over the counter and went onto the shelf."),
)

BY_CODE = {r.code: r for r in REASONS}


def get(code: str) -> Reason | None:
    """The reason, or None where the code is empty or unknown."""
    return BY_CODE.get((code or "").strip().lower())


def label(code: str) -> str:
    """What to show on a screen or a report for a stored code.

    Falls back to the code itself rather than to a blank: a row written before
    this list existed, or by an importer, should still say something.
    """
    found = get(code)
    return found.label if found else (code or "")


def catalogue() -> list[dict]:
    """The list, for a screen that builds its own chips from it."""
    return [{"code": r.code, "label": r.label,
             "writes_off": r.writes_off, "means": r.means} for r in REASONS]
