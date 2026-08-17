"""Dosage shorthand, and the label a patient actually reads.

A dispenser types the same directions dozens of times a day. Left to typing,
"one tablet three times a day after food" becomes "1 t tds pc" *on the label* —
because the shortcut a dispenser needs and the words a patient needs are the
same field. That is the failure this exists to prevent: the abbreviation lives
in the input, the sentence prints on the box.

The codes are the ones in common use, plus room for a pharmacy's own. They are
deliberately stored rather than hard-coded, because every pharmacy has a
shorthand it inherited from whoever trained there, and a fixed list would be
worked around within a week.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import DosageAbbreviation

# Seeded on first run. Latin abbreviations are what South African and
# Zimbabwean pharmacy training uses, so they are what a dispenser will reach
# for; the plain-English equivalents are included because not everyone was
# trained the same decade.
SEED: list[tuple[str, str, str, str]] = [
    # frequency
    ("od", "once a day", "omni die", "frequency"),
    ("bd", "twice a day", "bis die", "frequency"),
    ("tds", "three times a day", "ter die sumendus", "frequency"),
    ("qds", "four times a day", "quater die sumendus", "frequency"),
    ("qid", "four times a day", "quater in die", "frequency"),
    ("mane", "in the morning", "mane", "timing"),
    ("nocte", "at night", "nocte", "timing"),
    ("om", "in the morning", "omni mane", "timing"),
    ("on", "at night", "omni nocte", "timing"),
    ("prn", "when required", "pro re nata", "frequency"),
    ("stat", "immediately", "statim", "frequency"),
    ("q4h", "every four hours", "quaque 4 hora", "frequency"),
    ("q6h", "every six hours", "quaque 6 hora", "frequency"),
    ("q8h", "every eight hours", "quaque 8 hora", "frequency"),
    ("altd", "on alternate days", "alternis diebus", "frequency"),
    ("weekly", "once a week", "", "frequency"),
    # timing relative to food
    ("ac", "before food", "ante cibum", "timing"),
    ("pc", "after food", "post cibum", "timing"),
    ("cc", "with food", "cum cibo", "timing"),
    # route
    ("po", "by mouth", "per os", "route"),
    ("sl", "under the tongue", "sub lingua", "route"),
    ("pr", "into the rectum", "per rectum", "route"),
    ("pv", "into the vagina", "per vaginam", "route"),
    ("top", "apply to the affected area", "topical", "route"),
    ("inh", "by inhalation", "inhalation", "route"),
    ("neb", "by nebuliser", "nebulised", "route"),
    ("im", "by injection into the muscle", "intramuscular", "route"),
    ("iv", "by injection into a vein", "intravenous", "route"),
    ("sc", "by injection under the skin", "subcutaneous", "route"),
    ("od_eye", "into the right eye", "oculus dexter", "route"),
    ("os_eye", "into the left eye", "oculus sinister", "route"),
    ("ou", "into both eyes", "oculus uterque", "route"),
    # quantity
    ("1t", "take ONE tablet", "", "quantity"),
    ("2t", "take TWO tablets", "", "quantity"),
    ("3t", "take THREE tablets", "", "quantity"),
    ("halft", "take HALF a tablet", "", "quantity"),
    ("1c", "take ONE capsule", "", "quantity"),
    ("2c", "take TWO capsules", "", "quantity"),
    ("5ml", "take 5ml (one medicine spoon)", "", "quantity"),
    ("10ml", "take 10ml (two medicine spoons)", "", "quantity"),
    ("1d", "instil ONE drop", "", "quantity"),
    ("2d", "instil TWO drops", "", "quantity"),
    ("1p", "use ONE puff", "", "quantity"),
    ("2p", "use TWO puffs", "", "quantity"),
]


def seed_if_empty(db: Session) -> int:
    if db.query(DosageAbbreviation).first():
        return 0
    for code, expansion, meaning, category in SEED:
        db.add(DosageAbbreviation(code=code, expansion=expansion,
                                  meaning=meaning, category=category))
    db.commit()
    return len(SEED)


def table(db: Session) -> dict[str, str]:
    return {
        row.code.lower(): row.expansion
        for row in db.query(DosageAbbreviation).filter(DosageAbbreviation.active).all()
    }


def expand(db: Session, shorthand: str) -> str:
    """Turn `1t tds pc` into `Take ONE tablet three times a day after food`.

    Unknown tokens are passed through untouched rather than dropped. A dispenser
    typing "1t tds pc with water" must not silently lose "with water" — a label
    missing part of its instruction is worse than one that reads slightly
    awkwardly, because nothing on the box shows the omission.
    """
    text = (shorthand or "").strip()
    if not text:
        return ""
    codes = table(db)
    out: list[str] = []
    for token in re.split(r"\s+", text):
        # Keep trailing punctuation attached to whatever it followed.
        bare = token.strip(".,;").lower()
        replacement = codes.get(bare)
        out.append(replacement if replacement else token)
    sentence = " ".join(out).strip()
    # Sentence case, and a full stop, because this prints on a box.
    if sentence:
        sentence = sentence[0].upper() + sentence[1:]
        if sentence[-1] not in ".!":
            sentence += "."
    return sentence


def label(db: Session, *, patient: str, product: str, instructions: str,
          quantity: int, dispensed_on: str, pharmacy: str,
          pharmacist: str = "", warnings: list[str] | None = None,
          rx_number: str = "", expiry: str = "") -> dict:
    """The fields that go on the sticker, in the order they are read.

    The patient's name first and the directions largest: somebody holding the box
    is looking for what to take and when, not for the pharmacy's telephone
    number. Everything else is provenance, and belongs underneath.
    """
    expanded = expand(db, instructions)
    return {
        "patient": patient,
        "product": product,
        # The line the whole sticker exists for.
        "directions": expanded or instructions,
        "quantity": quantity,
        "rx_number": rx_number,
        "dispensed_on": dispensed_on,
        "expiry": expiry,
        "pharmacy": pharmacy,
        # Named, not a witness signature. Whoever checked it says so.
        "pharmacist": pharmacist,
        "warnings": warnings or [],
        # Printed on every label without being asked for, because it is the one
        # instruction that applies to all of them.
        "keep_out_of_reach": "Keep all medicines out of the reach of children.",
    }
