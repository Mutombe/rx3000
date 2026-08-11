"""The person using the till, and the business they work for.

Two different things live here on purpose, because they have two different
rules. Anyone may change their own name and their own password. Only an
administrator may change what the pharmacy is called, its registration number,
or the address that prints on a receipt — those appear on statutory documents,
and a locum changing them on a Tuesday is not a thing that should be possible.

The company profile is stored as key/value settings rather than columns on a
table. That is deliberate: this is a product sold to many pharmacies, each of
which will want a field the others do not, and a settings row can be added
without a migration on every customer's database.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Setting, User
from .. import auth

router = APIRouter(prefix="/api/profile", tags=["profile"])

# The company fields the product knows about. Anything not on this list is
# refused rather than silently stored, so a typo cannot quietly create
# `regisration_no` alongside the real one and leave a receipt printing blank.
COMPANY_FIELDS = {
    "trading_name": "The name the pharmacy trades under",
    "legal_name": "The registered legal entity",
    "registration_no": "Pharmacy council registration number",
    "vat_no": "VAT registration number",
    "tax_no": "Income tax number",
    "phone": "Telephone",
    "email": "Email",
    "address_line1": "Street address",
    "address_line2": "Suburb",
    "city": "City",
    "country": "Country",
    "responsible_pharmacist": "Pharmacist in charge",
    "receipt_footer": "Line printed at the foot of every receipt",
}


class MeIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class CompanyIn(BaseModel):
    values: dict[str, str]


def _get(db: Session, key: str) -> str:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else ""


def _set(db: Session, key: str, value: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


@router.get("/me")
def get_me(user: User = Depends(auth.get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "active": user.active,
        # What this person may do, answered here so the UI never has to guess
        # from the role string and get it wrong.
        "can_edit_company": user.role == "admin",
    }


@router.put("/me")
def update_me(
    body: MeIn,
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_user),
):
    user.full_name = body.full_name.strip()
    db.commit()
    return {"full_name": user.full_name, "message": "Your name has been updated."}


@router.post("/password")
def change_password(
    body: PasswordIn,
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_user),
):
    """Changing a password requires proving you know the current one.

    Without that check, an unattended till is a password reset: anyone who walks
    up to a signed-in session could lock the real user out of their own account.
    """
    if not auth.verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "The current password is not correct.")
    if body.new_password == body.current_password:
        raise HTTPException(400, "The new password is the same as the old one.")
    user.password_hash = auth.hash_password(body.new_password)
    db.commit()
    return {"message": "Your password has been changed."}


@router.get("/company")
def get_company(
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_user),
):
    """Readable by anyone — a dispenser needs to see which branch they are on.

    Writing is what is restricted.
    """
    return {
        "fields": [
            {"key": k, "label": label, "value": _get(db, f"company.{k}")}
            for k, label in COMPANY_FIELDS.items()
        ],
        "editable": user.role == "admin",
    }


@router.put("/company")
def update_company(
    body: CompanyIn,
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_user),
):
    if user.role != "admin":
        raise HTTPException(
            403,
            "Only an administrator can change the company profile. These details "
            "appear on statutory documents.",
        )
    unknown = sorted(set(body.values) - set(COMPANY_FIELDS))
    if unknown:
        raise HTTPException(400, f"Not a company field: {', '.join(unknown)}")
    for key, value in body.values.items():
        _set(db, f"company.{key}", value.strip())
    db.commit()
    return {"message": "The company profile has been saved.", "saved": len(body.values)}
