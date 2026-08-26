"""Turning what happened in the shop into what the ledger says.

A ledger nobody posts to is a ledger nobody trusts, and one posted to by hand is
a ledger that reflects whoever last typed into it. So the postings here are
derived from the transaction, not entered against it.

The rules are ordinary double entry, but two of them are worth stating because
they are where pharmacy accounting usually goes wrong:

* **A medical aid sale is two debtors, not one.** The scheme owes the approved
  amount and the patient owes the levy, and they are collected by completely
  different processes weeks apart. Posting the whole sale to one debtor makes
  the ageing report meaningless and hides which of the two is actually late.

* **Cost of goods sold uses the cost frozen on the sale line**, never the
  product's cost price today. Stock is bought again at a different price every
  month; valuing last month's sales at this month's cost produces a margin that
  is confidently wrong and moves every time the buyer negotiates.

Posting is deliberately non-fatal. If the ledger refuses — a closed period, a
missing account — the sale still completes. A till that would not sell medicine
because the bookkeeping was unhappy would be a worse product than one whose
ledger is briefly behind, and the failure is recorded rather than swallowed.
"""
import logging
from datetime import date

from sqlalchemy.orm import Session

from ..config import settings
from ..models import JournalEntry, Sale
from . import ledger

log = logging.getLogger("rx5000.posting")

# Where the money landed, by how it was tendered.
TENDER_ACCOUNT = {
    "cash": "1000",
    "card": "1010",
    "mobile_money": "1010",
    "eft": "1010",
    "account": "1100",
    "split": "1000",
}

REVENUE_ACCOUNT = {"medicine": "4000"}      # everything else is front shop
FRONT_SHOP = "4010"
SCHEME_DEBTORS = "1110"
PATIENT_DEBTORS = "1100"
VAT_OUTPUT = "2100"
COGS = "5000"
STOCK = "1200"


def already_posted(db: Session, source: str, source_id: int) -> JournalEntry | None:
    return (db.query(JournalEntry)
            .filter(JournalEntry.source == source,
                    JournalEntry.source_id == source_id,
                    JournalEntry.status == "posted")
            .first())


def post_sale(db: Session, sale: Sale, user_id: int | None = None) -> dict:
    """Post a settled sale. Idempotent: a sale posts once.

    Returns a result rather than raising, because the sale has already happened
    and the accounting must not be able to undo it.
    """
    existing = already_posted(db, "sale", sale.id)
    if existing:
        return {"posted": False, "reason": "already posted",
                "reference": existing.reference}

    ledger.ensure_chart(db)
    lines: list[ledger.Line] = []

    # --- revenue, split by what was sold ---
    revenue: dict[str, float] = {}
    cost_total = 0.0
    for item in sale.items:
        category = (item.product.category if item.product else "") or ""
        account = REVENUE_ACCOUNT.get(category, FRONT_SHOP)
        ex_vat = round(item.line_total / (1 + (item.vat_rate or 0.0)), 2)
        revenue[account] = round(revenue.get(account, 0.0) + ex_vat, 2)
        cost_total += round((item.unit_cost or 0.0) * item.quantity, 2)

    for account, amount in revenue.items():
        if amount:
            lines.append(ledger.Line(account_code=account, credit=amount,
                                     description="Sales"))
    if sale.vat_amount:
        lines.append(ledger.Line(account_code=VAT_OUTPUT, credit=round(sale.vat_amount, 2),
                                 description="VAT on sales"))

    # --- what was received, and from whom ---
    claim = sale.claim
    if claim and claim.status in ("approved", "partial", "deferred"):
        # Two debtors, not one: the scheme and the patient are chased by
        # different people on different timescales.
        scheme_share = round(claim.amount_approved or 0.0, 2)
        patient_share = round((sale.total or 0.0) - scheme_share, 2)
        if scheme_share:
            lines.append(ledger.Line(
                account_code=SCHEME_DEBTORS, debit=scheme_share,
                description=f"Claim {claim.claim_number}",
                party_type="scheme", party_id=claim.medical_aid_id))
        if patient_share:
            lines.append(ledger.Line(
                account_code=TENDER_ACCOUNT.get(sale.payment_method, "1000"),
                debit=patient_share, description="Patient portion",
                party_type="patient", party_id=sale.patient_id))
    else:
        account = TENDER_ACCOUNT.get(sale.payment_method or "cash", "1000")
        party_type = "patient" if account == PATIENT_DEBTORS else ""
        lines.append(ledger.Line(
            account_code=account, debit=round(sale.total or 0.0, 2),
            description=f"Settled by {sale.payment_method}",
            party_type=party_type,
            party_id=sale.patient_id if party_type else None))

    # --- cost of what left the shelf, at the cost frozen when it left ---
    cost_total = round(cost_total, 2)
    if cost_total:
        lines.append(ledger.Line(account_code=COGS, debit=cost_total,
                                 description="Cost of goods sold"))
        lines.append(ledger.Line(account_code=STOCK, credit=cost_total,
                                 description="Stock issued"))

    try:
        entry = ledger.post(
            db, entry_date=(sale.created_at.date() if sale.created_at else date.today()),
            description=f"Sale {sale.sale_number}", lines=lines,
            source="sale", source_id=sale.id,
            currency_code=sale.currency_code or "USD", user_id=user_id)
    except ledger.LedgerError as exc:
        # Never fatal. A till that refused to sell medicine because the
        # bookkeeping was unhappy would be a worse product than one whose ledger
        # is briefly behind — but the failure is recorded, not swallowed.
        log.warning("sale %s did not post: %s", sale.sale_number, exc)
        return {"posted": False, "reason": str(exc), "reference": ""}

    return {"posted": True, "reference": entry.reference,
            "total": entry_total(entry), "lines": len(entry.lines)}


def entry_total(entry: JournalEntry) -> float:
    return round(sum(l.debit for l in entry.lines), 2)


def post_reversal(db: Session, sale: Sale, user_id: int | None = None) -> dict:
    """Reverse a sale's posting when the sale itself is reversed."""
    entry = already_posted(db, "sale", sale.id)
    if not entry:
        return {"posted": False, "reason": "the sale was never posted"}
    try:
        reversal = ledger.reverse(db, entry, reason=f"Sale {sale.sale_number} reversed",
                                  user_id=user_id)
    except ledger.LedgerError as exc:
        log.warning("reversal of %s did not post: %s", sale.sale_number, exc)
        return {"posted": False, "reason": str(exc)}
    return {"posted": True, "reference": reversal.reference}


def unposted_sales(db: Session, limit: int = 200) -> list[dict]:
    """Sales the ledger has not caught up with.

    Posting is non-fatal, so this is the queue that stops "briefly behind" from
    becoming "quietly wrong". It is the first thing to read when the trial
    balance does not match the till.
    """
    posted = {e.source_id for e in db.query(JournalEntry)
              .filter(JournalEntry.source == "sale",
                      JournalEntry.status == "posted").all()}
    rows = (db.query(Sale).filter(Sale.status == "paid")
            .order_by(Sale.created_at.desc()).limit(limit * 3).all())
    return [{"sale_id": s.id, "sale_number": s.sale_number,
             "total": s.total, "created_at": s.created_at}
            for s in rows if s.id not in posted][:limit]


# ---------------------------------------------------------------------------
# The purchase side
#
# Without this the stock control account only ever goes down: sales credit it,
# nothing debits it, and within a month it is meaninglessly negative while the
# stock subledger says something else entirely. A ledger that only records half
# a business is not behind — it is wrong.
# ---------------------------------------------------------------------------

CREDITORS = "2000"
VAT_INPUT = "1300"


def post_stock_receipt(db: Session, order, user_id: int | None = None) -> dict:
    """Post goods received against a purchase order.

        Dr Stock          what the goods cost
        Dr VAT input      the recoverable tax
           Cr Creditors   what the supplier is owed

    Idempotent per order. Receiving is the event that creates the liability, not
    paying it — a pharmacy owes for stock the moment it is on the shelf, and a
    ledger that waits for the payment understates its creditors for a month.
    """
    existing = already_posted(db, "stock_receipt", order.id)
    if existing:
        return {"posted": False, "reason": "already posted",
                "reference": existing.reference}

    ledger.ensure_chart(db)
    goods = 0.0
    for item in order.items:
        received = getattr(item, "quantity_received", 0) or 0
        goods += round((item.unit_cost or 0.0) * received, 2)
    goods = round(goods, 2)
    if goods <= 0:
        return {"posted": False, "reason": "nothing received to post"}

    # VAT on purchases is recoverable, so it is an asset rather than part of the
    # cost of the goods. Folding it into stock would overstate cost of sales for
    # the life of the batch.
    rate = settings.VAT_RATE or 0.0
    net = round(goods / (1 + rate), 2) if rate else goods
    vat = round(goods - net, 2)

    lines = [ledger.Line(account_code=STOCK, debit=net, description="Goods received")]
    if vat:
        lines.append(ledger.Line(account_code=VAT_INPUT, debit=vat,
                                 description="VAT on purchases"))
    lines.append(ledger.Line(
        account_code=CREDITORS, credit=goods,
        description=f"Order {order.order_number}",
        party_type="supplier", party_id=order.supplier_id))

    try:
        entry = ledger.post(
            db, entry_date=date.today(),
            description=f"Goods received on {order.order_number}", lines=lines,
            source="stock_receipt", source_id=order.id, user_id=user_id)
    except ledger.LedgerError as exc:
        # Never fatal: the stock is on the shelf whatever the ledger thinks.
        log.warning("receipt for %s did not post: %s", order.order_number, exc)
        return {"posted": False, "reason": str(exc), "reference": ""}

    return {"posted": True, "reference": entry.reference,
            "goods": goods, "vat": vat, "lines": len(entry.lines)}


def unposted_receipts(db: Session, limit: int = 200) -> list[dict]:
    """Received orders the ledger has not caught up with."""
    from ..models import PurchaseOrder

    posted = {e.source_id for e in db.query(JournalEntry)
              .filter(JournalEntry.source == "stock_receipt",
                      JournalEntry.status == "posted").all()}
    rows = (db.query(PurchaseOrder).filter(PurchaseOrder.status == "received")
            .order_by(PurchaseOrder.id.desc()).limit(limit * 3).all())
    return [{"order_id": o.id, "order_number": o.order_number,
             "supplier_id": o.supplier_id}
            for o in rows if o.id not in posted][:limit]
