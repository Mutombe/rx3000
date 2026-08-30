"""Supplier invoices, the three-way match, payments and creditor ageing."""
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from ..auth import get_current_user, require_role
from ..database import get_db
from ..models import (
    PurchaseOrder, Supplier, SupplierInvoice, SupplierInvoiceItem,
    SupplierPayment, User,
)
from ..services import creditor_statement, payables

router = APIRouter(prefix="/api/payables", tags=["payables"],
                   dependencies=[Depends(get_current_user)])


def _loaded(query):
    """The supplier, the order and the lines, rather than three fetches a row.

    `_invoice_json` reached for all three with `db.get`, which is a round trip
    each against a hosted database. Thirteen invoices took nearly five seconds
    to return twelve kilobytes.
    """
    return query.options(
        joinedload(SupplierInvoice.supplier),
        joinedload(SupplierInvoice.order),
        selectinload(SupplierInvoice.items),
    )


def _invoice_json(db: Session, invoice: SupplierInvoice, paid: float = 0.0) -> dict:
    supplier = invoice.supplier
    order = invoice.order
    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "supplier_id": invoice.supplier_id,
        "supplier": supplier.name if supplier else "",
        "order_id": invoice.order_id,
        "order_number": order.order_number if order else "",
        "invoice_date": invoice.invoice_date,
        "due_date": invoice.due_date,
        "total": round(invoice.total or 0.0, 2),
        "vat_total": round(invoice.vat_total or 0.0, 2),
        "currency_code": invoice.currency_code or "USD",
        "status": invoice.status,
        "query_note": invoice.query_note or "",
        "posted_reference": invoice.posted_reference or "",
        "paid": round(paid, 2),
        "outstanding": round((invoice.total or 0.0) - paid, 2),
        "notes": invoice.notes or "",
        "items": [{
            "id": i.id, "product_id": i.product_id,
            "description": i.description or "",
            "quantity": i.quantity or 0,
            "unit_cost": round(i.unit_cost or 0.0, 2),
            "line_total": round(i.line_total or 0.0, 2),
        } for i in invoice.items],
    }


@router.get("/invoices")
def list_invoices(status: str = "", supplier_id: int = 0, q: str = "",
                  limit: int = Query(default=100, le=500),
                  db: Session = Depends(get_db)):
    query = _loaded(db.query(SupplierInvoice))
    if status:
        query = query.filter(SupplierInvoice.status == status)
    if supplier_id:
        query = query.filter(SupplierInvoice.supplier_id == supplier_id)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(SupplierInvoice.invoice_number.ilike(like),
                                 SupplierInvoice.notes.ilike(like)))
    rows = query.order_by(SupplierInvoice.invoice_date.desc(),
                          SupplierInvoice.id.desc()).limit(limit).all()
    paid = payables.paid_against(db, [r.id for r in rows])
    return {"items": [_invoice_json(db, r, paid.get(r.id, 0.0)) for r in rows]}


@router.get("/invoices/{invoice_id}")
def one_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = _loaded(db.query(SupplierInvoice)).filter(
        SupplierInvoice.id == invoice_id).first()
    if invoice is None:
        raise HTTPException(404, "No such invoice.")
    paid = payables.paid_against(db, [invoice_id]).get(invoice_id, 0.0)
    out = _invoice_json(db, invoice, paid)
    out["match"] = payables.match(db, invoice)
    return out


@router.post("/invoices")
def create_invoice(invoice_number: str = Body(...),
                   supplier_id: int = Body(...),
                   total: float = Body(...),
                   order_id: int | None = Body(default=None),
                   invoice_date: date | None = Body(default=None),
                   due_date: date | None = Body(default=None),
                   vat_total: float = Body(default=0.0),
                   items: list[dict] = Body(default=[]),
                   notes: str = Body(default=""),
                   db: Session = Depends(get_db),
                   user: User = Depends(require_role("admin", "pharmacist"))):
    """Record what the supplier billed, and match it against the order."""
    if db.get(Supplier, supplier_id) is None:
        raise HTTPException(400, "No such supplier.")
    # The supplier's own number, so uniqueness is per supplier rather than
    # global: two wholesalers will both eventually issue an "INV-1001".
    clash = (db.query(SupplierInvoice)
               .filter(SupplierInvoice.supplier_id == supplier_id,
                       SupplierInvoice.invoice_number == invoice_number.strip())
               .first())
    if clash:
        raise HTTPException(
            409, f"That supplier's invoice {invoice_number} is already recorded.")

    invoice = SupplierInvoice(
        invoice_number=invoice_number.strip(), supplier_id=supplier_id,
        order_id=order_id or None, invoice_date=invoice_date or date.today(),
        due_date=due_date, total=round(float(total or 0.0), 2),
        vat_total=round(float(vat_total or 0.0), 2), notes=notes or "")
    db.add(invoice)
    db.flush()

    for line in items:
        quantity = int(line.get("quantity") or 0)
        unit_cost = round(float(line.get("unit_cost") or 0.0), 2)
        db.add(SupplierInvoiceItem(
            invoice_id=invoice.id,
            product_id=int(line["product_id"]) if line.get("product_id") else None,
            description=str(line.get("description", ""))[:200],
            quantity=quantity, unit_cost=unit_cost,
            line_total=round(float(line.get("line_total") or quantity * unit_cost), 2)))
    db.commit()
    db.refresh(invoice)

    result = payables.match(db, invoice)
    invoice.status = "matched" if result["matched"] else "unmatched"
    db.commit()
    out = _invoice_json(db, invoice)
    out["match"] = result
    return out


@router.post("/invoices/{invoice_id}/query")
def query_invoice(invoice_id: int, note: str = Body(..., embed=True),
                  db: Session = Depends(get_db),
                  user: User = Depends(require_role("admin", "pharmacist"))):
    """Mark an invoice as being disputed with the supplier.

    A queried invoice still appears in the ageing and still counts as owed. It
    is not a way of hiding a bill; it is a note that somebody has telephoned.
    """
    invoice = db.get(SupplierInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "No such invoice.")
    if invoice.status == "paid":
        raise HTTPException(400, "That invoice has already been paid.")
    invoice.status = "queried"
    invoice.query_note = note.strip()
    db.commit()
    return {"message": f"Invoice {invoice.invoice_number} is marked as queried."}


@router.post("/invoices/{invoice_id}/approve")
def approve_invoice(invoice_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_role("admin", "pharmacist"))):
    """Approve for payment and bring the creditor to what was billed."""
    invoice = db.get(SupplierInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "No such invoice.")
    result = payables.post_invoice(db, invoice, user_id=user.id)
    paid = payables.paid_against(db, [invoice_id]).get(invoice_id, 0.0)
    out = _invoice_json(db, invoice, paid)
    out["posting"] = result
    out["message"] = (
        f"Posted {result.get('reference')}." if result.get("posted")
        else f"Nothing to post: {result.get('reason')}.")
    return out


@router.get("/ageing")
def creditor_ageing(asof: date | None = None, db: Session = Depends(get_db)):
    return payables.ageing(db, asof=asof)


@router.get("/suppliers/{supplier_id}/statement")
def creditor_statement_for(supplier_id: int,
                           since: date | None = None,
                           upto: date | None = None,
                           db: Session = Depends(get_db)):
    """One creditor account, movement by movement, ready to print.

    The document a pharmacy has to be able to put beside the wholesaler's own
    statement. Everything the letterhead needs comes from the profile in one
    call, so this returns only the account.
    """
    doc = creditor_statement.statement(db, supplier_id, since=since, upto=upto)
    if not doc:
        raise HTTPException(404, "No such creditor.")
    return doc


@router.get("/payments")
def list_payments(supplier_id: int = 0, limit: int = Query(default=100, le=500),
                  db: Session = Depends(get_db)):
    query = db.query(SupplierPayment)
    if supplier_id:
        query = query.filter(SupplierPayment.supplier_id == supplier_id)
    rows = query.order_by(SupplierPayment.paid_on.desc(),
                          SupplierPayment.id.desc()).limit(limit).all()
    return {"items": [payables.remittance(db, r.id) for r in rows]}


@router.post("/payments")
def pay(supplier_id: int = Body(...), amount: float = Body(...),
        paid_on: date | None = Body(default=None),
        method: str = Body(default="bank"),
        reference: str = Body(default=""),
        allocations: list[dict] = Body(default=[]),
        notes: str = Body(default=""),
        db: Session = Depends(get_db),
        user: User = Depends(require_role("admin", "pharmacist"))):
    try:
        result = payables.record_payment(
            db, supplier_id=supplier_id, amount=amount, paid_on=paid_on,
            method=method, reference=reference, allocations=allocations,
            notes=notes, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result["remittance"] = payables.remittance(db, result["payment_id"])
    return result


# GET /payments/{id}/remittance was here. /payments already returns each
# payment's remittance with the row, so the screen has it before it is
# asked for.


@router.get("/uninvoiced")
def uninvoiced(db: Session = Depends(get_db)):
    """Goods received that no invoice has arrived for.

    The other half of the match, and the one a pharmacy never thinks to ask
    for. Stock on the shelf with no bill behind it is a liability that has not
    been recorded, and it is invisible until the supplier's statement arrives.
    """
    invoiced = {i.order_id for i in db.query(SupplierInvoice)
                .filter(SupplierInvoice.order_id.isnot(None)).all()}
    rows = (db.query(PurchaseOrder)
              .filter(PurchaseOrder.status == "received")
              .order_by(PurchaseOrder.received_at.desc().nullslast())
              .limit(300).all())
    out = []
    for order in rows:
        if order.id in invoiced:
            continue
        value = round(sum((i.unit_cost or 0.0) * (i.quantity_received or 0)
                          for i in order.items), 2)
        if value <= 0:
            continue
        supplier = db.get(Supplier, order.supplier_id)
        out.append({
            "order_id": order.id, "order_number": order.order_number,
            "supplier_id": order.supplier_id,
            "supplier": supplier.name if supplier else "",
            "received_at": order.received_at, "value": value,
            "days": (date.today() - order.received_at.date()).days
                    if order.received_at else None,
        })
    return {"items": out, "total": round(sum(o["value"] for o in out), 2)}
