"""What each funder calls a medicine, and where that answer came from.

A claim line is adjudicated on a NAPPI code. The funder matches the code, not
the name, so a line carrying the wrong one is paid for the wrong medicine and a
line carrying none is not paid at all — and the pharmacy finds out weeks later
in a remittance, by which time the medicine has gone and the patient has too.

Three things this module exists to keep straight:

* **The code belongs to a (scheme, medicine) pair, not to a medicine.** Each
  funder issues its own. Cimas publishes a list; most never say anything.
* **There is a fallback, and it must be labelled as one.** Where a scheme has
  said nothing, the pharmacy's own general NAPPI is the best guess available and
  is better than a blank — but the dispenser has to be able to see that it is a
  guess, or they will trust it exactly as far as they trust a published one.
* **Correcting it corrects the catalogue.** The code is the same on every script
  that medicine will ever appear on, so it is taught once and kept.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import MedicalAid, Product, SchemeProductCode, User

#: Where an answer came from, in the order a dispenser should trust it.
SCHEME = "scheme"        # this funder's own code, published or typed here
GENERAL = "general"      # the pharmacy's own NAPPI, standing in
NONE = "none"


def for_products(db: Session, medical_aid_id: int | None,
                 product_ids: list[int]) -> dict[int, dict]:
    """The code each of these medicines claims under, in one query pair.

    Asked for a whole basket at once rather than a line at a time: this is read
    on every keystroke while a script is being built, and a query per line is a
    round trip per line on the screen a pharmacy spends its day on.
    """
    wanted = [int(p) for p in product_ids if p]
    if not wanted:
        return {}

    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(wanted)).all()}
    mine: dict[int, SchemeProductCode] = {}
    if medical_aid_id:
        mine = {row.product_id: row for row in
                db.query(SchemeProductCode)
                .filter(SchemeProductCode.medical_aid_id == medical_aid_id,
                        SchemeProductCode.product_id.in_(wanted))
                .all()}

    out: dict[int, dict] = {}
    for product_id in wanted:
        product = products.get(product_id)
        if product is None:
            continue
        row = mine.get(product_id)
        if row is not None and (row.code or "").strip():
            out[product_id] = {
                "product_id": product_id, "code": row.code.strip(),
                "origin": SCHEME, "source": row.source or "",
                "set_by": (row.set_by.full_name or row.set_by.username)
                          if row.set_by else "",
                "updated_at": row.updated_at.isoformat() if row.updated_at else "",
            }
        elif (product.nappi_code or "").strip():
            out[product_id] = {
                "product_id": product_id, "code": product.nappi_code.strip(),
                "origin": GENERAL, "source": "the pharmacy's own NAPPI",
                "set_by": "", "updated_at": "",
            }
        else:
            out[product_id] = {"product_id": product_id, "code": "",
                               "origin": NONE, "source": "", "set_by": "",
                               "updated_at": ""}
    return out


def remember(db: Session, *, medical_aid_id: int, product_id: int, code: str,
             user: User | None = None, source: str = "typed at the counter",
             pharmacy_id: int | None = None) -> SchemeProductCode:
    """Keep what this funder calls this medicine, from now on.

    An empty code deletes the scheme's own entry rather than storing a blank,
    so "no, that was wrong" falls back to the pharmacy's general NAPPI instead
    of being pinned to nothing.
    """
    code = (code or "").strip()[:24]
    row = (db.query(SchemeProductCode)
           .filter(SchemeProductCode.medical_aid_id == medical_aid_id,
                   SchemeProductCode.product_id == product_id).first())
    if not code:
        if row is not None:
            db.delete(row)
            db.commit()
        return row
    if row is None:
        row = SchemeProductCode(medical_aid_id=medical_aid_id, product_id=product_id)
        if pharmacy_id is not None:
            row.pharmacy_id = pharmacy_id
        db.add(row)
    row.code = code
    row.source = source
    row.set_by_id = user.id if user else None
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def missing_for(db: Session, medical_aid_id: int | None,
                product_ids: list[int]) -> list[int]:
    """Which of these cannot be claimed as they stand.

    A medicine standing on the pharmacy's general NAPPI is NOT counted missing:
    it has a code and the claim will carry it. What is missing is a line with no
    code at all, which the funder will reject outright.
    """
    known = for_products(db, medical_aid_id, product_ids)
    return [pid for pid, row in known.items() if row["origin"] == NONE]
