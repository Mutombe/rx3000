"""Drug interaction checking, and an honest account of what it does not cover.

The hard problem here is not the check. It is that **a partial interaction list
is more dangerous than no list at all** if the screen lets anyone read "nothing
found" as "this is safe". A pharmacist who has been told twice that the system
checks interactions will, on the third occasion, trust it — and the pair it does
not hold will go out.

So the design is:

* Every answer carries its **coverage**: how many pairs were consulted, and a
  statement that this is a small set of well-established interactions and not a
  clinical database.
* The wording of a clean result is never "no interactions". It is "none of the
  pairs this system holds", which is a different and true sentence.
* `SOURCE` is pluggable. When a licensed database is procured, one class is
  implemented and the coverage statement changes with it — the callers, the
  screen and the dispensing guard do not.

The seeded pairs below are textbook, high-severity, and chosen because they are
the ones a pharmacist would be embarrassed to miss — not because they are
sufficient. They are a floor, not a service.
"""
from dataclasses import dataclass

SEVERITIES = ("major", "moderate", "minor")


@dataclass(frozen=True)
class Interaction:
    a: str
    b: str
    severity: str
    effect: str
    action: str


# Established, high-severity pairs. Matched on active ingredient, lower-cased.
KNOWN: list[Interaction] = [
    Interaction("warfarin", "aspirin", "major",
                "Both impair clotting; together the bleeding risk rises sharply.",
                "Confirm the prescriber intended both. Check the last INR."),
    Interaction("warfarin", "ibuprofen", "major",
                "NSAIDs raise bleeding risk and can displace warfarin.",
                "Suggest paracetamol instead unless the prescriber says otherwise."),
    Interaction("warfarin", "miconazole", "major",
                "Even topical miconazole can raise INR substantially.",
                "Flag to the prescriber; INR monitoring is needed."),
    Interaction("methotrexate", "trimethoprim", "major",
                "Both are folate antagonists; together they risk marrow suppression.",
                "Do not dispense together without prescriber confirmation."),
    Interaction("simvastatin", "clarithromycin", "major",
                "Clarithromycin raises simvastatin levels; rhabdomyolysis risk.",
                "Statin is usually withheld for the course of the antibiotic."),
    Interaction("ace inhibitor", "spironolactone", "major",
                "Both retain potassium; hyperkalaemia risk.",
                "Check recent potassium before supplying."),
    Interaction("metformin", "contrast", "major",
                "Risk of lactic acidosis around iodinated contrast imaging.",
                "Confirm timing with the prescriber."),
    Interaction("tramadol", "fluoxetine", "major",
                "Both raise serotonin; risk of serotonin syndrome and seizures.",
                "Flag to the prescriber before supplying."),
    Interaction("tramadol", "sertraline", "major",
                "Both raise serotonin; risk of serotonin syndrome.",
                "Flag to the prescriber before supplying."),
    Interaction("amoxicillin", "methotrexate", "moderate",
                "Penicillins can reduce methotrexate clearance.",
                "Watch for methotrexate toxicity; mention it to the patient."),
    Interaction("ciprofloxacin", "theophylline", "major",
                "Ciprofloxacin raises theophylline levels; seizure risk.",
                "Prescriber should adjust the dose or choose another antibiotic."),
    Interaction("digoxin", "furosemide", "moderate",
                "Diuretic-induced low potassium increases digoxin toxicity.",
                "Check potassium; counsel on nausea and visual disturbance."),
]

COVERAGE_NOTE = (
    "Checked against {n} well-established interaction pairs held locally. This "
    "is not a clinical interaction database: a clear result means none of the "
    "pairs this system holds were found, not that the combination is safe. "
    "Clinical judgement and a licensed reference remain necessary."
)


def _terms(text: str) -> list[str]:
    return [t for t in (text or "").lower().replace("/", " ").split() if len(t) > 3]


def _matches(ingredient: str, term: str) -> bool:
    """Substring both ways: "amoxicillin/clavulanate" must match "amoxicillin",
    and a product named "Warfarin Sodium" must match "warfarin"."""
    ingredient = (ingredient or "").lower()
    return bool(ingredient) and (term in ingredient or ingredient in term)


def check(items: list[dict]) -> dict:
    """Check a basket. `items` are {name, active_ingredient} dicts.

    Also flags a duplicated active ingredient, which is not an interaction but is
    the same mistake with a worse outcome — two products, one drug, double dose.
    """
    profiles = []
    for item in items:
        # Interaction matching may use the name as a fallback — many products
        # carry the drug in the name and no ingredient on file. Duplicate
        # detection may NOT: two products from one brand share words in their
        # names and share no drug at all, and a safety check that cries wolf is
        # a safety check people learn to dismiss.
        ingredient = (item.get("active_ingredient") or "").lower()
        profiles.append({
            "label": item.get("name", ""),
            "text": f"{ingredient} {item.get('name', '')}".lower(),
            "ingredient": ingredient,
            "id": item.get("product_id"),
        })

    found = []
    for i, first in enumerate(profiles):
        for second in profiles[i + 1:]:
            for pair in KNOWN:
                hit_a = _matches(first["text"], pair.a) and _matches(second["text"], pair.b)
                hit_b = _matches(first["text"], pair.b) and _matches(second["text"], pair.a)
                if hit_a or hit_b:
                    found.append({
                        "severity": pair.severity,
                        "between": [first["label"], second["label"]],
                        "effect": pair.effect,
                        "action": pair.action,
                    })

    # Duplicate therapy: two products carrying the same ingredient.
    duplicates = []
    for i, first in enumerate(profiles):
        for second in profiles[i + 1:]:
            # Only the recorded ingredient counts here, never the name.
            if not (first["ingredient"] and second["ingredient"]):
                continue
            shared = set(_terms(first["ingredient"])) & set(_terms(second["ingredient"]))
            if shared:
                duplicates.append({
                    "severity": "major",
                    "between": [first["label"], second["label"]],
                    "effect": f"Both appear to contain {', '.join(sorted(shared))} — "
                              "the patient would take a double dose.",
                    "action": "Confirm this is intended before supplying both.",
                })

    all_found = found + duplicates
    order = {"major": 0, "moderate": 1, "minor": 2}
    all_found.sort(key=lambda f: order.get(f["severity"], 9))
    return {
        "checked": len(profiles),
        "pairs_consulted": len(KNOWN),
        "found": all_found,
        "major": sum(1 for f in all_found if f["severity"] == "major"),
        # Never "no interactions" — a different and untrue sentence.
        "summary": (f"{len(all_found)} flagged" if all_found else
                    "None of the pairs this system holds were found"),
        "coverage": COVERAGE_NOTE.format(n=len(KNOWN)),
        "is_clinical_database": False,
    }
