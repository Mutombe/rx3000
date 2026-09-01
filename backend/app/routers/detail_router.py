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


# ------------------------------------------------------------------ will-call

@router.get("/dispensing/will-call/{dispensing_id}")
def will_call_bag(dispensing_id: int, db: Session = Depends(get_db)):
    """One bag on the shelf: what is in it, who it is for, and what is owed.

    The shelf listed bags and opened none of them, so the questions asked at
    the counter — is this the right bag, has it been paid for, who may take it,
    how long has it been here — were answered by reading a row and guessing.
    """
    from ..services import willcall

    d = _found(
        db.query(Dispensing)
          .options(joinedload(Dispensing.prescription_item)
                   .joinedload(PrescriptionItem.product),
                   joinedload(Dispensing.prescription_item)
                   .joinedload(PrescriptionItem.prescription)
                   .joinedload(Prescription.patient),
                   joinedload(Dispensing.prescription_item)
                   .joinedload(PrescriptionItem.prescription)
                   .joinedload(Prescription.doctor),
                   joinedload(Dispensing.dispensed_by))
          .filter(Dispensing.id == dispensing_id).first(),
        "bag")

    item = d.prescription_item
    rx = item.prescription if item else None
    product = item.product if item else None
    days = (datetime.utcnow() - d.dispensed_at).days if d.dispensed_at else 0
    band, action = willcall._band(days)

    sale = db.get(Sale, d.sale_id) if d.sale_id else None
    owed = 0.0
    claim = None
    if sale is not None:
        claim = (db.query(Claim)
                   .filter(Claim.sale_id == sale.id,
                           Claim.status.notin_(("rejected", "reversed"))).first())
        if sale.status not in ("paid", "void"):
            from ..models import SaleTender

            paid = (db.query(func.coalesce(func.sum(SaleTender.amount_in_base), 0.0))
                      .filter(SaleTender.sale_id == sale.id).scalar() or 0.0)
            covered = float(claim.amount_approved) if claim else 0.0
            owed = max(0.0, round((sale.total or 0.0) - covered - float(paid), 2))

    # Everything else waiting for the same patient, so a bag is not handed over
    # while its other half stays on the shelf.
    alongside = []
    if rx and rx.patient_id:
        for other in (db.query(Dispensing)
                        .join(PrescriptionItem,
                              Dispensing.prescription_item_id == PrescriptionItem.id)
                        .join(Prescription,
                              PrescriptionItem.prescription_id == Prescription.id)
                        .options(joinedload(Dispensing.prescription_item)
                                 .joinedload(PrescriptionItem.product))
                        .filter(Prescription.patient_id == rx.patient_id,
                                Dispensing.collected_at.is_(None),
                                Dispensing.id != d.id).limit(20).all()):
            other_item = other.prescription_item
            other_product = other_item.product if other_item else None
            alongside.append({
                "dispensing_id": other.id,
                "product": (f"{other_product.name} {other_product.strength or ''}".strip()
                            if other_product else ""),
                "quantity": other.quantity,
                "dispensed_at": other.dispensed_at,
            })

    return {
        "dispensing_id": d.id,
        "quantity": d.quantity,
        "schedule": d.schedule or 0,
        "is_repeat": bool(d.is_repeat),
        "dispensed_at": d.dispensed_at,
        "dispensed_by_id": d.dispensed_by_id,
        "dispensed_by": d.dispensed_by.full_name if d.dispensed_by else "",
        "pharmacist_initial": d.pharmacist_initial or "",
        "collected_at": d.collected_at,
        "collected_name": d.collected_name or "",
        "days_waiting": days,
        "band": band,
        "action": action,
        # A controlled bag cannot go to whoever turns up, and the counter has
        # to know that before the person is standing there.
        "needs_id": (d.schedule or 0) >= 5,
        "product_id": item.product_id if item else None,
        "product": (f"{product.name} {product.strength or ''}".strip()
                    if product else ""),
        "directions": item.dosage_instructions if item else "",
        "prescription_id": rx.id if rx else None,
        "rx_number": rx.rx_number if rx else "",
        "prescriber_id": rx.doctor_id if rx else None,
        "prescriber": rx.doctor.name if rx and rx.doctor else "",
        "patient": _person(rx.patient if rx else None),
        "sale_id": sale.id if sale else None,
        "sale_number": sale.sale_number if sale else "",
        "sale_status": sale.status if sale else "",
        "sale_total": round(sale.total, 2) if sale else 0.0,
        "outstanding": owed,
        "claim_id": claim.id if claim else None,
        "scheme_pays": round(claim.amount_approved, 2) if claim else 0.0,
        "alongside": alongside,
    }


# --------------------------------------------------------------- dispensing

@router.get("/dispensings/{dispensing_id}")
def dispensing_detail(dispensing_id: int, db: Session = Depends(get_db)):
    """One handover, in full.

    The dispensing history listed thousands of these and opened none of them.
    Every column on that list was a link to something *else* — the script, the
    patient, the prescriber, and the dispensing itself, which is the record of
    what a named pharmacist actually handed to a named person on a named day,
    was the one thing you could not read.

    That is the wrong way round. On a controlled item this row IS the legal
    record, and "who had it, checked by whom, against which script" is a
    question asked by an inspector rather than out of curiosity.
    """
    d = _found(
        db.query(Dispensing)
          .options(joinedload(Dispensing.prescription_item)
                   .joinedload(PrescriptionItem.product),
                   joinedload(Dispensing.prescription_item)
                   .joinedload(PrescriptionItem.prescription)
                   .joinedload(Prescription.patient),
                   joinedload(Dispensing.prescription_item)
                   .joinedload(PrescriptionItem.prescription)
                   .joinedload(Prescription.doctor),
                   joinedload(Dispensing.dispensed_by),
                   joinedload(Dispensing.collected_by))
          .filter(Dispensing.id == dispensing_id).first(),
        "dispensing")

    item = d.prescription_item
    rx = item.prescription if item else None
    product = item.product if item else None
    sale = db.get(Sale, d.sale_id) if d.sale_id else None

    # What was charged for this line, rather than the whole sale. A script of
    # four items settled as one figure says nothing about this one.
    line_value = 0.0
    if sale is not None and product is not None:
        from ..models import SaleItem

        line = (db.query(SaleItem)
                  .filter(SaleItem.sale_id == sale.id,
                          SaleItem.product_id == product.id).first())
        line_value = round(float(line.line_total or 0.0), 2) if line else 0.0

    # The rest of the script, so this handover can be read in context: a bag
    # with one of three items in it is a different thing from a completed
    # script, and only the siblings say which.
    siblings = []
    if rx is not None:
        for other in (db.query(Dispensing)
                        .options(joinedload(Dispensing.prescription_item)
                                 .joinedload(PrescriptionItem.product))
                        .join(PrescriptionItem,
                              PrescriptionItem.id == Dispensing.prescription_item_id)
                        .filter(PrescriptionItem.prescription_id == rx.id,
                                Dispensing.id != d.id)
                        .order_by(Dispensing.dispensed_at.desc()).limit(20).all()):
            sibling_product = (other.prescription_item.product
                               if other.prescription_item else None)
            siblings.append({
                "id": other.id,
                "product": sibling_product.name if sibling_product else "—",
                "quantity": other.quantity,
                "dispensed_at": other.dispensed_at,
                "collected_at": other.collected_at,
            })

    # Where this sits in the repeat cycle. A fill is not just an event; it is
    # the third of six, and that is what tells somebody whether the patient is
    # keeping up.
    repeat = None
    if item is not None and (item.repeats_allowed or 0) > 0:
        repeat = {
            "item_id": item.id,
            "allowed": item.repeats_allowed or 0,
            "used": item.repeats_used or 0,
            "left": max(0, (item.repeats_allowed or 0) - (item.repeats_used or 0)),
            "next_due": item.next_repeat_date,
            "interval_days": item.repeat_interval_days or 0,
        }

    return {
        "id": d.id,
        "quantity": d.quantity,
        "dispensed_at": d.dispensed_at,
        "is_repeat": bool(d.is_repeat),
        "dispensed_by": (d.dispensed_by.full_name if d.dispensed_by else ""),
        "dispensed_by_id": d.dispensed_by_id,
        "pharmacist_initial": d.pharmacist_initial or "",
        # ---- the controlled-substance record ----------------------------
        #
        # Present on every dispensing rather than only on scheduled ones, so a
        # blank identity check on an S5 is visible as a blank rather than as a
        # missing section somebody has to notice is absent.
        "dispense_type": d.dispense_type or "prescription",
        "schedule": d.schedule or 0,
        "id_verified": bool(d.id_verified),
        "id_number_seen": d.id_number_seen or "",
        "script_sighted": bool(d.script_sighted),
        "prescriber_verified": bool(d.prescriber_verified),
        "compliance_notes": d.compliance_notes or "",
        # ---- collection ---------------------------------------------------
        "collected_at": d.collected_at,
        "collected_name": d.collected_name or "",
        "collected_by": (d.collected_by.full_name if d.collected_by else ""),
        "days_waiting": ((datetime.utcnow() - d.dispensed_at).days
                         if d.dispensed_at and not d.collected_at else None),
        # ---- what and for whom --------------------------------------------
        "product": ({"id": product.id,
                     "name": f"{product.name} {product.strength or ''}".strip(),
                     "form": product.dosage_form or "",
                     "schedule": product.schedule or 0}
                    if product else None),
        "patient": _person(rx.patient if rx else None),
        "prescription": ({"id": rx.id, "number": rx.rx_number or "",
                          "date": rx.date_prescribed,
                          "doctor": (rx.doctor.name if rx.doctor else ""),
                          "doctor_id": rx.doctor_id}
                         if rx else None),
        "directions": item.dosage_instructions if item else "",
        "icd10_code": item.icd10_code if item else "",
        "sale": ({"id": sale.id, "number": sale.sale_number,
                  "status": sale.status, "total": round(sale.total or 0.0, 2),
                  "line_value": line_value}
                 if sale else None),
        "repeat": repeat,
        "siblings": siblings,
    }


# ------------------------------------------------------------------- repeat

@router.get("/repeats/item/{item_id}")
def repeat_detail(item_id: int, db: Session = Depends(get_db)):
    """One repeat: what it is worth, how it has run, and whether it can be filled.

    Named `/repeats/item/{id}` rather than `/repeats/{id}` deliberately. There
    are already `/repeats/call-sheet`, `/repeats/performance` and
    `/repeats/churn`, and a bare `{id}` above them would swallow all three and
    answer 422 "not a valid integer" for the rest of its life. That has
    happened here before.
    """
    item = _found(
        db.query(PrescriptionItem)
          .options(joinedload(PrescriptionItem.product),
                   joinedload(PrescriptionItem.prescription)
                   .joinedload(Prescription.patient),
                   joinedload(PrescriptionItem.prescription)
                   .joinedload(Prescription.doctor))
          .filter(PrescriptionItem.id == item_id).first(),
        "repeat")

    rx = item.prescription
    product = item.product
    allowed = item.repeats_allowed or 0
    used = item.repeats_used or 0

    fills = (db.query(Dispensing)
               .options(joinedload(Dispensing.dispensed_by))
               .filter(Dispensing.prescription_item_id == item.id)
               .order_by(Dispensing.dispensed_at.desc()).all())

    # What one fill is worth. The whole point of the repeat book is that it is
    # money, and a queue that does not say what a line is worth cannot be
    # worked in the order that pays.
    unit = float(product.unit_price or 0.0) if product else 0.0
    per_fill = round(unit * (item.quantity or 0), 2)

    # Can it actually be supplied? Against unexpired batches, because that is
    # what dispensing draws from. The product's own count is the figure most
    # screens show and the one dispensing does not obey — reading it here said
    # "none on hand" for a medicine with 267 usable units.
    on_hand = 0
    if product is not None:
        on_hand = int(
            db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
              .filter(StockBatch.product_id == product.id,
                      StockBatch.quantity_remaining > 0)
              .filter((StockBatch.expiry_date.is_(None))
                      | (StockBatch.expiry_date >= date.today()))
              .scalar() or 0)

    due = item.next_repeat_date
    overdue_days = (date.today() - due).days if due and due < date.today() else 0

    # The gap the patient actually keeps, against the one the script asks for.
    # Two fills 45 days apart on a 30-day script is a patient running out for a
    # fortnight every month, and nothing said so.
    gaps = []
    dates = sorted([f.dispensed_at for f in fills if f.dispensed_at])
    for earlier, later in zip(dates, dates[1:]):
        gaps.append((later - earlier).days)
    average_gap = round(sum(gaps) / len(gaps)) if gaps else None

    return {
        "item_id": item.id,
        "patient": _person(rx.patient if rx else None),
        "product": ({"id": product.id,
                     "name": f"{product.name} {product.strength or ''}".strip(),
                     "form": product.dosage_form or "",
                     "schedule": product.schedule or 0,
                     "unit_price": round(unit, 2)}
                    if product else None),
        "prescription": ({"id": rx.id, "number": rx.rx_number or "",
                          "date": rx.date_prescribed,
                          "doctor": (rx.doctor.name if rx.doctor else ""),
                          "doctor_id": rx.doctor_id}
                         if rx else None),
        "directions": item.dosage_instructions or "",
        "icd10_code": item.icd10_code or "",
        "quantity": item.quantity or 0,
        "supply_days": item.supply_days or 0,
        "interval_days": item.repeat_interval_days or 0,
        "auto_refill": bool(item.auto_refill),
        # ---- where it has got to ------------------------------------------
        "allowed": allowed,
        "used": used,
        "left": max(0, allowed - used),
        "exhausted": allowed > 0 and used >= allowed,
        "next_due": due,
        "overdue_days": overdue_days,
        # ---- what it is worth ---------------------------------------------
        "value_per_fill": per_fill,
        "value_remaining": round(per_fill * max(0, allowed - used), 2),
        "value_filled": round(per_fill * used, 2),
        # ---- can we supply it ---------------------------------------------
        "on_hand": on_hand,
        "can_supply": on_hand >= (item.quantity or 0),
        # ---- how the patient has actually run it ---------------------------
        "average_gap_days": average_gap,
        "keeping_up": (None if average_gap is None or not item.repeat_interval_days
                       else average_gap <= (item.repeat_interval_days or 0) + 7),
        "fills": [{
            "id": f.id, "quantity": f.quantity,
            "dispensed_at": f.dispensed_at,
            "collected_at": f.collected_at,
            "by": f.dispensed_by.full_name if f.dispensed_by else "",
            "is_repeat": bool(f.is_repeat),
        } for f in fills],
    }
