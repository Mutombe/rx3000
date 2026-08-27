"""Read-only detail views for the things that had no page of their own.

Most tables in this system named something you could not open. A recall listed
the patients holding a batch and none of them was a link; the creditor ageing
named six suppliers and none of them led anywhere. The reader's next move was
always the same — memorise a name, go to another screen, search for it — which
is what a printout makes you do, and software should not.

Each of these answers the two questions a detail page exists for: *what is this
thing*, and *what else is attached to it*. A supplier without its orders is a
name and a telephone number; with them it is an account you can reason about.

Everything here is a GET. Editing already lives on the screens that own these
records, and duplicating it would mean two places to keep right.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user
from ..database import get_db
from ..models import (
    Campaign, Claim, Dispensing, Doctor, Message, Patient, Prescription,
    PrescriptionItem, Product, PurchaseOrder, PurchaseOrderItem, Sale, Shift,
    StockBatch, Supplier, SupplierInvoice, SupplierPayment, User,
)
from ..services import payables

router = APIRouter(prefix="/api", tags=["detail"],
                   dependencies=[Depends(get_current_user)])


def _found(obj, what: str):
    if obj is None:
        raise HTTPException(404, f"That {what} no longer exists.")
    return obj


def _person(patient: Patient | None) -> dict:
    if patient is None:
        # A walk-in. Named rather than left blank, because "" on a detail page
        # reads as data that failed to load.
        return {"id": None, "name": "Walk-in", "phone": ""}
    return {"id": patient.id,
            "name": f"{patient.first_name} {patient.last_name}".strip(),
            "phone": patient.phone or ""}


# ------------------------------------------------------------------ supplier

@router.get("/suppliers/{supplier_id}")
def supplier(supplier_id: int, db: Session = Depends(get_db)):
    """A supplier, its orders, what it has billed and what it has been paid."""
    row = _found(db.get(Supplier, supplier_id), "supplier")

    orders = (db.query(PurchaseOrder)
                .filter(PurchaseOrder.supplier_id == supplier_id)
                .order_by(PurchaseOrder.created_at.desc()).limit(100).all())
    invoices = (db.query(SupplierInvoice)
                  .filter(SupplierInvoice.supplier_id == supplier_id)
                  .order_by(SupplierInvoice.invoice_date.desc()).limit(100).all())
    payments = (db.query(SupplierPayment)
                  .filter(SupplierPayment.supplier_id == supplier_id)
                  .order_by(SupplierPayment.paid_on.desc()).limit(100).all())
    paid = payables.paid_against(db, [i.id for i in invoices])

    # What this supplier actually delivers, taken from the orders rather than a
    # field nobody maintains.
    lines = (db.query(Product.id, Product.name, Product.strength,
                      func.sum(PurchaseOrderItem.quantity_received),
                      func.max(PurchaseOrderItem.unit_cost))
               .join(PurchaseOrderItem, PurchaseOrderItem.product_id == Product.id)
               .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.order_id)
               .filter(PurchaseOrder.supplier_id == supplier_id)
               .group_by(Product.id, Product.name, Product.strength)
               .order_by(func.sum(PurchaseOrderItem.quantity_received).desc())
               .limit(60).all())

    owed = round(sum((i.total or 0.0) - paid.get(i.id, 0.0) for i in invoices), 2)
    return {
        "id": row.id, "name": row.name,
        "contact_person": row.contact_person or "",
        "phone": row.phone or "", "email": row.email or "",
        "owed": owed,
        "orders": [{"id": o.id, "order_number": o.order_number,
                    "status": o.status, "created_at": o.created_at,
                    "received_at": o.received_at,
                    "value": round(sum((i.unit_cost or 0.0) * (i.quantity_ordered or 0)
                                       for i in o.items), 2)}
                   for o in orders],
        "invoices": [{"id": i.id, "invoice_number": i.invoice_number,
                      "invoice_date": i.invoice_date, "due_date": i.due_date,
                      "total": round(i.total or 0.0, 2),
                      "outstanding": round((i.total or 0.0) - paid.get(i.id, 0.0), 2),
                      "status": i.status, "order_id": i.order_id}
                     for i in invoices],
        "payments": [{"id": p.id, "paid_on": p.paid_on,
                      "amount": round(p.amount or 0.0, 2),
                      "method": p.method, "reference": p.reference or ""}
                     for p in payments],
        "supplies": [{"product_id": pid, "product": f"{name} {strength or ''}".strip(),
                      "units_received": int(units or 0),
                      "last_cost": round(cost or 0.0, 2)}
                     for pid, name, strength, units, cost in lines],
    }


# --------------------------------------------------------------------- claim

@router.get("/claims/{claim_id}")
def claim(claim_id: int, db: Session = Depends(get_db)):
    """One claim: what was billed, what came back, and what the patient owes."""
    row = _found(
        db.query(Claim)
          .options(joinedload(Claim.patient), joinedload(Claim.medical_aid),
                   joinedload(Claim.sale))
          .filter(Claim.id == claim_id).first(),
        "claim")

    items = []
    if row.sale_id:
        items = (db.query(Sale)
                   .filter(Sale.id == row.sale_id).first())
        items = items.items if items else []

    return {
        "id": row.id, "claim_number": row.claim_number,
        "status": row.status,
        "patient": _person(row.patient),
        "scheme": {"id": row.medical_aid_id,
                   "name": row.medical_aid.name if row.medical_aid else ""},
        "sale_id": row.sale_id,
        "sale_number": row.sale.sale_number if row.sale else "",
        "gross": round(row.gross or 0.0, 2),
        "discount": round(row.discount or 0.0, 2),
        "levy": round(row.levy or 0.0, 2),
        "dispensing_fee": round(row.dispensing_fee or 0.0, 2),
        "amount_claimed": round(row.amount_claimed or 0.0, 2),
        "amount_approved": round(row.amount_approved or 0.0, 2),
        "settled_amount": round(row.settled_amount or 0.0, 2),
        "patient_liable": round(row.patient_liable or 0.0, 2),
        # The shortfall said out loud. It is the number the patient argues
        # about, and it was only ever implied by two others.
        "shortfall": round((row.amount_claimed or 0.0) - (row.amount_approved or 0.0), 2),
        "icd10_code": row.icd10_code or "",
        "authorisation": row.authorisation or "",
        "response_message": row.response_message or "",
        "deferred_reason": row.deferred_reason or "",
        "submitted_at": row.submitted_at, "settled_at": row.settled_at,
        "submit_attempts": row.submit_attempts or 0,
        "created_at": row.created_at,
        "lines": [{"product_id": i.product_id,
                   "product": (f"{i.product.name} {i.product.strength or ''}".strip()
                               if getattr(i, "product", None) else ""),
                   "quantity": i.quantity,
                   "line_total": round(i.line_total or 0.0, 2)}
                  for i in items],
    }


# --------------------------------------------------------------- stock batch

@router.get("/stock/batches/{batch_id}")
def stock_batch(batch_id: int, db: Session = Depends(get_db)):
    """A batch: what it is, where it came from, and where it went.

    The forward trace is the recall service's, reused rather than rewritten —
    two answers to "who has this batch" would eventually disagree.
    """
    from ..services import recall

    row = _found(db.get(StockBatch, batch_id), "batch")
    traced = recall.trace(db, batch_id)
    product = db.get(Product, row.product_id)
    days = ((row.expiry_date - date.today()).days
            if row.expiry_date else None)
    return {
        "id": row.id, "batch_number": row.batch_number or "",
        "product_id": row.product_id,
        "product": f"{product.name} {product.strength or ''}".strip() if product else "",
        "schedule": product.schedule if product else 0,
        "expiry_date": row.expiry_date,
        "days_to_expiry": days,
        "quantity_received": row.quantity_received,
        "quantity_remaining": row.quantity_remaining,
        "unit_cost": round(row.unit_cost or 0.0, 2),
        "value_on_hand": round((row.quantity_remaining or 0) * (row.unit_cost or 0.0), 2),
        "received_at": row.received_at,
        "reference": row.reference or "",
        "origin": traced.get("origin", {}),
        "quantities": traced.get("quantities", {}),
        "recipients": traced.get("recipients", [])[:100],
        "warnings": traced.get("warnings", []),
    }


# --------------------------------------------------------------------- staff

@router.get("/users/{user_id}")
def staff(user_id: int, db: Session = Depends(get_db)):
    """A member of staff, and what they have actually done.

    Deliberately a record of work rather than a permissions screen: who
    dispensed what, which tills they cashed up. The account settings live in the
    control panel and are not repeated here.
    """
    row = _found(db.get(User, user_id), "member of staff")

    dispensed = (db.query(func.count(Dispensing.id))
                   .filter(Dispensing.dispensed_by_id == user_id).scalar() or 0)
    recent = (db.query(Dispensing)
                .options(joinedload(Dispensing.prescription_item)
                         .joinedload(PrescriptionItem.product),
                         joinedload(Dispensing.prescription_item)
                         .joinedload(PrescriptionItem.prescription)
                         .joinedload(Prescription.patient))
                .filter(Dispensing.dispensed_by_id == user_id)
                .order_by(Dispensing.dispensed_at.desc()).limit(50).all())
    shifts = (db.query(Shift).filter(Shift.user_id == user_id)
                .order_by(Shift.opened_at.desc()).limit(30).all())

    return {
        "id": row.id, "username": row.username, "full_name": row.full_name,
        "role": row.role, "active": bool(row.active),
        "is_demo": bool(getattr(row, "is_demo", False)),
        "dispensed_count": int(dispensed),
        "shift_count": db.query(func.count(Shift.id))
                         .filter(Shift.user_id == user_id).scalar() or 0,
        "dispensings": [{
            "id": d.id,
            "dispensed_at": d.dispensed_at,
            "quantity": d.quantity,
            "schedule": d.schedule,
            "product_id": (d.prescription_item.product_id
                           if d.prescription_item else None),
            "product": (f"{d.prescription_item.product.name} "
                        f"{d.prescription_item.product.strength or ''}".strip()
                        if d.prescription_item and d.prescription_item.product else ""),
            "prescription_id": (d.prescription_item.prescription_id
                                if d.prescription_item else None),
            "rx_number": (d.prescription_item.prescription.rx_number
                          if d.prescription_item and d.prescription_item.prescription
                          else ""),
            "patient": _person(d.prescription_item.prescription.patient
                               if d.prescription_item and d.prescription_item.prescription
                               else None),
        } for d in recent],
        "shifts": [{"id": s.id, "opened_at": s.opened_at, "closed_at": s.closed_at,
                    "status": s.status,
                    "variance": round(getattr(s, "variance", 0.0) or 0.0, 2)}
                   for s in shifts],
    }


# ---------------------------------------------------------------- prescriber

@router.get("/doctors/{doctor_id}")
def prescriber(doctor_id: int, db: Session = Depends(get_db)):
    """A prescriber and the scripts they have sent in."""
    row = _found(db.get(Doctor, doctor_id), "prescriber")

    scripts = (db.query(Prescription)
                 .options(joinedload(Prescription.patient))
                 .filter(Prescription.doctor_id == doctor_id)
                 .order_by(Prescription.created_at.desc()).limit(100).all())
    total = (db.query(func.count(Prescription.id))
               .filter(Prescription.doctor_id == doctor_id).scalar() or 0)

    # What they prescribe most, which is the useful thing to know about a
    # prescriber the pharmacy deals with often.
    top = (db.query(Product.id, Product.name, Product.strength,
                    func.count(PrescriptionItem.id))
             .join(PrescriptionItem, PrescriptionItem.product_id == Product.id)
             .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
             .filter(Prescription.doctor_id == doctor_id)
             .group_by(Product.id, Product.name, Product.strength)
             .order_by(func.count(PrescriptionItem.id).desc()).limit(15).all())

    return {
        "id": row.id, "name": row.name,
        "practice_number": getattr(row, "practice_number", "") or "",
        "phone": getattr(row, "phone", "") or "",
        "email": getattr(row, "email", "") or "",
        "speciality": getattr(row, "speciality", "") or "",
        "script_count": int(total),
        "prescriptions": [{"id": p.id, "rx_number": p.rx_number,
                           "status": p.status,
                           "date_prescribed": p.date_prescribed,
                           "created_at": p.created_at,
                           "patient": _person(p.patient)}
                          for p in scripts],
        "most_prescribed": [{"product_id": pid,
                             "product": f"{name} {strength or ''}".strip(),
                             "times": int(n)}
                            for pid, name, strength, n in top],
    }


# ------------------------------------------------------------------ campaign

@router.get("/marketing/campaigns/{campaign_id}")
def campaign(campaign_id: int, db: Session = Depends(get_db)):
    """A campaign and what it actually sent."""
    row = _found(db.get(Campaign, campaign_id), "campaign")
    sent = (db.query(Message)
              .options(joinedload(Message.patient))
              .filter(Message.campaign_id == campaign_id)
              .order_by(Message.scheduled_for.desc()).limit(200).all()
            if hasattr(Message, "campaign_id") else [])
    by_status: dict[str, int] = {}
    for m in sent:
        by_status[m.status] = by_status.get(m.status, 0) + 1
    return {
        "id": row.id, "name": row.name,
        "channel": getattr(row, "channel", ""),
        "segment": getattr(row, "segment", ""),
        "subject": getattr(row, "subject", "") or "",
        "body": getattr(row, "body", "") or "",
        "status": getattr(row, "status", ""),
        "created_at": getattr(row, "created_at", None),
        "sent_count": len(sent),
        "by_status": by_status,
        "messages": [{"id": m.id, "status": m.status, "channel": m.channel,
                      "scheduled_for": m.scheduled_for, "sent_at": m.sent_at,
                      "patient": _person(m.patient)}
                     for m in sent[:100]],
    }


# --------------------------------------------------------------------- shift

@router.get("/shifts/{shift_id}")
def shift(shift_id: int, db: Session = Depends(get_db)):
    """One till session: who had it, what went through it, and the variance."""
    row = _found(
        db.query(Shift).options(joinedload(Shift.user),
                                joinedload(Shift.counted_by))
          .filter(Shift.id == shift_id).first(),
        "shift")

    sales = []
    if row.opened_at:
        finish = row.closed_at or datetime.utcnow()
        sales = (db.query(Sale)
                   .options(joinedload(Sale.patient))
                   .filter(Sale.created_at >= row.opened_at,
                           Sale.created_at <= finish,
                           Sale.cashier_id == row.user_id)
                   .order_by(Sale.created_at.desc()).limit(200).all())

    return {
        "id": row.id,
        "user": {"id": row.user_id,
                 "name": row.user.full_name if row.user else ""},
        "counted_by": {"id": getattr(row, "counted_by_id", None),
                       "name": row.counted_by.full_name if row.counted_by else ""},
        "status": row.status,
        "opened_at": row.opened_at, "closed_at": row.closed_at,
        "opening_float": round(getattr(row, "opening_float", 0.0) or 0.0, 2),
        "counted_total": round(getattr(row, "counted_total", 0.0) or 0.0, 2),
        "expected_total": round(getattr(row, "expected_total", 0.0) or 0.0, 2),
        "variance": round(getattr(row, "variance", 0.0) or 0.0, 2),
        "notes": getattr(row, "notes", "") or "",
        "sale_count": len(sales),
        "sales_value": round(sum(s.total or 0.0 for s in sales), 2),
        "sales": [{"id": s.id, "sale_number": s.sale_number,
                   "created_at": s.created_at,
                   "total": round(s.total or 0.0, 2),
                   "payment_method": s.payment_method,
                   "patient": _person(s.patient)}
                  for s in sales[:100]],
    }


# ------------------------------------------------------------------- message

@router.get("/messages/{message_id}")
def message(message_id: int, db: Session = Depends(get_db)):
    """One message, in full, with the others sent to the same patient."""
    row = _found(
        db.query(Message).options(joinedload(Message.patient))
          .filter(Message.id == message_id).first(),
        "message")

    siblings = []
    if row.patient_id:
        siblings = (db.query(Message)
                      .filter(Message.patient_id == row.patient_id,
                              Message.id != row.id)
                      .order_by(Message.scheduled_for.desc()).limit(30).all())
    return {
        "id": row.id,
        "patient": _person(row.patient),
        "channel": row.channel, "message_type": row.message_type,
        "subject": row.subject or "", "body": row.body or "",
        "status": row.status, "detail": row.detail or "",
        "scheduled_for": row.scheduled_for, "sent_at": row.sent_at,
        "campaign_id": getattr(row, "campaign_id", None),
        "history": [{"id": m.id, "channel": m.channel,
                     "message_type": m.message_type, "status": m.status,
                     "subject": m.subject or "",
                     "scheduled_for": m.scheduled_for, "sent_at": m.sent_at}
                    for m in siblings],
    }
