"""Asking several wholesalers what they would charge, and comparing the answers.

WHY THIS EXISTS

A purchase order names one supplier and a price somebody typed in. Where that
price came from was a telephone call, remembered. Nothing recorded that three
wholesalers were asked, what each said, or why the dearest was chosen — which
is the question an owner asks afterwards, and the difference between buying
well and buying from whoever answered the phone.

WHAT THE COMPARISON REFUSES TO DO

It does not pick a winner. It orders the answers by price and says which is
cheapest, and it stops there, because the cheapest quote is not always the
right buy: a supplier who cannot deliver for three weeks is no use for a line
that is out of stock today, and one who has short-delivered every order this
year is not a bargain at any price. Those facts sit beside the price, from
the buying record the pharmacy already has, and a person decides.

"NOT QUOTED" IS NOT ZERO

A supplier who did not answer for a line, and a supplier who answered "we
cannot supply it", are different facts, and both are different from a price
of nought. Each is carried separately, because a comparison that treats
silence as free is a comparison that recommends the wrong wholesaler.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .. import helpers
from ..models import (Product, PurchaseOrder, PurchaseOrderItem, Rfq, RfqLine,
                      RfqQuote, RfqSupplier, Supplier, User)
from . import messaging, sourcing


class RfqError(Exception):
    """Why this could not be done, in words for the person asking."""


# ------------------------------------------------------------------ raising

def create(db: Session, *, user: User | None = None, notes: str = "",
           closes_at: datetime | None = None) -> Rfq:
    row = Rfq(
        reference=helpers.next_number(db, Rfq, "RFQ", "reference"),
        status="draft",
        notes=(notes or "").strip(),
        closes_at=closes_at,
        created_by_id=getattr(user, "id", None),
    )
    db.add(row)
    db.flush()
    return row


def add_line(db: Session, rfq: Rfq, *, product_id: int, quantity: int) -> RfqLine:
    if quantity <= 0:
        raise RfqError("Say how many are wanted. A request for nought of "
                       "something is not a question anybody can answer.")
    product = db.get(Product, product_id)
    if product is None:
        raise RfqError("That product is not on file.")
    existing = next((l for l in rfq.lines if l.product_id == product_id), None)
    if existing is not None:
        existing.quantity = quantity
        return existing
    line = RfqLine(rfq_id=rfq.id, product_id=product_id, quantity=quantity)
    db.add(line)
    db.flush()
    return line


def invite(db: Session, rfq: Rfq, *, supplier_id: int) -> RfqSupplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise RfqError("That supplier is not on file.")
    existing = next((i for i in rfq.invited if i.supplier_id == supplier_id), None)
    if existing is not None:
        return existing
    row = RfqSupplier(rfq_id=rfq.id, supplier_id=supplier_id)
    db.add(row)
    db.flush()
    return row


def suggest_suppliers(db: Session, rfq: Rfq, *, limit: int = 4) -> list[dict]:
    """Who is worth asking, from who has actually supplied these lines.

    The buying record already knows. Offering it means a request goes to the
    three wholesalers who stock the thing rather than to whoever somebody
    remembers, which is where most of the benefit of asking around comes from.
    """
    seen: dict[int, dict] = {}
    for line in rfq.lines:
        for row in sourcing.for_product(db, line.product_id).get("suppliers", []):
            at = seen.setdefault(row["supplier_id"], {
                "supplier_id": row["supplier_id"], "supplier": row["supplier"],
                "lines": 0, "delivers": row.get("delivers", False),
                "record": row.get("record", ""),
            })
            at["lines"] += 1
            at["delivers"] = at["delivers"] or row.get("delivers", False)
    # Most of the lines first, and among those the ones who deliver.
    out = sorted(seen.values(), key=lambda r: (-r["lines"], not r["delivers"]))
    return out[:limit]


# ------------------------------------------------------------------ sending

def document(db: Session, rfq: Rfq, *, pharmacy_name: str = "") -> str:
    """The request, as a wholesaler's desk will read it.

    No prices. That is the entire point of asking.
    """
    rows = []
    for line in rfq.lines:
        product = line.product
        name = (product.name if product else f"#{line.product_id}")
        strength = (product.strength or "") if product else ""
        if strength and strength.lower() not in name.lower():
            name = f"{name} {strength}"
        code = ((product.stock_code or product.barcode or "") if product else "")
        rows.append(f"{line.quantity:>6}  {code or '—':<14}  {name[:46]}")

    when = (f"Please reply by {rfq.closes_at:%d %B %Y}."
            if rfq.closes_at else "Please reply at your earliest convenience.")
    return "\n".join([
        f"REQUEST FOR QUOTATION  {rfq.reference}",
        f"From: {pharmacy_name or 'the pharmacy'}",
        "",
        "We would like your best price and availability for the following.",
        "",
        f"{'QTY':>6}  {'CODE':<14}  ITEM",
        "-" * 72,
        *rows,
        "-" * 72,
        "",
        *( [f"Note: {rfq.notes}", ""] if rfq.notes else [] ),
        when,
        "Please include your lead time in working days for each line.",
    ])


def send(db: Session, rfq: Rfq, *, pharmacy_name: str = "") -> dict:
    """Email the request to everybody invited who has an address."""
    if not rfq.lines:
        raise RfqError(f"{rfq.reference} has no lines on it. There is nothing "
                       "to ask about.")
    if not rfq.invited:
        raise RfqError(f"{rfq.reference} has nobody to ask. Invite at least "
                       "one supplier.")

    body = document(db, rfq, pharmacy_name=pharmacy_name)
    subject = (f"Request for quotation {rfq.reference}"
               + (f" from {pharmacy_name}" if pharmacy_name else ""))

    sent, skipped = 0, []
    for invited in rfq.invited:
        supplier = invited.supplier
        address = ((supplier.email or "").strip() if supplier else "")
        if not address:
            # Named rather than dropped: somebody has to ring these, and they
            # cannot ring a list they cannot see.
            skipped.append(supplier.name if supplier else f"#{invited.supplier_id}")
            continue
        ok, _how = messaging.send_email(address, subject, body)
        if not ok:
            skipped.append(f"{supplier.name} ({address})")
            continue
        invited.sent_at = datetime.utcnow()
        invited.sent_to = address[:200]
        sent += 1

    if sent:
        rfq.status = "sent"
        rfq.sent_at = rfq.sent_at or datetime.utcnow()
    return {
        "sent": sent,
        "not_sent": skipped,
        "message": (
            f"{rfq.reference} sent to {sent} supplier(s)."
            + (f" {len(skipped)} could not be emailed and will have to be "
               f"asked another way: {', '.join(skipped[:4])}." if skipped else "")
            if sent else
            "Nobody could be emailed. "
            + (f"{', '.join(skipped[:4])} have no address on file."
               if skipped else "")),
    }


# ---------------------------------------------------------------- answering

def record(db: Session, invited: RfqSupplier, *, answers: list[dict],
           user: User | None = None, declined: bool = False,
           note: str = "") -> dict:
    """Write down what a wholesaler said.

    Entered by staff today, because a supplier cannot sign in yet. Who wrote
    it down is kept, since a price nobody can attribute is a price nobody can
    query.
    """
    invited.responded_at = datetime.utcnow()
    invited.recorded_by_id = getattr(user, "id", None)
    invited.declined = bool(declined)
    invited.note = (note or "").strip()[:400]

    if declined:
        for old in list(invited.quotes):
            db.delete(old)
        return {"lines": 0, "message": f"{invited.supplier.name if invited.supplier else 'They'} "
                                       "cannot supply this request."}

    by_line = {q.rfq_line_id: q for q in invited.quotes}
    wrote = 0
    for answer in answers:
        line_id = int(answer.get("rfq_line_id") or 0)
        if not line_id:
            continue
        quote = by_line.get(line_id)
        if quote is None:
            quote = RfqQuote(rfq_supplier_id=invited.id, rfq_line_id=line_id)
            db.add(quote)
        quote.available = bool(answer.get("available", True))
        quote.unit_price = float(answer.get("unit_price") or 0.0)
        lead = answer.get("lead_days")
        quote.lead_days = int(lead) if lead not in (None, "") else None
        quote.note = str(answer.get("note") or "").strip()[:200]
        wrote += 1
    return {"lines": wrote,
            "message": f"{wrote} line(s) recorded against "
                       f"{invited.supplier.name if invited.supplier else 'that supplier'}."}


# --------------------------------------------------------------- comparing

def compare(db: Session, rfq: Rfq) -> dict:
    """Every answer, line by line, with the cheapest named and nothing chosen.

    See the note at the top of this file for why this does not pick a winner.
    """
    invited = list(rfq.invited)
    record_of = {}
    for i in invited:
        record_of[i.id] = {
            "rfq_supplier_id": i.id,
            "supplier_id": i.supplier_id,
            "supplier": i.supplier.name if i.supplier else "",
            "sent_at": i.sent_at,
            "responded_at": i.responded_at,
            "declined": bool(i.declined),
            "note": i.note or "",
        }

    lines = []
    for line in rfq.lines:
        product = line.product
        answers = []
        for i in invited:
            quote = next((q for q in i.quotes if q.rfq_line_id == line.id), None)
            answers.append({
                "rfq_supplier_id": i.id,
                "supplier": i.supplier.name if i.supplier else "",
                # Three different states, kept apart. A supplier who did not
                # answer, one who cannot supply, and one quoting nought are
                # not the same thing, and flattening them recommends the
                # wrong wholesaler.
                "answered": quote is not None,
                "available": bool(quote.available) if quote else None,
                "unit_price": round(quote.unit_price, 4) if quote and quote.available else None,
                "line_total": (round(quote.unit_price * (line.quantity or 0), 2)
                               if quote and quote.available else None),
                "lead_days": quote.lead_days if quote else None,
                "note": (quote.note or "") if quote else "",
            })
        priced = [a for a in answers if a["unit_price"] is not None]
        best = min(priced, key=lambda a: a["unit_price"]) if priced else None
        for a in answers:
            a["cheapest"] = bool(best and a["rfq_supplier_id"] == best["rfq_supplier_id"])
        spread = (round(max(a["unit_price"] for a in priced)
                        - min(a["unit_price"] for a in priced), 4)
                  if len(priced) > 1 else 0.0)
        lines.append({
            "rfq_line_id": line.id,
            "product_id": line.product_id,
            "product": (f"{product.name} {product.strength or ''}".strip()
                        if product else f"#{line.product_id}"),
            "quantity": line.quantity,
            "answers": answers,
            "quoted_by": len(priced),
            # What asking around was worth on this line, said plainly.
            "spread": spread,
            "saving": round(spread * (line.quantity or 0), 2),
        })

    return {
        "reference": rfq.reference,
        "status": rfq.status,
        "closes_at": rfq.closes_at,
        "suppliers": list(record_of.values()),
        "lines": lines,
        "waiting_on": [r["supplier"] for r in record_of.values()
                       if r["sent_at"] and not r["responded_at"]],
        "saving": round(sum(l["saving"] for l in lines), 2),
    }


# --------------------------------------------------------------- converting

def to_orders(db: Session, rfq: Rfq, *, picks: list[dict],
              user: User | None = None) -> dict:
    """Turn chosen answers into draft purchase orders, grouped by supplier.

    Draft, never sent. Choosing a quote is a buying decision; sending the
    order is a separate one, and on a pharmacy that has set a threshold it
    may need somebody else's signature first.
    """
    if not picks:
        raise RfqError("Nothing was chosen. Pick a supplier for at least one "
                       "line.")

    wanted: dict[int, list[tuple[RfqLine, float]]] = {}
    for pick in picks:
        line = db.get(RfqLine, int(pick.get("rfq_line_id") or 0))
        invited = db.get(RfqSupplier, int(pick.get("rfq_supplier_id") or 0))
        if line is None or invited is None or line.rfq_id != rfq.id:
            raise RfqError("One of those choices does not belong to this request.")
        quote = next((q for q in invited.quotes if q.rfq_line_id == line.id), None)
        if quote is None or not quote.available:
            raise RfqError(
                f"{invited.supplier.name if invited.supplier else 'That supplier'} "
                "did not quote a price for one of the lines chosen.")
        wanted.setdefault(invited.supplier_id, []).append((line, quote.unit_price))

    created = []
    for supplier_id, rows in wanted.items():
        order = PurchaseOrder(
            order_number=helpers.next_number(db, PurchaseOrder, "PO", "order_number"),
            supplier_id=supplier_id,
            notes=f"From {rfq.reference}",
            created_by_id=getattr(user, "id", None),
        )
        db.add(order)
        db.flush()
        for line, price in rows:
            db.add(PurchaseOrderItem(
                order_id=order.id, product_id=line.product_id,
                quantity_ordered=line.quantity, unit_cost=price))
        created.append(order)

    rfq.status = "closed"
    return {
        "orders": [o.id for o in created],
        "message": (f"{len(created)} draft order(s) raised from "
                    f"{rfq.reference}. Nothing has been sent yet."),
    }
