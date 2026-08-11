"""ICD-10 chapter structure, and what to do about codes we do not hold.

The full WHO release is over 70,000 codes. No pharmacy system ships all of them
in its seed data, and this one holds a few dozen. That creates a trap worth
naming, because the obvious implementation gets it exactly backwards:

    if code not in our_table: reject as invalid

That rule is wrong far more often than it is right. A pharmacy dispensing
against a real prescription will meet codes outside any starter list constantly,
and every one of them would be refused as though the prescriber had invented it.
The pharmacist cannot fix it, cannot claim, and learns to work around the system.

So validation is graded by what is actually knowable:

    malformed                     reject - this is definitely an error
    outside every chapter         reject - no such code can exist
    in a chapter, in our table    accept, with the description
    in a chapter, not in our table  accept, and say the description is unknown

The last case is the important one. Structure and chapter membership are things
we can genuinely check; presence in a partial table is not evidence of anything.

**The chapter ranges below are ICD-10-CM boundaries** (the United States clinical
modification), which differ slightly from the WHO ICD-10 that Zimbabwe and South
Africa use: CM ends neoplasms at D49 where WHO ends at D48, endocrine at E89
where WHO uses E90, digestive at K95 where WHO uses K93, and injury at T88 where
WHO uses T98. The ranges here are deliberately widened to the union of both, so
a code valid under either release passes. Being generous at the boundary costs
nothing - a funder will reject a genuinely wrong code anyway - while being strict
at the boundary would refuse valid claims for no benefit.
"""
import re

# Structure: any letter, two digits, then optionally a dot and up to four more
# characters. The older form of this pattern was [A-TV-Z], excluding U — correct
# when U was unassigned, and wrong since WHO put COVID-19 at U07.1. Which roots
# actually exist is decided by the chapter table below, not by the alphabet, so
# there is nothing to gain from second-guessing the letter here.
PATTERN = re.compile(r"^[A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$")

# (first letter+2 digits, last letter+2 digits, title). Ranges are inclusive and
# compared on the three-character root.
CHAPTERS = [
    ("A00", "B99", "Certain infectious and parasitic diseases"),
    ("C00", "D49", "Neoplasms"),
    ("D50", "D89", "Diseases of the blood and blood-forming organs, and immune disorders"),
    ("E00", "E90", "Endocrine, nutritional and metabolic diseases"),
    # WHO starts this chapter at F00 (dementia in Alzheimer's disease); CM starts
    # at F01 because it moved that code to G30. Taking the lower bound keeps a
    # valid WHO code claimable.
    ("F00", "F99", "Mental, behavioural and neurodevelopmental disorders"),
    ("G00", "G99", "Diseases of the nervous system"),
    ("H00", "H59", "Diseases of the eye and adnexa"),
    ("H60", "H95", "Diseases of the ear and mastoid process"),
    ("I00", "I99", "Diseases of the circulatory system"),
    ("J00", "J99", "Diseases of the respiratory system"),
    ("K00", "K95", "Diseases of the digestive system"),
    ("L00", "L99", "Diseases of the skin and subcutaneous tissue"),
    ("M00", "M99", "Diseases of the musculoskeletal system and connective tissue"),
    ("N00", "N99", "Diseases of the genitourinary system"),
    ("O00", "O99", "Pregnancy, childbirth and the puerperium"),
    ("P00", "P96", "Certain conditions originating in the perinatal period"),
    ("Q00", "Q99", "Congenital malformations, deformations and chromosomal abnormalities"),
    ("R00", "R99", "Symptoms, signs and abnormal findings, not elsewhere classified"),
    ("S00", "T98", "Injury, poisoning and certain other consequences of external causes"),
    ("U00", "U85", "Codes for special purposes"),
    ("V00", "Y99", "External causes of morbidity"),
    ("Z00", "Z99", "Factors influencing health status and contact with health services"),
]

# Chapters that describe a circumstance rather than a disease. A funder will
# usually not accept one as the sole reason for a claim, so they are flagged
# rather than blocked — the prescriber may have a good reason, and refusing
# outright would be this system overruling a clinician on a matter of fact.
WEAK_PRIMARY_PREFIXES = ("Z", "U")


def normalise(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def _root(code: str) -> str:
    """The three-character root a chapter range is compared on."""
    return normalise(code)[:3]


def chapter_for(code: str) -> tuple[str, str] | None:
    """The chapter a code belongs to, or None if it falls outside every range."""
    root = _root(code)
    if len(root) < 3:
        return None
    for start, end, title in CHAPTERS:
        if start <= root <= end:
            return f"{start}-{end}", title
    return None


def classify(code: str) -> dict:
    """Everything knowable about a code without a database.

    `known_structure` and `chapter` are facts. Whether the code is in any
    particular table is not a property of the code, so it is not decided here.
    """
    code = normalise(code)
    if not code:
        return {"code": "", "valid_structure": False, "chapter": None,
                "chapter_title": "", "reason": "No diagnosis code was given."}
    if not PATTERN.match(code):
        return {"code": code, "valid_structure": False, "chapter": None,
                "chapter_title": "",
                "reason": f"'{code}' is not a structurally valid ICD-10 code - "
                          "expect a letter, two digits, and optionally a dot with "
                          "up to four more characters, as in J45.9."}
    chapter = chapter_for(code)
    if chapter is None:
        return {"code": code, "valid_structure": True, "chapter": None,
                "chapter_title": "",
                "reason": f"'{code}' is structurally valid but falls outside every "
                          "ICD-10 chapter, so no such code exists."}
    return {"code": code, "valid_structure": True, "chapter": chapter[0],
            "chapter_title": chapter[1], "reason": "",
            "weak_primary": code[0] in WEAK_PRIMARY_PREFIXES}


def chapters() -> list[dict]:
    return [{"range": f"{start}-{end}", "start": start, "end": end, "title": title}
            for start, end, title in CHAPTERS]


def in_chapter(code: str, chapter_range: str) -> bool:
    """Whether a code sits in a chapter, given as 'A00-B99'."""
    if "-" not in (chapter_range or ""):
        return False
    start, _, end = chapter_range.partition("-")
    root = _root(code)
    return bool(root) and start.strip().upper() <= root <= end.strip().upper()
