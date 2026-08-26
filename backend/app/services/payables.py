"""Supplier invoices: the three-way match, payment, and what is owed to whom.

The ledger already raised a creditor when goods were received, using the costs
written on the purchase order. That is the best figure available at that moment
and it is not a bill. Nothing in this system had ever read the invoice the
supplier actually sent, which left three holes:

  **A price rise between ordering and delivery vanished.** The order said 4.20,
  the wholesaler billed 4.85, and the creditor stayed at 4.20 for ever. The
  pharmacy paid the higher figure out of the bank and the difference came to
  rest as an unexplained reconciling item nobody could name.

  **Being billed for more than arrived was invisible.** Ten boxes came, twelve
  were invoiced. Only a comparison of the receipt against the bill catches that,
  and there was nothing to compare against.

  **Nothing ever debited trade creditors.** Not once, anywhere in the codebase.
  Every receipt credited it and no payment reduced it, so the account grew
  monotonically for the life of the pharmacy and the balance sheet showed debts
  that had been settled years earlier.

What is posted here is the **difference**, not a second liability. The receipt
already booked the creditor; posting the invoice in full would book it twice and
each entry would look perfectly correct on its own. This is the same trap as the
stock provision and it is the one that is hardest to find afterwards.

Where the variance lands is a judgement, and it is stated rather than hidden.
It goes to a purchase price variance account, not back into stock, because by
the time an invoice is keyed the goods are usually part sold and restating the
batch cost would misstate the margin already reported on those sales. The effect
is that a price rise is a cost of the period it was billed in. An accountant who
prefers it capitalised has one account to reclassify and can see exactly which
entries to move.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Account, JournalEntry, Product, PurchaseOrder, PurchaseOrderItem, Supplier,
    SupplierInvoice, SupplierInvoiceItem, SupplierPayment,
    SupplierPaymentAllocation,
)
from . import ledger

CREDITORS = "2000"
VAT_INPUT = "1300"
BANK = "1010"
CASH = "1000"
STOCK = "1200"

#: Added to a chart that predates this module.
VARIANCE_ACCOUNT = ("5120", "Purchase price variance", "expense", "")

#: How far a line may differ before it is worth a pharmacist's attention.
#:
#: Zero tolerance sounds rigorous and is useless: rounding on a twelve-line
#: invoice throws a cent, and a match that flags every invoice is a match
#: nobody reads. These are deliberately loose enough that a flag means
#: something. Both are applied — a large percentage on a trivial amount is
#: noise, and so is a small percentage on a hundred dollars.
PRICE_TOLERANCE = 0.02        # 2% either way
VALUE_TOLERANCE = 1.00        # or a dollar, whichever is the larger

#: Creditor ageing buckets, in days past the due date.
AGE_BANDS = [(0, "Not yet due"), (30, "1 to 30 days"), (60, "31 to 60 days"),
             (90, "61 to 90 days")]
AGE_OLDEST = "Over 90 days"

#: Where no supplier terms are recorded. Thirty days is the Zimbabwean
#: wholesale norm and is used only when the invoice carries no due date.
DEFAULT_TERM_DAYS = 30


def _ensure_accounts(db: Session) -> None:
    code, name, kind, subledger = VARIANCE_ACCOUNT
    if not db.query(Account).filter(Account.code == code).first():
        db.add(Account(code=code, name=name, type=kind, subledger=subledger))
        db.commit()


def _split_vat(gross: float) -> tuple[float, float]:
    """Net and tax out of a tax-inclusive figure."""
    rate = settings.VAT_RATE or 0.0
    net = round(gross / (1 + rate), 2) if rate else round(gross, 2)
    return net, round(gross - net, 2)


def _within_tolerance(expected: float, actual: float) -> bool:
    gap = abs(actual - expected)
    if gap <= VALUE_TOLERANCE:
        return True
    return bool(expected) and gap / abs(expected) <= PRICE_TOLERANCE


# ---------------------------------------------------------------------------
# The match
# ---------------------------------------------------------------------------

def match(db: Session, invoice: SupplierInvoice) -> dict:
    """Compare what was ordered, what arrived, and what was billed.

    Returns the comparison rather than a verdict. Whether a two per cent price
    rise is acceptable is a decision for whoever knows the supplier, and a
    routine that silently approves is worse than one that silently rejects.

    When the invoice has no lines keyed this degrades to a comparison of totals
    and says so in `depth`, because a total that agrees can hide a short
    delivery and an overcharge cancelling each other out.
    """
    order = db.get(PurchaseOrder, invoice.order_id) if invoice.order_id else None
    billed = round(invoice.total or 0.0, 2)

    if order is None:
        return {
            "depth": "none",
            "matched": False,
            "ordered": 0.0, "received": 0.0, "billed": billed,
            "variance": billed,
            "lines": [],
            "problems": ["No purchase order is linked, so there is nothing to "
                         "check this invoice against. It can still be recorded "
                         "and paid, but nobody has confirmed the goods arrived "
                         "or that this is the price agreed."],
        }

    ordered_value = 0.0
    received_value = 0.0
    po_by_product: dict[int, PurchaseOrderItem] = {}
    for item in order.items:
        ordered_value += (item.unit_cost or 0.0) * (item.quantity_ordered or 0)
        received_value += (item.unit_cost or 0.0) * (item.quantity_received or 0)
        if item.product_id:
            po_by_product[item.product_id] = item
    ordered_value = round(ordered_value, 2)
    received_value = round(received_value, 2)

    problems: list[str] = []
    lines: list[dict] = []

    if invoice.items:
        seen: set[int] = set()
        for line in invoice.items:
            po = po_by_product.get(line.product_id) if line.product_id else None
            if po is not None:
                seen.add(po.product_id)
            product = db.get(Product, line.product_id) if line.product_id else None
            name = (f"{product.name} {product.strength or ''}".strip()
                    if product else (line.description or "Unidentified line"))
            billed_qty = line.quantity or 0
            billed_cost = round(line.unit_cost or 0.0, 2)
            recv_qty = (po.quantity_received or 0) if po else 0
            order_cost = round((po.unit_cost or 0.0), 2) if po else 0.0

            row = {
                "description": name,
                "product_id": line.product_id,
                "billed_quantity": billed_qty,
                "received_quantity": recv_qty,
                "billed_unit_cost": billed_cost,
                "ordered_unit_cost": order_cost,
                "line_total": round(line.line_total or billed_qty * billed_cost, 2),
                "issues": [],
            }
            if po is None:
                row["issues"].append("not on the order")
                problems.append(f"{name} is billed but was never ordered.")
            else:
                if billed_qty > recv_qty:
                    row["issues"].append("billed for more than arrived")
                    problems.append(
                        f"{name}: billed for {billed_qty} but {recv_qty} "
                        f"{'was' if recv_qty == 1 else 'were'} received.")
                elif billed_qty < recv_qty:
                    row["issues"].append("billed for less than arrived")
                if not _within_tolerance(order_cost, billed_cost):
                    row["issues"].append("price differs from the order")
                    direction = "above" if billed_cost > order_cost else "below"
                    problems.append(
                        f"{name}: billed at {billed_cost:.2f}, which is "
                        f"{direction} the {order_cost:.2f} on the order.")
            lines.append(row)

        for product_id, po in po_by_product.items():
            if product_id in seen or not (po.quantity_received or 0):
                continue
            product = db.get(Product, product_id)
            name = f"{product.name} {product.strength or ''}".strip() if product else "A line"
            lines.append({
                "description": name, "product_id": product_id,
                "billed_quantity": 0, "received_quantity": po.quantity_received,
                "billed_unit_cost": 0.0,
                "ordered_unit_cost": round(po.unit_cost or 0.0, 2),
                "line_total": 0.0,
                "issues": ["received but not billed"],
            })
        depth = "lines"
    else:
        depth = "totals"
        problems.append(
            "Only the invoice total was keyed, so this is a check of totals "
            "rather than a line-by-line match. A short delivery and an "
            "overcharge of the same size would cancel out and pass.")

    variance = round(billed - received_value, 2)
    if not _within_tolerance(received_value, billed):
        problems.append(
            f"The invoice totals {billed:.2f} against {received_value:.2f} of "
            f"goods received on {order.order_number}, a difference of "
            f"{variance:+.2f}.")

    return {
        "depth": depth,
        "matched": not problems,
        "order_number": order.order_number,
        "ordered": ordered_value,
        "received": received_value,
        "billed": billed,
        "variance": variance,
        "lines": lines,
        "problems": problems,
    }


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------

def _receipt_entry(db: Session, order_id: int) -> JournalEntry | None:
    return (db.query(JournalEntry)
              .filter(JournalEntry.source == "stock_receipt",
                      JournalEntry.source_id == order_id,
                      JournalEntry.status == "posted")
              .first())


def post_invoice(db: Session, invoice: SupplierInvoice,
                 user_id: int | None = None) -> dict:
    """Bring the creditor to what the supplier actually billed.

    Posts the movement. If the goods receipt already raised 420.00 and the
    invoice says 485.00, this posts 65.00 — not 485.00 on top of it. Where no
    receipt was ever posted the whole invoice is raised, because then nothing
    else has.
    """
    if invoice.posted_reference:
        return {"posted": False, "reason": "already posted",
                "reference": invoice.posted_reference}
    _ensure_accounts(db)

    billed = round(invoice.total or 0.0, 2)
    if billed <= 0:
        return {"posted": False, "reason": "the invoice has no value"}

    receipt = _receipt_entry(db, invoice.order_id) if invoice.order_id else None
    order = db.get(PurchaseOrder, invoice.order_id) if invoice.order_id else None

    if receipt is None:
        # Nothing booked this liability, so book all of it. The goods are on the
        # shelf either way; the ledger is what is behind.
        net, vat = _split_vat(billed)
        lines = [ledger.Line(account_code=STOCK, debit=net,
                             description="Goods invoiced")]
        if vat:
            lines.append(ledger.Line(account_code=VAT_INPUT, debit=vat,
                                     description="VAT on purchases"))
        lines.append(ledger.Line(
            account_code=CREDITORS, credit=billed,
            description=f"Invoice {invoice.invoice_number}",
            party_type="supplier", party_id=invoice.supplier_id))
        what = f"Invoice {invoice.invoice_number}"
        kind = "full"
        amount = billed
    else:
        received_value = 0.0
        for item in (order.items if order else []):
            received_value += (item.unit_cost or 0.0) * (item.quantity_received or 0)
        variance = round(billed - round(received_value, 2), 2)
        if abs(variance) < 0.005:
            invoice.posted_reference = receipt.reference
            invoice.status = "approved" if invoice.status != "paid" else invoice.status
            db.commit()
            return {"posted": False, "reason": "agrees with the goods receipt",
                    "reference": receipt.reference, "variance": 0.0}
        net, vat = _split_vat(abs(variance))
        up = variance > 0
        lines = [ledger.Line(account_code=VARIANCE_ACCOUNT[0],
                             debit=net if up else 0.0,
                             credit=0.0 if up else net,
                             description="Billed above the order" if up
                                         else "Billed below the order")]
        if vat:
            lines.append(ledger.Line(account_code=VAT_INPUT,
                                     debit=vat if up else 0.0,
                                     credit=0.0 if up else vat,
                                     description="VAT on the difference"))
        lines.append(ledger.Line(
            account_code=CREDITORS,
            debit=0.0 if up else abs(variance),
            credit=abs(variance) if up else 0.0,
            description=f"Invoice {invoice.invoice_number} against "
                        f"{order.order_number if order else 'the receipt'}",
            party_type="supplier", party_id=invoice.supplier_id))
        what = (f"Invoice {invoice.invoice_number}: difference against goods "
                f"received")
        kind = "variance"
        amount = variance

    try:
        entry = ledger.post(
            db, entry_date=invoice.invoice_date or date.today(),
            description=what, lines=lines, source="supplier_invoice",
            source_id=invoice.id, user_id=user_id,
            currency_code=invoice.currency_code or "USD")
    except ledger.LedgerError as exc:
        return {"posted": False, "reason": str(exc)}

    invoice.posted_reference = entry.reference
    if invoice.status in ("unmatched", "matched", "queried"):
        invoice.status = "approved"
    invoice.approved_at = datetime.utcnow()
    invoice.approved_by = user_id
    db.commit()
    return {"posted": True, "reference": entry.reference, "kind": kind,
            "amount": amount}


# ---------------------------------------------------------------------------
# Paying
# ---------------------------------------------------------------------------

def record_payment(db: Session, *, supplier_id: int, amount: float,
                   paid_on: date | None = None, method: str = "bank",
                   reference: str = "", allocations: list[dict] | None = None,
                   notes: str = "", user_id: int | None = None) -> dict:
    """Pay a supplier and say which invoices it settled.

        Dr Creditors    what is no longer owed
           Cr Bank      what left the account

    An unallocated payment is still recorded. A pharmacy that pays a round
    figure on account is doing something normal, and refusing to record it until
    somebody works out the split is how payments end up only in the bank
    statement.
    """
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise ValueError("No such supplier.")
    amount = round(float(amount or 0.0), 2)
    if amount <= 0:
        raise ValueError("A payment has to be for something.")

    allocations = allocations or []
    allocated = round(sum(float(a.get("amount") or 0.0) for a in allocations), 2)
    if allocated - amount > 0.005:
        raise ValueError(
            f"The allocations come to {allocated:.2f}, which is more than the "
            f"{amount:.2f} being paid.")

    payment = SupplierPayment(
        supplier_id=supplier_id, amount=amount, paid_on=paid_on or date.today(),
        method=method or "bank", reference=reference or "", notes=notes or "",
        user_id=user_id)
    db.add(payment)
    db.flush()

    for alloc in allocations:
        invoice = db.get(SupplierInvoice, int(alloc.get("invoice_id") or 0))
        if invoice is None or invoice.supplier_id != supplier_id:
            raise ValueError("A payment cannot be allocated to another "
                             "supplier's invoice.")
        share = round(float(alloc.get("amount") or 0.0), 2)
        if share <= 0:
            continue
        db.add(SupplierPaymentAllocation(
            payment_id=payment.id, invoice_id=invoice.id, amount=share))

    ledger.ensure_chart(db)
    credit_account = CASH if method == "cash" else BANK
    lines = [
        ledger.Line(account_code=CREDITORS, debit=amount,
                    description=f"Paid {supplier.name}",
                    party_type="supplier", party_id=supplier_id),
        ledger.Line(account_code=credit_account, credit=amount,
                    description=reference or f"Payment to {supplier.name}"),
    ]
    try:
        entry = ledger.post(
            db, entry_date=payment.paid_on,
            description=f"Payment to {supplier.name}", lines=lines,
            source="supplier_payment", source_id=payment.id, user_id=user_id)
        payment.posted_reference = entry.reference
    except ledger.LedgerError as exc:
        # The money has left the bank whatever the ledger thinks. Recording the
        # payment and flagging the posting beats losing both.
        db.commit()
        return {"payment_id": payment.id, "posted": False, "reason": str(exc)}

    db.commit()
    _restate_status(db, [int(a.get("invoice_id") or 0) for a in allocations])
    return {"payment_id": payment.id, "posted": True,
            "reference": payment.posted_reference, "amount": amount,
            "allocated": allocated, "on_account": round(amount - allocated, 2)}


def _restate_status(db: Session, invoice_ids: list[int]) -> None:
    for invoice_id in {i for i in invoice_ids if i}:
        invoice = db.get(SupplierInvoice, invoice_id)
        if invoice is None:
            continue
        paid = round(db.query(func.coalesce(
            func.sum(SupplierPaymentAllocation.amount), 0.0))
            .filter(SupplierPaymentAllocation.invoice_id == invoice_id).scalar() or 0.0, 2)
        if paid + 0.005 >= round(invoice.total or 0.0, 2):
            invoice.status = "paid"
    db.commit()


def paid_against(db: Session, invoice_ids: list[int]) -> dict[int, float]:
    if not invoice_ids:
        return {}
    rows = (db.query(SupplierPaymentAllocation.invoice_id,
                     func.coalesce(func.sum(SupplierPaymentAllocation.amount), 0.0))
              .filter(SupplierPaymentAllocation.invoice_id.in_(invoice_ids))
              .group_by(SupplierPaymentAllocation.invoice_id).all())
    return {invoice_id: round(total or 0.0, 2) for invoice_id, total in rows}


# ---------------------------------------------------------------------------
# What is owed
# ---------------------------------------------------------------------------

def _due(invoice: SupplierInvoice) -> date:
    if invoice.due_date:
        return invoice.due_date
    base = invoice.invoice_date or date.today()
    return base + timedelta(days=DEFAULT_TERM_DAYS)


def ageing(db: Session, *, asof: date | None = None) -> dict:
    """Who is owed what, and how late it is.

    Ages on the due date rather than the invoice date. Ageing on the invoice
    date reports a supplier on sixty-day terms as thirty days overdue on the
    day the goods arrive, and a report that cries wolf on every line is one the
    owner stops opening.
    """
    asof = asof or date.today()
    invoices = (db.query(SupplierInvoice)
                  .filter(SupplierInvoice.status != "paid").all())
    outstanding_by_id = paid_against(db, [i.id for i in invoices])

    by_supplier: dict[int, dict] = {}
    band_labels = [label for _, label in AGE_BANDS] + [AGE_OLDEST]
    totals = {label: 0.0 for label in band_labels}
    grand = 0.0
    queried_total = 0.0

    for invoice in invoices:
        owed = round((invoice.total or 0.0) - outstanding_by_id.get(invoice.id, 0.0), 2)
        if owed <= 0.005:
            continue
        due = _due(invoice)
        overdue = (asof - due).days
        label = AGE_OLDEST
        if overdue <= 0:
            label = AGE_BANDS[0][1]
        else:
            for days, name in AGE_BANDS[1:]:
                if overdue <= days:
                    label = name
                    break

        bucket = by_supplier.setdefault(invoice.supplier_id, {
            "supplier_id": invoice.supplier_id,
            "supplier": "",
            "bands": {b: 0.0 for b in band_labels},
            "total": 0.0, "oldest_days": 0, "queried": 0.0, "invoices": [],
        })
        bucket["bands"][label] = round(bucket["bands"][label] + owed, 2)
        bucket["total"] = round(bucket["total"] + owed, 2)
        bucket["oldest_days"] = max(bucket["oldest_days"], max(overdue, 0))
        if invoice.status == "queried":
            bucket["queried"] = round(bucket["queried"] + owed, 2)
            queried_total += owed
        bucket["invoices"].append({
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date,
            "due_date": due,
            "total": round(invoice.total or 0.0, 2),
            "outstanding": owed,
            "days_overdue": max(overdue, 0),
            "status": invoice.status,
            "band": label,
        })
        totals[label] = round(totals[label] + owed, 2)
        grand += owed

    for supplier in db.query(Supplier).filter(
            Supplier.id.in_(by_supplier.keys() or [0])).all():
        by_supplier[supplier.id]["supplier"] = supplier.name

    rows = sorted(by_supplier.values(), key=lambda r: -r["total"])
    for row in rows:
        row["invoices"].sort(key=lambda i: -i["days_overdue"])

    # What has been billed but not yet accepted into the books. This is the
    # usual explanation for the two figures below not agreeing.
    unapproved = round(sum(
        (i.total or 0.0) for i in invoices
        if not i.posted_reference and i.status != "paid"), 2)

    try:
        # `balance` already reports each account in the direction its type runs,
        # so a liability comes back positive. Negating it here read as a
        # nine-hundred-dollar disagreement on a ledger that was perfectly fine.
        control = round(ledger.balance(db, CREDITORS), 2)
    except ledger.LedgerError:
        control = 0.0

    return {
        "as_at": asof,
        "bands": band_labels,
        "totals": totals,
        "total": round(grand, 2),
        "queried": round(queried_total, 2),
        "suppliers": rows,
        # Said out loud on the same screen. The ledger and this list are kept
        # separately precisely so they can disagree, and the difference is the
        # most useful number here — but it is reported with its likely cause
        # rather than an accusation, because the commonest reason is entirely
        # innocent: a delivery raised the creditor and its invoice has not been
        # approved yet, so the ledger is holding the order's cost while this
        # list holds what was billed.
        "control_balance": control,
        "difference": round(control - round(grand, 2), 2),
        "awaiting_approval": round(unapproved, 2),
    }


def remittance(db: Session, payment_id: int) -> dict:
    """What to send the supplier so they can find the money on their side."""
    payment = db.get(SupplierPayment, payment_id)
    if payment is None:
        return {}
    supplier = db.get(Supplier, payment.supplier_id)
    lines = []
    for alloc in payment.allocations:
        invoice = db.get(SupplierInvoice, alloc.invoice_id)
        lines.append({
            "invoice_number": invoice.invoice_number if invoice else "",
            "invoice_date": invoice.invoice_date if invoice else None,
            "invoice_total": round(invoice.total or 0.0, 2) if invoice else 0.0,
            "allocated": round(alloc.amount or 0.0, 2),
        })
    allocated = round(sum(l["allocated"] for l in lines), 2)
    return {
        "payment_id": payment.id,
        "supplier": supplier.name if supplier else "",
        "paid_on": payment.paid_on,
        "amount": round(payment.amount or 0.0, 2),
        "method": payment.method,
        "reference": payment.reference,
        "lines": lines,
        "allocated": allocated,
        "on_account": round((payment.amount or 0.0) - allocated, 2),
    }
