"""Dispensing routes split by medicine schedule.

Three distinct workflows:
  * OTC / pharmacy medicine (S0-S2) — counter sale, no script, counselling recorded
  * Prescription (S3-S4)            — ordinary script dispensing
  * Controlled / dangerous drugs    — S5/S6, with the full compliance record
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from .. import helpers, schedule_policy, schemas
from ..auth import get_current_user
from ..database import get_db
from ..services import doses, interactions, paging, willcall
from ..models import (
    Claim, Dispensing, OTCSale, Patient, Prescription, PrescriptionItem, Product, Sale, SaleItem, User,
)
from . import shifts_router

router = APIRouter(prefix="/api/dispensing", tags=["dispensing"], dependencies=[Depends(get_current_user)])


@router.get("/policy", response_model=list[schemas.SchedulePolicyOut])
def dispensing_policy():
    """The schedule rulebook the UI uses to pick the right workflow."""
    return schedule_policy.all_policies()


@router.get("/products", response_model=list[schemas.ProductOut])
def products_by_route(route: str = "otc", q: str = "", limit: int = 40, db: Session = Depends(get_db)):
    """Products available on a given dispensing route (otc | prescription | controlled)."""
    schedules = schedule_policy.schedules_for_route(route)
    if not schedules:
        raise HTTPException(status_code=400, detail="Route must be otc, prescription or controlled")
    query = db.query(Product).filter(Product.active, Product.schedule.in_(schedules))
    if route == "otc":
        query = query.filter(Product.category != "airtime")
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    return query.order_by(Product.name).limit(limit).all()


# ---------- OTC / pharmacy medicine ----------
@router.post("/otc", response_model=schemas.OTCSaleOut)
def otc_sale(
    body: schemas.OTCSaleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Sell a pharmacy medicine over the counter and record the consultation."""
    product = db.get(Product, body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    policy = schedule_policy.policy_for(product.schedule)
    if policy.route != "otc":
        raise HTTPException(
            status_code=400,
            detail=f"{product.name} is {policy.label}. It requires a prescription and cannot be "
                   "sold over the counter.",
        )
    if policy.requires_pharmacist and user.role not in ("pharmacist", "admin"):
        raise HTTPException(
            status_code=403,
            detail=f"{policy.label} must be handed over by a pharmacist.",
        )
    if policy.counselling_required and not body.counselling_given:
        raise HTTPException(
            status_code=400,
            detail=f"{policy.label} requires the patient to be counselled before hand-over.",
        )
    if body.quantity < 1:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")

    shift = shifts_router.current_open_shift(db, user.id)
    sale = Sale(
        sale_number=helpers.next_number(db, Sale, "INV", "sale_number"),
        patient_id=body.patient_id,
        cashier_id=user.id,
        shift_id=shift.id if shift else None,
    )
    db.add(sale)
    db.flush()

    line_total = round(product.unit_price * body.quantity, 2)
    line_ex = round(line_total / (1 + product.vat_rate), 2)
    sale_item = SaleItem(
        sale_id=sale.id, product_id=product.id,
        description=f"{product.name} {product.strength}".strip(),
        quantity=body.quantity, unit_price=product.unit_price,
        unit_cost=product.cost_price or 0.0,
        vat_rate=product.vat_rate, line_total=line_total,
    )
    db.add(sale_item)
    db.flush()

    helpers.consume_stock_fefo(
        db, product, body.quantity, "sale", user.id,
        reference=sale.sale_number, sale_item_id=sale_item.id,
    )
    sale.subtotal = line_ex
    sale.vat_amount = round(line_total - line_ex, 2)
    sale.total = line_total
    sale.payment_method = body.payment_method
    if body.payment_method == "cash":
        if body.amount_tendered + 0.005 < sale.total:
            raise HTTPException(status_code=400, detail="Amount tendered is less than the total")
        sale.amount_tendered = body.amount_tendered
        sale.change_due = round(body.amount_tendered - sale.total, 2)
    else:
        sale.amount_tendered = sale.total
    sale.status = "paid"

    record = OTCSale(
        product_id=product.id, quantity=body.quantity, schedule=product.schedule or 0,
        patient_id=body.patient_id, customer_name=body.customer_name,
        pharmacist_id=user.id, indication=body.indication,
        counselling_given=body.counselling_given, referred_to_doctor=body.referred_to_doctor,
        notes=body.notes, sale_id=sale.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _otc_query(db: Session, days: int, schedule: int | None):
    query = db.query(OTCSale).filter(OTCSale.created_at >= datetime.utcnow() - timedelta(days=days))
    if schedule is not None:
        query = query.filter(OTCSale.schedule == schedule)
    return query.order_by(OTCSale.created_at.desc())


@router.get("/otc", response_model=list[schemas.OTCSaleOut])
def list_otc_sales(days: int = 30, schedule: int | None = None, limit: int = 200, db: Session = Depends(get_db)):
    """The pharmacy-medicine sales register (S1/S2 record keeping)."""
    return _otc_query(db, days, schedule).limit(limit).all()


@router.get("/otc/paged")
def list_otc_sales_paged(days: int = 30, schedule: int | None = None, page: int = 1,
                         per_page: int = paging.DEFAULT_PER_PAGE, db: Session = Depends(get_db)):
    """The same register, a page at a time, with the true total.

    A register is the wrong place to show a capped list with no total: the screen
    said nothing about the difference between "this is everything" and "this is
    the most recent two hundred".
    """
    result = paging.page(_otc_query(db, days, schedule), page=page, per_page=per_page)
    return result.envelope(lambda r: schemas.OTCSaleOut.model_validate(r, from_attributes=True).model_dump())


# ---------- controlled substances ----------
#: What makes a hand-over controlled. Schedule 5 and above is the legal line.
CONTROLLED_FROM = 5


def _controlled_query(db: Session, days: int):
    """The register, defined by the schedule rather than by a label on the row.

    This filtered on `dispense_type == "controlled"`, a field written when the
    dispensing was created. Every seeded row defaulted to "prescription", so
    the register an inspector reads was empty while two hundred and twenty-six
    schedule 5 and 6 hand-overs sat in the database — the worst possible way
    for this particular screen to be wrong.

    A schedule 5 hand-over is controlled because of what it is, not because
    something remembered to say so. Either condition puts it in the register,
    so a row typed correctly and a row typed by an older code path both appear.
    """
    return (db.query(Dispensing)
            .filter(or_(Dispensing.dispense_type == "controlled",
                        Dispensing.schedule >= CONTROLLED_FROM),
                    Dispensing.dispensed_at >= datetime.utcnow() - timedelta(days=days))
            .order_by(Dispensing.dispensed_at.desc()))


@router.get("/controlled/log", response_model=list[schemas.DispensingOut])
def controlled_log(days: int = 90, limit: int = 200, db: Session = Depends(get_db)):
    """Every controlled-substance hand-over with its compliance record."""
    return _controlled_query(db, days).limit(limit).all()


@router.get("/controlled/log/paged")
def controlled_log_paged(days: int = 90, page: int = 1,
                         per_page: int = paging.DEFAULT_PER_PAGE,
                         db: Session = Depends(get_db)):
    """The controlled register, paged, with the count over the whole period.

    This is the list an inspector reads. Showing the most recent two hundred
    hand-overs with nothing saying so is the one place a silent cap is not a
    presentation choice.
    """
    result = paging.page(_controlled_query(db, days), page=page, per_page=per_page)
    return result.envelope(lambda d: schemas.DispensingOut.model_validate(d, from_attributes=True).model_dump())


# Four counts over a window — controlled, prescriptions, over the counter, and
# referrals — all of which the branch scorecard already computes per branch and
# with the denominators that make them mean something. A total with nothing to
# compare it against is a number somebody reads once.

@router.post("/interaction-screen")
def interaction_screen(patient_id: int | None = Body(default=None),
                       product_ids: list[int] = Body(default_factory=list),
                       lines: list[dict] = Body(default_factory=list),
                       db: Session = Depends(get_db)):
    """Screen a basket, and screen it against what the patient already takes.

    Called by the dispensing screen every time the basket changes, not from a
    button. A safety check somebody has to remember to run is a safety check that
    gets skipped on exactly the busy afternoon it was written for.

    **The medication history is the point.** Two new lines interacting with each
    other is the case that is easy to picture and uncommon in practice: one
    prescriber wrote both and has usually thought about it. The dangerous case is
    a new line against a repeat from two years ago — warfarin from a cardiologist
    in March, ibuprofen for a sore back today, different prescriber, nobody
    holding both facts. The pharmacy counter is the only place both are visible.

    Deliberately does not block on its own. The checker holds twelve pairs and
    says so in every response; blocking on twelve while missing thousands would
    teach a pharmacist that a clear result means safe, which is the failure this
    whole module is written against. The screen asks for an acknowledgement on a
    major finding and never claims more than it knows.
    """
    products = db.query(Product).filter(Product.id.in_(product_ids)).all() if product_ids else []

    history: list[dict] = []
    if patient_id:
        # What this patient is actually on: every line dispensed in the last six
        # months, most recent first, one row per product. Six months because a
        # chronic repeat cycles monthly and a quarterly script is ordinary; much
        # longer and a course finished in March starts flagging in September.
        cutoff = datetime.utcnow() - timedelta(days=182)
        rows = (db.query(Product, func.max(Dispensing.dispensed_at))
                  .join(PrescriptionItem, PrescriptionItem.product_id == Product.id)
                  .join(Dispensing, Dispensing.prescription_item_id == PrescriptionItem.id)
                  .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
                  .filter(Prescription.patient_id == patient_id,
                          Dispensing.dispensed_at >= cutoff)
                  .group_by(Product.id)
                  .all())
        basket = {p.id for p in products}
        for product, last in rows:
            # A product already in the basket is not also "history": flagging a
            # repeat against itself would report every chronic refill as a
            # duplicate.
            if product.id in basket:
                continue
            history.append({
                "product_id": product.id,
                "name": f"{product.name} {product.strength or ''}".strip(),
                "active_ingredient": product.active_ingredient or "",
                "since": last.strftime("%d %b") if last else "",
            })

    result = interactions.check(
        [{"product_id": p.id,
          "name": f"{p.name} {p.strength or ''}".strip(),
          "active_ingredient": p.active_ingredient or ""}
         for p in products],
        existing=history,
    )
    # --- dose ranges, on the same call --------------------------------------
    #
    # One request rather than two, because both screens answer the same
    # question — is this basket safe to hand over — and two requests firing on
    # every keystroke is two chances for the answers to arrive out of order and
    # contradict each other on screen.
    #
    # `lines` carries the directions and is optional: the checker needs to know
    # how often, and only the dispensing screen knows that. Called with product
    # ids alone it still reports what it could not read, which is the honest
    # answer rather than a silent pass.
    typed = {int(l.get("product_id")): l for l in lines if l.get("product_id")}
    dose_items = []
    for product in products:
        line = typed.get(product.id, {})
        dose_items.append({
            "name": f"{product.name} {product.strength or ''}".strip(),
            "active_ingredient": product.active_ingredient or "",
            "strength": product.strength or "",
            "instructions": line.get("instructions", ""),
            "quantity": line.get("quantity"),
        })

    age = None
    if patient_id:
        patient = db.get(Patient, patient_id)
        if patient and patient.date_of_birth:
            today = date.today()
            born = patient.date_of_birth
            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))

    result["doses"] = doses.check(dose_items, age=age)
    result["patient_age"] = age

    result["history_source"] = (
        f"{len(history)} medicine(s) dispensed to this patient in the last six months"
        if history else
        ("Nothing dispensed to this patient in the last six months"
         if patient_id else "No patient selected, so nothing was checked against history")
    )
    return result


# ---------------------------------------------------------- the will-call shelf

@router.get("/history")
def dispensing_history(
    q: str = "",
    patient_id: int = 0,
    product_id: int = 0,
    schedule: int = -1,
    dispensed_by: int = 0,
    days: int = 0,
    unpaid_only: bool = False,
    uncollected_only: bool = False,
    page: int = 1,
    per_page: int = paging.DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
):
    """What has been dispensed, and what happened to it afterwards.

    There was no such screen. The controlled register covers S5 and S6, the
    counter log covers over-the-counter sales, and everything in between — the
    ordinary prescription dispensed an hour ago — could only be found by
    knowing the patient and opening their record.

    That is the question a pharmacy actually asks: "what went out this
    morning", "did that one get paid for", "has she collected it". So the row
    carries the money and the collection alongside the medicine, because those
    are the three reasons anybody looks.
    """
    query = (
        db.query(Dispensing)
        .join(PrescriptionItem, Dispensing.prescription_item_id == PrescriptionItem.id)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .join(Product, PrescriptionItem.product_id == Product.id)
        .options(
            joinedload(Dispensing.prescription_item)
            .joinedload(PrescriptionItem.product),
            joinedload(Dispensing.prescription_item)
            .joinedload(PrescriptionItem.prescription)
            .joinedload(Prescription.patient),
            joinedload(Dispensing.prescription_item)
            .joinedload(PrescriptionItem.prescription)
            .joinedload(Prescription.doctor),
            joinedload(Dispensing.dispensed_by),
        )
    )

    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            Prescription.rx_number.ilike(like),
            Product.name.ilike(like),
            Patient.first_name.ilike(like),
            Patient.last_name.ilike(like),
        )).join(Patient, Prescription.patient_id == Patient.id)
    if patient_id:
        query = query.filter(Prescription.patient_id == patient_id)
    if product_id:
        query = query.filter(PrescriptionItem.product_id == product_id)
    if schedule >= 0:
        query = query.filter(Dispensing.schedule == schedule)
    if dispensed_by:
        query = query.filter(Dispensing.dispensed_by_id == dispensed_by)
    if days > 0:
        query = query.filter(
            Dispensing.dispensed_at >= datetime.utcnow() - timedelta(days=days))
    if uncollected_only:
        query = query.filter(Dispensing.collected_at.is_(None))

    result = paging.page(query.order_by(Dispensing.dispensed_at.desc()),
                         page=page, per_page=per_page)

    # The sale and the claim for these rows, in two queries rather than two per
    # row. Every row shows whether it was paid for, and that is a different
    # table from the dispensing.
    sale_ids = {d.sale_id for d in result.items if d.sale_id}
    sales = {s.id: s for s in db.query(Sale).filter(Sale.id.in_(sale_ids or [0])).all()}
    claims = {c.sale_id: c for c in
              db.query(Claim).filter(Claim.sale_id.in_(sale_ids or [0])).all()}

    def row(d):
        item = d.prescription_item
        rx = item.prescription if item else None
        patient = rx.patient if rx else None
        product = item.product if item else None
        sale = sales.get(d.sale_id)
        claim = claims.get(d.sale_id)
        owed = 0.0
        if sale and sale.status != "paid":
            owed = round(claim.patient_liable if claim else (sale.total or 0.0), 2)
        return {
            "id": d.id,
            "dispensed_at": d.dispensed_at,
            "quantity": d.quantity,
            "schedule": d.schedule or 0,
            "is_repeat": bool(d.is_repeat),
            "prescription_id": rx.id if rx else None,
            "rx_number": rx.rx_number if rx else "",
            "patient_id": rx.patient_id if rx else None,
            "patient": (f"{patient.first_name} {patient.last_name}".strip()
                        if patient else "Walk-in"),
            "product_id": item.product_id if item else None,
            "product": (f"{product.name} {product.strength or ''}".strip()
                        if product else ""),
            "prescriber_id": rx.doctor_id if rx else None,
            "prescriber": rx.doctor.name if rx and rx.doctor else "",
            "dispensed_by_id": d.dispensed_by_id,
            "dispensed_by": d.dispensed_by.full_name if d.dispensed_by else "",
            "pharmacist_initial": d.pharmacist_initial or "",
            "collected_at": d.collected_at,
            "collected_name": d.collected_name or "",
            "sale_id": d.sale_id,
            "sale_number": sale.sale_number if sale else "",
            "sale_status": sale.status if sale else "",
            "sale_total": round(sale.total, 2) if sale else 0.0,
            "claim_id": claim.id if claim else None,
            "claim_status": claim.status if claim else "",
            "scheme_pays": round(claim.amount_approved, 2) if claim else 0.0,
            # What the patient still has to hand over. The reason a dispensing
            # is looked up at all, as often as not.
            "outstanding": owed,
        }

    rows = [row(d) for d in result.items]
    if unpaid_only:
        rows = [r for r in rows if r["outstanding"] > 0.005]
    return {**result.envelope(), "items": rows}


@router.get("/will-call")
def will_call(limit: int = 200, db: Session = Depends(get_db)):
    """Everything dispensed and not yet collected, oldest first."""
    return willcall.waiting(db, limit=max(1, min(limit, 500)))


@router.post("/will-call/{dispensing_id}/collect")
def will_call_collect(dispensing_id: int,
                      taken_by: str = Body(default="", embed=False),
                      id_seen: str = Body(default=""),
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """Hand a bag over, and record who took it.

    Often not the patient: a relative, a driver, a neighbour going that way. On a
    Schedule 5 or 6 item the name is required, because the register has to answer
    "who had it and when" and a blank is not an answer.
    """
    try:
        d = willcall.collect(db, dispensing_id, user_id=user.id,
                             taken_by=taken_by, id_seen=id_seen)
    except willcall.CollectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "collected_at": d.collected_at, "collected_name": d.collected_name}


@router.post("/will-call/{dispensing_id}/uncollect")
def will_call_uncollect(dispensing_id: int, db: Session = Depends(get_db),
                        _: User = Depends(get_current_user)):
    """Put a bag back on the shelf, for a collection marked in error."""
    try:
        willcall.uncollect(db, dispensing_id)
    except willcall.CollectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}
