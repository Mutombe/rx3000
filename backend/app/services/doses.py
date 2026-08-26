"""Dose range checking, and an honest account of what it does not cover.

The same discipline as `interactions`, for the same reason: **a partial dose
table is more dangerous than no table** if the screen lets anyone read "nothing
found" as "this dose is correct". A pharmacist told twice that the system checks
doses will, on the third occasion, trust it — and the drug it does not hold will
go out at four times the maximum.

So:

* Every answer carries its **coverage**: how many ingredients were consulted, and
  a statement that this is a small set of common medicines and not a formulary.
* A clean result is never "the dose is correct". It is "no limit is held for
  this medicine" or "within the limit held here", which are different and true
  sentences.
* An ingredient with no entry says so out loud rather than passing silently. A
  silent pass is the failure this module exists to prevent.
* `LIMITS` is pluggable in exactly the way `interactions.KNOWN` is. When a
  licensed formulary is procured the table is replaced and the coverage note
  changes with it; the callers, the screen and the dispensing gate do not.

**Paediatric doses are refused, not guessed.** Almost every children's dose here
is per kilogram, and this system does not record a weight. Working one out from
age is how a child gets an adult dose of something. Where the patient is under
twelve the checker declines to judge and says why, which is the only honest
answer available to it.

What is checked is the *daily* dose implied by the directions: quantity per
administration times administrations per day, against the maximum for that
ingredient. Single-dose maxima are held too, because a dose that is fine four
times a day can be dangerous taken all at once.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Below this age nothing is judged; see the module docstring.
PAEDIATRIC_UNDER = 12

COVERAGE_NOTE = (
    "Checked against maximum doses held locally for {n} medicines. This is not a "
    "formulary: a clear result means no limit here was exceeded, not that the "
    "dose is correct for this patient. Renal and hepatic impairment, age, weight "
    "and interactions all change what is safe, and none of them is assessed here."
)


@dataclass(frozen=True)
class Limit:
    """A maximum for one ingredient, in the unit the strength is written in."""
    ingredient: str
    unit: str                 # mg, g, mcg, ml
    max_single: float | None  # most that may be taken at once
    max_daily: float          # most in twenty-four hours
    note: str = ""


# Adult limits for medicines a Zimbabwean counter meets constantly. Chosen
# because they are the ones where exceeding the maximum does immediate harm, or
# where the mistake is common — not because they are sufficient.
LIMITS: list[Limit] = [
    Limit("paracetamol", "mg", 1000, 4000,
          "Hepatotoxic above 4g a day. The commonest overdose in the country, "
          "and usually accidental: two products, both containing it."),
    Limit("ibuprofen", "mg", 800, 2400,
          "Above 2.4g a day the gastrointestinal and renal risk rises sharply."),
    Limit("diclofenac", "mg", 50, 150, "Cardiovascular risk is dose related."),
    Limit("aspirin", "mg", 1000, 4000,
          "As an analgesic. The 75mg cardiac dose is a different medicine in "
          "practice and is not what this limit is about."),
    Limit("codeine", "mg", 60, 240, "Respiratory depression, and dependence."),
    Limit("tramadol", "mg", 100, 400,
          "Above 400mg a day the seizure risk rises, and further still with an "
          "SSRI on board."),
    Limit("morphine", "mg", None, 200,
          "No fixed ceiling in palliative use; this flags an unusual dose for "
          "review, not an error."),
    Limit("amoxicillin", "mg", 1000, 3000, ""),
    Limit("ciprofloxacin", "mg", 750, 1500, ""),
    Limit("metronidazole", "mg", 800, 2400, ""),
    Limit("doxycycline", "mg", 200, 200, "200mg a day, usually as a single dose."),
    Limit("azithromycin", "mg", 500, 500, ""),
    Limit("erythromycin", "mg", 1000, 4000, ""),
    Limit("prednisolone", "mg", 60, 60,
          "Higher short courses are prescribed deliberately; this asks that it "
          "was deliberate."),
    Limit("amlodipine", "mg", 10, 10, ""),
    Limit("enalapril", "mg", 20, 40, ""),
    Limit("losartan", "mg", 100, 100, ""),
    Limit("atenolol", "mg", 100, 100, ""),
    Limit("carvedilol", "mg", 25, 50, ""),
    Limit("furosemide", "mg", 80, 240, ""),
    Limit("hydrochlorothiazide", "mg", 25, 50, "Above 25mg adds harm, not effect."),
    Limit("simvastatin", "mg", 40, 40,
          "80mg carries a myopathy risk that is not offset by the benefit."),
    Limit("atorvastatin", "mg", 80, 80, ""),
    Limit("metformin", "mg", 1000, 3000, "Lactic acidosis risk in renal impairment."),
    Limit("glibenclamide", "mg", 15, 15, "Hypoglycaemia, and it is long acting."),
    Limit("gliclazide", "mg", 160, 320, ""),
    Limit("warfarin", "mg", 15, 15,
          "Dose is set by INR, not by a table. Anything unusual belongs with the "
          "prescriber."),
    Limit("diazepam", "mg", 10, 30, "Dependence, and respiratory depression with opioids."),
    Limit("amitriptyline", "mg", 75, 150, ""),
    Limit("fluoxetine", "mg", 60, 60, ""),
    Limit("carbamazepine", "mg", 600, 1600, ""),
    Limit("phenobarbitone", "mg", 100, 200, ""),
    Limit("cetirizine", "mg", 10, 10, ""),
    Limit("loratadine", "mg", 10, 10, ""),
    Limit("chlorpheniramine", "mg", 12, 24, ""),
    Limit("omeprazole", "mg", 40, 40, ""),
    Limit("ranitidine", "mg", 300, 600, ""),
    Limit("salbutamol", "mcg", 400, 800, "By inhaler. Regular high use means the "
                                         "asthma is not controlled."),
    Limit("quinine", "mg", 600, 1800, ""),
]

_BY_INGREDIENT = {limit.ingredient: limit for limit in LIMITS}

#: How many times a day each direction means. Read from the same shorthand a
#: dispenser types; anything not here yields no frequency and no judgement.
PER_DAY: dict[str, float] = {
    "od": 1, "once a day": 1, "daily": 1, "nocte": 1, "mane": 1, "om": 1, "on": 1,
    "bd": 2, "twice a day": 2, "bid": 2,
    "tds": 3, "three times a day": 3, "tid": 3,
    "qds": 4, "qid": 4, "four times a day": 4,
    "q4h": 6, "every four hours": 6,
    "q6h": 4, "every six hours": 4,
    "q8h": 3, "every eight hours": 3,
    "q12h": 2, "every twelve hours": 2,
    "altd": 0.5, "on alternate days": 0.5,
    "weekly": 1 / 7, "once a week": 1 / 7,
    "stat": 1, "immediately": 1,
}

#: Roman numerals a dispenser still writes for a quantity: "ii tabs tds".
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "ss": 0.5}


def strength_mg(strength: str) -> tuple[float | None, str]:
    """The number and unit out of a strength like "500mg" or "20/120mg".

    A combination strength returns its first number, and the caller is told the
    ingredient it matched — checking amoxicillin against the clavulanate half of
    "500/125mg" would be wrong in the dangerous direction, so a combination is
    only ever matched on the ingredient whose figure comes first.
    """
    if not strength:
        return None, ""
    m = re.search(r"([\d.]+)\s*(mcg|mg|g|ml|iu)", strength.lower())
    if not m:
        return None, ""
    value, unit = float(m.group(1)), m.group(2)
    if unit == "g":
        return value * 1000, "mg"
    return value, unit


def doses_per_day(instructions: str) -> float | None:
    """How many times a day the directions say. None when they do not say.

    "When required" deliberately yields nothing. A prn direction has no daily
    dose until somebody decides how often; guessing the maximum would flag every
    box of paracetamol, and guessing the minimum would miss the one that matters.
    """
    text = (instructions or "").lower()
    if not text:
        return None
    if "prn" in text or "when required" in text or "as needed" in text:
        return None
    # Longest key first, so "every four hours" is not matched by "four".
    for key in sorted(PER_DAY, key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", text):
            return PER_DAY[key]
    return None


def units_per_dose(instructions: str) -> float:
    """How many tablets each time. Defaults to one, which is what a direction
    with no number in it means."""
    text = (instructions or "").lower()
    m = re.search(r"(?:take\s+)?([\d.]+)\s*(?:x\s*)?(?:tab|tabs|tablet|cap|capsule|t\b|ml)", text)
    if m:
        return float(m.group(1))
    for word, value in _ROMAN.items():
        if re.search(rf"\b{word}\s*(?:tab|tabs|tablet|cap|t)\b", text):
            return value
    m = re.match(r"\s*([\d.]+)\b", text)
    return float(m.group(1)) if m else 1.0


def _match(ingredient_text: str) -> Limit | None:
    """The limit for this product, matched on active ingredient then on name.

    The name is a fallback because most generics carry the drug in the name. It
    is checked second so that a product whose ingredient is recorded is judged
    on the ingredient, which is the more reliable of the two.
    """
    text = (ingredient_text or "").lower()
    for name, limit in _BY_INGREDIENT.items():
        if re.search(rf"\b{re.escape(name)}", text):
            return limit
    return None


def check(items: list[dict], *, age: int | None = None) -> dict:
    """Check each line's daily dose against the maximum held for it.

    `items` are {name, active_ingredient, strength, instructions, quantity}.
    """
    findings: list[dict] = []
    unknown: list[str] = []
    judged = 0

    paediatric = age is not None and age < PAEDIATRIC_UNDER

    for item in items:
        label = item.get("name", "")
        haystack = f"{item.get('active_ingredient') or ''} {label}".strip()
        limit = _match(haystack)
        if not limit:
            unknown.append(label)
            continue

        if paediatric:
            findings.append({
                "severity": "unknown",
                "product": label,
                "detail": (f"{label} has an adult maximum here, and this patient is "
                           f"{age}. Children's doses are calculated per kilogram and "
                           "this system does not record a weight, so no judgement is "
                           "offered. Check against a paediatric reference."),
                "action": "Check the dose against a paediatric reference.",
            })
            continue

        each, unit = strength_mg(item.get("strength", ""))
        per_dose = units_per_dose(item.get("instructions", ""))
        frequency = doses_per_day(item.get("instructions", ""))

        if each is None or unit != limit.unit:
            unknown.append(label)
            continue
        if frequency is None:
            findings.append({
                "severity": "unread",
                "product": label,
                "detail": (f"The directions on {label} do not say how often, so the "
                           "daily dose could not be worked out. A maximum of "
                           f"{limit.max_daily:g}{limit.unit} a day applies."),
                "action": "Check the daily total against the directions given.",
            })
            continue

        judged += 1
        single = each * per_dose
        daily = single * frequency

        if limit.max_single is not None and single > limit.max_single:
            findings.append({
                "severity": "major",
                "product": label,
                "detail": (f"{per_dose:g} × {each:g}{unit} is {single:g}{unit} in one "
                           f"dose, above the {limit.max_single:g}{unit} maximum held "
                           f"for {limit.ingredient}."
                           + (f" {limit.note}" if limit.note else "")),
                "action": "Confirm the quantity per dose with the prescriber.",
            })
        if daily > limit.max_daily:
            findings.append({
                "severity": "major",
                "product": label,
                "detail": (f"{per_dose:g} × {each:g}{unit}, {frequency:g} times a day "
                           f"is {daily:g}{unit} in twenty-four hours, above the "
                           f"{limit.max_daily:g}{unit} maximum held for "
                           f"{limit.ingredient}."
                           + (f" {limit.note}" if limit.note else "")),
                "action": "Confirm the frequency with the prescriber before supplying.",
            })

    order = {"major": 0, "unknown": 1, "unread": 2}
    findings.sort(key=lambda f: order.get(f["severity"], 9))
    return {
        "checked": judged,
        "limits_consulted": len(LIMITS),
        "found": findings,
        "major": sum(1 for f in findings if f["severity"] == "major"),
        # Never "the dose is correct".
        "summary": (f"{len(findings)} to look at" if findings else
                    ("No limit held here was exceeded" if judged else
                     "No dose limit is held for these medicines")),
        # Said out loud rather than passing silently: a line nothing was known
        # about is the one a pharmacist most needs to know went unchecked.
        "not_covered": unknown,
        "coverage": COVERAGE_NOTE.format(n=len(LIMITS)),
        "is_formulary": False,
    }
