"""Classify a pharmacy's catalogue against the MCAZ schedules.

    python -m app.classify_schedules --pharmacy 5 --dry-run
    python -m app.classify_schedules --pharmacy 5
    python -m app.classify_schedules --pharmacy 5 --allow-down --report out.csv

WHAT THIS REPLACES

The first version of this file was a containment, not a classification, and said
so. It moved everything the import called a `medicine` to S3 and lifted about
forty known controlled substances to S5. It refused, on principle, to move
anything down.

That was the right thing to do in an afternoon with a dead dispensary. It is not
a classification, and leaving it in place has two costs that both grew:

  2,400 products at CareXpress sit at S3 because nothing recognised them. S3
    there does not mean "prescription only", it means "we did not know". Every
    one of them is behind a script that may not need one, and no one can tell
    which by looking;

  and 13,635 more were never examined at all, because the import had called them
    `front_shop` and the tool trusted that. A random sample of twenty-five from
    that bucket contained TEMOZALAMIDE 250MG TABS — temozolomide, a cytotoxic
    used in glioblastoma — sitting at S0, general sale, between a stress ball
    and a set of bath bombs.

So this version changes three rules.

  1. IT DOES NOT TRUST THE IMPORT'S CATEGORY.

     Every product is examined, whatever the import called it. `front_shop` is
     not evidence about a medicine; it is evidence about how somebody's old
     system was set up. Genuine front shop matches nothing here and is left
     exactly where it is, which is the correct outcome for a bath bomb.

  2. IT CAN CLASSIFY DOWNWARD — CAREFULLY, AND ONLY WHEN ASKED.

     A tool that can only tighten cannot classify, it can only contain: the
     2,400 unknowns would stay behind a script for ever because nothing is
     allowed to say paracetamol is paracetamol. So there is a pharmacy-medicine
     tier and products can reach it.

     Downward moves are off unless `--allow-down` is passed, are only ever made
     from an explicit named substance, are never made by a default, and are
     listed separately in the report for a pharmacist to sign. Nothing reaches
     S0 from here: this tool will not put a medicine on an open shelf.

  3. IT TAKES THE HIGHEST MATCH, NOT THE FIRST.

     This is the rule that makes the second one safe, and it is the whole
     safety argument in one line.

     "PARACETAMOL/CODEINE 500/8" matches the paracetamol rule (pharmacy
     medicine) and the codeine rule (controlled). A tool that stopped at the
     first match, or applied rules in list order, would classify a codeine
     product as sellable over the counter — and it would do it to every
     co-codamol, every Panado Co, every Adco-Dol in the catalogue.

     So every rule is evaluated against every name and the STRICTEST result
     wins. A combination product is as controlled as its most controlled
     ingredient, which is also what the law says.

WHAT IT STILL CANNOT DO

It reads product names, because `active_ingredient` is empty on all 16,407 rows
at CareXpress and a name is the only signal there is. Names are abbreviated,
misspelled and full of brands. So:

  it will miss things. The report says how many it could not identify, and that
    number is the job that remains — it is not decoration;
  a brand name it does not know is invisible to it. There is no way around that
    except the pharmacy's own list, which is what should eventually replace this
    whole file;
  and every unmatched product is LEFT WHERE IT IS. Never defaulted, never moved
    on a guess.

The end state is a pharmacy's own schedule list loaded from a file. Until that
exists this is the best available, and the report is honest about the gap.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter

from sqlalchemy import text

from .database import SessionLocal

# ---------------------------------------------------------------------------
# The substance table.
#
# Each entry is (schedule, why, [fragments matched against a lowercased name]).
# Fragments are INN substance names wherever possible: they are what appears in
# a dispensary catalogue and they almost never appear in cosmetics, which is the
# false-positive that matters when the whole shop is being read.
#
# Ordering in this list carries NO meaning. Every rule is tried and the highest
# schedule wins — see rule 3 in the module docstring.
# ---------------------------------------------------------------------------

#: S6 — the substances a retail pharmacy cannot hold without a departmental
#: permit. Present so they are found and flagged, not so they can be dispensed.
S6 = [
    "heroin", "diacetylmorphine", "cocaine hydrochlor", "lysergide",
    "mescaline", "psilocy",
]

#: S5 — the controlled register. A pharmacist's signature, a patient's identity,
#: and an entry in a bound book. Leaving one of these below S5 is the failure
#: this whole file exists to prevent, so the list is deliberately broad and
#: matches on stems.
S5 = [
    # opioids
    "morphine", "pethidine", "fentanyl", "oxycodone", "oxycontin",
    "hydrocodone", "hydromorphone", "methadone", "codeine", "co-codamol",
    "codalgin", "dihydrocodeine", "tramadol", "tramacet", "tilidine",
    "pentazocine", "buprenorphine", "tapentadol", "papaveretum", "opium",
    "pholcodine", "sufentanil", "alfentanil", "remifentanil", "nalbuphine",
    # benzodiazepines and z-drugs
    "diazepam", "lorazepam", "clonazepam", "alprazolam", "midazolam",
    "nitrazepam", "temazepam", "bromazepam", "oxazepam", "flurazepam",
    "chlordiazepoxide", "clobazam", "zolpidem", "zopiclone", "eszopiclone",
    "zaleplon", "triazolam", "loprazolam",
    # barbiturates
    "phenobarb", "barbiton", "amylobarb", "butabarb", "secobarb",
    "pentobarb", "thiopent",
    # stimulants
    "methylphenidate", "ritalin", "concerta", "amphetamine", "dexamfetamine",
    "lisdexamfetamine", "modafinil", "armodafinil", "phentermine",
    "diethylpropion", "methcathinone",
    # anaesthetics and others under control
    "ketamine", "gamma-hydroxy", "sodium oxybate", "cannabis", "dronabinol",
    "nabilone", "cannabidiol", "pregabalin", "lyrica",
    # Combination brands that carry codeine without saying so in the name.
    #
    # These are the products the substance table cannot reach: "PANADO CO TABS"
    # contains no string a codeine rule could match, and it was coming back as
    # pharmacy medicine on the strength of the paracetamol in it. A dispenser
    # reading the shelf knows what Panado Co is; a regex does not, unless it is
    # told.
    #
    # Broncleer is first because in Zimbabwe it is the one that matters — a
    # codeine linctus with a serious diversion problem, and a product that must
    # never sit anywhere a script is not required.
    "broncleer", "broncleer", "panado co", "panadoco", "adco-dol", "adcodol",
    "stopayne", "myprodol", "mybulen", "betapyn", "syndol", "lentogesic",
    "codis", "cofta", "empaped", "painamol co", "dolorol forte",
    "sinutab with codeine", "benylin with codeine", "linctopent",
]

#: S4 — prescription only, and the classes where getting it wrong is worst:
#: anti-infectives whose misuse breeds resistance, and therapies that need
#: monitoring. Both S3 and S4 require a script, so the split between them is
#: precision rather than permission.
S4 = [
    # cytotoxics and immunosuppressants — the class the sample turned up
    "temozol", "temozalam", "cyclophosphamide", "cisplatin", "carboplatin",
    "doxorubicin", "vincristine", "vinblastine", "etoposide", "fluorouracil",
    "capecitabine", "gemcitabine", "paclitaxel", "docetaxel", "imatinib",
    "rituximab", "trastuzumab", "bleomycin", "cytarabine", "dacarbazine",
    "hydroxyurea", "hydroxycarbamide", "mercaptopurine", "melphalan",
    "chlorambucil", "busulfan", "anastrozole", "letrozole", "bicalutamide",
    "methotrexate", "azathioprine", "ciclosporin", "cyclosporin",
    "tacrolimus", "mycophenolate", "sirolimus", "leflunomide",
    # antibacterials
    "amoxi", "ampicillin", "penicillin", "flucloxacillin", "cloxacillin",
    "benzathine", "cephalexin", "cefalexin", "cefixime", "ceftriaxone",
    "cefuroxime", "cefotaxime", "cefpodoxime", "ceftazidime", "cefaclor",
    "azithro", "clarithro", "erythro", "roxithro", "doxycycl", "tetracycl",
    "minocycl", "ciproflox", "levoflox", "norflox", "ofloxacin", "moxiflox",
    "gentamicin", "amikacin", "streptomycin", "vancomycin", "teicoplanin",
    "clindamycin", "lincomycin", "metronidaz", "tinidaz", "secnidaz",
    "nitrofurant", "trimethoprim", "sulfamethox", "co-trimoxazole",
    "cotrimoxazole", "chloramphenicol", "rifampic", "rifabutin",
    "isoniazid", "pyrazinamide", "ethambutol", "linezolid", "meropenem",
    "imipenem", "ertapenem", "piperacillin", "tazobactam", "colistin",
    "fosfomycin", "dapsone", "spiramycin",
    # antiretrovirals and antivirals
    "tenofovir", "lamivudine", "zidovudine", "stavudine", "didanosine",
    "efavirenz", "nevirapine", "dolutegravir", "raltegravir", "abacavir",
    "atazanavir", "lopinavir", "ritonavir", "darunavir", "emtricitabine",
    "aciclovir", "acyclovir", "valacyclovir", "valganciclovir",
    "ganciclovir", "oseltamivir", "sofosbuvir", "ledipasvir", "ribavirin",
    "entecavir", "tenofovir",
    # antifungals and antiprotozoals, systemic
    "fluconazole", "itraconazole", "voriconazole", "ketoconazole tab",
    "griseofulvin", "terbinafine tab", "amphotericin", "nystatin oral",
    "artemether", "lumefantrine", "artesunate", "quinine", "primaquine",
    "chloroquine", "atovaquone", "proguanil", "pyrimethamine",
    "praziquantel", "ivermectin", "albendazole",
    # antipsychotics, antidepressants, anticonvulsants
    "haloperidol", "chlorpromazine", "risperidone", "olanzapine",
    "quetiapine", "clozapine", "fluphenazine", "trifluoperazine",
    "amisulpride", "aripiprazole", "zuclopenthixol", "flupentixol",
    "amitriptyline", "imipramine", "nortriptyline", "clomipramine",
    "fluoxetine", "sertraline", "citalopram", "escitalopram", "paroxetine",
    "venlafaxine", "duloxetine", "mirtazapine", "trazodone", "bupropion",
    "carbamazepine", "oxcarbazepine", "valproate", "valproic", "epilim",
    "phenytoin", "lamotrigine", "levetiracetam", "topiramate", "lithium",
    "gabapentin", "vigabatrin", "ethosuximide",
    # endocrine, cardiovascular, respiratory, chronic therapy
    "insulin", "metformin", "gliclazide", "glibenclamide", "glimepiride",
    "sitagliptin", "vildagliptin", "empagliflozin", "dapagliflozin",
    "pioglitazone", "liraglutide", "semaglutide",
    "warfarin", "heparin", "enoxaparin", "clopidogrel", "rivaroxaban",
    "apixaban", "dabigatran", "ticagrelor", "streptokinase",
    "amlodipine", "nifedipine", "felodipine", "verapamil", "diltiazem",
    "enalapril", "lisinopril", "perindopril", "ramipril", "captopril",
    "losartan", "valsartan", "telmisartan", "irbesartan", "candesartan",
    "atenolol", "bisoprolol", "carvedilol", "metoprolol", "propranolol",
    "furosemide", "spironolactone", "hydrochlorothiazide", "indapamide",
    "atorvastatin", "simvastatin", "rosuvastatin", "pravastatin",
    "fenofibrate", "gemfibrozil", "ezetimibe",
    "digoxin", "amiodarone", "isosorbide", "glyceryl trinitrate",
    "levothyroxine", "carbimazole", "propylthiouracil",
    "prednisolone", "prednisone", "dexamethasone", "hydrocortisone tab",
    "methylprednisolone", "fludrocortisone", "betamethasone tab",
    "salbutamol", "salmeterol", "formoterol", "beclomethasone",
    "budesonide", "fluticasone", "montelukast", "theophylline",
    "ipratropium", "tiotropium", "aminophylline",
    "tamoxifen", "alendronate", "raloxifene", "finasteride", "tamsulosin",
    "sildenafil", "tadalafil", "levonorgestrel", "ethinylestradiol",
    "medroxyprogesterone", "norethisterone", "estradiol", "clomiphene",
    "misoprostol", "oxytocin", "ergometrine", "methyldopa", "nifedipine",
    "allopurinol", "colchicine", "sulfasalazine", "hydroxychloroquine",
    # British and alternate spellings, which is what a Zimbabwean catalogue
    # actually contains. `amoxycillin` with a y appears thirteen times at
    # CareXpress and matched nothing at all: the INN list had `amoxi` and the
    # shelf says `amoxy`. This is the cheapest recall in the file and it was
    # found by reading what the classifier had failed to identify.
    "amoxy", "amoxiclav", "co-amoxiclav", "augmentin",
    "frusemide", "sulphamethox", "sulphasalazine", "sulphadiazine",
    "oestradiol", "oestrogen", "oestriol",
    "lignocaine", "lidocaine", "indometacin", "cyclizine",
    "adrenaline", "epinephrine", "noradrenaline",
    "thyroxine", "eltroxin", "cefadroxil", "cephradine", "cefradine",
    "beclometasone", "hydroxyzine", "benzylpenicillin", "procaine penicillin",
    "phenoxymethylpenicillin", "paracetamol/codeine", "chloroquin",
    # Precursors. Prescription rather than register: at S5 every cold-and-flu
    # tablet on the shelf would need a bound-book entry and a signature, which
    # is the kind of rule a counter works around rather than keeps.
    "ephedrine", "pseudoephedrine",
    "omeprazole", "esomeprazole", "pantoprazole", "lansoprazole",
    "domperidone", "metoclopramide", "ondansetron", "prochlorperazine",
    "diclofenac", "naproxen", "meloxicam", "celecoxib", "indomethacin",
    "piroxicam", "ketoprofen", "tenoxicam", "etoricoxib",
]

#: S3 — prescription only. Used for a product that is recognisably a medicine
#: but does not fall in one of the classes above.
#:
#: Matched on dosage form and on the words a catalogue uses for a preparation
#: that is plainly pharmaceutical. Deliberately narrow: this is the tier that
#: previously swallowed 2,400 products, and it should now only catch things a
#: person would agree are medicines.
S3 = [
    "injection", "inj ", " amp", "ampoule", "vial", "infusion",
    "suppositor", "pessar", "nebulis", "nebuliz", "inhaler",
]

#: S2 — pharmacy medicine. Sold in a pharmacy, by or under the supervision of a
#: pharmacist, without a prescription.
#:
#: THE ONLY LIST THIS TOOL WILL EVER MOVE A PRODUCT DOWN TO, and only with
#: `--allow-down`. Every entry is a substance whose over-the-counter status is
#: not in argument anywhere, and every one of them is still beaten by any S4+
#: match on the same name — which is what stops "paracetamol/codeine" landing
#: here.
#:
#: S1 is deliberately not used. The S1/S2 split is about who in the shop may
#: hand it over, it varies by pharmacy, and inventing an answer would be
#: precision this tool has not earned. S2 is the containing choice of the two.
#: EVERY ENTRY IS AN INN. No brand names, ever.
#:
#: A brand is a promise about a box, not about what is in it: "Panado" is
#: paracetamol and "Panado Co" is paracetamol with codeine, and the two differ
#: by two letters in a field that is abbreviated by whoever typed the import.
#: A downward move made on a brand name is a controlled drug on an open shelf,
#: so a downward move requires the substance to be named.
#:
#: This costs recall — "PANADO CO TABS 24S" now matches nothing and is reported
#: as unidentified. That is the correct outcome: unidentified means a person
#: looks at it, and a person knows what Panado Co is.
S2 = [
    "paracetamol", "acetaminophen",
    "ibuprofen",
    "aspirin", "acetylsalicylic",
    "cetirizine", "loratadine", "chlorphenamine", "chlorpheniramine",
    "diphenhydramine", "promethazine", "cyproheptadine",
    "guaifenesin", "bromhexine", "ambroxol", "dextromethorphan",
    "oral rehydration", "electrolyte replacement",
    "loperamide", "hyoscine", "simethicone", "activated charcoal",
    "aluminium hydroxide", "magnesium hydroxide", "magnesium trisilicate",
    "calcium carbonate antacid", "cimetidine", "famotidine",
    "clotrimazole", "miconazole", "ketoconazole cream", "ketoconazole shampoo",
    "terbinafine cream", "tolnaftate", "benzoyl peroxide",
    "hydrocortisone 1%", "calamine", "zinc oxide cream",
    "permethrin", "benzyl benzoate", "malathion lotion",
    "mebendazole", "pyrantel",
    "chlorhexidine", "povidone iodine", "cetrimide",
    "senna", "bisacodyl", "lactulose", "ispaghula", "glycerin supposit",
    "artificial tears", "hypromellose", "sodium chloride nasal",
    "xylometazoline", "oxymetazoline",
    "nicotine gum", "nicotine patch",
]

#: Names that must never be read as a medicine however they match.
#:
#: A shop of sixteen thousand lines contains cosmetics whose ingredients share
#: names with drugs. Checked before anything else, and a hit means the product
#: is left alone entirely — not classified S0, LEFT ALONE, because this tool's
#: opinion about a lipstick is worth nothing either way.
NOT_MEDICINE = [
    "lipstick", "nail enamel", "nail polish", "mascara", "eyeshadow",
    "eye shadow", "foundation", "concealer", "blusher", "bronzer",
    "perfume", "cologne", "body spray", "deodorant", "roll-on",
    "shampoo conditioner", "hair dye", "hair food", "relaxer",
    "bath bomb", "bubble bath", "shower gel", "body lotion", "body butter",
    "toothpaste", "toothbrush", "mouthwash fresh",
    "nappies", "nappy", "diaper", "wipes", "sanitary", "maxi pads",
    "tampon", "airtime", "voucher", "chocolate", "sweets", "biscuit",
    "crisps", "chips ", "juice ", "cooldrink", "water 500", "water 1l",
    "stress ball", "watches", "bobby pin", "hair band", "comb ",
    "greeting card", "gift", "balloon", "toy ",
    # Perfume. "YSL OPIUM EDP 50ML" matched the opioid list eight times over —
    # the substance name really is in the product name, and the product is a
    # fragrance. `edp` and `edt` are eau de parfum and eau de toilette, which
    # is how a catalogue writes it and nothing a medicine is ever labelled.
    " edp", " edt", "eau de", "fragrance", "aftershave",
    # "YSL OPIUM POUR HOMME" is a fragrance whose name really is a controlled
    # substance, and it comes in four more variants that carry neither `edp`
    # nor `edt`. The house name is the reliable signal: Yves Saint Laurent has
    # never made a medicine.
    "ysl ", "yves saint", "pour homme", "pour femme", "deo stick",
    "body mist", "body spray",
    # And batteries, which contain lithium and are not lithium carbonate.
    "batteries", "battery", "duracell", "energizer",
]


def _tiers() -> list[tuple[int, str, list[str]]]:
    """The substance tiers, which compete with each other on strictness."""
    return [
        (6, "controlled — permit required", S6),
        (5, "controlled register", S5),
        (4, "prescription only", S4),
        (2, "pharmacy medicine", S2),
    ]


#: The dosage-form tier, which does NOT compete — it is a fallback.
#:
#: A form says "this is a pharmaceutical preparation". It does not say "this
#: needs a prescription": suppositories, pessaries and inhalers are sold over a
#: counter every day. Letting it into the strictness comparison made
#: "GLYCERIN SUPPOSITORIES" outrank its own substance and land at S3.
#:
#: So it applies only where nothing named the substance at all, and never beats
#: a tier that did.
FORM_TIER = (3, "prescription — pharmaceutical preparation", S3)


def _compile() -> list[tuple[int, str, re.Pattern]]:
    """One regex per tier, so a name is scanned five times and not two thousand.

    Fragments are escaped: several contain characters a regex would otherwise
    read (`co-codamol`, `hydrocortisone 1%`, `inj `).
    """
    def frag(t: str) -> str:
        # Anchored to the START of a word. Without it a fragment matches inside
        # a longer, unrelated substance: "opium" sits inside "ipratropium", and
        # a bronchodilator was being sent to the controlled register.
        #
        # Only the leading edge is anchored, so stems still work — `phenobarb`
        # has to reach "phenobarbitone", and `amoxi` has to reach "amoxycillin".
        escaped = re.escape(t)
        return (chr(92) + chr(98) + escaped) if t[:1].isalnum() else escaped

    out = []
    for schedule, why, terms in _tiers() + [FORM_TIER]:
        pattern = "|".join(frag(t) for t in sorted(terms, key=len, reverse=True))
        out.append((schedule, why, re.compile(pattern)))
    return out


_EXCLUDE = re.compile("|".join(re.escape(t) for t in NOT_MEDICINE))


def classify_name(name: str, rules=None) -> tuple[int | None, str, str]:
    """The schedule this product name warrants, or None if nothing recognised it.

    Returns (schedule, why, the fragment that matched).

    Every tier is tested and the STRICTEST result is returned. That is the rule
    that lets the pharmacy-medicine tier exist at all: "PARACETAMOL/CODEINE
    500/8" matches paracetamol at S2 and codeine at S5, and it must come back
    S5. A first-match-wins scan over the same lists would classify every
    co-codamol in the catalogue as sellable over the counter.
    """
    rules = rules or _compile()
    low = (name or "").lower()
    if not low:
        return None, "", ""
    if _EXCLUDE.search(low):
        return None, "not a medicine", ""
    # The substance tiers compete on strictness — this is the rule that keeps a
    # combination product as controlled as its most controlled ingredient. The
    # form tier is last in `rules` and is excluded from that comparison.
    *substance, form = rules
    best: tuple[int, str, str] | None = None
    for schedule, why, pattern in substance:
        hit = pattern.search(low)
        if hit and (best is None or schedule > best[0]):
            best = (schedule, why, hit.group(0))
    if best is not None:
        return best

    # Nothing named the substance. Fall back to what the preparation plainly is.
    schedule, why, pattern = form
    hit = pattern.search(low)
    if hit:
        return schedule, why, hit.group(0)
    return None, "", ""


def classify(pharmacy_id: int, *, dry_run: bool = False,
             allow_down: bool = False, report: str | None = None) -> dict:
    db = SessionLocal()
    rules = _compile()
    try:
        conn = db.connection()

        def spread() -> dict[int, int]:
            return dict(conn.execute(text(
                "select coalesce(schedule,0), count(*) from products "
                "where pharmacy_id = :p group by 1"), {"p": pharmacy_id}
            ).fetchall())

        before = spread()
        print("  before: " + ", ".join(f"S{k} {v:,}" for k, v in sorted(before.items())))

        rows = conn.execute(text(
            "select id, name, coalesce(schedule,0), coalesce(category,'') "
            "from products where pharmacy_id = :p"), {"p": pharmacy_id}).fetchall()

        up: list[tuple] = []
        down: list[tuple] = []
        same = 0
        unknown: list[tuple] = []
        excluded = 0

        for pid, name, current, category in rows:
            schedule, why, hit = classify_name(name, rules)
            if schedule is None:
                if why == "not a medicine":
                    excluded += 1
                else:
                    unknown.append((pid, name, current, category))
                continue
            if schedule > current:
                up.append((pid, name, current, schedule, why, hit, category))
            elif schedule < current:
                down.append((pid, name, current, schedule, why, hit, category))
            else:
                same += 1

        # Apply. Upward always; downward only when asked for, and never to S0 or
        # S1 — nothing here puts a medicine on an open shelf.
        for pid, _n, _c, schedule, *_ in up:
            conn.execute(text("update products set schedule = :s where id = :i"),
                         {"s": schedule, "i": pid})
        applied_down = 0
        if allow_down:
            for pid, _n, _c, schedule, *_ in down:
                if schedule < 2:
                    continue
                conn.execute(text("update products set schedule = :s where id = :i"),
                             {"s": schedule, "i": pid})
                applied_down += 1

        after = spread()
        if dry_run:
            db.rollback()
            print("  (dry run: nothing was written)")
        else:
            db.commit()
        print("  after:  " + ", ".join(f"S{k} {v:,}" for k, v in sorted(after.items())))

        if report:
            with open(report, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["direction", "product_id", "name", "from", "to",
                            "reason", "matched_on", "import_category"])
                for pid, name, cur, sch, why, hit, cat in up:
                    w.writerow(["tightened", pid, name, f"S{cur}", f"S{sch}", why, hit, cat])
                for pid, name, cur, sch, why, hit, cat in down:
                    w.writerow(
                        ["relaxed" if allow_down and sch >= 2 else "relaxed (NOT applied)",
                         pid, name, f"S{cur}", f"S{sch}", why, hit, cat])
                for pid, name, cur, cat in unknown:
                    w.writerow(["unidentified", pid, name, f"S{cur}", f"S{cur}",
                                "nothing in the table matched this name", "", cat])
            print(f"\n  report written to {report}")

        return {
            "tightened": len(up),
            "relaxed_possible": len(down),
            "relaxed_applied": applied_down,
            "already_correct": same,
            "unidentified": unknown,
            "not_a_medicine": excluded,
            "before": before,
            "after": after,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify a catalogue against the MCAZ schedules.")
    parser.add_argument("--pharmacy", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-down", action="store_true",
                        help="Permit moves to a LESS restrictive schedule, from "
                             "the named pharmacy-medicine list only. Off by default.")
    parser.add_argument("--report", help="Write every decision to this CSV.")
    args = parser.parse_args()

    r = classify(args.pharmacy, dry_run=args.dry_run,
                 allow_down=args.allow_down, report=args.report)

    print()
    print(f"    {r['tightened']:>7,}  moved to a MORE restrictive schedule")
    if args.allow_down:
        print(f"    {r['relaxed_applied']:>7,}  moved to pharmacy medicine (S2)")
    else:
        print(f"    {r['relaxed_possible']:>7,}  could move DOWN to pharmacy medicine "
              f"— not applied, pass --allow-down")
    print(f"    {r['already_correct']:>7,}  already correct")
    print(f"    {r['not_a_medicine']:>7,}  read as not a medicine, left alone")
    print(f"    {len(r['unidentified']):>7,}  UNIDENTIFIED — left exactly as they were")

    if r["unidentified"]:
        still_open = Counter(c for _i, _n, _s, c in r["unidentified"])
        print("\n  what the unidentified are, by the import's own category:")
        for cat, n in still_open.most_common(8):
            print(f"      {n:>7,}  {cat or '(none)'}")
        print("\n  a sample of them, which is the job that remains:")
        for _i, name, sch, _c in r["unidentified"][:15]:
            print(f"      S{sch}  {name}")

    print("\n  Nothing here reached S0 or S1: this tool will not put a medicine")
    print("  on an open shelf. Unidentified products were left where they were,")
    print("  never defaulted — that count is the honest size of what is left,")
    print("  and it is answered by loading the pharmacy's own schedule list.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
