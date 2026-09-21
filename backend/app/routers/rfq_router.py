"""Requests for quotation: ask several wholesalers, compare, then buy.

Everything here is a thin skin over `services/rfq`, which is where the
reasoning lives — particularly why the comparison names the cheapest and
refuses to pick a winner.
"""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import auth
from ..auth import get_current_user
from ..database import get_db
from ..models import Pharmacy, Rfq, RfqSupplier, User
from ..services import config, portal_tokens, rfq_auto
from ..services import rfq as rfq_svc
from ..tenancy import current_pharmacy_id

router = APIRouter(prefix="/api/rfqs", tags=["rfq"],
                   dependencies=[Depends(get_current_user)])


def _pharmacy_name(db: Session) -> str:
    pid = current_pharmacy_id()
    row = db.get(Pharmacy, pid) if pid else None
    return (row.trading_name or row.name) if row else ""


def _found(rfq_id: int, db: Session) -> Rfq:
    row = db.get(Rfq, rfq_id)
    if row is None:
        raise HTTPException(404, "That request is not on file.")
    return row


def _shape(db: Session, row: Rfq) -> dict:
    answered = sum(1 for i in row.invited if i.responded_at)
    return {
        "id": row.id,
        "reference": row.reference,
        "status": row.status,
        "notes": row.notes or "",
        "closes_at": row.closes_at,
        "created_at": row.created_at,
        "sent_at": row.sent_at,
        "line_count": len(row.lines),
        "raised_automatically": bool(row.raised_automatically),
        "asked": len(row.invited),
        "answered": answered,
        # The one figure that says whether this is worth chasing.
        "waiting_on": sum(1 for i in row.invited if i.sent_at and not i.responded_at),
    }


@router.get("")
def list_rfqs(status: str = "", db: Session = Depends(get_db)):
    """Requests on file, newest first."""
    # The lines and the invitations come with the request: `_shape` counts
    # both, so without this the list is two queries per row and gets slower
    # every time somebody asks a wholesaler for a price.
    query = db.query(Rfq).options(joinedload(Rfq.lines),
                                  joinedload(Rfq.invited))
    if status:
        query = query.filter(Rfq.status == status)
    rows = query.order_by(Rfq.created_at.desc()).limit(200).all()
    return {"rfqs": [_shape(db, r) for r in rows], "count": len(rows)}


@router.post("")
def create_rfq(body: dict = Body(default={}), db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """Raise a request, with its lines and the suppliers to ask."""
    closes = body.get("closes_at")
    row = rfq_svc.create(
        db, user=user, notes=str(body.get("notes") or ""),
        closes_at=datetime.fromisoformat(closes) if closes else None)
    try:
        for line in body.get("lines") or []:
            rfq_svc.add_line(db, row, product_id=int(line["product_id"]),
                             quantity=int(line.get("quantity") or 0))
        for sid in body.get("supplier_ids") or []:
            rfq_svc.invite(db, row, supplier_id=int(sid))
    except rfq_svc.RfqError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    db.refresh(row)
    return {**_shape(db, row),
            "message": f"{row.reference} raised. Nothing has been asked yet."}


@router.get("/auto")
def auto_settings(db: Session = Depends(get_db)):
    """What would be asked about this morning, and whether it happens by itself.

    Declared above /{rfq_id} deliberately: FastAPI matches in declaration
    order and this would otherwise be read as a request numbered "auto".
    """
    rows = rfq_auto.candidates(db)
    return {
        "trigger": rfq_auto.trigger(db),
        "choices": list(rfq_auto.TRIGGERS),
        "waiting": [
            {"product_id": p.id,
             "product": f"{p.name} {p.strength or ''}".strip(),
             "on_hand": p.quantity_on_hand or 0,
             "reorder_level": p.reorder_level or 0,
             "wanted": rfq_auto.wanted(p)}
            for p in rows
        ],
        "most_lines": rfq_auto.MOST_LINES,
        # Said plainly, because "automatic" makes people assume the worst.
        "note": ("Raised as a draft every morning at a quarter past seven. "
                 "Nothing is ever emailed to a supplier by itself."),
    }


@router.post("/auto")
def set_auto(body: dict = Body(default={}), db: Session = Depends(get_db),
             _may=Depends(auth.requires("stock.receive"))):
    """Choose what gets asked about by itself."""
    want = str(body.get("trigger") or "").strip().lower()
    if want not in rfq_auto.TRIGGERS:
        raise HTTPException(
            400, "Choose one of: " + ", ".join(rfq_auto.TRIGGERS) + ".")
    config.put(db, rfq_auto.SETTING, want)
    db.commit()
    said = {
        "off": "Nothing will be raised automatically. Ask for prices by hand.",
        "out_of_stock": "A draft request will be raised each morning for "
                        "anything that has run out.",
        "reorder": "A draft request will be raised each morning for anything "
                   "at or below its reorder level.",
    }[want]
    return {"trigger": want, "message": said}


@router.post("/auto/run")
def run_auto_now(db: Session = Depends(get_db),
                 _may=Depends(auth.requires("stock.receive"))):
    """Raise it now rather than waiting for the morning.

    A line that runs out at eleven should not have to wait until tomorrow to
    be asked about, and a buyer who has just turned this on wants to see what
    it does before trusting it overnight.
    """
    row = rfq_auto.raise_one(db)
    if row is None:
        return {"raised": False,
                "message": ("Nothing has run out that is not already on order "
                            "or already out for quotation.")}
    db.commit()
    db.refresh(row)
    return {"raised": True, "id": row.id, "reference": row.reference,
            "message": (f"{row.reference} raised with {len(row.lines)} line(s), "
                        f"asking {len(row.invited)} supplier(s). Check it, "
                        "then send it.")}


@router.get("/{rfq_id}")
def get_rfq(rfq_id: int, db: Session = Depends(get_db)):
    """One request, with every answer laid against every line."""
    row = _found(rfq_id, db)
    return {**_shape(db, row), **rfq_svc.compare(db, row),
            "document": rfq_svc.document(db, row,
                                         pharmacy_name=_pharmacy_name(db))}


@router.get("/{rfq_id}/suggested-suppliers")
def suggested(rfq_id: int, db: Session = Depends(get_db)):
    """Who is worth asking, from who has actually supplied these lines."""
    row = _found(rfq_id, db)
    return {"suppliers": rfq_svc.suggest_suppliers(db, row)}


@router.post("/{rfq_id}/invite")
def invite_supplier(rfq_id: int, body: dict = Body(...),
                    db: Session = Depends(get_db)):
    row = _found(rfq_id, db)
    try:
        rfq_svc.invite(db, row, supplier_id=int(body.get("supplier_id") or 0))
    except rfq_svc.RfqError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return {"ok": True, **_shape(db, row)}


@router.post("/{rfq_id}/send")
def send_rfq(rfq_id: int, db: Session = Depends(get_db),
             _may=Depends(auth.requires("stock.receive"))):
    """Email the request to everybody invited who has an address."""
    row = _found(rfq_id, db)
    try:
        said = rfq_svc.send(db, row, pharmacy_name=_pharmacy_name(db))
    except rfq_svc.RfqError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return said


@router.get("/{rfq_id}/suppliers/{invited_id}/link")
def supplier_link(rfq_id: int, invited_id: int, db: Session = Depends(get_db)):
    """The wholesaler's own quote link, for sending by hand.

    The email carries it already. This is for the supplier who says they never
    received it, or who wants it on WhatsApp instead, which in Zimbabwe is
    most of them.
    """
    row = _found(rfq_id, db)
    invited = db.get(RfqSupplier, invited_id)
    if invited is None or invited.rfq_id != row.id:
        raise HTTPException(404, "That supplier was not asked for this request.")
    link = rfq_svc.quote_link(db, invited)
    who = invited.supplier.name if invited.supplier else "the supplier"
    return {
        "link": link,
        "supplier": who,
        "send_to": (invited.supplier.email or "") if invited.supplier else "",
        "expires_in_days": portal_tokens.DEFAULT_TTL // 86400,
        # Written to be sent as it stands. A pharmacy that has to compose the
        # message itself sends a bare URL with no explanation.
        "share_text": (
            f"Good day. {_pharmacy_name(db) or 'We'} would like your best "
            f"price on {len(row.lines)} item(s), reference {row.reference}. "
            f"You can enter them here: {link}"),
        "message": f"Link for {who} created. It lasts "
                   f"{portal_tokens.DEFAULT_TTL // 86400} days.",
    }


@router.post("/{rfq_id}/answers/{invited_id}")
def record_answer(rfq_id: int, invited_id: int, body: dict = Body(...),
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Write down what one wholesaler said.

    Entered by staff, because a supplier cannot sign in yet. Who wrote it
    down is kept: a price nobody can attribute is a price nobody can query.
    """
    row = _found(rfq_id, db)
    invited = db.get(RfqSupplier, invited_id)
    if invited is None or invited.rfq_id != row.id:
        raise HTTPException(404, "That supplier was not asked for this request.")
    said = rfq_svc.record(
        db, invited, answers=body.get("answers") or [], user=user,
        declined=bool(body.get("declined")), note=str(body.get("note") or ""))
    db.commit()
    return said


@router.post("/{rfq_id}/to-orders")
def convert(rfq_id: int, body: dict = Body(...), db: Session = Depends(get_db),
            user: User = Depends(get_current_user),
            _may=Depends(auth.requires("stock.receive"))):
    """Turn the chosen answers into draft purchase orders."""
    row = _found(rfq_id, db)
    try:
        said = rfq_svc.to_orders(db, row, picks=body.get("picks") or [], user=user)
    except rfq_svc.RfqError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return said


@router.post("/{rfq_id}/cancel")
def cancel(rfq_id: int, db: Session = Depends(get_db)):
    row = _found(rfq_id, db)
    if row.status == "closed":
        raise HTTPException(
            409, f"{row.reference} has already been turned into orders.")
    row.status = "cancelled"
    db.commit()
    return {"ok": True, "message": f"{row.reference} cancelled."}
