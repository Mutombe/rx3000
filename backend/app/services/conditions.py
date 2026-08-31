"""What the patient's recorded conditions say about what is being handed over.

The pharmacy already asks. "Chronic conditions" is a first-class field on every
patient, the picker offers Pregnancy and Breastfeeding as its own entries, and
a pharmacist records them for exactly one reason: they change what may be
dispensed.

Nothing read the field. It was used by the worklist to decide whose repeat was
urgent, by the AI prompt, and by marketing to pick a campaign audience — and
not by dispensing. So a pharmacy could hold the single most important fact
about a patient, typed in by a pharmacist who knew why it mattered, and the
screen that hands over the medicine would not mention it.

That is the worst shape a safety gap can take. Not missing data: *recorded and
ignored*. The pharmacist has already done the hard part.

WHAT THIS IS, EXACTLY

A named rule table, matched on active ingredient and product name, in the same
conservative way the allergy check works. It is not a clinical decision support
system and does not pretend to be one. Every response carries what the table
holds, because a checker that returns "nothing found" while holding forty rules
teaches a pharmacist that a clear result means safe — which is the failure this
whole area is written against.

It does not block on its own. A pregnancy warning on a medicine a specialist
has deliberately continued is a conversation, not a refusal, and software that
refuses what an obstetrician prescribed will be worked around within a week.
Severity says how loudly to say it; the pharmacist decides.

WHY THESE RULES AND NOT MORE

Each one below is a contraindication or a caution a dispensing pharmacist is
expected to know, drawn from the classes that actually appear in a Zimbabwean
pharmacy's stock. Rules were left out where they need a fact the record does
not hold — trimester, eGFR, seizure type — because a warning that fires on
every pregnancy regardless of stage is a warning that gets dismissed on every
pregnancy, including the one that mattered.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import ClinicalTerm, Patient, Product

#: (condition words, ingredient words, severity, what to say)
#:
#: `severity` is "stop" for a recognised contraindication and "warn" for a
#: caution. Neither refuses the dispensing — see the module docstring.
#:
#: Ingredient words are matched whole, against the active ingredient and the
#: product name, so "ace" cannot fire inside "paracetamol".
RULES: list[tuple[tuple[str, ...], tuple[str, ...], str, str]] = [
    # ---- pregnancy ------------------------------------------------------
    (("pregnan", "antenatal"), ("warfarin",), "stop",
     "Warfarin crosses the placenta and is teratogenic. Confirm the "
     "prescriber knows the patient is pregnant."),
    (("pregnan", "antenatal"),
     ("enalapril", "lisinopril", "captopril", "ramipril", "perindopril",
      "losartan", "valsartan", "telmisartan", "candesartan"), "stop",
     "ACE inhibitors and ARBs cause foetal injury in the second and third "
     "trimesters and are contraindicated in pregnancy."),
    (("pregnan", "antenatal"), ("isotretinoin", "acitretin"), "stop",
     "Retinoids are absolutely contraindicated in pregnancy."),
    (("pregnan", "antenatal"), ("methotrexate",), "stop",
     "Methotrexate is teratogenic and abortifacient."),
    (("pregnan", "antenatal"),
     ("doxycycline", "tetracycline", "minocycline", "oxytetracycline"), "stop",
     "Tetracyclines discolour foetal teeth and affect bone growth from the "
     "second trimester."),
    (("pregnan", "antenatal"),
     ("simvastatin", "atorvastatin", "rosuvastatin", "pravastatin"), "stop",
     "Statins are contraindicated in pregnancy."),
    (("pregnan", "antenatal"),
     ("ibuprofen", "diclofenac", "naproxen", "indomethacin", "meloxicam",
      "piroxicam", "aspirin"), "warn",
     "NSAIDs are avoided in the third trimester — premature closure of the "
     "ductus arteriosus. Check how far along the patient is."),
    (("pregnan", "antenatal"), ("sodium valproate", "valproate", "valproic"),
     "stop",
     "Valproate carries a high risk of birth defects and developmental "
     "disorders. It should not be started in pregnancy and continuing it is a "
     "specialist decision."),
    (("pregnan", "antenatal"), ("fluconazole",), "warn",
     "Fluconazole is avoided in the first trimester other than as a single "
     "low dose."),
    (("pregnan", "antenatal"), ("codeine", "tramadol", "morphine"), "warn",
     "Opioids near term can cause neonatal respiratory depression and "
     "withdrawal."),

    # ---- breastfeeding --------------------------------------------------
    (("breastfeed", "lactating", "nursing"), ("codeine",), "stop",
     "Codeine is contraindicated while breastfeeding. A mother who "
     "metabolises it rapidly passes dangerous levels of morphine to the "
     "infant, and this has caused deaths."),
    (("breastfeed", "lactating", "nursing"),
     ("doxycycline", "tetracycline", "minocycline"), "warn",
     "Tetracyclines pass into breast milk; short courses are usually "
     "accepted but check the alternative first."),
    (("breastfeed", "lactating", "nursing"),
     ("methotrexate", "amiodarone", "chloramphenicol"), "stop",
     "Contraindicated while breastfeeding."),
    (("breastfeed", "lactating", "nursing"), ("aspirin",), "warn",
     "Aspirin is avoided while breastfeeding — Reye's syndrome risk."),

    # ---- asthma ---------------------------------------------------------
    (("asthma", "asthmatic"),
     ("propranolol", "atenolol", "bisoprolol", "carvedilol", "metoprolol",
      "timolol", "sotalol"), "stop",
     "Beta-blockers can cause severe bronchospasm in asthma. Even eye drops "
     "are absorbed enough to matter."),
    (("asthma", "asthmatic"),
     ("ibuprofen", "diclofenac", "naproxen", "aspirin", "indomethacin"),
     "warn",
     "NSAIDs trigger bronchospasm in roughly one asthmatic in ten. Ask "
     "whether they have taken this class before."),

    # ---- renal ----------------------------------------------------------
    (("renal", "kidney", "dialysis"),
     ("ibuprofen", "diclofenac", "naproxen", "indomethacin", "meloxicam",
      "piroxicam"), "stop",
     "NSAIDs reduce renal perfusion and can precipitate acute kidney injury "
     "in existing renal disease."),
    (("renal", "kidney", "dialysis"), ("metformin",), "stop",
     "Metformin accumulates in renal impairment and risks lactic acidosis. "
     "The dose depends on eGFR, which this record does not hold."),
    (("renal", "kidney", "dialysis"),
     ("gentamicin", "amikacin", "streptomycin", "vancomycin"), "stop",
     "Aminoglycosides are nephrotoxic and need level monitoring."),
    (("renal", "kidney", "dialysis"),
     ("enalapril", "lisinopril", "captopril", "ramipril", "losartan"), "warn",
     "ACE inhibitors and ARBs need renal function watched closely."),

    # ---- cardiac --------------------------------------------------------
    (("cardiac", "heart failure", "heart"),
     ("ibuprofen", "diclofenac", "naproxen", "indomethacin", "meloxicam"),
     "warn",
     "NSAIDs cause fluid retention and can worsen heart failure."),
    (("cardiac", "heart failure"), ("verapamil", "diltiazem"), "warn",
     "Rate-limiting calcium channel blockers are avoided in heart failure."),
    (("cardiac", "heart", "angina"), ("salbutamol", "pseudoephedrine"), "warn",
     "Sympathomimetics raise heart rate and can provoke angina."),

    # ---- epilepsy -------------------------------------------------------
    (("epilep", "seizure", "fits"),
     ("tramadol", "ciprofloxacin", "levofloxacin", "norfloxacin",
      "bupropion"), "warn",
     "Lowers the seizure threshold. Check with the prescriber before "
     "handing over."),

    # ---- glaucoma -------------------------------------------------------
    (("glaucoma",),
     ("amitriptyline", "hyoscine", "atropine", "oxybutynin",
      "chlorpheniramine", "promethazine"), "warn",
     "Anticholinergics can precipitate acute angle-closure glaucoma."),

    # ---- diabetes -------------------------------------------------------
    (("diabet",),
     ("prednisolone", "prednisone", "dexamethasone", "hydrocortisone"),
     "warn",
     "Corticosteroids raise blood glucose. The patient should test more "
     "often while on this course."),
    (("diabet",),
     ("propranolol", "atenolol", "bisoprolol", "carvedilol"), "warn",
     "Beta-blockers mask the warning signs of hypoglycaemia."),

    # ---- peptic / arthritis on long-term NSAIDs --------------------------
    (("ulcer", "peptic", "gastritis"),
     ("ibuprofen", "diclofenac", "naproxen", "aspirin", "indomethacin",
      "prednisolone", "prednisone"), "stop",
     "NSAIDs and steroids cause gastrointestinal bleeding, and the risk is "
     "much higher with a history of ulcer."),

    # ---- liver ----------------------------------------------------------
    (("liver", "hepat", "cirrhosis"),
     ("methotrexate", "simvastatin", "atorvastatin", "isoniazid"), "warn",
     "Hepatotoxic. Liver function should be monitored."),
    (("liver", "hepat", "cirrhosis"), ("paracetamol", "acetaminophen"), "warn",
     "The maximum daily paracetamol dose is lower in liver disease."),

    # ---- thyroid --------------------------------------------------------
    (("thyroid",), ("amiodarone",), "warn",
     "Amiodarone causes both hyper- and hypothyroidism and needs thyroid "
     "function monitored."),
]

#: How many (condition, medicine) pairs this holds. Published in every
#: response, because a checker that says "nothing found" without saying what it
#: looked for is teaching the reader that clear means safe.
def coverage() -> dict:
    pairs = sum(len(ingredients) for _, ingredients, _, _ in RULES)
    conditions = {c[0] for c, _, _, _ in RULES}
    return {
        "rules": len(RULES),
        "pairs": pairs,
        "conditions": len(conditions),
        "note": (f"{pairs} medicine-and-condition pairs across {len(conditions)} "
                 f"conditions. This is a named list, not a clinical database — "
                 f"a clear result means nothing on the list matched, which is "
                 f"not the same as safe."),
    }


def _words(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def _hit(haystack: str, needle: str) -> bool:
    """Whole-word, so a short fragment cannot fire inside an unrelated name."""
    return re.search(r"\b" + re.escape(needle), haystack) is not None


def _recorded_conditions(db: Session, patient: Patient) -> list[tuple[str, str]]:
    """The patient's conditions, each with the words that stand for it.

    Expanded through the same vocabulary the picker writes from, so "Cardiac
    disease" is found by a rule that keys on "heart" — the pharmacist chose the
    catalogue's wording and the rule should not have to guess which of the
    synonyms they landed on.
    """
    raw = [c.strip() for c in
           (patient.chronic_conditions or "").replace(";", ",").split(",")
           if c.strip()]
    if not raw:
        return []

    terms = {t.name.lower(): t for t in
             db.query(ClinicalTerm).filter(ClinicalTerm.kind == "condition").all()}
    out = []
    for entry in raw:
        term = terms.get(entry.lower())
        words = entry.lower()
        if term and term.synonyms:
            words = words + " " + term.synonyms.lower().replace(",", " ")
        out.append((entry, _words(words)))
    return out


def check(db: Session, patient: Patient | None,
          products: list[Product]) -> list[dict]:
    """Warnings raised by what this patient is recorded as living with.

    Shaped like the allergy warnings beside it — same keys, same negative id
    for a derived finding — so the dispensing screen renders them together
    without knowing there are two sources.
    """
    if patient is None or not products:
        return []
    conditions = _recorded_conditions(db, patient)
    if not conditions:
        return []

    seen: set[tuple[int, str]] = set()
    out: list[dict] = []
    for product in products:
        haystack = _words(f"{product.name} {product.active_ingredient or ''}")
        for recorded, condition_words in conditions:
            for cond_needles, ingredients, severity, why in RULES:
                if not any(_hit(condition_words, c) for c in cond_needles):
                    continue
                match = next((i for i in ingredients if _hit(haystack, i)), None)
                if not match:
                    continue
                key = (product.id, recorded)
                if key in seen:
                    # One warning per medicine per condition. Two rules that
                    # both fire — an NSAID in a patient with both renal disease
                    # and asthma — are two warnings, which is right; the same
                    # rule firing on name and on ingredient is one.
                    continue
                seen.add(key)
                out.append({
                    "id": -(product.id * 1000 + len(out) + 1),
                    "scope": "patient", "target_id": patient.id,
                    "derived": True,
                    "severity": severity,
                    "category": "condition",
                    "body": (
                        f"{patient.first_name} {patient.last_name} is recorded "
                        f"as {recorded.lower()}. {product.name} contains "
                        f"{match}. {why}"),
                    "source": "recorded conditions",
                    # Never blocks on its own. A pregnancy warning on something
                    # an obstetrician deliberately continued is a conversation,
                    # and software that refuses what a specialist prescribed is
                    # worked around inside a week — after which it warns about
                    # nothing at all.
                    "blocking": False,
                    "created_at": None, "created_by": "",
                })
                break
    return out
