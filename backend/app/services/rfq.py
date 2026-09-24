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
from . import config, messaging, portal_pins, portal_tokens, sourcing


#: Where a supplier's quote link points. The application's own host, because
#: that is where `/quote/` exists; see `quote_link` for why the prettier
#: rx5000.com address is a setting rather than the default.
DEFAULT_PORTAL_BASE = "https://rx3000-app.onrender.com"


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
        rows.append(f"{line.quantity:>6}  {code or '':<14}  {name[:46]}")

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


def quote_link(db: Session, invited: RfqSupplier) -> str:
    """The address a wholesaler fills their own prices in at.

    A LINK, NOT AN ACCOUNT

    Nobody at a wholesaler is going to create an account to quote a pharmacy
    for eight boxes of amoxicillin. Asking them to is how a supplier portal
    ends up unused and the prices go on being read down a telephone. So the
    link is the credential, exactly as it already is for a patient checking a
    repeat: signed with the application secret, scoped to this one request and
    this one supplier, and expiring.

    It is also what removes the last transcription step. A price typed by the
    person selling it needs nobody to write it down afterwards, and "who
    recorded this" stops being a question anybody has to ask.

    WHY THE DEFAULT IS THE APP'S OWN ADDRESS AND NOT THE PRETTY ONE

    `rx5000.com` is the marketing site; the application is served from its own
    host, and `/quote/` only exists on the application. The nicer address
    needs a redirect rule on the site, exactly as `/scanner` did. Until that
    rule is in place, defaulting to the pretty address would put a link in a
    wholesaler's email that opens a brochure, and a supplier who clicks a dead
    link does not click a second one. So the default is the address that
    works, and `portal.base_url` is there to make it the pretty one the moment
    the rule exists.
    """
    token = portal_tokens.issue(kind="rfq", subject_id=invited.id)
    base = config.text(db, "portal.base_url", DEFAULT_PORTAL_BASE).rstrip("/")
    return f"{base}/quote/{token}"


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
        # Their own link, so they can answer by typing rather than by
        # telephoning somebody who then types it for them.
        link = quote_link(db, invited)
        ok, _how = messaging.send_email(
            address, subject,
            "\n".join([
                body, "",
                "You can enter your prices here, which saves us both a "
                "telephone call:",
                link, "",
            ]))
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
           note: str = "", by_supplier: bool = False) -> dict:
    """Write down what a wholesaler said.

    Either the supplier typed it into their own link, or somebody here wrote
    down what they were told on the telephone. Both are kept, and which one it
    was is kept too: a price nobody can attribute is a price nobody can query,
    and a price the seller typed themselves is the only one with nothing
    between the quote and the record.
    """
    invited.responded_at = datetime.utcnow()
    invited.self_quoted = bool(by_supplier)
    invited.recorded_by_id = None if by_supplier else getattr(user, "id", None)
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


# ------------------------------------------------------------ their own view

def portal_view(db: Session, invited: RfqSupplier, *,
                pharmacy_name: str = "") -> dict:
    """What one wholesaler sees on their own link.

    WHAT IS DELIBERATELY NOT HERE

    Not one other supplier's name, and not one other supplier's price. A
    quotation screen that shows a wholesaler what the others have bid is not a
    quotation, it is an auction the pharmacy did not mean to run, and the
    prices it produces are worse for everybody on the second round. Each link
    shows this supplier's own lines, their own answers, and nothing else.

    Their previous answer comes back filled in, because a supplier correcting
    one price should not have to retype the other eleven, and a blank form on
    a second visit is how a corrected quote loses the lines nobody changed.
    """
    rfq = invited.rfq
    mine = {q.rfq_line_id: q for q in invited.quotes}
    lines = []
    for line in rfq.lines:
        product = line.product
        name = (product.name if product else f"#{line.product_id}")
        strength = (product.strength or "") if product else ""
        if strength and strength.lower() not in name.lower():
            name = f"{name} {strength}"
        quote = mine.get(line.id)
        lines.append({
            "rfq_line_id": line.id,
            "product": name,
            # Their own code where the pharmacy has one on file, because a
            # wholesaler matches on the pack, not on our name for it.
            "code": ((product.stock_code or product.barcode or "")
                     if product else ""),
            "pack": (product.pack_size if product else "") or "",
            "quantity": line.quantity,
            "available": (bool(quote.available) if quote else True),
            "unit_price": (round(quote.unit_price, 4)
                           if quote and quote.unit_price else None),
            "lead_days": quote.lead_days if quote else None,
            "note": (quote.note or "") if quote else "",
        })

    closed = rfq.status in ("closed", "cancelled")
    return {
        "reference": rfq.reference,
        "pharmacy": pharmacy_name,
        "supplier": invited.supplier.name if invited.supplier else "",
        "notes": rfq.notes or "",
        "closes_at": rfq.closes_at,
        "lines": lines,
        "answered_at": invited.responded_at,
        "declined": bool(invited.declined),
        "their_note": invited.note or "",
        # Said rather than implied. A form that silently refuses to save is
        # how a supplier concludes the link is broken and telephones instead.
        "closed": closed,
        "closed_because": (
            f"{rfq.reference} has already been decided, so it can no longer "
            "be answered here. Please ring the pharmacy."
            if closed else ""),
    }


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
            "opened_at": i.opened_at,
            "responded_at": i.responded_at,
            "declined": bool(i.declined),
            "note": i.note or "",
            # Where the figure came from, shown rather than assumed. See
            # `record` for why this is not inferred from `recorded_by_id`.
            "self_quoted": bool(i.self_quoted),
            "recorded_by": (i.recorded_by.full_name
                            if getattr(i, "recorded_by", None) else ""),
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

def to_orders(db: Session, rfq: Rfq, *, user: User | None = None) -> dict:
    """Turn the AWARDED answers into draft purchase orders, by supplier.

    Draft, never sent. Choosing a quote is a buying decision; sending the
    order is a separate one, and on a pharmacy that has set a threshold it
    may need somebody else's signature first.

    WHY THIS NO LONGER TAKES THE CHOICES FROM THE CALLER

    It used to raise orders from whatever the screen posted. Once an award
    can be signed off by a second person, that is a hole straight through the
    control: a manager approves Datlabs at 12.40 and the orders go to
    whichever suppliers the buyer's screen happened to be holding when they
    pressed the button. The choices are written to the lines when the award
    is proposed and read back from them here, so what was approved is what is
    raised.
    """
    wanted: dict[int, list[tuple[RfqLine, float]]] = {}
    for line in rfq.lines:
        invited = line.chosen
        if invited is None:
            continue
        if invited.rfq_id != rfq.id:
            raise RfqError("One of those choices does not belong to this request.")
        quote = next((q for q in invited.quotes if q.rfq_line_id == line.id), None)
        if quote is None or not quote.available:
            raise RfqError(
                f"{invited.supplier.name if invited.supplier else 'That supplier'} "
                "did not quote a price for one of the lines chosen.")
        wanted.setdefault(invited.supplier_id, []).append((line, quote.unit_price))

    if not wanted:
        raise RfqError("Nothing has been awarded on this request. Choose a "
                       "supplier for at least one line first.")

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
