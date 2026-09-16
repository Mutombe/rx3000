"""Whose pharmacy this is, for anything a patient or a funder reads.

A dispensing label, a claim copy and a receipt all have to name the pharmacy
that handed the medicine over: its trading name, where it is, its telephone
number and the number it is registered under. That is not decoration. It is how
a patient with a reaction telephones the right shop at nine at night, and how an
inspector ties a sticker on a box to a licensed premises.

WHERE IT USED TO COME FROM, AND WHY THAT WAS WRONG

`settings.PHARMACY_NAME` and friends — environment variables on the server.
That is right for a desktop install serving one pharmacy and wrong for a hosted
server that holds several: every label printed by every tenant said "RX5000
Pharmacy", with the placeholder registration number `Y123456` under it, because
those are the defaults the software ships with. CareXpress printed another
company's name on their own boxes.

So the pharmacy's own record is the authority, then the branch that is more
specific than it, and the environment only where there is no record at all,
which is the single-tenant case those variables were written for.

A field nobody has filled in is left empty rather than defaulted. An empty
address line on a sticker is a gap somebody notices and fills; a plausible
wrong one is a gap nobody ever notices.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Pharmacy
from ..tenancy import current_pharmacy_id, unscoped


def of(db: Session) -> dict:
    """The pharmacy in force: its name, registration number, address and phone."""
    pharmacy = None
    pharmacy_id = current_pharmacy_id()
    if pharmacy_id:
        with unscoped():
            pharmacy = db.get(Pharmacy, pharmacy_id)
    if pharmacy is None:
        # No tenancy at all: the desktop install, where the environment is the
        # only place these have ever been.
        return {"name": settings.PHARMACY_NAME, "reg_no": settings.PHARMACY_REG_NO,
                "address": settings.PHARMACY_ADDRESS, "phone": settings.PHARMACY_PHONE}
    return {
        # The trading name is what is over the door; the registered name is what
        # is on the licence, and the patient knows the first one.
        "name": (pharmacy.trading_name or pharmacy.name or "").strip(),
        "reg_no": (pharmacy.registration_no or "").strip(),
        "address": (pharmacy.address or "").strip(),
        "phone": (pharmacy.phone or "").strip(),
    }
