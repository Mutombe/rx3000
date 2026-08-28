"""The vocabulary behind the clinical fields.

Allergies and chronic conditions were free text in a box, and both are read by
code rather than only by people: an allergy raises a blocking warning at
dispensing by matching what was typed against product names and ingredients, and
a chronic condition decides whether a repeat is treated as urgent. A misspelt
allergy is therefore not untidy data, it is a safety check that never fires.

So the counter picks from a list. The list is open — anything missing can be
added at the moment it is needed, because a vocabulary a pharmacy cannot extend
is one people work around by typing into a notes field, and an allergy in the
notes warns nobody.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import ClinicalTerm, User

router = APIRouter(prefix="/api/clinical-terms", tags=["clinical-terms"])

KINDS = ("allergy", "condition")

#: What a Zimbabwean dispensary actually meets at the counter. Kept short on
#: purpose: a list of four hundred allergens is one nobody scrolls, and the
#: point is that the common answer is one click. Anything else gets added when
#: somebody needs it, which is also how the list learns what this shop sees.
SEED = {
    "allergy": [
        ("Penicillin", "penicillin,amoxicillin,ampicillin,augmentin,co-amoxiclav,flucloxacillin", "drug"),
        ("Sulphonamides", "sulfa,sulpha,sulfamethoxazole,cotrimoxazole,bactrim", "drug"),
        ("Aspirin", "aspirin,acetylsalicylic,asa", "drug"),
        ("NSAIDs", "ibuprofen,brufen,diclofenac,voltaren,naproxen,indomethacin", "drug"),
        ("Codeine", "codeine,dihydrocodeine", "drug"),
        ("Morphine", "morphine,opiate,opioid,pethidine", "drug"),
        ("Cephalosporins", "cephalexin,ceftriaxone,cefixime,cefuroxime", "drug"),
        ("Tetracyclines", "tetracycline,doxycycline,minocycline", "drug"),
        ("Erythromycin", "erythromycin,macrolide,azithromycin,clarithromycin", "drug"),
        ("Metronidazole", "metronidazole,flagyl", "drug"),
        ("Quinine", "quinine,quinidine", "drug"),
        ("Nevirapine", "nevirapine,nvp", "drug"),
        ("Cotrimoxazole", "cotrimoxazole,septrin,bactrim", "drug"),
        ("Chloroquine", "chloroquine,hydroxychloroquine", "drug"),
        ("Iodine", "iodine,povidone,betadine,contrast", "drug"),
        ("Latex", "latex,rubber,gloves", "environmental"),
        ("Peanuts", "peanut,groundnut,nuts", "food"),
        ("Shellfish", "shellfish,prawn,crab,seafood", "food"),
        ("Eggs", "egg,albumin", "food"),
        ("Cow's milk", "milk,lactose,dairy", "food"),
        ("Soya", "soya,soy", "food"),
        ("Gluten", "gluten,wheat,coeliac", "food"),
        ("Bee stings", "bee,wasp,sting,venom", "environmental"),
        ("Dust mite", "dust,mite", "environmental"),
        ("Pollen", "pollen,hay fever", "environmental"),
    ],
    "condition": [
        # These words are matched by the dispensary worklist to decide whose
        # repeat is urgent, so they are spelt the way that check expects.
        ("Diabetes", "diabetes,diabetic,type 2,type 1", "chronic"),
        ("Hypertension", "hypertension,high blood pressure,bp", "chronic"),
        ("Asthma", "asthma,asthmatic", "chronic"),
        ("Epilepsy", "epilepsy,epileptic,seizures,fits", "chronic"),
        ("HIV", "hiv,art,arv,retroviral", "chronic"),
        ("Cardiac disease", "cardiac,heart,heart failure,angina", "chronic"),
        ("Thyroid disease", "thyroid,hypothyroid,hyperthyroid", "chronic"),
        ("Arthritis", "arthritis,rheumatoid,osteoarthritis", "chronic"),
        ("COPD", "copd,emphysema,chronic bronchitis", "chronic"),
        ("Renal disease", "renal,kidney,dialysis", "chronic"),
        ("High cholesterol", "cholesterol,hyperlipidaemia,lipids", "chronic"),
        ("Tuberculosis", "tb,tuberculosis", "chronic"),
        ("Sickle cell", "sickle,sickle cell", "chronic"),
        ("Glaucoma", "glaucoma", "chronic"),
        ("Depression", "depression,depressive", "chronic"),
        ("Pregnancy", "pregnant,pregnancy,antenatal", ""),
        ("Breastfeeding", "breastfeeding,lactating,nursing", ""),
    ],
}


def seed_if_empty(db: Session) -> int:
    """Put the common answers in, once.

    Runs on every boot and adds only what is missing, so a pharmacy already
    using the system picks up terms added in a later release instead of only a
    fresh database getting them.
    """
    made = 0
    for kind, rows in SEED.items():
        have = {n for (n,) in db.query(ClinicalTerm.name)
                .filter(ClinicalTerm.kind == kind).all()}
        for name, synonyms, category in rows:
            if name in have:
                continue
            db.add(ClinicalTerm(kind=kind, name=name, synonyms=synonyms,
                                category=category, common=True))
            made += 1
    if made:
        db.commit()
    return made


def _out(t: ClinicalTerm) -> dict:
    return {
        "id": t.id, "kind": t.kind, "name": t.name,
        "synonyms": t.synonyms or "", "category": t.category or "",
        "common": bool(t.common), "times_used": t.times_used or 0,
    }


@router.get("")
def list_terms(kind: str, q: str = "", limit: int = 50,
               db: Session = Depends(get_db),
               _: User = Depends(get_current_user)):
    """Search the vocabulary for one kind of field.

    Ordered by what this pharmacy actually uses, then by what is common, then
    alphabetically. A picker whose first option is the one usually wanted is the
    difference between choosing and hunting.
    """
    if kind not in KINDS:
        raise HTTPException(status_code=400,
                            detail=f"Kind must be one of: {', '.join(KINDS)}")
    query = db.query(ClinicalTerm).filter(ClinicalTerm.kind == kind,
                                          ClinicalTerm.active.is_(True))
    term = (q or "").strip()
    if term:
        like = f"%{term.lower()}%"
        # Synonyms are searched too, because the patient says "sulfa" and the
        # catalogue says "Sulphonamides". Making somebody know the second word
        # to find the first is how a picker sends them back to free text.
        query = query.filter(or_(func.lower(ClinicalTerm.name).like(like),
                                 func.lower(ClinicalTerm.synonyms).like(like)))
    rows = (query.order_by(ClinicalTerm.times_used.desc(),
                           ClinicalTerm.common.desc(),
                           ClinicalTerm.name.asc())
            .limit(max(1, min(limit, 200))).all())
    return {"items": [_out(t) for t in rows]}


@router.post("")
def add_term(body: dict, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """Add a term at the moment somebody needs it.

    Deliberately not restricted to a pharmacist. The person typing a patient's
    allergy into the record is whoever is at the counter, and a permission wall
    here does not produce a better vocabulary — it produces the allergy being
    written somewhere that warns nobody.

    An existing name is returned rather than refused. Two people adding "Latex"
    on the same afternoon is not an error, and an error is what would send the
    second one back to free text.
    """
    kind = (body.get("kind") or "").strip()
    name = " ".join((body.get("name") or "").split())
    if kind not in KINDS:
        raise HTTPException(status_code=400,
                            detail=f"Kind must be one of: {', '.join(KINDS)}")
    if len(name) < 2:
        raise HTTPException(status_code=400,
                            detail="Give the term a name of at least two letters.")
    if len(name) > 120:
        raise HTTPException(status_code=400,
                            detail="That is too long for a term. Use a few words.")

    existing = (db.query(ClinicalTerm)
                .filter(ClinicalTerm.kind == kind,
                        func.lower(ClinicalTerm.name) == name.lower())
                .first())
    if existing:
        if not existing.active:
            existing.active = True
            db.commit()
        return _out(existing)

    term = ClinicalTerm(
        kind=kind, name=name,
        synonyms=(body.get("synonyms") or "").strip()[:300],
        category=(body.get("category") or "").strip()[:40],
        common=False, created_by_id=user.id,
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return _out(term)


@router.post("/used")
def mark_used(body: dict, db: Session = Depends(get_db),
              _: User = Depends(get_current_user)):
    """Count a term as chosen, so the list orders itself by this shop's reality.

    Best effort and never fatal: a counted term is a convenience, and failing a
    patient's record because a tally could not be written would be the wrong
    trade entirely.
    """
    names = body.get("names") or []
    kind = (body.get("kind") or "").strip()
    if kind not in KINDS or not isinstance(names, list):
        return {"counted": 0}
    counted = 0
    for name in names[:50]:
        row = (db.query(ClinicalTerm)
               .filter(ClinicalTerm.kind == kind,
                       func.lower(ClinicalTerm.name) == str(name).strip().lower())
               .first())
        if row:
            row.times_used = (row.times_used or 0) + 1
            counted += 1
    if counted:
        db.commit()
    return {"counted": counted}
