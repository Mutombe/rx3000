"""The direction codes a Zimbabwean dispenser already has in their fingers.

Read off 57 photographs of the previous system's "Possible Descriptions" picker
— the dialog that opens in Proppharm when you start typing into Directions.
Roughly 280 codes, A to Z and 1 to 8.

WHY THIS FILE EXISTS

A dispenser who has typed `12A` for "take 1-2 tablets" every working day for
fifteen years does not learn `1t`. They type `12A`, get nothing, and decide the
new software is slower than the old one. They are right: it is, for them,
because their hands know a vocabulary the software does not.

The keystrokes are the whole product here. Everything else about a dispensary
screen can be learned in a morning; the shorthand is muscle memory measured in
years. So the old vocabulary is imported wholesale and the new one is kept —
both codes reach the same sentence, and nobody has to be retrained to type.

WHAT IS NOT HERE, AND WHY

Four Proppharm codes mean something DIFFERENT from a code RX5000 already ships.
Importing them would silently change what an installed pharmacy's labels say.
They are listed in `CONFLICTS` below and deliberately not seeded — see the note
there; `1c` in particular is tablet in one system and capsule in the other, and
that is a dispensing error, not a preference.

Twenty-eight more are missing because the photograph cut them off: the dialog is
narrower than the sentence, so `AMOX  **ANTIBIOTIC** TAKE ONE CAPSULE THREE
TIMES A…` is all that was ever on screen. Their codes are known and their
wording is not, and half a sentence on a label is worse than no code at all —
so they are recorded in `TRUNCATED` for somebody to read off the old system, and
are not guessed at.

HOUSE STYLE

Proppharm printed in capitals because it was a DOS-era screen. RX5000 prints
sentence case with the count in capitals — "take TWO tablets three times a day"
— and these follow that, because a label composed of two codes must not shout
half a sentence. The code is what a dispenser's hands know; the casing is not.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import DosageAbbreviation

#: code, what prints, provenance, category, caution
#:
#: `meaning` says "Proppharm" so a dispenser reading the code book can see at a
#: glance which half of it is the vocabulary they already had.
P = "Proppharm"

CODES: list[tuple[str, str, str, str, str]] = [
    # ------------------------------------------------------------ quantity
    # Numerals first, because that is how a direction is composed: how many,
    # then how often, then when.
    ("1", "ONE", P, "quantity", ""),
    ("1.5", "ONE AND A HALF", P, "quantity", ""),
    ("1.5a", "take ONE AND A HALF tablets", P, "quantity", ""),
    ("1.5l", "take ONE AND A HALF medicine measures", P, "quantity", ""),
    ("1a", "take ONE tablet", P, "quantity", ""),
    ("1b", "take ONE capsule", P, "quantity", ""),
    ("1e", "take ONE dissolved in water", P, "quantity", ""),
    ("1f", "insert ONE into the rectum", P, "quantity", ""),
    ("1g", "suck ONE lozenge", P, "quantity", ""),
    ("1h", "insert ONE into the vagina", P, "quantity", ""),
    ("1hm", "ONE AND A HALF medicine measures (7.5ml)", P, "quantity", ""),
    ("1i", "apply", P, "quantity", ""),
    ("1j", "ONE sachet dissolved in water", P, "quantity", ""),
    ("1l", "take ONE medicine measure", P, "quantity", ""),
    ("1m", "ONE measure (5ml)", P, "quantity", ""),
    ("1nk", "take ONE capsule at night", P, "quantity", ""),
    ("1no", "ONE at noon", P, "quantity", ""),
    ("1puff", "take ONE puff", P, "quantity", ""),
    ("1s", "take ONE sachet in water", P, "quantity", ""),
    ("1v", "take ONE dose (one level cap)", P, "quantity", ""),
    ("1w", "chew ONE tablet", P, "quantity", ""),
    ("1x", "take ONE puff", P, "quantity", ""),
    ("10", "take 10ml", P, "quantity", ""),
    ("12", "take 1-2 tablet(s)", P, "quantity", ""),
    ("12a", "take 1-2 tablet(s)", P, "quantity", ""),
    ("12b", "take 1-2 capsules", P, "quantity", ""),
    ("12d", "instill 1-2 drops", P, "quantity", ""),
    ("12e", "take 1 to 2 dissolved in water", P, "quantity", ""),
    ("12j", "1-2 sachets dissolved in water", P, "quantity", ""),
    ("12l", "take 1-2 medicine measures", P, "quantity", ""),
    ("12m", "ONE TO TWO measures", P, "quantity", ""),
    ("12x", "take 1-2 puffs", P, "quantity", ""),
    ("122", "instill 1 to 2 drops", P, "quantity", ""),
    ("2", "TWO", P, "quantity", ""),
    ("2a", "take TWO tablets", P, "quantity", ""),
    ("2b", "take TWO capsules", P, "quantity", ""),
    ("2e", "take TWO dissolved in water", P, "quantity", ""),
    ("2j", "TWO sachets dissolved in water", P, "quantity", ""),
    ("2l", "take TWO medicine measures", P, "quantity", ""),
    ("2m", "TWO measures", P, "quantity", ""),
    ("2puff", "take TWO puffs", P, "quantity", ""),
    ("2x", "take TWO puffs", P, "quantity", ""),
    ("23a", "take 2-3 tablets", P, "quantity", ""),
    ("23b", "take 2-3 capsules", P, "quantity", ""),
    ("23l", "take 2-3 medicine measures", P, "quantity", ""),
    ("23x", "take 2-3 puffs", P, "quantity", ""),
    ("3", "THREE", P, "quantity", ""),
    ("3a", "take THREE tablets", P, "quantity", ""),
    ("3b", "take THREE capsules", P, "quantity", ""),
    ("3l", "take THREE medicine measures", P, "quantity", ""),
    ("3m", "THREE measures (15ml)", P, "quantity", ""),
    ("3x", "take THREE puffs", P, "quantity", ""),
    ("324", "instill 3 to 4 drops", P, "quantity", ""),
    ("4", "FOUR", P, "quantity", ""),
    ("4l", "take FOUR medicine measures", P, "quantity", ""),
    ("4t", "take FOUR tablets", P, "quantity", ""),
    ("5", "take 5ml", P, "quantity", ""),
    ("5t", "take FIVE tablets", P, "quantity", ""),
    ("6", "SIX", P, "quantity", ""),
    ("7.5", "ONE AND A HALF medicine measures (7.5ml)", P, "quantity", ""),
    ("8t", "take EIGHT tablets", P, "quantity", ""),
    # Tablets, by the number, the way the old picker listed them under T.
    ("t1", "take ONE tablet", P, "quantity", ""),
    ("t2", "take TWO tablets", P, "quantity", ""),
    ("t3", "take THREE tablets", P, "quantity", ""),
    ("t4", "take FOUR tablets", P, "quantity", ""),
    ("t5", "take FIVE tablets", P, "quantity", ""),
    ("t6", "take SIX tablets", P, "quantity", ""),
    ("t7", "take SEVEN tablets", P, "quantity", ""),
    ("t8", "take EIGHT tablets", P, "quantity", ""),
    ("t9", "take NINE tablets", P, "quantity", ""),
    ("t10", "take TEN tablets", P, "quantity", ""),
    ("t12", "take TWELVE tablets", P, "quantity", ""),
    ("t1h", "take ONE AND A HALF tablets", P, "quantity", ""),
    ("t1q", "take ONE AND A QUARTER tablets", P, "quantity", ""),
    ("th", "take HALF a tablet", P, "quantity", ""),
    ("ht", "take HALF a tablet", P, "quantity", ""),
    ("tq", "take a QUARTER tablet", P, "quantity", ""),
    ("tk", "take", P, "quantity", ""),
    ("h", "a HALF", P, "quantity", ""),
    ("hl", "take HALF a medicine measure", P, "quantity", ""),
    ("hm", "HALF a medicine measure (2.5ml)", P, "quantity", ""),
    ("mmh", "HALF a medicine measure (2.5ml)", P, "quantity", ""),
    # Capsules.
    ("c1", "take ONE capsule", P, "quantity", ""),
    ("c2", "take TWO capsules", P, "quantity", ""),
    ("c3", "take THREE capsules", P, "quantity", ""),
    ("c4", "take FOUR capsules", P, "quantity", ""),
    ("c12", "take 1 or 2 capsules", P, "quantity", ""),
    # Liquids and measures.
    ("g1.25", "give 1.25ml", P, "quantity", ""),
    ("g2.5", "give 2.5ml", P, "quantity", ""),
    ("g5", "give 5ml", P, "quantity", ""),
    ("g7.5", "give 7.5ml", P, "quantity", ""),
    ("g10", "give 10ml", P, "quantity", ""),
    ("g15", "give 15ml", P, "quantity", ""),
    ("g20", "give 20ml", P, "quantity", ""),
    ("m1", "take 5ml", P, "quantity", ""),
    ("m1h", "take ONE AND A HALF measures (7.5ml)", P, "quantity", ""),
    ("mm", "medicine measure(s)", P, "quantity", ""),
    ("mm1", "take ONE medicine measure (5ml)", P, "quantity", ""),
    ("ms", "medicine measures", P, "quantity", ""),
    # Drops.
    ("d1", "instill ONE drop", P, "quantity", ""),
    ("d1-2", "instill 1 or 2 drops", P, "quantity", ""),
    ("d2", "instill TWO drops", P, "quantity", ""),
    ("d3", "instill THREE drops", P, "quantity", ""),
    ("dr", "drop(s)", P, "quantity", ""),
    ("dr1", "instill ONE drop", P, "quantity", ""),
    ("dr2", "instill TWO drops", P, "quantity", ""),
    ("il", "instill", P, "quantity", ""),
    # Suppositories, pessaries, sachets, lozenges, applicators.
    ("s1", "insert ONE suppository", P, "quantity", ""),
    ("s2", "insert TWO suppositories", P, "quantity", ""),
    ("p1", "insert ONE pessary", P, "quantity", ""),
    ("a1", "insert ONE applicatorful", P, "quantity", ""),
    ("n1s", "take ONE sachet", P, "quantity", ""),
    ("n2s", "take TWO sachets", P, "quantity", ""),
    ("suc", "suck ONE lozenge", P, "quantity", ""),
    ("ins", "insert", P, "quantity", ""),

    # ----------------------------------------------------------- frequency
    ("b", "twice a day", P, "frequency", ""),
    ("t", "three times a day", P, "frequency", ""),
    ("o", "once a day", P, "frequency", ""),
    ("d", "daily", P, "frequency", ""),
    ("q", "four times a day", P, "frequency", ""),
    ("qh", "every four hours", P, "frequency", ""),
    ("qqh", "every four hours", P, "frequency", ""),
    ("q12", "every twelve hours", P, "frequency", ""),
    ("2h", "every two hours", P, "frequency", ""),
    ("3h", "every three hours", P, "frequency", ""),
    ("4h", "every four hours", P, "frequency", ""),
    ("6h", "every six hours", P, "frequency", ""),
    ("8h", "every eight hours", P, "frequency", ""),
    ("12h", "every twelve hours", P, "frequency", ""),
    ("24h", "every twenty-four hours", P, "frequency", ""),
    ("223", "every two to three hours", P, "frequency", ""),
    ("46u", "every 4 to 6 hours", P, "frequency", ""),
    ("68u", "every 6 to 8 hours", P, "frequency", ""),
    ("5x", "five times a day", P, "frequency", ""),
    ("alt", "on alternate days", P, "frequency", ""),
    ("sec", "every second day", P, "frequency", ""),
    ("sd", "as a single dose", P, "frequency", ""),
    ("sta", "immediately", P, "frequency", ""),
    ("f", "as prescribed", P, "frequency", ""),
    ("tud", "to be taken as prescribed", P, "frequency", ""),
    ("u", "use as before", P, "frequency", ""),
    ("ua", "as before", P, "frequency", ""),
    ("ab", "as before", P, "frequency", ""),
    ("ta", "take as before", P, "frequency", ""),
    ("uf", "until finished", P, "frequency", ""),
    ("prp", "when needed for pain", P, "frequency", ""),
    ("qw", "according to the original prescription", P, "frequency", ""),

    # -------------------------------------------------------------- timing
    ("m", "in the morning", P, "timing", ""),
    ("n", "at night", P, "timing", ""),
    ("bt", "at bedtime", P, "timing", ""),
    ("nm", "night and morning", P, "timing", ""),
    ("mn", "in the morning and evening", P, "timing", ""),
    ("flom", "in the morning after breakfast", P, "timing", ""),
    ("lose", "in the morning with a glass of water", P, "timing", ""),
    ("am", "after meals", P, "timing", ""),
    ("paro", "after meals", P, "timing", ""),
    ("purb", "after meals", P, "timing", ""),
    ("flag", "after meals", P, "timing", ""),
    ("spor", "immediately after a meal", P, "timing", ""),
    ("zinn", "half an hour after food", P, "timing", ""),
    ("prep", "before meals", P, "timing", ""),
    ("colo", "before meals", P, "timing", ""),
    ("ruli", "before meals", P, "timing", ""),
    ("lanz", "before a meal", P, "timing", ""),
    ("augm", "immediately before meals", P, "timing", ""),
    ("eryt", "immediately before meals", P, "timing", ""),
    ("inte", "15 minutes before meals", P, "timing", ""),
    ("maxo", "15 minutes before meals", P, "timing", ""),
    ("mega", "half an hour before meals", P, "timing", ""),
    ("supr", "one hour before meals", P, "timing", ""),
    ("noro", "one hour before meals", P, "timing", ""),
    ("utin", "one hour before meals", P, "timing", ""),
    ("ampi", "1 hour or 2 hours after a meal", P, "timing", ""),
    ("tetr", "1 hour before or 2 hours after a meal", P, "timing", ""),
    ("rios", "half an hour before or 2 hours after a meal", P, "timing", ""),
    ("roxy", "half an hour before or 2 hours after a meal", P, "timing", ""),
    ("lora", "half an hour before or 2 hours after food", P, "timing", ""),
    ("zith", "half an hour before or 2 hours after food", P, "timing", ""),
    ("sto", "on an empty stomach", P, "timing", ""),
    ("bm", "between meals", P, "timing", ""),
    ("macr", "with meals", P, "timing", ""),
    ("moxa", "with meals", P, "timing", ""),
    ("moxy", "with meals", P, "timing", ""),
    ("orel", "with meals", P, "timing", ""),
    ("cefa", "with food", P, "timing", ""),
    ("arth", "with food", P, "timing", ""),
    ("oruv", "with food", P, "timing", ""),
    ("mobi", "with or after food", P, "timing", ""),
    ("pulm", "with or after meals", P, "timing", ""),
    ("tari", "with or without meals", P, "timing", ""),
    ("cefr", "with or without meals", P, "timing", ""),
    ("cipr", "with or without meals", P, "timing", ""),
    ("spas", "just before or with meals", P, "timing", ""),
    ("cont", "with breakfast", P, "timing", ""),
    ("pant", "with breakfast", P, "timing", ""),
    ("fm", "with a fatty meal", P, "timing", ""),
    ("aq", "with water", P, "timing", ""),
    ("fgw", "with a full glass of water", P, "timing", ""),
    ("w", "with plenty of fluids", P, "timing", ""),
    ("ple", "with plenty of fluids", P, "timing", ""),
    ("als", "after each loose stool", P, "timing", ""),
    ("kak", "after each loose stool", P, "timing", ""),
    ("run", "then ONE after each loose stool", P, "timing", ""),
    ("sil", "take ONE tablet 30 minutes before intercourse", P, "timing", ""),

    # --------------------------------------------------------------- route
    ("ap", "apply to the affected areas", P, "route", ""),
    ("aaa", "apply to the affected area", P, "route", ""),
    ("pa", "to affected parts", P, "route", ""),
    ("aps", "apply sparingly", P, "route", ""),
    ("sp", "sparingly", P, "route", ""),
    ("atc", "apply the cream", P, "route", ""),
    ("ato", "apply the ointment", P, "route", ""),
    ("ww", "rub in", P, "route", ""),
    # Laterality. RX5000 writes these in full and hyphenated on purpose;
    # these are the codes a Proppharm hand reaches for, and they expand to
    # exactly the same words, so both routes reach one sentence.
    ("rey", "into the RIGHT eye", P, "route", ""),
    ("reye", "into the RIGHT eye", P, "route", ""),
    ("leye", "into the LEFT eye", P, "route", ""),
    ("beye", "into BOTH eyes", P, "route", ""),
    ("ey", "into the affected eye(s)", P, "route", ""),
    ("aeye", "into the affected eye(s)", P, "route", ""),
    ("eyd", "eye drops", P, "route", ""),
    ("inn", "apply to the inner eyelid", P, "route", ""),
    ("rea", "into the RIGHT ear", P, "route", ""),
    ("rer", "into the RIGHT ear", P, "route", ""),
    ("bear", "into BOTH ears", P, "route", ""),
    ("aear", "into the affected ear(s)", P, "route", ""),
    ("erd", "ear drops", P, "route", ""),
    ("bnos", "into each nostril", P, "route", ""),
    ("ibn", "into BOTH nostrils", P, "route", ""),
    ("nos", "into BOTH nostrils", P, "route", ""),
    ("hiv", "higher into the vagina", P, "route", ""),
    ("subl", "under the tongue", P, "route", ""),
    ("ngt", "through the nasogastric tube", P, "route", ""),
    ("nebs", "through a nebuliser", P, "route", ""),
    ("ga", "gargle with", P, "route", ""),
    ("gw", "gargle with", P, "route", ""),
    ("tg", "the gargle", P, "route", ""),
    ("gar", "use as a gargle as directed", P, "route", ""),
    ("diw", "dissolve in water", P, "route", ""),
    ("dw", "dissolved in water", P, "route", ""),
    ("opg", "dissolved in water", P, "route", ""),
    ("cit", "dissolved in water", P, "route", ""),

    # ---------------------------------------------------------------- what
    ("dz", "for dizziness", P, "indication", ""),
    ("co", "for cough", P, "indication", ""),
    ("tus", "for cough", P, "indication", ""),
    ("fd", "for diarrhoea", P, "indication", ""),
    ("ft", "for fever", P, "indication", ""),
    ("nv", "for nausea and vomiting", P, "indication", ""),
    ("vn", "for nausea and vomiting", P, "indication", ""),
    ("fa", "for allergies and irritation", P, "indication", ""),
    ("ale", "for allergies and sneezing", P, "indication", ""),
    ("p", "for pain", P, "indication", ""),
    ("pd", "for pain", P, "indication", ""),
    ("pf", "for pain and fever", P, "indication", ""),
    ("fpf", "for pain and fever", P, "indication", ""),
    ("pdf", "for pain and fever", P, "indication", ""),
    ("pt", "for pain and fever", P, "indication", ""),
    ("pi", "for pain and inflammation", P, "indication", ""),
    ("pdi", "for pain and inflammation", P, "indication", ""),
    ("pai", "for pain, inflammation and fever", P, "indication", ""),
    ("gout", "until the pain stops", P, "indication", ""),

    # ------------------------------------------------------------- caution
    # These are the reason a code book earns its keep: the warning a dispenser
    # would otherwise write out longhand, and therefore sometimes not at all.
    ("aa", "AVOID ALCOHOL", P, "caution", ""),
    ("nal", "NO ALCOHOL", P, "caution", ""),
    ("mcd", "MAY CAUSE DROWSINESS", P, "caution", ""),
    ("cd", "MAY CAUSE DROWSINESS", P, "caution", ""),
    ("dro", "MAY CAUSE DROWSINESS", P, "caution", ""),
    ("ex", "FOR EXTERNAL USE ONLY", P, "caution", ""),
    ("ext", "FOR EXTERNAL USE ONLY", P, "caution", ""),
    ("exu", "FOR EXTERNAL USE ONLY", P, "caution", ""),
    ("inj", "FOR INJECTION ONLY", P, "caution", ""),
    ("gg", "POISON — DANGER", P, "caution", ""),
    ("ntbt", "NOT TO BE TAKEN", P, "caution", ""),
    ("mil", "DO NOT TAKE WITH MILK", P, "caution", ""),
    ("milk", "NO MILK PRODUCTS", P, "caution", ""),
    ("cecl", "with meals. DO NOT CRUSH OR CUT", P, "caution", ""),
    ("sun", "AVOID EXCESSIVE SUNLIGHT", P, "caution", ""),
    ("roac", "AVOID EXPOSURE TO THE SUN", P, "caution", ""),
    ("azo", "your urine may turn red — this is harmless", P, "caution", ""),
    ("iod", "CONTAINS IODINE", P, "caution", ""),
    ("pen", "CONTAINS PENICILLIN", P, "caution", ""),
    ("cef", "CONTAINS A CEPHALOSPORIN", P, "caution", ""),
    ("an", "ANTIBIOTIC", P, "caution", ""),
    ("ant", "ANTIBIOTIC — complete the course", P, "caution", ""),
    ("af", "ANTIFUNGAL — complete the course", P, "caution", ""),
    ("fc", "FINISH THE COURSE", P, "caution", ""),
    ("com", "COMPLETE THE COURSE", P, "caution", ""),
    ("j", "COMPLETE THE COURSE", P, "caution", ""),
    ("disc", "DISCARD ANY REMAINDER", P, "caution", ""),
    ("ice", "STORE IN THE FRIDGE", P, "caution", ""),
    ("y", "STORE IN THE FRIDGE", P, "caution", ""),
    ("kif", "KEEP IN THE FRIDGE", P, "caution", ""),
    ("frid", "KEEP IN THE FRIDGE", P, "caution", ""),
    ("cool", "KEEP IN THE FRIDGE", P, "caution", ""),
    ("sbw", "SHAKE THE BOTTLE WELL", P, "caution", ""),
    ("sh", "SHAKE THE BOTTLE", P, "caution", ""),
    ("shk", "SHAKE THE BOTTLE", P, "caution", ""),
    ("sg", "shake gently before use", P, "caution", ""),
    ("doc", "to be administered by the doctor", P, "caution", ""),
    ("fi", "for injection by the doctor", P, "caution", ""),

    # --------------------------------------------------------------- forms
    ("ds", "days", P, "form", ""),

    # ------------------------------------------------------ the dispensary
    # Workflow markers rather than label text. They never printed on a box in
    # Proppharm either — they are notes to whoever picks the script up next.
    ("r1", "REPEATABLE x1", P, "dispensary", ""),
    ("r2", "REPEATABLE x2", P, "dispensary", ""),
    ("r3", "REPEATABLE x3", P, "dispensary", ""),
    ("r4", "REPEATABLE x4", P, "dispensary", ""),
    ("r5", "REPEATABLE x5", P, "dispensary", ""),
    ("r6", "REPEATABLE x6", P, "dispensary", ""),
    ("r12", "REPEATABLE x12", P, "dispensary", ""),
    ("lr", "LAST REPEAT", P, "dispensary", ""),
    ("nd", "NOT DISPENSED", P, "dispensary", ""),
    ("tf", "TO FOLLOW", P, "dispensary", ""),
    ("bal", "BALANCE OF MEDICINE", P, "dispensary", ""),
    ("tt", "TELEPHONIC PRESCRIPTION — doctor to sign", P, "dispensary", ""),
    ("maid", "MEDICAL AID BENEFITS EXCEEDED", P, "dispensary", ""),
    ("nk", "EMERGENCY CUPBOARD", P, "dispensary", ""),
    ("ckk", "NOT FOR TTO DISPENSING", P, "dispensary", ""),
    ("ck", "Codis cocktail", P, "dispensary", ""),
    ("cor", "with ONE tablet of Corenza-C", P, "dispensary", ""),
    # Two codes whose Proppharm text carried a date typed in once, in 2007,
    # and printed unchanged ever since — `RD  RETURN DATE 14/11/2007`. They are
    # templates, not sentences, so the date is left for the dispenser to add
    # rather than shipped nineteen years stale.
    ("rd", "return date:", P, "dispensary",
     "Type the date after the code — it prints exactly as you write it."),
    ("x", "expiry date:", P, "dispensary",
     "Type the date after the code — it prints exactly as you write it."),

    # ------------------------------------------------------------ greeting
    # Real, and used: a dispenser typed `MX` in December and it went on the
    # label. Kept in a category of their own so they do not sit between two
    # clinical codes in the picker.
    ("gws", "Get well soon.", P, "greeting", ""),
    ("mx", "Merry Christmas.", P, "greeting", ""),
    ("hn", "Happy New Year.", P, "greeting", ""),
    ("hv", "Happy Valentine's Day.", P, "greeting", ""),
    ("holi", "away for 2 months holiday", P, "greeting", ""),
]

#: Proppharm codes that mean something DIFFERENT from a code RX5000 ships.
#:
#: Not imported. Seeding them would change what an installed pharmacy's labels
#: say without anybody asking for it, and two of these are the kind of change
#: that ends in a patient taking the wrong thing:
#:
#:   1c   Proppharm: a TABLET.  RX5000: a CAPSULE. Not a preference.
#:   1p   Proppharm: a weekly PATCH.  RX5000: a PUFF of an inhaler.
#:   inh  Proppharm: "inhale 1 or 2 puffs" — a whole instruction with a count
#:        in it.  RX5000: "by inhalation" — a route, meant to follow a count.
#:        `2p inh` would read "use TWO puffs inhale 1 or 2 puffs".
#:   i    Proppharm: "immediately, and then" — the head of a loading dose.
#:        RX5000: the roman numeral ONE, which is how a prescriber writes it
#:        by hand. `i tab tds` would read "immediately, and then tablet…".
#:   aa   Proppharm: AVOID ALCOHOL.  RX5000: "of each" (ana), used when
#:        compounding. Imported above as a caution BECAUSE the existing row is
#:        the one that has to give way here — see the note in `seed()`.
#:
#: Both halves of each pair are the wording actually in each book — not a
#: description of it — so this can be read as data by whatever asks the pharmacy
#: to choose, and by the check that proves the old reading survived the import.
#:
#: A pharmacy migrating off Proppharm should be shown this list and asked which
#: reading it wants. It is four decisions, once, and it is not ours to take.
CONFLICTS: dict[str, tuple[str, str]] = {
    "i": ("immediately, and then", "ONE"),
    "1c": ("take ONE tablet", "take ONE capsule"),
    "1p": ("apply ONE patch to the skin weekly", "use ONE puff"),
    "inh": ("inhale 1 or 2 puffs", "by inhalation"),
    "aa": ("AVOID ALCOHOL", "of each"),
}

#: Codes read off the photographs whose wording the dialog cut off.
#:
#: The picker is narrower than the sentence, so what was on screen was
#: `AMOX  **ANTIBIOTIC** TAKE ONE CAPSULE THREE TIMES A…` and no more. The code
#: is certain; the label text is not, and a label carrying half an instruction
#: is worse than one carrying none — nothing on the box shows the omission.
#:
#: These are not guessed at. Read them off the old system and add them.
TRUNCATED: dict[str, str] = {
    "amox": "**ANTIBIOTIC** TAKE ONE CAPSULE THREE TIMES A…",
    "amoxys": "***SHAKE BOTTLE WELL*** GIVE 5MLS THREE TIMES…",
    "cele": "TAKE ONE CAPSULE TWICE DAILY AFTER MEALS WHEN…",
    "cet": "TAKE ONE TABLET ONCE DAILY WHEN NECESSARY FO…",
    "cipro": "**ANTIBIOTIC** TAKE ONE TABLET TWICE DAILY AT L…",
    "clot": "GENTLY APPLY 10-20 DROPS INTO THE MOUTH 3-4 TIME…",
    "co-c": "TAKE 1-2 TABLET THREE TIMES A DAY AFTER FOOD WH…",
    "coar": "TAKE 4 TABLETS IMMEDIATELY THEN TAKE 4 TABLETS A…",
    "cream": "***FOR EXTERNAL USE ONLY*** APPLY CREAM TO AF…",
    "diclo": "TAKE ONE TABLET THREE TIMES DAILY AFTER MEALS…",
    "discard": "DISCARD 1 MONTH AFTER OPENING",
    "dissolve": "DISSOLVE IN A TEASPOONFUL OF WATER/FRUIT JUIC…",
    "doxy": "**ANTIBIOTIC** TAKE ONE CAPSULE TWICE DAILY U…",
    "gris1": "TAKE ONE TABLET ONCE DAILY AFTER MEALS. TAKE W…",
    "gris2": "TAKE TWO TABLETS ONCE DAILY AFTER MEALS. TAKE…",
    "ibup": "TAKE ONE TABLET THREE TIMES A DAY AFTER FOOD W…",
    "maxi": "INSTIL 1-2 DROPS INTO THE AFFECTED EYE THREE TIM…",
    "metro": "**ANTIBIOTIC** TAKE 1 TABLET THREE TIMES DAILY A…",
    "mog": "INFANTS: UPTO 1YR 1/4 MEASURING SPOON 4 TIMES D…",
    "mupi": "**FOR EXTERNAL USE ONLY** APPLY OINTMENT TO T…",
    "omep": "TAKE ONE CAPSULE TWICE DAILY 30MINS BEFORE FO…",
    "oral": "TAKE 2.5MLS-5MLS OF THE GEL AND THEN HOLD IN TH…",
    "paint": "INSTIL 10-20 DROPS THREE TIMES DAILY AFTER FOOD…",
    "ref": "TAKE ONE TABLET TWICE DAILY AFTER MEALS WHEN…",
    "supp": "INSERT ONE SUPPOSITORY PER RECTUM TWICE DAILY…",
    "tram": "TAKE 1-2 TABLET THREE TIMES A DAY WHEN NECESSA…",
    "trama": "TAKE ONE CAPSULE THREE TIMES DAILY FOR PAIN…",
    "zinc": "TAKE ONE TABLET DISSOLVED IN A TABLESPOON OF W…",
}

#: Proppharm's `SC  SUB CUTANEOUS`, which is deliberately NOT imported.
#:
#: RX5000 already retired `sc` on purpose: ISMP records it being read as `sl`,
#: under the tongue, which turns an injection into a tablet held in the mouth.
#: The code RX5000 ships is `subcut`, and re-adding `sc` to feel familiar would
#: undo a safety decision to save four keystrokes. A Proppharm hand that types
#: `sc` gets nothing and looks, which is the outcome that was designed for.
NOT_IMPORTED = {"sc": "subcut"}


def seed(db: Session) -> dict[str, list[str]]:
    """Add the Proppharm vocabulary alongside RX5000's own, changing nothing.

    Every existing row is left exactly as it is. A code already in the book —
    whether RX5000 seeded it or the pharmacy typed it themselves — keeps its
    wording, because a dispensary whose labels changed meaning during an upgrade
    is one that stops trusting the upgrade.

    The single exception is `aa`, and it is deliberate. RX5000 seeded it as "of
    each" (ana), a compounding term; Proppharm and every dispenser coming from
    it read `aa` as AVOID ALCOHOL. Of the two, one is a warning and the other is
    a quantity, and getting a warning where you expected a quantity is visible
    on the preview line before anything prints — whereas losing an alcohol
    warning is not visible anywhere. So the caution wins, and the row is only
    replaced where it still says exactly what RX5000 shipped.
    """
    added: list[str] = []
    kept: list[str] = []

    # Called from the label path, which runs once per script line. Reading four
    # hundred rows and committing to discover there is nothing to do would put a
    # round trip on every dispensing. One indexed lookup answers it instead.
    #
    # `12a` is the sentinel because it is Proppharm's and nothing else's: RX5000
    # never shipped it, no other seeder writes it, and it is not a code anybody
    # would type into the book by hand before this import had run.
    if db.query(DosageAbbreviation.id).filter(
            DosageAbbreviation.code == "12a").first():
        return {"added": [], "already known": []}

    existing = {row.code.lower(): row
                for row in db.query(DosageAbbreviation).all()}

    for code, expansion, meaning, category, caution in CODES:
        row = existing.get(code)
        if row is None:
            db.add(DosageAbbreviation(code=code, expansion=expansion,
                                      meaning=meaning, category=category,
                                      caution=caution))
            added.append(code)
            continue
        if code == "aa" and row.expansion == "of each":
            row.expansion = expansion
            row.meaning = meaning
            row.category = category
            added.append("aa (replaced 'of each')")
            continue
        # Anything else that is already here stays as it is.
        kept.append(code)

    db.commit()
    return {"added": added, "already known": kept}
