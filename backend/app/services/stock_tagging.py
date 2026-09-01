"""Put every product in a department.

A catalogue where two thirds of the lines belong to no department is a
catalogue that cannot be reported on. Every stock valuation, every margin
comparison, every "what is front shop actually worth" question groups on this
column, and an untagged product silently drops out of all of them, so the
totals look plausible and are wrong by however much is missing. CareXpress had
10,271 of 16,407 untagged.

HOW A PRODUCT IS PLACED

In this order, stopping at the first that answers:

  **Its schedule.** Anything S1 or above is a medicine that a pharmacist hands
  over. That is not a guess about the product; it is what the schedule means.

  **Its dosage form.** A tablet, an injection, a suppository or an inhaler is
  dispensary stock whatever it is called.

  **What it is called.** A keyword list, deliberately narrow and ordered from
  most specific to least, so "BABY OIL" lands in baby care rather than in
  cosmetics because it contains "OIL".

  **Nothing.** Left alone rather than swept into a bucket. A product nobody can
  place is a product somebody should look at, and burying it under MISC is how
  a department comes to hold two thousand things with nothing in common.

The rules are stated here rather than learned, because a pharmacist has to be
able to disagree with one and change it, and because a wrong department is
invisible until somebody reads a report and cannot see why the numbers move.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import Product, StockCategory

#: The departments a pharmacy actually lays out, and what falls in each.
#: Order matters: the first rule that matches wins, so the specific ones come
#: before the general.
DEPARTMENTS: list[tuple[str, list[str]]] = [
    ("Baby & Infant", [
        r"\bBABY\b", r"\bINFANT", r"NAPP?Y", r"\bDIAPER", r"\bPRAM\b",
        r"\bDUMMY\b", r"TEETH?ING", r"\bFORMULA\b", r"\bNAN\b", r"\bS-?26\b",
        r"NESTUM", r"CERELAC", r"\bBOTTLE TEAT",
    ]),
    ("Wound Care & Dressings", [
        r"\bBANDAGE", r"\bGAUZE\b", r"\bPLASTER", r"\bDRESSING", r"\bSWAB",
        r"\bCOTTON WOOL", r"ELASTOPLAST", r"\bLINT\b", r"\bMICROPORE",
        r"\bSUTURE", r"\bTOURNIQUET",
    ]),
    ("Surgical & Devices", [
        r"\bSYRINGE", r"\bNEEDLE", r"\bCATHETER", r"\bGLOVE", r"\bTHERMOMETER",
        r"\bNEBUL[IY]", r"\bGLUCOMETER", r"\bLANCET", r"\bTEST STRIP",
        r"\bBP\b.*\b(MACHINE|MONITOR|CHECK)", r"\bWHEELCHAIR", r"\bCRUTCH",
        r"\bSCALE\b", r"\bSTETHOSCOPE", r"\bMASK\b", r"\bAPRON\b",
    ]),
    ("Vitamins & Supplements", [
        r"\bVITAMIN", r"\bMULTIVIT", r"\bOMEGA\b", r"\bCALCIUM\b", r"\bIRON\b",
        r"\bZINC\b", r"\bFOLIC\b", r"\bSUPPLEMENT", r"\bTONIC\b",
        r"\bCOD LIVER", r"\bPROBIOTIC", r"\bCOLLAGEN",
    ]),
    ("Cosmetics & Fragrance", [
        r"\bLIPSTICK", r"\bMASCARA", r"\bFOUNDATION\b", r"\bCONCEALER",
        r"\bNAIL\b", r"\bPERFUME", r"\bEDT\b", r"\bEDP\b", r"\bCOLOGNE",
        r"\bMAKEUP", r"\bMAKE-?UP", r"\bEYE ?(SHADOW|LINER|BROW)",
        r"\bBLUSH", r"\bPOWDER COMPACT", r"\bLIP ?GLOSS",
    ]),
    ("Hair Care", [
        r"\bHAIR\b", r"\bRELAXER", r"\bBRAID", r"\bWEAVE\b", r"\bWIG\b",
        r"\bCURL", r"\bDREAD", r"\bAFRO\b", r"\bCOMB\b", r"\bBRUSH\b",
        r"\bGEL\b.*\bHAIR", r"\bSLEEK\b", r"\bAMLA\b", r"\bDARK ?& ?LOVELY",
        r"\bMOTIONS\b", r"\bPERM\b", r"\bHENNA\b",
    ]),
    ("Skin Care", [
        r"\bSKIN\b", r"\bFACE\b", r"\bFACIAL", r"\bCLEANSER", r"\bTONER\b",
        r"\bSCRUB\b", r"\bMOISTURI[SZ]", r"\bSUNSCREEN", r"\bSPF\b",
        r"\bNIVEA\b", r"\bPONDS\b", r"\bDOVE\b", r"\bVASELINE",
        r"\bGLYCERIN", r"\bAQUEOUS", r"\bE45\b", r"\bCETAPHIL",
        r"\bBIO-?OIL", r"\bSHEA\b", r"\bCOCOA BUTTER",
    ]),
    ("Confectionery & Drinks", [
        r"\bCHOCOLATE", r"\bSWEETS?\b", r"\bCHEWING GUM", r"\bBISCUIT",
        r"\bCRISPS?\b", r"\bJUICE\b", r"\bWATER \d", r"\bSODA\b",
        r"\bENERGY DRINK", r"\bCOKE\b", r"\bMAZOE", r"\bCEREAL",
        r"\bPEANUT", r"\bSUGAR\b", r"\bCOFFEE\b", r"\bTEA BAGS?\b",
    ]),
    ("Gifts & Novelty", [
        r"\bGIFT\b", r"\bTOY\b", r"\bBALLOON", r"\bCARD\b(?!.*CODE)",
        r"\bJEWELL?", r"\bWATCH\b", r"\bSUNGLASSES", r"\bUMBRELLA",
        r"\bHAMPER",
    ]),
    ("Optical & Reading", [
        r"\bREADING GLASSES", r"\bGLASSES\b", r"\bLENS\b", r"\bCONTACT LENS",
        r"\bSPECTACLE", r"\bEYE ?GLASS",
    ]),
    ("Toiletries & Personal Care", [
        r"\bSOAP\b", r"\bSHAMPOO", r"\bCONDITIONER\b", r"\bLOTION\b",
        r"\bDEODOR", r"\bROLL-?ON", r"\bBODY ?(SPRAY|WASH|CREAM|BUTTER)",
        r"\bTOOTH ?(PASTE|BRUSH)", r"\bMOUTHWASH", r"\bSANITAR",
        r"\bTAMPON", r"\bPAD[S]?\b", r"\bRAZOR", r"\bSHAVING",
        r"\bTISSUE", r"\bWIPES?\b", r"\bPETROLEUM JELLY", r"\bVASELINE",
        r"\bSANITI[SZ]ER", r"\bTALC", r"\bBODY\b", r"\bSHOWER\b",
        r"\bBATH\b", r"\bWASH\b", r"\bFOAM\b", r"\bSPRAY\b",
        r"\bPOWDER\b", r"\bCREAM\b", r"\bBALM\b", r"\bSCENT",
        r"\bFRESH(NER)?\b", r"\bANTIPERSPIRANT", r"\bRADOX\b",
        r"\bCOLGATE", r"\bSENSODYNE", r"\bPROTEX\b", r"\bLIFEBUOY",
    ]),
    ("Stationery & Sundries", [
        r"\bFILE\b", r"\bFOLDER", r"\bPEN\b", r"\bPAPER\b", r"\bENVELOPE",
        r"\bSTAPLE", r"\bBATTER(Y|IES)", r"\bAIRTIME", r"\bVOUCHER",
        r"\bCARD CODE", r"\bBAG[S]?\b", r"\bCANDLE",
    ]),
]

#: A dosage form that settles it, whatever the product is called.
DISPENSARY_WORDS = re.compile(
    r"\b(TABS?|TABLETS?|CAPS?|CAPSULES?|SYR(UP)?|SUSP(ENSION)?|INJ(ECTION)?|"
    r"VIAL|AMPOULE|SUPPOSITOR|INHALER|NEBULES|DROPS|OINTMENT|CREAM \d|"
    r"PESSAR|LOZENGE|SACHET|INFUSION|IV\b|SOLUTION FOR)\b", re.I)

#: The department a scheduled medicine belongs to.
DISPENSARY = "Dispensary"

#: What a pharmacy may already call one of these.
#:
#: A shop that has used "COSMETICS" for ten years should not end up with that
#: department AND a "Cosmetics & Fragrance" beside it because a rule table
#: spelled it differently. The names below are folded into an existing
#: department where the pharmacy has one; where it does not, the rule's own
#: name is used.
SAME_AS = {
    "Cosmetics & Fragrance": ["COSMETICS", "COSMETIC"],
    "Toiletries & Personal Care": ["TOILETRIES", "PERSONAL CARE"],
    "Dispensary": ["DISPENSARY", "PHARMACY", "ETHICAL"],
    "Vitamins & Supplements": ["VITAMINS", "SUPPLEMENTS", "VMS"],
    "Baby & Infant": ["BABY", "BABY CARE", "INFANT"],
    "Surgical & Devices": ["SURGICAL", "DEVICES", "EQUIPMENT"],
    "Wound Care & Dressings": ["WOUND CARE", "DRESSINGS"],
    "Confectionery & Drinks": ["CONFECTIONERY", "FOOD", "GROCERIES"],
    "Stationery & Sundries": ["STATIONERY", "SUNDRIES"],
    "Optical & Reading": ["OPTICAL"],
    "Skin Care": ["SKINCARE", "SKIN"],
    "Hair Care": ["HAIRCARE", "HAIR"],
}


def _department(name: str, existing: dict) -> str:
    """The pharmacy's own name for this department, where it has one."""
    if name.upper() in existing:
        return name
    for alias in SAME_AS.get(name, []):
        if alias in existing:
            return existing[alias].name
    return name


def _rules() -> list[tuple[str, re.Pattern]]:
    return [(name, re.compile("|".join(patterns), re.I))
            for name, patterns in DEPARTMENTS]


def place(product: Product, rules) -> str | None:
    """Which department this product belongs to, or None if it cannot be said."""
    text = f"{product.name or ''} {product.dosage_form or ''} " \
           f"{product.strength or ''}".upper()

    # A schedule is not an opinion about the product. S1 and above is a medicine
    # a pharmacist hands over, whatever the shelf it sits on.
    if (product.schedule or 0) >= 1:
        return DISPENSARY

    for name, pattern in rules:
        if pattern.search(text):
            return name

    # A dosage form settles it after the named departments, not before: a baby
    # syrup is baby care to the person looking for it.
    if DISPENSARY_WORDS.search(text):
        return DISPENSARY
    return None


def tag(db: Session, *, pharmacy_id: int, apply: bool = False,
        retag: bool = False) -> dict:
    """Place every product that has no department.

    `retag` reconsiders products that already have one — off by default,
    because a department somebody set by hand is a decision, and a rule table
    should not quietly overrule it.
    """
    rules = _rules()
    products = (db.query(Product)
                .filter(Product.pharmacy_id == pharmacy_id, Product.active)
                .all())
    existing = {c.name.upper(): c for c in
                db.query(StockCategory)
                .filter(StockCategory.pharmacy_id == pharmacy_id).all()}

    placed: dict[str, int] = {}
    # Departments this would have to create. Said in the preview, because a
    # rule table quietly inventing eight new departments in somebody's shop is
    # a thing they should agree to before it happens, not discover afterwards.
    created: list[str] = []
    unplaced = 0
    considered = 0

    for product in products:
        if product.category_id and not retag:
            continue
        considered += 1
        where = place(product, rules)
        if where is None:
            unplaced += 1
            continue
        where = _department(where, existing)
        if where.upper() not in existing and where not in created:
            created.append(where)
        placed[where] = placed.get(where, 0) + 1
        if not apply:
            continue
        category = existing.get(where.upper())
        if category is None:
            category = StockCategory(name=where, pharmacy_id=pharmacy_id)
            db.add(category)
            db.flush()
            existing[where.upper()] = category
        product.category_id = category.id

    if apply:
        db.commit()

    return {
        "applied": apply,
        "products": len(products),
        "considered": considered,
        "placed": sum(placed.values()),
        "unplaced": unplaced,
        "by_department": sorted(({"department": k, "products": v}
                                 for k, v in placed.items()),
                                key=lambda r: -r["products"]),
        "departments": dict(placed),
        "created": created,
        "message": (
            f"{sum(placed.values()):,} of {considered:,} placed into "
            f"{len(placed)} department(s)."
            + (f" {unplaced:,} could not be placed from their name, form or "
               f"schedule and were left alone — a product nobody can place is "
               f"one somebody should look at." if unplaced else "")),
    }
