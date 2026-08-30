"""A creditor's statement: everything that moved on one supplier account.

This is the document a wholesaler sends a pharmacy every month, and the one a
pharmacy has to be able to produce back — because reconciling the two is how
either side finds out about the invoice that never arrived or the payment that
was never allocated.

The shape is not ours to invent; it is the one every statement in this trade
uses, and departing from it makes the two impossible to lay side by side:

    Balance brought forward
    date · reference · description · debit · credit · running balance
    ...
    ageing: 180 · 150 · 120 · 90 · 60 · 30 · current · amount due

Two things matter more than they look:

  **The running balance is carried, not recomputed per row.** A statement whose
  final balance does not equal the sum of its lines is worse than no statement
  — the supplier will find the discrepancy and neither party will know which
  figure to believe.

  **The brought-forward is real.** Everything before the window, netted into
  one line. Without it a statement covering June opens at zero and appears to
  say the account was settled on the first, which is how a pharmacy comes to
  pay an invoice twice.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..models import Supplier, SupplierInvoice, SupplierPayment

#: The bands a wholesaler's own statement uses, oldest first. Wider than the
#: payables ageing report on purpose: that one is for deciding who to pay, and
#: stops caring past ninety days. A statement is a legal record of a debt and
#: has to show the whole of it, however old.
BANDS = [180, 150, 120, 90, 60, 30]


def _money(v) -> float:
    return round(float(v or 0.0), 2)


def statement(db: Session, supplier_id: int, *,
              since: date | None = None, upto: date | None = None) -> dict:
    """One supplier account, movement by movement."""
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        return {}

    upto = upto or date.today()
    since = since or (upto - timedelta(days=60))

    invoices = (db.query(SupplierInvoice)
                .filter(SupplierInvoice.supplier_id == supplier_id).all())
    payments = (db.query(SupplierPayment)
                .filter(SupplierPayment.supplier_id == supplier_id).all())

    # An invoice is a debit — it increases what we owe. A payment is a credit.
    moves: list[dict] = []
    for inv in invoices:
        when = inv.invoice_date or upto
        moves.append({
            "when": when,
            "reference": inv.invoice_number or "",
            "description": "Invoice",
            "debit": _money(inv.total),
            "credit": 0.0,
            "due": inv.due_date,
        })
    for pay in payments:
        moves.append({
            "when": pay.paid_on or upto,
            "reference": pay.reference or f"PMT{pay.id}",
            # The wording a wholesaler uses, kept because a pharmacy reading
            # both statements side by side should not have to translate.
            "description": "Payment — thank you",
            "debit": 0.0,
            "credit": _money(pay.amount),
            "due": None,
        })

    moves.sort(key=lambda m: (m["when"], m["reference"]))

    # Everything before the window, netted into one line.
    brought = _money(sum(m["debit"] - m["credit"] for m in moves if m["when"] < since))

    balance = brought
    lines = []
    for m in moves:
        if m["when"] < since or m["when"] > upto:
            continue
        balance = _money(balance + m["debit"] - m["credit"])
        lines.append({
            "date": m["when"],
            "reference": m["reference"],
            "description": m["description"],
            "debit": m["debit"] or None,
            "credit": m["credit"] or None,
            "balance": balance,
        })

    # ---- the ageing strip ---------------------------------------------------
    #
    # Aged on the due date where there is one. An invoice on sixty-day terms is
    # not overdue on the day the goods arrive, and a statement that says it is
    # starts an argument the pharmacy will lose.
    outstanding = _money(sum(m["debit"] - m["credit"] for m in moves
                             if m["when"] <= upto))
    paid_total = _money(sum(m["credit"] for m in moves if m["when"] <= upto))
    unallocated = paid_total

    buckets = {b: 0.0 for b in BANDS}
    current = 0.0
    # Oldest first, so the money on the account settles the oldest debt — which
    # is what a wholesaler does with an unallocated payment and therefore what
    # a statement has to assume.
    for inv in sorted(invoices, key=lambda i: (i.invoice_date or upto)):
        owed = _money(inv.total)
        take = min(owed, unallocated)
        unallocated = _money(unallocated - take)
        owed = _money(owed - take)
        if owed <= 0.005:
            continue
        reference_date = inv.due_date or inv.invoice_date or upto
        age = (upto - reference_date).days
        for band in BANDS:
            if age >= band:
                buckets[band] = _money(buckets[band] + owed)
                break
        else:
            current = _money(current + owed)

    return {
        "supplier": supplier.name,
        "supplier_id": supplier.id,
        # A supplier record here carries no account code of its own — the
        # wholesaler allocates that, and we have nowhere to keep it yet.
        # Ours is at least stable and quotable over the telephone, which is
        # what an account reference is for.
        "account_code": f"CR{supplier.id:04d}",
        "contact": supplier.contact_person or "",
        "phone": supplier.phone or "",
        "email": supplier.email or "",
        "from": since,
        "to": upto,
        "brought_forward": brought,
        "lines": lines,
        "debits": _money(sum(l["debit"] or 0 for l in lines)),
        "credits": _money(sum(l["credit"] or 0 for l in lines)),
        "closing": balance,
        "ageing": [{"label": f"{b} days", "value": buckets[b]} for b in BANDS]
                  + [{"label": "Current", "value": current}],
        "amount_due": _money(outstanding),
    }
