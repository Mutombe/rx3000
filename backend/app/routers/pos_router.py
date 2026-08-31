from datetime import datetime

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import helpers, schemas
from ..auth import get_current_user
from ..database import get_db
from .periods_router import require_step_up
from ..models import (BatchAllocation, Claim, Patient, Product, Sale, SaleItem,
                      SaleTender, User)
from ..services import claims_engine, currency, fiscal, posting, reconciliation, stepup
from . import shifts_router

router = APIRouter(prefix="/api/pos", tags=["pos"])

LOYALTY_EARN_RATE = 0.01      # 1 point per R100 -> points = total * rate
LOYALTY_POINT_VALUE = 1.0     # 1 point = R1 when redeemed


CARD_FIELDS = ("card_auth_code", "card_reference", "card_last4",
               "card_scheme", "terminal_id", "card_batch")


def _record_card_tender(sale: Sale, body) -> None:
    """Copy the terminal slip detail onto the sale so it can be reconciled."""
    if sale.payment_method != "card":
        return
    for field in CARD_FIELDS:
        value = (getattr(body, field, "") or "").strip()
        if value:
            setattr(sale, field, value[:40])


def _already_claimed(db: Session, sale: Sale) -> bool:
    """Whether this sale has a live claim against it already.

    A script claimed when it was dispensed must not be claimed a second time
    when the patient reaches the till — the scheme would be billed twice for
    one dispensing, and the second claim is the one that gets noticed, in a
    reconciliation, by somebody who cannot tell which was real.
    """
    return db.query(Claim).filter(
        Claim.sale_id == sale.id,
        Claim.status.notin_(("reversed", "rejected")),
    ).first() is not None


def _settle_split_tender(db: Session, sale: Sale, body, amount_due: float) -> None:
    """Settle a sale from an explicit list of tenders, possibly across currencies.

    Each tender is converted to base at the rate in force and recorded with that
    rate. Change is written back as a negative tender in whichever currency it
    was handed over, so each drawer can be reconciled independently — paying in
    USD and taking ZiG change moves both.
    """
    try:
        collected = 0.0
        for line in body.tenders:
            if line.amount <= 0:
                continue
            tender = currency.record_tender(
                db, sale, method=line.method,
                currency_code=line.currency_code or currency.base_code(),
                amount=line.amount, reference=line.reference,
                # The till has known which wallet since the day the mobile
                # money screen was built. It just had nowhere to put it.
                instrument=getattr(line, "instrument", "") or getattr(line, "wallet", ""),
            )
            collected += tender.amount_in_base

        collected = round(collected, 2)
        if collected + 0.005 < amount_due:
            short = round(amount_due - collected, 2)
            # Short, and sometimes that is the answer.
            #
            # A patient who can find twenty of fifty-seven today still needs
            # their medicine, and refusing is what makes a counter ring the
            # whole thing up as cash and lose the difference where nobody can
            # find it. So the shortfall is allowed to become a debt — but only
            # deliberately, and only with a pharmacist behind it, because the
            # pharmacy is lending money and somebody has to own that.
            if not getattr(body, "part_payment", False):
                raise HTTPException(
                    status_code=400,
                    detail=f"Tendered {collected} of {amount_due}, short by {short}"
                           f"{currency.base_code()}. Mark it as a part payment to "
                           f"let the patient owe the balance.",
                )
            if not sale.patient_id:
                raise HTTPException(
                    status_code=400,
                    detail="A balance has to be owed by somebody — link the "
                           "patient before taking a part payment.")
            sale.status = "part_paid"
            return

        change_base = round(collected - amount_due, 2)
        if change_base > 0:
            change_code = (body.change_currency or "").upper() or _default_change_currency(body)
            currency.record_tender(db, sale, method="cash", currency_code=change_code,
                                   amount=currency.from_base(change_base,
                                                             change_code,
                                                             currency.current_rate(db, change_code)),
                                   is_change=True)
        sale.change_due = change_base
        sale.amount_tendered = collected
    except currency.CurrencyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _default_change_currency(body) -> str:
    """Give change in the currency most of the payment arrived in."""
    cash = [t for t in body.tenders if t.method == "cash" and t.amount > 0]
    if cash:
        return (cash[-1].currency_code or currency.base_code()).upper()
    return currency.base_code()


def _settle_payment(db: Session, sale: Sale, payment_method: str,
                    amount_tendered: float, points_redeemed: int, user: User,
                    body_tenders=None) -> None:
    patient = db.get(Patient, sale.patient_id) if sale.patient_id else None

    # Loyalty redemption is a tender, not a price reduction: sale.total (and
    # therefore VAT) stays intact; points settle part of the amount due.
    redeem_value = 0.0
    if points_redeemed:
        if not patient:
            raise HTTPException(status_code=400, detail="Loyalty redemption requires a linked patient")
        if payment_method == "medical_aid":
            raise HTTPException(status_code=400, detail="Loyalty points cannot be combined with a medical aid claim")
        if patient.loyalty_points < points_redeemed:
            raise HTTPException(status_code=400, detail=f"Patient only has {patient.loyalty_points} points")
        redeem_value = min(points_redeemed * LOYALTY_POINT_VALUE, sale.total)
        points_redeemed = int(redeem_value / LOYALTY_POINT_VALUE)
        patient.loyalty_points -= points_redeemed
        sale.loyalty_points_redeemed = points_redeemed

    # What is still owed, not what the sale came to.
    #
    # A part-paid sale is settled a second time when the patient comes back
    # with the rest, and asking for the whole total again is asking them to pay
    # twice. Anything already tendered against this sale comes off first.
    already = _paid_on(db, [sale.id]).get(sale.id, 0.0) if sale.id else 0.0
    amount_due = round(sale.total - redeem_value - already, 2)
    if amount_due < 0:
        amount_due = 0.0
    sale.payment_method = payment_method
    sale.currency_code = sale.currency_code or currency.base_code()

    # Split tender takes over when supplied — the single-tender fields below
    # stay for callers that never need more than one payment.
    if getattr(body_tenders, "tenders", None):
        _settle_split_tender(db, sale, body_tenders, amount_due)
        methods = {t.method for t in body_tenders.tenders if t.amount > 0}

        # A medical aid line in a split is a claim, exactly as it is on its own.
        #
        # This branch used to return two lines above the `medical_aid` branch
        # below, so a sale settled half by scheme and half by cash recorded the
        # scheme's share as collected and never billed anybody for it. The
        # medicine went out, the books showed the money in, and the funder was
        # never asked — a hole that only shows up as an ageing debtor nobody
        # can explain, months later.
        if "medical_aid" in methods and not _already_claimed(db, sale):
            if not patient:
                raise HTTPException(
                    status_code=400,
                    detail="A medical aid tender needs a linked patient to claim against.")
            if getattr(body_tenders, "claim_later", False):
                claims_engine.defer_claim(
                    db, sale, patient,
                    getattr(body_tenders, "claim_later_reason", "")
                    or "Held at the counter")
            else:
                claims_engine.submit_claim(db, sale, patient)

        sale.payment_method = methods.pop() if len(methods) == 1 else "split"
        # Points are earned on what has actually been paid, not on what was
        # rung up: a patient owing half the sale has not spent it yet.
        if patient and sale.status != "part_paid":
            earned = int(amount_due * LOYALTY_EARN_RATE)
            sale.loyalty_points_earned = earned
            patient.loyalty_points += earned
        if sale.status != "part_paid":
            sale.status = "paid"
        return

    if payment_method == "medical_aid":
        if not patient:
            raise HTTPException(status_code=400, detail="Medical aid payment requires a linked patient")
        # "Claim later": the switch is down, or the member's card is not here,
        # and the medicine still has to go out. Holding the claim is the only
        # option that neither turns the patient away nor loses the money — the
        # patient settles now and is refunded when the funder pays.
        if getattr(body_tenders, "claim_later", False):
            claim = claims_engine.defer_claim(
                db, sale, patient,
                getattr(body_tenders, "claim_later_reason", "") or "Held at the counter")
        else:
            claim = claims_engine.submit_claim(db, sale, patient)
        if claim.status == "rejected":
            sale.payment_method = "cash"  # falls back to private payment
        sale.amount_tendered = claim.patient_liable
    elif payment_method == "cash":
        if amount_tendered + 0.005 < amount_due:
            # Short, and sometimes that is the answer — the same judgement the
            # split-tender path above already makes.
            #
            # It was not made here. `part_payment` was honoured only when the
            # till sent a list of tenders, so the identical request expressed as
            # a single cash amount was refused outright. One intention, two
            # settlement paths, and only one of them had heard of it: a counter
            # taking twenty of fifty-seven got "Amount tendered is less than the
            # amount due" and no way past it, which is how the whole thing gets
            # rung up as cash and the difference lost where nobody can find it.
            if not getattr(body_tenders, "part_payment", False):
                short = round(amount_due - amount_tendered, 2)
                raise HTTPException(
                    status_code=400,
                    detail=f"Tendered {amount_tendered:.2f} of {amount_due:.2f}, "
                           f"short by {short:.2f}. Mark it as a part payment to "
                           f"let the patient owe the balance.")
            if not sale.patient_id:
                raise HTTPException(
                    status_code=400,
                    detail="A balance has to be owed by somebody — link the "
                           "patient before taking a part payment.")
            # Recorded as a tender, not merely stamped on the sale.
            #
            # A settled sale can get away with `amount_tendered` alone because
            # nothing asks it again. A part payment is asked again by
            # definition: /owed works out the balance from the tenders, so
            # money taken and not recorded here reads as nothing paid — the
            # patient hands over twenty and the screen still says they owe the
            # whole fifty-seven.
            currency.record_tender(
                db, sale, method="cash",
                currency_code=currency.base_code(), amount=amount_tendered,
                reference="part payment")
            sale.amount_tendered = amount_tendered
            sale.change_due = 0.0
            sale.status = "part_paid"
            return
        sale.amount_tendered = amount_tendered
        sale.change_due = round(amount_tendered - amount_due, 2)
    else:  # card / account (EFTPOS integration point)
        sale.amount_tendered = amount_due

    if patient:
        earned = int(amount_due * LOYALTY_EARN_RATE)
        sale.loyalty_points_earned = earned
        patient.loyalty_points += earned

    sale.status = "paid"


@router.post("/sales", response_model=schemas.SaleOut)
def create_sale(body: schemas.SaleCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Direct POS sale: builds the basket, moves stock, settles payment."""
    if not body.items:
        raise HTTPException(status_code=400, detail="Basket is empty")

    # A till replaying a sale it took while the line was down sends the same
    # reference every time. If this one has been seen, the sale is already on
    # the books and the right answer is the sale we already have — not a second
    # one, and not an error either, because from the till's point of view the
    # request succeeded and it needs the result to clear its queue.
    if body.client_ref:
        seen = db.query(Sale).filter(Sale.client_ref == body.client_ref).first()
        if seen:
            return seen

    shift = shifts_router.current_open_shift(db, user.id)
    sale = Sale(
        client_ref=body.client_ref or None,
        taken_offline_at=body.taken_offline_at,
        sale_number=helpers.next_number(db, Sale, "INV", "sale_number"),
        patient_id=body.patient_id,
        cashier_id=user.id,
        shift_id=shift.id if shift else None,
    )
    db.add(sale)
    db.flush()

    subtotal = vat_total = 0.0
    # One query for the basket rather than one a line: a ten-item sale was ten
    # round trips before the till could total it.
    basket = {p.id: p for p in db.query(Product)
              .filter(Product.id.in_([l.product_id for l in body.items])).all()}
    for line in body.items:
        product = basket.get(line.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {line.product_id} not found")
        line_total = round(product.unit_price * line.quantity, 2)
        line_ex = round(line_total / (1 + product.vat_rate), 2)
        subtotal += line_ex
        vat_total += line_total - line_ex
        sale_item = SaleItem(
            sale_id=sale.id, product_id=product.id,
            description=f"{product.name} {product.strength}".strip(),
            quantity=line.quantity, unit_price=product.unit_price,
            unit_cost=product.cost_price or 0.0,
            vat_rate=product.vat_rate, line_total=line_total,
        )
        db.add(sale_item)
        db.flush()
        if product.category != "airtime":
            # FEFO batch consumption — expired stock is never sold
            helpers.consume_stock_fefo(
                db, product, line.quantity, "sale", user.id,
                reference=sale.sale_number, sale_item_id=sale_item.id,
            )
            helpers.record_register_entry(
                db, product, -line.quantity, "dispense", user.id,
                patient_id=body.patient_id, reference=sale.sale_number,
            )

    sale.subtotal = round(subtotal, 2)
    sale.vat_amount = round(vat_total, 2)
    sale.total = round(subtotal + vat_total, 2)

    _settle_payment(db, sale, body.payment_method, body.amount_tendered,
                    body.loyalty_points_redeemed, user, body_tenders=body)
    _record_card_tender(sale, body)
    db.commit()
    fiscal.fiscalise(db, sale)
    # Post to the ledger. Deliberately after the sale is committed and
    # deliberately non-fatal: the medicine has gone out, and the bookkeeping
    # must not be able to undo that. A refusal lands on the unposted queue.
    posting.post_sale(db, sale, user.id)
    db.refresh(sale)
    return sale


def _require_part_payment_approval(db: Session, user: User, token: str) -> None:
    """A debt needs a pharmacist's name against it.

    Not because a cashier is untrusted, but because "she will bring it on
    Friday" is a decision about the pharmacy's money made under the eye of
    somebody who cannot pay, and the person who made it should be recorded.
    """
    if not token:
        # 428, in the shape the rest of the application already speaks.
        #
        # Not 403: the till's `guarded` helper watches for 428 and raises the
        # authorisation prompt, and a 403 would simply have shown the cashier
        # an error with no way past it. Matching `require_step_up` means the
        # prompt that already exists works here without a second one.
        detail = {"error_code": "STEP_UP_REQUIRED",
                  **stepup.describe("sale.part_payment")}
        detail["message"] = ("Letting a patient owe the balance needs a "
                             "pharmacist's password.")
        raise HTTPException(status_code=428, detail=detail)
    try:
        stepup.redeem(db, action_key="sale.part_payment", token=token, actor=user)
    except stepup.StepUpError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _paid_on(db: Session, sale_ids: list[int]) -> dict[int, float]:
    """What has actually been collected against each sale.

    Summed from the tenders rather than stored on the sale: a second column
    holding the same fact is a second thing to keep right, and this one only
    changes when a tender is written.
    """
    if not sale_ids:
        return {}
    rows = (db.query(SaleTender.sale_id,
                     func.coalesce(func.sum(SaleTender.amount_in_base), 0.0))
              .filter(SaleTender.sale_id.in_(sale_ids))
              .group_by(SaleTender.sale_id).all())
    return {sale_id: round(total or 0.0, 2) for sale_id, total in rows}


@router.get("/owed")
def money_owed(patient_id: int = 0, db: Session = Depends(get_db),
               _: User = Depends(get_current_user)):
    """Sales that went out without being paid for in full.

    A work list, not a report. Every row is medicine the pharmacy has already
    handed over and money it has not been given, and it stays here until
    somebody collects it — which is exactly why it has to be visible.
    """
    query = (db.query(Sale)
               .options(*_sale_graph())
               .filter(Sale.status == "part_paid"))
    if patient_id:
        query = query.filter(Sale.patient_id == patient_id)
    sales = query.order_by(Sale.created_at).limit(500).all()

    paid = _paid_on(db, [s.id for s in sales])
    rows = []
    for sale in sales:
        collected = paid.get(sale.id, 0.0)
        balance = round((sale.total or 0.0) - collected, 2)
        if balance <= 0.005:
            continue
        person = sale.patient
        rows.append({
            "sale_id": sale.id,
            "sale_number": sale.sale_number,
            "created_at": sale.created_at,
            "patient_id": sale.patient_id,
            "patient": (f"{person.first_name} {person.last_name}".strip()
                        if person else "Walk-in"),
            "phone": (person.phone or "") if person else "",
            "total": round(sale.total or 0.0, 2),
            "paid": collected,
            "balance": balance,
            "days": (datetime.utcnow() - sale.created_at).days if sale.created_at else 0,
        })
    return {
        "items": rows,
        "total_owed": round(sum(r["balance"] for r in rows), 2),
        "patients": len({r["patient_id"] for r in rows if r["patient_id"]}),
    }


@router.get("/sales/{sale_id}/pay", response_model=schemas.SaleOut)
def sale_for_payment(sale_id: int, db: Session = Depends(get_db),
                     _: User = Depends(get_current_user)):
    """One sale, for a till about to take money against it."""
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    return sale


@router.post("/sales/{sale_id}/pay", response_model=schemas.SaleOut)
def pay_sale(sale_id: int, body: schemas.PayRequest, db: Session = Depends(get_db),
             user: User = Depends(get_current_user),
             step_up: str = Header(default="", alias="X-Step-Up")):
    """Settle a pending sale created by the dispensary."""
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    # A part-paid sale is still collectable: the patient is coming back with
    # the rest of it, which is the entire point of allowing the balance.
    if sale.status not in ("pending", "part_paid"):
        raise HTTPException(status_code=400,
                            detail=f"Sale is {sale.status}, not awaiting payment")
    if getattr(body, "part_payment", False):
        _require_part_payment_approval(db, user, step_up)
    if sale.shift_id is None:
        shift = shifts_router.current_open_shift(db, user.id)
        sale.shift_id = shift.id if shift else None
    _settle_payment(db, sale, body.payment_method, body.amount_tendered,
                    body.loyalty_points_redeemed, user, body_tenders=body)
    _record_card_tender(sale, body)
    db.commit()
    fiscal.fiscalise(db, sale)
    # Post to the ledger. Deliberately after the sale is committed and
    # deliberately non-fatal: the medicine has gone out, and the bookkeeping
    # must not be able to undo that. A refusal lands on the unposted queue.
    posting.post_sale(db, sale, user.id)
    db.refresh(sale)
    return sale


@router.post("/reconciliation/card", response_model=schemas.CardReconciliation)
def reconcile_card(body: schemas.CardReconcileRequest, db: Session = Depends(get_db),
                   _: User = Depends(get_current_user)):
    """Match an acquirer settlement file against the card sales on record."""
    if not body.csv_text.strip():
        raise HTTPException(status_code=400, detail="No settlement data supplied")
    return reconciliation.reconcile(db, body.csv_text, body.date_from, body.date_to)


def _sale_graph():
    """Everything SaleOut renders, fetched in a fixed number of queries.

    SaleOut carries the tenders, the lines, the claim and the patient. Only the
    patient was eager-loaded, so the other three were fetched per row: fifty
    paid sales cost 266 queries. On SQLite that is invisible. Against a hosted
    Postgres at roughly ninety milliseconds a round trip it is most of half a
    minute, which is why the front shop's billing history appeared to hang.

    `selectinload` rather than `joinedload` for the collections: a join across
    two one-to-many relations multiplies the rows out, so a sale with four
    lines and two tenders would come back eight times and be de-duplicated in
    Python. This issues one extra query per relation regardless of how many
    rows there are.
    """
    return (
        # PatientOut nests the medical aid, so loading the patient alone still
        # left one query per row to find out which scheme they are on.
        joinedload(Sale.patient).joinedload(Patient.medical_aid),
        # SaleItemOut carries the batch allocations, and AllocationOut carries
        # the batch itself — so each line cost two more round trips, which is
        # where the bulk of the 266 actually went. Serialisation walks whatever
        # the schema declares, so the eager load has to reach as deep as the
        # schema does.
        selectinload(Sale.items)
        .selectinload(SaleItem.allocations)
        .joinedload(BatchAllocation.batch),
        selectinload(Sale.tenders),
        joinedload(Sale.claim),
    )


@router.get("/sales", response_model=list[schemas.SaleOut])
def list_sales(status: str = "", q: str = "", limit: int = 100,
               db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """What the till has taken, newest first.

    `q` searches the invoice number and the customer's name, which are the two
    things anybody actually has when they ask: a slip in their hand, or the name
    of the person who was standing there. The front shop had no history screen
    at all until now, so this had never needed to answer a search.

    The patient is joined rather than lazily loaded — the list renders a name
    per row, and fifty rows was fifty extra queries against a hosted database.
    """
    query = db.query(Sale).options(*_sale_graph())
    if status:
        query = query.filter(Sale.status == status)
    term = (q or "").strip()
    if term:
        like = f"%{term.lower()}%"
        query = (query.outerjoin(Patient, Sale.patient_id == Patient.id)
                 .filter(or_(
                     func.lower(Sale.sale_number).like(like),
                     func.lower(Patient.first_name).like(like),
                     func.lower(Patient.last_name).like(like),
                 )))
    return query.order_by(Sale.created_at.desc()).limit(max(1, min(limit, 200))).all()


@router.get("/sales/{sale_id}", response_model=schemas.SaleOut)
def get_sale(sale_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    return sale


@router.post("/sales/{sale_id}/void", response_model=schemas.SaleOut)
def void_sale(sale_id: int, db: Session = Depends(get_db),
              user: User = Depends(get_current_user),
              _grant=Depends(require_step_up("sale.void"))):
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.status == "void":
        raise HTTPException(status_code=400, detail="Sale already voided")
    if fiscal.is_locked(db, sale):
        # A receipt filed with the revenue authority cannot be withdrawn.
        raise HTTPException(
            status_code=400,
            # Written for whoever is standing at the till with a customer, not
            # for somebody holding curl. The sale screen offers the credit note
            # itself now, so nobody should reach this — but an error message is
            # read precisely when something unexpected happened.
            detail="This sale was filed with ZIMRA and cannot be voided. A "
                   "filed receipt stands; it is reversed by a credit note "
                   "instead, which the sale's own page will issue.",
        )
    # Return stock to the exact batches it was drawn from.
    helpers.return_sale_stock(db, sale, user.id, reference=f"VOID {sale.sale_number}")
    if sale.claim and sale.claim.status in ("approved", "partial"):
        claims_engine.reverse_claim(db, sale.claim)
    if sale.patient_id:
        patient = db.get(Patient, sale.patient_id)
        patient.loyalty_points = max(0, patient.loyalty_points - sale.loyalty_points_earned + sale.loyalty_points_redeemed)
    sale.status = "void"
    db.commit()
    db.refresh(sale)
    return sale


# A bare list of the newest hundred claims used to be here. The claiming
# screens use /api/claiming/* and /api/claims/*, which page, filter, batch and
# settle — everything this could not do. An unfiltered list of a table that
# grows forever is a wrong answer waiting for the pharmacy to get busy.

@router.post("/sales/{sale_id}/return")
def return_lines(sale_id: int,
                 lines: list[dict] = Body(default_factory=list),
                 apply: bool = Body(default=False),
                 reason: str = Body(default=""),
                 restock: bool = Body(default=True),
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Take part of a sale back.

    Preview first. A return moves money and stock at once and both are awkward
    to undo, so nothing is written until somebody has read what would happen.

    Everything coming back is a full reversal and has its own route — void, or
    a credit note where the receipt has been filed. This says so rather than
    quietly doing something subtly different from either.
    """
    from ..services import returns

    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.status in ("void", "credited"):
        raise HTTPException(
            status_code=400,
            detail=f"This sale is already {sale.status} — there is nothing "
                   f"left on it to return.")
    if sale.status == "pending":
        raise HTTPException(
            status_code=400,
            detail="This sale has not been paid for yet. Take the line off the "
                   "sale rather than returning it.")

    if not apply:
        return returns.plan(db, sale, lines)

    preview = returns.plan(db, sale, lines)
    if preview["is_whole_sale"]:
        raise HTTPException(
            status_code=400,
            detail="Every line is coming back, which is a reversal of the "
                   "whole sale. Void it, or issue a credit note if the receipt "
                   "has been filed with ZIMRA — either keeps the claim and the "
                   "loyalty points right, which a line-by-line return does not.")
    try:
        result = returns.apply(db, sale, lines, user_id=user.id,
                               reason=reason, restock=restock)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return result


@router.post("/sales/{sale_id}/transfer-to-account")
def transfer_to_account(
    sale_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Move an unpaid sale onto the customer's account.

    The third thing that can happen to a COD, after being paid and being
    cancelled. The goods have gone, the customer is not paying today, and the
    debt moves from "money expected at the door" to "money owed on an account"
    — which is where it can be aged, chased and eventually provided against.

    It needs a customer, because an account balance with nobody attached to it
    cannot be collected. That is the same unattributed debt the aged analysis
    keeps reporting, and this is where it would come from if it were allowed.
    """
    sale = db.query(Sale).get(sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="That sale no longer exists.")
    if sale.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=(
                "Only a sale still awaiting payment can be transferred. "
                f"This one is {sale.status}."
            ),
        )
    if not sale.patient_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "This sale has no customer on it, so there is no account to "
                "transfer it to. Attach the customer first."
            ),
        )
    if sale.transferred_at:
        return {"ok": True, "already": True,
                "message": "This sale is already on the customer's account."}

    sale.transferred_at = datetime.utcnow()
    sale.transferred_by_id = user.id
    db.commit()
    return {
        "ok": True,
        "message": (
            f"{sale.sale_number} moved to the customer's account. It will now "
            "appear in the aged analysis rather than as an outstanding COD."
        ),
    }
