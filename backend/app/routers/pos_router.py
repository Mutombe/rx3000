from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import helpers, schemas
from ..auth import get_current_user
from ..database import get_db
from .periods_router import require_step_up
from ..models import Claim, Patient, Product, Sale, SaleItem, User
from ..services import claims_engine, currency, fiscal, posting, reconciliation
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
            )
            collected += tender.amount_in_base

        collected = round(collected, 2)
        if collected + 0.005 < amount_due:
            short = round(amount_due - collected, 2)
            raise HTTPException(
                status_code=400,
                detail=f"Tendered {collected} of {amount_due}, short by {short}"
                       f"{currency.base_code()}",
            )

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

    amount_due = round(sale.total - redeem_value, 2)
    sale.payment_method = payment_method
    sale.currency_code = sale.currency_code or currency.base_code()

    # Split tender takes over when supplied — the single-tender fields below
    # stay for callers that never need more than one payment.
    if getattr(body_tenders, "tenders", None):
        _settle_split_tender(db, sale, body_tenders, amount_due)
        methods = {t.method for t in body_tenders.tenders if t.amount > 0}
        sale.payment_method = methods.pop() if len(methods) == 1 else "split"
        if patient:
            earned = int(amount_due * LOYALTY_EARN_RATE)
            sale.loyalty_points_earned = earned
            patient.loyalty_points += earned
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
            raise HTTPException(status_code=400, detail="Amount tendered is less than the amount due")
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
    for line in body.items:
        product = db.get(Product, line.product_id)
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


@router.post("/sales/{sale_id}/pay", response_model=schemas.SaleOut)
def pay_sale(sale_id: int, body: schemas.PayRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Settle a pending sale created by the dispensary."""
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.status != "pending":
        raise HTTPException(status_code=400, detail=f"Sale is {sale.status}, not pending")
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


@router.get("/sales", response_model=list[schemas.SaleOut])
def list_sales(status: str = "", limit: int = 100, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    query = db.query(Sale)
    if status:
        query = query.filter(Sale.status == status)
    return query.order_by(Sale.created_at.desc()).limit(limit).all()


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
            detail="This sale has been fiscalised and cannot be voided. "
                   "Issue a credit note instead (POST /api/fiscal/credit-note/{sale_id})",
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


@router.get("/claims", response_model=list[schemas.ClaimOut])
def list_claims(limit: int = 100, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Claim).order_by(Claim.created_at.desc()).limit(limit).all()


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
