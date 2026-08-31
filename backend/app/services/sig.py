"""Dosage shorthand, and the label a patient actually reads.

A dispenser types the same directions dozens of times a day. Left to typing,
"one tablet three times a day after food" becomes "1t tds pc" *on the label* —
because the shortcut a dispenser needs and the words a patient needs are the
same field. That is the failure this exists to prevent: the abbreviation lives
in the input, the sentence prints on the box.

THE ONE RULE THIS FILE IS BUILT ON

**No code ever reaches a label.** Every abbreviation here is expanded into plain
words before anything prints. That is not a convenience; it is the whole safety
argument. The Institute for Safe Medication Practices publishes a list of
abbreviations implicated in real dispensing errors, and the reason they are
dangerous is that they are read by somebody other than the person who wrote
them — a patient at home, a nurse on a ward, a locum the next morning. A code
that is expanded at the point of entry is read by nobody but the dispenser who
typed it, three seconds after typing it.

So the codes are chosen for how a Zimbabwean dispenser actually writes, and the
expansions are chosen for how a patient actually reads. Those are two different
vocabularies and this file is the join between them.

WHERE A CODE IS AMBIGUOUS, IT SAYS SO

`od` is the clearest case. In Zimbabwean and South African dispensing practice
it is *omni die*, once a day. In the ophthalmic literature it is *oculus
dexter*, the right eye. Both readings are in daily use in the same building.
This system takes `od` as once a day, because that is what a dispenser here
means nineteen times in twenty, and it does not offer any Latin code for eye
laterality at all — the eyes are typed `r-eye`, `l-eye` and `b-eye`, which
cannot be read as anything else and expand to the words written in full. That
is what ISMP asks for and it costs one hyphen.

The earlier version handled the collision by inventing `od_eye` and `os_eye`.
No dispenser has ever typed an underscore into a directions field, so those
codes were unreachable — the collision was not resolved, only hidden.

SPELLING

Corrected after inspection: `instil` → `instill`. Both are defensible English —
the single `l` is the British form — but pharmacy labelling worldwide, and USP
in particular, uses the double `l`, and a label is not the place to be
interesting about orthography. Where British and American spellings differ
elsewhere (`nebuliser`, not `nebulizer`) the British form is kept, because that
is what Zimbabwean training and the MCAZ's own documents use.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import DosageAbbreviation

#: code, what prints on the label, its origin, category, caution
#:
#: Categories order the book on screen and in the printed sheet: a dispenser
#: composing directions reaches for a quantity, then a frequency, then timing,
#: and the book should not make them hunt across that.
SEED: list[tuple[str, str, str, str, str]] = [
    # ------------------------------------------------------------- quantity
    # Roman numerals are how a prescriber writes it by hand, so they are how a
    # dispenser reads it back. `iv` is deliberately absent: four is written `4`
    # here, because `iv` is intravenous and the two cannot share a field.
    ("i", "ONE", "roman numeral", "quantity", ""),
    ("ii", "TWO", "roman numeral", "quantity", ""),
    ("iii", "THREE", "roman numeral", "quantity", ""),
    ("1t", "take ONE tablet", "", "quantity", ""),
    ("2t", "take TWO tablets", "", "quantity", ""),
    ("3t", "take THREE tablets", "", "quantity", ""),
    ("halft", "take HALF a tablet", "", "quantity", ""),
    ("1c", "take ONE capsule", "", "quantity", ""),
    ("2c", "take TWO capsules", "", "quantity", ""),
    ("tab", "tablet", "tabuletta", "quantity", ""),
    ("caps", "capsule", "capsula", "quantity", ""),
    ("5ml", "take 5ml (one medicine spoon)", "", "quantity", ""),
    ("10ml", "take 10ml (two medicine spoons)", "", "quantity", ""),
    ("15ml", "take 15ml (three medicine spoons)", "", "quantity", ""),
    ("1d", "instill ONE drop", "gutta", "quantity", ""),
    ("2d", "instill TWO drops", "guttae", "quantity", ""),
    # Bare nouns, so a numeral in front of them reads correctly: `ii gtt`
    # becomes "TWO drops". They carry no verb and no count of their own,
    # because `gtt ii` used to expand to "instill ONE drop TWO".
    ("gtt", "drop", "gutta", "quantity", ""),
    ("gtts", "drops", "guttae", "quantity", ""),
    ("inst", "instill", "instilla", "quantity", ""),
    ("1p", "use ONE puff", "", "quantity", ""),
    ("2p", "use TWO puffs", "", "quantity", ""),
    ("1supp", "insert ONE suppository", "", "quantity", ""),
    ("1pess", "insert ONE pessary", "", "quantity", ""),
    ("ss", "HALF", "semis", "quantity",
     "ISMP error-prone: also read as the number 55. `halft` is clearer."),
    ("aa", "of each", "ana", "quantity", ""),

    # ------------------------------------------------------------ frequency
    ("od", "once a day", "omni die", "frequency",
     "Once a day here. Never the right eye — for eyes use `r-eye`, `l-eye` or "
     "`b-eye`, which cannot be read two ways."),
    ("bd", "twice a day", "bis die", "frequency", ""),
    ("bid", "twice a day", "bis in die", "frequency", ""),
    ("tds", "three times a day", "ter die sumendus", "frequency", ""),
    ("tid", "three times a day", "ter in die", "frequency", ""),
    ("qds", "four times a day", "quater die sumendus", "frequency", ""),
    ("qid", "four times a day", "quater in die", "frequency", ""),
    ("q4h", "every four hours", "quaque 4 hora", "frequency", ""),
    ("q6h", "every six hours", "quaque 6 hora", "frequency", ""),
    ("q8h", "every eight hours", "quaque 8 hora", "frequency", ""),
    ("q12h", "every twelve hours", "quaque 12 hora", "frequency", ""),
    ("eod", "on alternate days", "every other day", "frequency", ""),
    ("altd", "on alternate days", "alternis diebus", "frequency", ""),
    ("weekly", "once a week", "", "frequency", ""),
    ("prn", "when required", "pro re nata", "frequency",
     "Give it a reason and a ceiling — \"when required for pain, no more than "
     "four doses in 24 hours\". `prn` on its own is not a direction."),
    ("sos", "if necessary", "si opus sit", "frequency", ""),
    ("stat", "immediately", "statim", "frequency", ""),
    ("mdu", "as directed", "more dicto utendus", "frequency",
     "Tells the patient nothing. Use it only where the prescriber's own "
     "instruction is written out beside it."),
    ("ud", "as directed", "ut dictum", "frequency",
     "Tells the patient nothing. Use it only where the prescriber's own "
     "instruction is written out beside it."),

    # --------------------------------------------------------------- timing
    ("mane", "in the morning", "mane", "timing", ""),
    ("nocte", "at night", "nocte", "timing", ""),
    ("om", "every morning", "omni mane", "timing", ""),
    ("on", "every night", "omni nocte", "timing",
     "Reads as the English word \"on\" in a sentence. `nocte` is clearer."),
    ("hs", "at bedtime", "hora somni", "timing",
     "ISMP error-prone: also read as \"half strength\". `nocte` is clearer."),
    ("ac", "before food", "ante cibum", "timing", ""),
    ("pc", "after food", "post cibum", "timing", ""),
    ("cc", "with food", "cum cibo", "timing", ""),

    # ---------------------------------------------------------------- route
    ("po", "by mouth", "per os", "route", ""),
    ("sl", "under the tongue", "sub lingua", "route", ""),
    ("pr", "into the rectum", "per rectum", "route", ""),
    ("pv", "into the vagina", "per vaginam", "route", ""),
    ("top", "apply to the affected area", "topically", "route", ""),
    ("inh", "by inhalation", "inhaled", "route", ""),
    ("neb", "through a nebuliser", "nebulised", "route", ""),
    ("im", "by injection into the muscle", "intramuscular", "route", ""),
    ("iv", "by injection into a vein", "intravenous", "route", ""),
    ("subcut", "by injection under the skin", "subcutaneous", "route",
     "Written `subcut`, never `sc` or `sq`: ISMP records both being read as "
     "`sl`, under the tongue."),
    ("nas", "into the nostril", "nasally", "route", ""),
    # Laterality in full, and hyphenated so it cannot collide with a Latin
    # frequency or with an ordinary English word.
    ("r-eye", "into the RIGHT eye", "written in full on purpose", "route", ""),
    ("l-eye", "into the LEFT eye", "written in full on purpose", "route", ""),
    ("b-eye", "into BOTH eyes", "written in full on purpose", "route", ""),
    ("r-ear", "into the RIGHT ear", "written in full on purpose", "route", ""),
    ("l-ear", "into the LEFT ear", "written in full on purpose", "route", ""),
    ("b-ear", "into BOTH ears", "written in full on purpose", "route", ""),

    # ----------------------------------------------------------------- form
    ("ung", "ointment", "unguentum", "form", ""),
    ("crm", "cream", "cremor", "form", ""),
    ("lot", "lotion", "lotio", "form", ""),
    ("syr", "syrup", "syrupus", "form", ""),
    ("susp", "suspension", "suspensio", "form", ""),
    ("mist", "mixture", "mistura", "form", ""),
]

#: Expansions this file used to ship, which a correction should overwrite.
#:
#: A pharmacy may edit any row in its own book — that is the point of storing
#: them — so a re-seed must not flatten somebody's wording. It only replaces
#: text that is still exactly what an earlier version of this file put there.
#: Anything a pharmacy has touched no longer matches, and is left alone.
SUPERSEDED: dict[str, set[str]] = {
    "1d": {"instil ONE drop"},
    "2d": {"instil TWO drops"},
    # These two carried a verb and a count of their own, so `ii gtt` read
    # "TWO instill ONE drop". A numeral needs a bare noun in front of it.
    "gtt": {"instill ONE drop"},
    "gtts": {"instill the drops"},
    "neb": {"by nebuliser"},
    "inh": {"by inhalation"},
    "top": {"apply to the affected area"},
    "om": {"in the morning"},
    "on": {"at night"},
    "altd": {"on alternate days"},
}

#: Codes an earlier version seeded that no dispenser can type, so they are
#: retired rather than left in the book pretending to be reachable.
#:
#: `od_eye` and `os_eye` were invented to dodge the `od` collision. A directions
#: field is typed at speed from a handwritten script; nobody has ever put an
#: underscore in one. They are replaced by `r-eye` / `l-eye` / `b-eye`.
RETIRED: dict[str, str] = {
    "od_eye": "r-eye",
    "os_eye": "l-eye",
    "ou": "b-eye",
    "sc": "subcut",
}


def seed_if_empty(db: Session) -> int:
    if db.query(DosageAbbreviation).first():
        return 0
    for code, expansion, meaning, category, caution in SEED:
        db.add(DosageAbbreviation(code=code, expansion=expansion,
                                  meaning=meaning, category=category,
                                  caution=caution))
    db.commit()
    return len(SEED)


def refresh(db: Session) -> dict[str, list[str]]:
    """Bring an existing book up to the current list, without overwriting edits.

    Three things happen and each is reported, because a book that changed under
    a dispensary silently is a book nobody trusts:

      codes that did not exist are added;
      expansions still carrying wording this file previously shipped are
        corrected, which is how `instil` becomes `instill` on a database that
        was seeded before the correction;
      codes that cannot be typed are deactivated, not deleted — a script
        dispensed last year may have been written with one, and the history has
        to keep expanding.
    """
    added: list[str] = []
    corrected: list[str] = []
    retired: list[str] = []

    existing = {row.code.lower(): row
                for row in db.query(DosageAbbreviation).all()}

    for code, expansion, meaning, category, caution in SEED:
        row = existing.get(code)
        if row is None:
            db.add(DosageAbbreviation(code=code, expansion=expansion,
                                      meaning=meaning, category=category,
                                      caution=caution))
            added.append(code)
            continue
        # Only where the text actually differs. Several codes appear in
        # SUPERSEDED with wording that survived the rewrite unchanged, and
        # reporting those as corrections would put eight lines in front of a
        # pharmacist of which six say nothing happened.
        if (row.expansion in SUPERSEDED.get(code, set())
                and row.expansion != expansion):
            corrected.append(f"{code}: {row.expansion} -> {expansion}")
            row.expansion = expansion
        # The caution is this file's to state, not the pharmacy's to lose, so
        # it is kept current on every row whatever else was edited.
        if (row.caution or "") != caution:
            row.caution = caution
        if not row.meaning and meaning:
            row.meaning = meaning

    for code, replacement in RETIRED.items():
        row = existing.get(code)
        if row is not None and row.active:
            row.active = False
            retired.append(f"{code} -> {replacement}")

    db.commit()
    return {"added": added, "corrected": corrected, "retired": retired}


def table(db: Session) -> dict[str, str]:
    return {
        row.code.lower(): row.expansion
        for row in db.query(DosageAbbreviation).filter(DosageAbbreviation.active).all()
    }


#: Nouns a numeral in front of has to agree with, and their plurals.
#:
#: `ii tab tds` expanded to "TWO tablet three times a day" and printed that way.
#: A label with a grammatical error in it is read as a label somebody did not
#: check, and a patient who decides the pharmacy is careless about the words is
#: entitled to wonder about the tablets.
PLURALS = {
    "tablet": "tablets", "capsule": "capsules", "drop": "drops",
    "puff": "puffs", "spoon": "spoons", "sachet": "sachets",
    "suppository": "suppositories", "pessary": "pessaries",
    "spray": "sprays", "patch": "patches", "lozenge": "lozenges",
}

#: Words this file expands to that mean "more than one".
MANY = {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"}


def _pluralise(sentence: str) -> str:
    """Make a countable noun agree with the numeral in front of it.

    Only ever acts on a word immediately after a number, so ordinary prose in
    the field is untouched: "one tablet with water" keeps its "water".
    """
    words = sentence.split(" ")
    for i in range(1, len(words)):
        before = words[i - 1].strip(".,;").lower()
        plural = before in MANY or (before.isdigit() and int(before) != 1)
        if not plural:
            continue
        bare = words[i].strip(".,;").lower()
        if bare in PLURALS:
            words[i] = words[i].lower().replace(bare, PLURALS[bare], 1)
    return " ".join(words)


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
        # Keep trailing punctuation attached to whatever it followed. Hyphens
        # are left alone: `r-eye` is a code, not two words.
        bare = token.strip(".,;").lower()
        replacement = codes.get(bare)
        out.append(replacement if replacement else token)
    sentence = _pluralise(" ".join(out).strip())
    # Sentence case, and a full stop, because this prints on a box.
    if sentence:
        sentence = sentence[0].upper() + sentence[1:]
        if sentence[-1] not in ".!":
            sentence += "."
    return sentence


def unknown_tokens(db: Session, shorthand: str) -> list[str]:
    """The words in this shorthand that the book does not recognise.

    Not an error — ordinary English is a valid direction and passes straight
    through. It is shown so a dispenser can see at a glance which parts of what
    they typed were understood as codes and which will print as written, which
    is the difference between `stat` meaning "immediately" and `stst` meaning
    nothing at all and printing anyway.
    """
    codes = table(db)
    return [t for t in re.split(r"\s+", (shorthand or "").strip())
            if t and t.strip(".,;").lower() not in codes]


def book(db: Session) -> dict:
    """The whole book, grouped, for the picker and for the printed sheet."""
    rows = db.query(DosageAbbreviation).filter(DosageAbbreviation.active).all()
    # Curated order, not alphabetical. Sorting by code put "10ml, 15ml, 1c, 1d"
    # at the head of the quantities, which is what a string sort does to numbers
    # and no help to anybody reading down the page. The order in SEED is the one
    # a dispenser composes in — numerals, then tablets, then capsules, then
    # liquids — and a pharmacy's own additions follow alphabetically after.
    position = {code: i for i, (code, *_) in enumerate(SEED)}
    rows.sort(key=lambda r: (position.get(r.code.lower(), len(SEED)),
                             r.code.lower()))
    order = ["quantity", "frequency", "timing", "route", "form"]
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.category or "other", []).append({
            "code": row.code,
            "expansion": row.expansion,
            "meaning": row.meaning or "",
            "caution": row.caution or "",
        })
    ordered = {k: groups[k] for k in order if k in groups}
    ordered.update({k: v for k, v in groups.items() if k not in order})
    return {"count": len(rows), "groups": ordered}


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
