"""The licences and certificates a branch trades on.

Upload one, see what is due, see what was never uploaded at all — which is the
half that matters, because a register of what you hold cannot tell you what you
do not.
"""
import base64
from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_role
from ..database import get_db
from ..models import Branch, ComplianceDocument, User
from ..services import compliance

router = APIRouter(prefix="/api/compliance", tags=["compliance"],
                   dependencies=[Depends(get_current_user)])

#: A certificate is a photograph or a scan. Above this it is a photograph
#: nobody compressed, and a hundred of them in a row is a database nobody can
#: back up over a Zimbabwean connection.
MAX_BYTES = 6 * 1024 * 1024

ALLOWED = {
    "application/pdf", "image/png", "image/jpeg", "image/webp", "image/heic",
}


@router.get("/kinds")
def kinds():
    """What a pharmacy is expected to hold, and why each one matters."""
    return [
        {"kind": k, "name": n, "issuer": i, "renewal_months": m,
         "critical": c, "why": w}
        for k, n, i, m, c, w in compliance.KINDS
    ]


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """Every branch's standing, worst first.

    An owner with four shops asks one question of this, and it is not "show me
    the certificates" — it is "is anything about to stop one of my branches
    trading".
    """
    return compliance.overview(db)


@router.get("/branches/{branch_id}")
def branch(branch_id: int, db: Session = Depends(get_db)):
    try:
        return compliance.branch_register(db, branch_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/branches/{branch_id}/documents")
async def upload(branch_id: int,
                 kind: str = Form(...),
                 title: str = Form(default=""),
                 reference: str = Form(default=""),
                 issuer: str = Form(default=""),
                 issued_on: str = Form(default=""),
                 expires_on: str = Form(default=""),
                 renewal_cost: float = Form(default=0.0),
                 notes: str = Form(default=""),
                 file: UploadFile | None = File(default=None),
                 db: Session = Depends(get_db),
                 user: User = Depends(require_role("admin", "manager"))):
    """Record a document, with the certificate behind it where there is one.

    The file is optional and the date is not. A pharmacy that knows its licence
    expires in March and has not scanned it yet is better served by recording
    the date now than by waiting until it can find the scanner — the date is
    what produces the reminder, and a register nobody can enter anything into
    stays empty.
    """
    if db.get(Branch, branch_id) is None:
        raise HTTPException(404, "That branch does not exist.")

    def as_date(value: str):
        try:
            return date.fromisoformat(value) if value else None
        except ValueError:
            raise HTTPException(400, f"{value!r} is not a date.") from None

    doc = ComplianceDocument(
        branch_id=branch_id, kind=kind.strip()[:40],
        title=title.strip()[:160], reference=reference.strip()[:80],
        issuer=issuer.strip()[:120],
        issued_on=as_date(issued_on), expires_on=as_date(expires_on),
        renewal_cost=round(float(renewal_cost or 0), 2),
        notes=notes.strip(), created_by_id=user.id,
    )

    if file is not None and file.filename:
        kind_of = (file.content_type or "").lower()
        if kind_of not in ALLOWED:
            raise HTTPException(
                400,
                f"A certificate has to be a PDF or a photograph. That one is "
                f"{kind_of or 'of unknown type'}.")
        raw = await file.read()
        if not raw:
            raise HTTPException(400, "That file is empty.")
        if len(raw) > MAX_BYTES:
            raise HTTPException(
                400,
                f"That file is {len(raw) // (1024 * 1024)}MB. A scan of a "
                f"certificate should be under {MAX_BYTES // (1024 * 1024)}MB — "
                f"anything larger is an uncompressed photograph, and a hundred "
                f"of those is a database nobody can back up.")
        doc.file_name = file.filename[:200]
        doc.file_type = kind_of[:80]
        doc.file_bytes = len(raw)
        doc.file_data = (f"data:{kind_of};base64,"
                         + base64.b64encode(raw).decode("ascii"))

    # A renewal supersedes rather than replaces. Last year's certificate is the
    # proof the shop was licensed last year, which is what an audit asks about.
    previous = (db.query(ComplianceDocument)
                .filter(ComplianceDocument.branch_id == branch_id,
                        ComplianceDocument.kind == doc.kind,
                        ComplianceDocument.active.is_(True)).all())
    db.add(doc)
    db.flush()
    for old in previous:
        old.superseded_by_id = doc.id

    db.commit()
    db.refresh(doc)
    return {"ok": True, "id": doc.id,
            "superseded": len(previous),
            "message": (f"Recorded."
                        + (f" It supersedes {len(previous)} earlier one(s), "
                           f"which stay on file as proof of the period they "
                           f"covered." if previous else ""))}


@router.get("/documents/{document_id}/file")
def download(document_id: int, db: Session = Depends(get_db)):
    """The certificate itself, for showing an inspector."""
    doc = db.get(ComplianceDocument, document_id)
    if doc is None:
        raise HTTPException(404, "That document does not exist.")
    if not doc.file_data:
        raise HTTPException(
            404,
            "Only the details were recorded for this one — no scan was "
            "uploaded with it.")
    header, _, payload = doc.file_data.partition(",")
    return Response(
        content=base64.b64decode(payload),
        media_type=doc.file_type or "application/octet-stream",
        headers={"Content-Disposition":
                 f'inline; filename="{doc.file_name or "document"}"'})


@router.put("/documents/{document_id}")
def update(document_id: int, body: dict = Body(...),
           db: Session = Depends(get_db),
           _: User = Depends(require_role("admin", "manager"))):
    """Correct a date or a reference without re-uploading the scan."""
    doc = db.get(ComplianceDocument, document_id)
    if doc is None:
        raise HTTPException(404, "That document does not exist.")
    for field, width in (("title", 160), ("reference", 80), ("issuer", 120),
                         ("notes", 4000)):
        if field in body:
            setattr(doc, field, str(body[field] or "").strip()[:width])
    for field in ("issued_on", "expires_on"):
        if field in body:
            value = body[field]
            try:
                setattr(doc, field,
                        date.fromisoformat(value) if value else None)
            except (ValueError, TypeError):
                raise HTTPException(400, f"{value!r} is not a date.") from None
    if "renewal_cost" in body:
        doc.renewal_cost = round(float(body["renewal_cost"] or 0), 2)
    db.commit()
    return {"ok": True}


@router.delete("/documents/{document_id}")
def retire(document_id: int, db: Session = Depends(get_db),
           _: User = Depends(require_role("admin", "manager"))):
    """Take it off the register. Never deleted.

    A certificate that was on file is evidence the branch held it. Removing the
    row does not un-hold it; it removes the ability to prove it, which is the
    opposite of what a compliance register is for.
    """
    doc = db.get(ComplianceDocument, document_id)
    if doc is None:
        raise HTTPException(404, "That document does not exist.")
    doc.active = False
    db.commit()
    return {"ok": True,
            "message": "Off the register. It stays on file as proof of the "
                       "period it covered."}
