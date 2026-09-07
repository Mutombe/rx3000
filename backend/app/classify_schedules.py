"""Give an imported catalogue its MCAZ schedules.

    python -m app.classify_schedules --pharmacy 5
    python -m app.classify_schedules --pharmacy 5 --dry-run

WHY THIS EXISTS

A catalogue imported from another system arrives with product names, codes and
prices, and no schedule — because the schedule is a regulatory classification
the old system kept somewhere else, or not at all. Every product then sits at
S0, and S0 is not a neutral default: it says the item may be sold off a shelf
by anybody. A pharmacy in that state cannot dispense at all, because the
dispensary filters the prescription route on S3 and S4 and finds nothing, and
meanwhile its controlled drugs are classified as general sale.

That is what CareXpress looked like: 16,407 products, all S0, a dead dispensary
and no register.

THE RULE THIS FOLLOWS, AND THE ONE IT REFUSES

It only ever makes a product MORE restricted. Never less.

That single property is what makes it safe to run without a pharmacist reading
every line. Marking a simple analgesic as prescription-only is an
inconvenience — somebody has to write a script for something that could have
been sold over the counter. Marking a benzodiazepine as general sale is a
criminal offence. The asymmetry is total, so the tool only moves one way.

Which is why nothing here classifies anything DOWN to S1 or S2, even where the
name makes it obvious. Deciding that paracetamol may be sold off a shelf is a
pharmacist's call, and it is the call that carries the risk.

WHAT IT ACTUALLY KNOWS

Three things, in order of confidence:

  the category the import did carry — front_shop is general merchandise and
    stays at S0, which is correct and is most of any real catalogue;
  a list of substances that are scheduled 5 or 6 in Zimbabwe, matched on the
    product name;
  a list of classes that are unambiguously prescription-only — antibiotics,
    antiretrovirals, antipsychotics, insulins, anticoagulants — which get S4
    rather than the S3 default. Both are prescription-only, so this is
    precision rather than permission.

Everything else catalogued as a medicine gets S3 and waits for review.

WHAT IT IS NOT

A classification. It is a containment, and the report says how much of the
catalogue is sitting on the default so somebody can see the size of the job
that remains. The right end state is the pharmacy's own schedule list loaded
from a file, which replaces all of this in one pass.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from .database import SessionLocal

#: Scheduled 5 or 6 in Zimbabwe: the opioids, the benzodiazepines, the
#: barbiturates and the stimulants. Dispensing one requires the controlled
#: register and a pharmacist's signature, so leaving one below S5 is the
#: failure this list exists to prevent.
#:
#: Matched on the product name. That finds the obvious ones and cannot promise
#: it found them all, which is why the report says how many it moved rather
#: than declaring the catalogue done.
CONTROLLED = [
    # opioids
    "morphine", "pethidine", "fentanyl", "oxycodone", "hydrocodone",
    "methadone", "codeine", "dihydrocodeine", "tramadol", "tilidine",
    "pentazocine", "buprenorphine", "tapentadol", "papaveretum", "opium",
    # benzodiazepines and the z-drugs
    "diazepam", "lorazepam", "clonazepam", "alprazolam", "midazolam",
    "nitrazepam", "temazepam", "bromazepam", "oxazepam", "flurazepam",
    "chlordiazepoxide", "zolpidem", "zopiclone", "zaleplon",
    # barbiturates
    "phenobarbit", "barbiton", "amylobarb", "butabarb", "secobarb",
    # stimulants and others
    "methylphenidate", "amphetamine", "dexamfetamine", "modafinil",
    "ketamine", "gamma-hydroxy", "cannabis", "dronabinol",
]

#: Classes that are prescription-only beyond argument. These take S4 instead of
#: the S3 default — both require a script, so this is accuracy and not a
#: loosening of anything.
PRESCRIPTION_ONLY = [
    # antibiotics and antibacterials
    "amoxi", "ampicillin", "penicillin", "flucloxacillin", "cloxacillin",
    "cephalexin", "cefixime", "ceftriaxone", "cefuroxime", "cefotaxime",
    "azithro", "clarithro", "erythro", "doxycycl", "tetracycl",
    "ciproflox", "levoflox", "norflox", "ofloxacin", "moxiflox",
    "gentamicin", "amikacin", "streptomycin", "vancomycin", "clindamycin",
    "metronidaz", "tinidaz", "nitrofurant", "trimethoprim", "sulfamethox",
    "co-trimoxazole", "cotrimoxazole", "chloramphenicol", "rifampic",
    "isoniazid", "pyrazinamide", "ethambutol", "linezolid", "meropenem",
    # antiretrovirals and antivirals
    "tenofovir", "lamivudine", "zidovudine", "efavirenz", "nevirapine",
    "dolutegravir", "abacavir", "atazanavir", "lopinavir", "ritonavir",
    "emtricitabine", "aciclovir", "acyclovir", "valacyclovir",
    # antipsychotics, antidepressants, anticonvulsants
    "haloperidol", "chlorpromazine", "risperidone", "olanzapine",
    "quetiapine", "clozapine", "fluphenazine", "amitriptyline",
    "fluoxetine", "sertraline", "citalopram", "escitalopram", "venlafaxine",
    "carbamazepine", "valproate", "valproic", "phenytoin", "lamotrigine",
    "levetiracetam", "lithium",
    # cardiovascular, endocrine, and other chronic prescription therapy
    "insulin", "metformin", "gliclazide", "glibenclamide", "glimepiride",
    "warfarin", "heparin", "enoxaparin", "clopidogrel", "rivaroxaban",
    "amlodipine", "enalapril", "lisinopril", "losartan", "atenolol",
    "bisoprolol", "carvedilol", "furosemide", "spironolactone",
    "atorvastatin", "simvastatin", "digoxin", "levothyroxine",
    "carbimazole", "prednisolone", "dexamethasone", "hydrocortisone",
    "salbutamol", "beclomethasone", "budesonide", "montelukast",
    "tamoxifen", "methotrexate", "azathioprine", "ciclosporin",
]

#: What an unrecognised medicine gets. Prescription-only: it cannot be sold
#: without a script, which is the containing answer while it waits for review.
DEFAULT_MEDICINE = 3


def _like_clause(prefix: str, terms: list[str]) -> tuple[str, dict]:
    where = " or ".join(f"lower(name) like :{prefix}{i}"
                        for i in range(len(terms)))
    params = {f"{prefix}{i}": f"%{t}%" for i, t in enumerate(terms)}
    return where, params


def classify(pharmacy_id: int, *, dry_run: bool = False) -> dict[str, int]:
    db = SessionLocal()
    done: dict[str, int] = {}
    try:
        conn = db.connection()

        def spread() -> dict[int, int]:
            return dict(conn.execute(text(
                "select coalesce(schedule,0), count(*) from products "
                "where pharmacy_id = :p group by 1"), {"p": pharmacy_id}
            ).fetchall())

        before = spread()
        print(f"  before: " + ", ".join(
            f"S{k} {v:,}" for k, v in sorted(before.items())))

        # 1. Everything catalogued as a medicine becomes prescription-only.
        #    Guarded on `< 3` so a schedule somebody has already set by hand is
        #    never overwritten downward.
        done["medicines to S3"] = conn.execute(text("""
            update products set schedule = :s
            where pharmacy_id = :p and category = 'medicine'
              and coalesce(schedule, 0) < :s
        """), {"p": pharmacy_id, "s": DEFAULT_MEDICINE}).rowcount

        # 2. The classes that are prescription-only beyond argument take S4.
        where, params = _like_clause("rx", PRESCRIPTION_ONLY)
        params.update({"p": pharmacy_id})
        done["identified as S4"] = conn.execute(text(f"""
            update products set schedule = 4
            where pharmacy_id = :p and category = 'medicine'
              and coalesce(schedule, 0) < 4 and ({where})
        """), params).rowcount

        # 3. And the controlled ones go to S5, which forces the register.
        where, params = _like_clause("c", CONTROLLED)
        params.update({"p": pharmacy_id})
        done["controlled to S5"] = conn.execute(text(f"""
            update products set schedule = 5
            where pharmacy_id = :p and category = 'medicine'
              and coalesce(schedule, 0) < 5 and ({where})
        """), params).rowcount

        after = spread()
        if dry_run:
            db.rollback()
            print("  (dry run: nothing was written)")
        else:
            db.commit()

        print(f"  after:  " + ", ".join(
            f"S{k} {v:,}" for k, v in sorted(after.items())))
        return done
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pharmacy", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    done = classify(args.pharmacy, dry_run=args.dry_run)
    print()
    for what, n in done.items():
        print(f"    {n:>7,}  {what}")

    print("\n  Every change is to a MORE restrictive schedule. Nothing in this")
    print("  catalogue is easier to dispense than it was before this ran.")
    print("\n  This is a containment, not a classification. The S3 rows are")
    print("  medicines nothing recognised: some are genuinely S1 or S2 and are")
    print("  now needlessly behind a script, and only a pharmacist can move")
    print("  them down. Load the pharmacy's own schedule list when you have it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
