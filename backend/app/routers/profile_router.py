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
import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
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
    # ---- what a document needs beyond an address -------------------------
    #
    # A statement that goes to a wholesaler, a claim schedule that goes to a
    # funder and a tax invoice that may be read by ZIMRA are all documents that
    # leave this pharmacy carrying its name. What was here covered a receipt
    # and nothing else, so anything larger had to invent its own letterhead.
    "bank_name": "Bank the pharmacy is paid into",
    "bank_account": "Bank account number",
    "bank_branch": "Bank branch and code",
    "document_footer": "Line printed at the foot of every statement and report",
    "terms": "Payment terms, printed on a statement",
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


def _many(db: Session, keys: list[str]) -> dict[str, str]:
    """Several settings in one query, not one query each.

    The letterhead reads twenty of them and is fetched before every document
    this pharmacy prints. Twenty round trips is nothing on SQLite and close to
    two seconds on the hosted database — two seconds of a blank window while
    somebody waits to print a statement.
    """
    rows = db.query(Setting).filter(Setting.key.in_(keys)).all()
    found = {r.key: r.value for r in rows}
    return {k: found.get(k, "") for k in keys}


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


#: The pharmacy's mark, held as a data URI in settings rather than on disk.
#:
#: A file on disk is a file that has to be backed up separately, served by
#: something, and found again after a move — for one small image that has to
#: appear on every printed page, the indirection costs more than it saves. It
#: goes wherever the settings go, which is what the backup already covers.
LOGO_KEY = "company.logo"
#: Small enough to sit in a settings row and to print sharply at the size a
#: letterhead uses. A photograph of a shopfront is not a logo, and accepting
#: one produces a document that takes a minute to print.
MAX_LOGO_BYTES = 512 * 1024


@router.post("/company/logo")
async def upload_logo(file: UploadFile = File(...),
                      db: Session = Depends(get_db),
                      user: User = Depends(auth.get_current_user)):
    """Put the pharmacy's mark on everything it prints."""
    if user.role != "admin":
        raise HTTPException(403, "Only an administrator can change the branding.")

    kind = (file.content_type or "").lower()
    if kind not in ("image/png", "image/jpeg", "image/svg+xml", "image/webp"):
        raise HTTPException(
            400,
            "A logo has to be a PNG, JPEG, SVG or WebP. Whatever was chosen is "
            f"a {kind or 'file of unknown type'}.")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "That file is empty.")
    if len(raw) > MAX_LOGO_BYTES:
        raise HTTPException(
            400,
            f"That image is {len(raw) // 1024}KB. A logo has to be under "
            f"{MAX_LOGO_BYTES // 1024}KB — anything larger is a photograph, and "
            f"it has to print sharply at about two centimetres wide.")

    encoded = base64.b64encode(raw).decode("ascii")
    _set(db, LOGO_KEY, f"data:{kind};base64,{encoded}")
    db.commit()
    return {"ok": True, "bytes": len(raw),
            "message": "That mark will now appear on everything this pharmacy prints."}


@router.delete("/company/logo")
def remove_logo(db: Session = Depends(get_db),
                user: User = Depends(auth.get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Only an administrator can change the branding.")
    _set(db, LOGO_KEY, "")
    db.commit()
    return {"ok": True, "message": "Documents will print without a logo."}


@router.get("/company/letterhead")
def letterhead(db: Session = Depends(get_db),
               _: User = Depends(auth.get_current_user)):
    """Everything a printed document needs about this pharmacy, in one call.

    One request rather than each report assembling its own header out of six
    settings lookups — which is how one document ends up showing the VAT number
    and another does not.
    """
    stored = _many(db, [f"company.{k}" for k in COMPANY_FIELDS] + [LOGO_KEY])
    values = {k: stored[f"company.{k}"] for k in COMPANY_FIELDS}
    return {
        **values,
        "logo": stored[LOGO_KEY] or "",
        # The name to print. A pharmacy trades under one name and is registered
        # under another, and a statement carries the trading name with the legal
        # entity beneath it.
        "display_name": values.get("trading_name") or values.get("legal_name") or "",
        "address": [line for line in (values.get("address_line1"),
                                      values.get("address_line2"),
                                      values.get("city"),
                                      values.get("country")) if line],
    }


@router.get("/company")
def get_company(
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_user),
):
    """Readable by anyone — a dispenser needs to see which branch they are on.

    Writing is what is restricted.
    """
    stored = _many(db, [f"company.{k}" for k in COMPANY_FIELDS])
    return {
        "fields": [
            {"key": k, "label": label, "value": stored[f"company.{k}"]}
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
