"""Waybills, quick pricing, and export.

Three counter functions the incumbent has and RX3000 did not.
"""
import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .. import helpers, schedule_policy
from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import (
    MedicalAid, Patient, Prescription, Product, Sale, User, Waybill,
)
from ..services import pricing, branches

router = APIRouter(prefix="/api", tags=["dispensing-extras"],
                   dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Quick pricing — "what will this cost me on my scheme?"
# ---------------------------------------------------------------------------

@router.post("/quick-price")
def quick_price(product_id: int = Body(...), quantity: int = Body(default=1),
                medical_aid_id: int | None = Body(default=None),
                db: Session = Depends(get_db)):
    """Price something without starting a script.

    A patient at the counter asks what a repeat will cost them. Answering that
    in seconds — without capturing a script that then has to be abandoned — is a
    counter-speed function staff use dozens of times a day, and the alternative
    is a pharmacist doing arithmetic on a till roll.
    """
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive.")

    aid = db.get(MedicalAid, medical_aid_id) if medical_aid_id else None
    priced = pricing.price_line(db, product, quantity, aid)
    policy = schedule_policy.policy_for(product.schedule)

    cash_total = round(product.unit_price * quantity, 2)
    # On a scheme the price is the regulated one, not the shelf price — the
    # dispensing fee and any levy are part of what the patient is quoted.
    scheme_total = round(priced.gross, 2) if aid else cash_total
    return {
        "product_id": product.id,
        "product": f"{product.name} {product.strength}".strip(),
        "quantity": quantity,
        "classification": policy.code,
        "route": policy.route,
        "requires_prescription": policy.requires_prescription,
        "cash_price": cash_total,
        "scheme": aid.name if aid else "",
        "scheme_price": scheme_total,
        "dispensing_fee": round(priced.dispensing_fee, 2) if aid else 0.0,
        # What the scheme pays and what the patient pays are different answers
        # to different questions, and the patient is asking the second one.
        "scheme_pays": round(priced.claimable, 2) if aid else 0.0,
        "patient_pays": round(priced.patient_portion, 2) if aid else cash_total,
        "levy": round(priced.levy, 2) if aid else 0.0,
        "in_stock": product.quantity_on_hand,
        "can_supply": product.quantity_on_hand >= quantity,
        "note": ("" if not aid else
                 "An estimate from the scheme's terms on file. The funder's own "
                 "adjudication is the final answer."),
    }


# ---------------------------------------------------------------------------
# Waybills
# ---------------------------------------------------------------------------

def _row(w: Waybill) -> dict:
    return {
        "id": w.id, "waybill_number": w.waybill_number, "status": w.status,
        "sale_id": w.sale_id, "patient_id": w.patient_id,
        "recipient": w.recipient, "address": w.address, "phone": w.phone,
        "instructions": w.instructions,
        "driver": w.driver.full_name if w.driver else "",
        "received_by": w.received_by, "failure_reason": w.failure_reason,
        "requires_id_check": w.requires_id_check, "id_number_seen": w.id_number_seen,
        "created_at": w.created_at, "dispatched_at": w.dispatched_at,
        "delivered_at": w.delivered_at,
        "created_by": w.created_by.full_name if w.created_by else "",
    }


@router.post("/waybills")
def create_waybill(sale_id: int | None = Body(default=None),
                   patient_id: int | None = Body(default=None),
                   recipient: str = Body(default=""), address: str = Body(default=""),
                   phone: str = Body(default=""), instructions: str = Body(default=""),
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Raise a delivery note for a dispensed sale."""
    sale = db.get(Sale, sale_id) if sale_id else None
    if sale_id and not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    patient = db.get(Patient, patient_id) if patient_id else (sale.patient if sale else None)

    if not (recipient or patient):
        raise HTTPException(status_code=400,
                            detail="A delivery needs a recipient or a patient.")
    if not (address or (patient and patient.address)):
        raise HTTPException(status_code=400,
                            detail="A delivery needs an address to go to.")

    # A controlled item leaving the premises has to be identified at the door,
    # because it never reaches the counter where that would normally happen.
    controlled = False
    if sale:
        for item in sale.items:
            if item.product and schedule_policy.policy_for(item.product.schedule).register_entry:
                controlled = True
                break

    waybill = Waybill(
        waybill_number=helpers.next_number(db, Waybill, "WB", "waybill_number"),
        sale_id=sale.id if sale else None,
        patient_id=patient.id if patient else None,
        recipient=recipient or (f"{patient.first_name} {patient.last_name}".strip()
                                if patient else ""),
        address=address or (patient.address if patient else ""),
        phone=phone or (patient.phone if patient else ""),
        instructions=instructions,
        requires_id_check=controlled,
        created_by_id=user.id,
    )
    db.add(waybill)
    db.commit()
    db.refresh(waybill)
    return _row(waybill)


@router.get("/waybills")
def list_waybills(status: str = "", limit: int = 200, db: Session = Depends(get_db)):
    query = db.query(Waybill)
    if status:
        query = query.filter(Waybill.status == status)
    return [_row(w) for w in query.order_by(desc(Waybill.created_at)).limit(limit).all()]


@router.get("/waybills/{waybill_id}")
def get_waybill(waybill_id: int, db: Session = Depends(get_db)):
    w = db.get(Waybill, waybill_id)
    if not w:
        raise HTTPException(status_code=404, detail="Waybill not found")
    return _row(w)


@router.post("/waybills/{waybill_id}/dispatch")
def dispatch(waybill_id: int, driver_id: int | None = Body(default=None, embed=True),
             db: Session = Depends(get_db)):
    w = db.get(Waybill, waybill_id)
    if not w:
        raise HTTPException(status_code=404, detail="Waybill not found")
    if w.status != "pending":
        raise HTTPException(status_code=400, detail=f"Waybill is {w.status}, not pending.")
    w.status = "out"
    w.driver_id = driver_id
    w.dispatched_at = datetime.utcnow()
    db.commit()
    return _row(w)


@router.post("/waybills/{waybill_id}/deliver")
def deliver(waybill_id: int, received_by: str = Body(..., embed=True),
            id_number_seen: str = Body(default="", embed=True),
            db: Session = Depends(get_db)):
    """Close a delivery. Somebody has to have signed for it."""
    w = db.get(Waybill, waybill_id)
    if not w:
        raise HTTPException(status_code=404, detail="Waybill not found")
    if w.status not in ("pending", "out"):
        raise HTTPException(status_code=400, detail=f"Waybill is already {w.status}.")
    if not received_by.strip():
        raise HTTPException(
            status_code=400,
            detail="Record who took delivery. A parcel signed for by nobody is "
                   "not a delivery, it is a missing parcel with a tick against it.")
    if w.requires_id_check and not id_number_seen.strip():
        raise HTTPException(
            status_code=400,
            detail="This delivery contains a controlled substance. The recipient's "
                   "identity must be verified at the door and recorded.")
    w.status = "delivered"
    w.received_by = received_by.strip()
    w.id_number_seen = id_number_seen.strip()
    w.delivered_at = datetime.utcnow()
    db.commit()
    return _row(w)


@router.post("/waybills/{waybill_id}/fail")
def fail(waybill_id: int, reason: str = Body(..., embed=True),
         db: Session = Depends(get_db)):
    """A delivery that did not happen. The medicine is still the pharmacy's."""
    w = db.get(Waybill, waybill_id)
    if not w:
        raise HTTPException(status_code=404, detail="Waybill not found")
    if not reason.strip():
        raise HTTPException(status_code=400, detail="A failed delivery needs a reason.")
    w.status = "failed"
    w.failure_reason = reason.strip()
    db.commit()
    return _row(w)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _csv(rows: list[dict], filename: str, db: Session | None = None) -> Response:
    """Write a dataset out, with a header saying what it is and where it is from.

    An exported spreadsheet outlives the screen it came from. It gets emailed,
    printed, and argued about a month later, by which time "which branch is this
    and when was it run" is the first question and nobody can answer it. Three
    lines at the top cost nothing and settle it.
    """
    buffer = io.StringIO()
    branch_name = ""
    if db is not None:
        try:
            branch_name = branches.default_branch(db).name
        except Exception:      # a provenance header must never break an export
            branch_name = ""
    buffer.write(f"# {settings.PHARMACY_NAME}\r\n")
    if branch_name:
        buffer.write(f"# Branch: {branch_name}\r\n")
    buffer.write(f"# Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}\r\n")
    buffer.write(f"# Dataset: {filename.rsplit(chr(46), 1)[0]}\r\n")
    if not rows:
        buffer.write("# No rows\r\n")
        return Response(content=buffer.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/{dataset}")
def export(dataset: str, db: Session = Depends(get_db)):
    """Every grid leaves as a spreadsheet.

    A pharmacy manager reconciles in Excel whatever the software offers, so a
    report that cannot leave the system is a report they will not trust. CSV
    rather than a real workbook: it opens in everything, needs no dependency,
    and nobody has ever failed to import one.
    """
    from ..models import Account, Claim, JournalEntry, OwedItem, StockBatch

    stamp = date.today()
    if dataset == "products":
        rows = [{"code": p.nappi_code, "name": p.name, "strength": p.strength,
                 "schedule": p.schedule, "on_hand": p.quantity_on_hand,
                 "cost_price": p.cost_price, "unit_price": p.unit_price}
                for p in db.query(Product).filter(Product.active).all()]
    elif dataset == "batches":
        rows = [{"product": b.product.name if b.product else "", "batch": b.batch_number,
                 "expiry": b.expiry_date, "remaining": b.quantity_remaining,
                 "unit_cost": b.unit_cost}
                for b in db.query(StockBatch).filter(StockBatch.quantity_remaining > 0).all()]
    elif dataset == "claims":
        rows = [{"claim": c.claim_number, "status": c.status,
                 "claimed": c.amount_claimed, "approved": c.amount_approved,
                 "patient_liable": c.patient_liable, "settled": c.settled_amount,
                 "created": c.created_at} for c in db.query(Claim).limit(5000).all()]
    elif dataset == "to-follows":
        rows = [{"reference": o.reference, "status": o.status,
                 "product": o.product.name if o.product else "",
                 "owed": o.quantity_owed, "settled": o.quantity_settled,
                 "promised_for": o.promised_for}
                for o in db.query(OwedItem).limit(5000).all()]
    elif dataset == "journal":
        rows = [{"reference": e.reference, "date": e.entry_date, "period": e.period_code,
                 "description": e.description, "source": e.source, "status": e.status,
                 "total": round(sum(l.debit for l in e.lines), 2)}
                for e in db.query(JournalEntry).limit(5000).all()]
    elif dataset == "trial-balance":
        from ..services import ledger
        rows = ledger.trial_balance(db)["lines"]
    elif dataset == "accounts":
        rows = [{"code": a.code, "name": a.name, "type": a.type,
                 "subledger": a.subledger} for a in db.query(Account).all()]
    else:
        raise HTTPException(
            status_code=404,
            detail="Nothing exports under that name. Available: products, batches, "
                   "claims, to-follows, journal, trial-balance, accounts.")
    return _csv(rows, f"rx3000-{dataset}-{stamp}.csv", db)


# ---------------------------------------------------------------------------
# The totals bar
# ---------------------------------------------------------------------------

@router.post("/script-totals")
def script_totals(items: list[dict] = Body(...),
                  medical_aid_id: int | None = Body(default=None),
                  db: Session = Depends(get_db)):
    """The twelve figures the incumbent puts along the bottom of the script.

    A pharmacist reads these at a glance to know a script is right *before*
    finishing it. Margin belongs here rather than in a report next month: it is
    how a good dispenser notices they are about to sell below cost, and by the
    time it reaches a report the medicine has gone.
    """
    aid = db.get(MedicalAid, medical_aid_id) if medical_aid_id else None
    lines, totals = [], {
        "rx_gross": 0.0, "gross": 0.0, "nett": 0.0, "no_claim": 0.0,
        "surcharge": 0.0, "vat": 0.0, "levy": 0.0, "tot_levy": 0.0,
        "claim": 0.0, "cost": 0.0,
    }

    for row in items:
        product = db.get(Product, int(row.get("product_id", 0)))
        if not product:
            raise HTTPException(status_code=404,
                                detail=f"Product {row.get('product_id')} not found")
        quantity = max(1, int(row.get("quantity") or 1))
        no_claim = bool(row.get("no_claim"))
        priced = pricing.price_line(db, product, quantity, None if no_claim else aid)
        cost = round((product.cost_price or 0.0) * quantity, 2)
        vat = round(priced.gross - priced.gross / (1 + (product.vat_rate or 0.0)), 2)

        totals["rx_gross"] += priced.base_price
        totals["gross"] += priced.gross
        totals["cost"] += cost
        totals["vat"] += vat
        if no_claim:
            totals["no_claim"] += priced.gross
        else:
            totals["claim"] += priced.claimable
            totals["levy"] += priced.levy
        totals["surcharge"] += priced.mmap_excess

        lines.append({
            "product_id": product.id,
            "description": priced.description,
            "quantity": quantity,
            "gross": round(priced.gross, 2),
            "cost": cost,
            "claim": 0.0 if no_claim else round(priced.claimable, 2),
            "no_claim": no_claim,
            # Per-line margin, because one bad line inside a profitable script
            # is invisible in the total and is exactly what a buyer needs told.
            "margin_percent": (round(100 * (priced.gross - cost) / priced.gross, 1)
                               if priced.gross else 0.0),
        })

    for key in totals:
        totals[key] = round(totals[key], 2)
    totals["tot_levy"] = totals["levy"]
    totals["nett"] = round(totals["gross"] - totals["no_claim"], 2)
    profit = round(totals["gross"] - totals["cost"], 2)
    totals["profit"] = profit
    totals["profit_percent"] = (round(100 * profit / totals["gross"], 1)
                                if totals["gross"] else 0.0)
    totals["patient_pays"] = round(totals["gross"] - totals["claim"], 2)

    return {
        "lines": lines,
        "totals": totals,
        "scheme": aid.name if aid else "",
        # Selling below cost is not a rounding question and should not be left
        # for the pharmacist to spot in a column of ten numbers.
        "warning": ("" if profit >= 0 else
                    f"This script sells at {abs(profit):.2f} below cost."),
    }


# ---------------------------------------------------------------------------
# Future repeats — who is due, and when
# ---------------------------------------------------------------------------

# /repeats/due already exists and returns the raw script lines. This is a
# different thing with a different name: the call sheet — who to telephone,
# in what order, and whether the shelf can actually serve them.
@router.get("/repeats/call-sheet")
def repeats_call_sheet(within_days: int = 14, overdue_only: bool = False,
                limit: int = 200, db: Session = Depends(get_db)):
    """Chronic patients whose repeat is due or overdue.

    Chronic scripts are the reliable revenue and the reliable adherence risk at
    the same time: a patient who has not collected is a patient not taking their
    medicine. Knowing who is due is worth more than any marketing campaign,
    because these are people who have already chosen the pharmacy.
    """
    from ..models import PrescriptionItem

    today = date.today()
    horizon = today + __import__("datetime").timedelta(days=max(0, within_days))
    rows = (db.query(PrescriptionItem)
            .filter(PrescriptionItem.next_repeat_date.isnot(None),
                    PrescriptionItem.next_repeat_date <= horizon,
                    PrescriptionItem.repeats_used < PrescriptionItem.repeats_allowed)
            .order_by(PrescriptionItem.next_repeat_date)
            .limit(limit * 2).all())

    out = []
    for item in rows:
        rx = item.prescription
        if not rx or rx.status == "draft":
            continue
        due = item.next_repeat_date
        overdue = due < today
        if overdue_only and not overdue:
            continue
        patient = rx.patient
        out.append({
            "prescription_id": rx.id, "rx_number": rx.rx_number,
            "item_id": item.id,
            "patient_id": rx.patient_id,
            "patient_name": (f"{patient.first_name} {patient.last_name}".strip()
                             if patient else ""),
            "patient_phone": patient.phone if patient else "",
            "product_id": item.product_id,
            "product": item.product.name if item.product else "",
            "quantity": item.quantity,
            "supply_days": item.supply_days,
            "repeats_used": item.repeats_used,
            "repeats_allowed": item.repeats_allowed,
            "repeats_left": max(0, item.repeats_allowed - item.repeats_used),
            "due_on": due,
            "days_overdue": (today - due).days if overdue else 0,
            "overdue": overdue,
            "in_stock": item.product.quantity_on_hand if item.product else 0,
            "can_supply": bool(item.product
                               and item.product.quantity_on_hand >= item.quantity),
        })
    # Overdue first, then soonest — the order somebody would telephone in.
    out.sort(key=lambda r: (not r["overdue"], r["due_on"]))
    return {
        "as_at": today,
        "within_days": within_days,
        "count": len(out[:limit]),
        "overdue": sum(1 for r in out if r["overdue"]),
        "items": out[:limit],
    }


# ---------------------------------------------------------------------------
# Alter script
# ---------------------------------------------------------------------------

@router.post("/prescriptions/{rx_id}/alter")
def alter_script(rx_id: int, item_id: int = Body(...),
                 quantity: int | None = Body(default=None),
                 dosage_instructions: str | None = Body(default=None),
                 icd10_code: str | None = Body(default=None),
                 supply_days: int | None = Body(default=None),
                 reason: str = Body(...),
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Correct a captured script without voiding and re-keying it.

    The rule that makes this safe rather than a hole: **what has already been
    dispensed cannot be altered.** A line that has left the shelf records
    something that physically happened, and editing it would make the register
    disagree with the medicine. Only the undispensed part is correctable, and
    every correction is written into the script's notes with a reason and a
    name - a silent edit is indistinguishable from a mistake.
    """
    from ..models import PrescriptionItem

    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if rx.status == "draft":
        raise HTTPException(status_code=400,
                            detail="This is still a draft - edit it rather than altering it.")
    if not reason.strip():
        raise HTTPException(status_code=400, detail="An alteration needs a reason.")

    item = db.get(PrescriptionItem, item_id)
    if not item or item.prescription_id != rx.id:
        raise HTTPException(status_code=404, detail="That line is not on this script.")
    if item.dispensings:
        raise HTTPException(
            status_code=400,
            detail=f"{item.product.name} has already been dispensed and cannot be "
                   "altered - the register would no longer match the medicine. "
                   "Reverse the dispensing first, or capture a new script.")

    from ..models import ScriptChange

    changes = []
    # Each change is also written as a row, not only as prose in the notes.
    # A sentence appended to a free-text field cannot be queried, filtered by
    # field, counted, or aged — so "how often are directions changed after
    # capture, and by whom" had no answer despite the information being there.
    recorded: list[ScriptChange] = []

    def record(field: str, old_value, new_value):
        recorded.append(ScriptChange(
            prescription_id=rx.id,
            prescription_item_id=item.id,
            field=field,
            old_value=str(old_value if old_value not in (None, "") else ""),
            new_value=str(new_value if new_value not in (None, "") else ""),
            reason=reason.strip(),
            changed_at=datetime.utcnow(),
            changed_by_id=user.id,
        ))

    if quantity is not None and quantity != item.quantity:
        if quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be positive.")
        changes.append(f"quantity {item.quantity} to {quantity}")
        record("quantity", item.quantity, quantity)
        item.quantity = quantity
    if dosage_instructions is not None and dosage_instructions != item.dosage_instructions:
        changes.append("directions changed")
        # The old directions are kept in full. "Directions changed" is exactly
        # the note that is useless when somebody asks what they used to say.
        record("dosage_instructions", item.dosage_instructions, dosage_instructions)
        item.dosage_instructions = dosage_instructions
    if icd10_code is not None and icd10_code.upper() != (item.icd10_code or ""):
        changes.append(f"diagnosis {item.icd10_code or 'none'} to {icd10_code.upper()}")
        record("icd10_code", item.icd10_code, icd10_code.upper())
        item.icd10_code = icd10_code.upper()
    if supply_days is not None and supply_days != item.supply_days:
        changes.append(f"supply days {item.supply_days} to {supply_days}")
        record("supply_days", item.supply_days, supply_days)
        item.supply_days = supply_days

    if not changes:
        return {"altered": False, "reason": "Nothing on that line was different."}

    for row in recorded:
        db.add(row)

    stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    rx.notes = (f"{rx.notes}\n[{stamp}] {user.full_name} altered "
                f"{item.product.name}: {'; '.join(changes)}. "
                f"Reason: {reason.strip()}").strip()
    db.commit()
    return {"altered": True, "rx_number": rx.rx_number, "changes": changes,
            "by": user.full_name, "note": rx.notes.splitlines()[-1]}


# ---------------------------------------------------------------------------
# Realtime reversals and logs
# ---------------------------------------------------------------------------

@router.get("/realtime/log")
def realtime_log(kind: str = "", funder_id: str = "", errors_only: bool = False,
                 limit: int = 100, db: Session = Depends(get_db)):
    """What was said to the switch and what came back.

    The screen a pharmacist opens when a funder disputes a claim six months
    later. The gateway has always recorded this; until now there was no way to
    read it without a database client.
    """
    from ..models import GatewayTransaction

    query = db.query(GatewayTransaction)
    if kind:
        query = query.filter(GatewayTransaction.kind == kind)
    if funder_id:
        query = query.filter(GatewayTransaction.funder_id == funder_id.upper())
    if errors_only:
        query = query.filter(GatewayTransaction.http_status >= 400)
    rows = query.order_by(desc(GatewayTransaction.created_at)).limit(limit).all()
    return [{
        "transaction_id": r.transaction_id, "kind": r.kind, "funder_id": r.funder_id,
        "switch_id": r.switch_id, "status": r.status, "error_code": r.error_code,
        "http_status": r.http_status, "amount_claimed": r.amount_claimed,
        "amount_approved": r.amount_approved,
        "switch_reference": r.switch_reference, "funder_reference": r.funder_reference,
        "duration_ms": r.duration_ms, "created_at": r.created_at,
    } for r in rows]


@router.post("/realtime/reverse/{transaction_id}")
def realtime_reverse(transaction_id: str, reason: str = Body(..., embed=True),
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Reverse a claim at the switch.

    Recorded as its own transaction rather than by amending the original: what
    was sent is a fact, and a reversal is a second fact about it. Amending the
    first would leave the funder's copy and ours disagreeing with no way to say
    which one moved.
    """
    import time as _time

    from ..models import GatewayTransaction
    from ..services import gateway

    original = (db.query(GatewayTransaction)
                .filter(GatewayTransaction.transaction_id == transaction_id).first())
    if not original:
        raise HTTPException(status_code=404, detail="No such gateway transaction")
    if original.kind != "claim":
        raise HTTPException(status_code=400,
                            detail=f"A {original.kind} is not something to reverse.")
    if not reason.strip():
        raise HTTPException(status_code=400, detail="A reversal needs a reason.")

    already = (db.query(GatewayTransaction)
               .filter(GatewayTransaction.kind == "reversal",
                       GatewayTransaction.switch_reference == original.switch_reference)
               .first())
    if already and original.switch_reference:
        raise HTTPException(status_code=400,
                            detail=f"Already reversed by {already.transaction_id}.")

    try:
        funder = gateway.resolve_funder(db, original.funder_id)
        adapter = gateway.adapter_for(funder)
    except gateway.GatewayError as exc:
        raise HTTPException(status_code=exc.http_status, detail={
            "error_code": exc.code, "message": exc.detail}) from exc

    if adapter.switch_id != "SIMULATOR":
        # Only the simulator can be reversed today. A real switch reversal is
        # part of that switch's own specification and is not guessed at.
        raise HTTPException(status_code=502, detail={
            "error_code": "SWITCH_UNAVAILABLE",
            "message": f"Reversal against {adapter.switch_id} is not implemented - "
                       "it is part of that switch's specification."})

    txn = gateway.new_transaction_id()
    gateway.record(
        db, transaction_id=txn, kind="reversal", funder_id=original.funder_id,
        switch_id=original.switch_id, status="REVERSED", http_status=200,
        claimed=original.amount_claimed, approved=-(original.amount_approved or 0.0),
        switch_ref=original.switch_reference, funder_ref=original.funder_reference,
        request={"reverses": original.transaction_id, "reason": reason.strip(),
                 "by": user.full_name},
        response={"accepted": True}, started=_time.monotonic())
    return {"reversed": original.transaction_id, "reversal_id": txn,
            "amount": original.amount_approved, "by": user.full_name}
