"""How the medicine reached the patient, how it was paid for, and what they
thought of it.

WHY THESE FOUR TRAVEL TOGETHER

A dispensing record answered "what was handed over and by whom" and stopped
there. The four questions anybody actually asks afterwards are the ones it
could not answer:

  - **How did it reach them.** Over the counter, off the will-call shelf a
    week later, or driven to the house. A pharmacy deciding whether delivery
    pays for itself cannot work that out from a record that does not say.
  - **How was it paid for.** Cash at the counter and cash at the door are
    different risks; a scheme claim and an account are different money.
  - **Was it signed for.** A delivery with a signature is a delivery that can
    be defended; one without is a claim somebody will lose.
  - **Were they happy.** The pharmacy's own patients are the only people who
    can say, and nobody had ever asked them.

NOTHING HERE IS TYPED IN

That is the whole design. The till already knows whether somebody walked out
with the bag; the shelf already knows whether it waited; raising a waybill
already says it was driven; the sale's own tenders already record how it was
paid. Asking a dispenser to classify a handover they have just done is a
control that gets clicked through, and a second record of a fact the system
already holds is a second record to disagree with the first.

So these are worked out and written down. The only one a person supplies is
the review, and the person who supplies it is the patient, from their own
portal, in their own time.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Dispensing, Sale, SaleTender, Waybill

#: How it reached them.
COUNTER = "counter"
WILL_CALL = "will_call"
DELIVERY = "delivery"

#: What each is called on a screen. The keys are the server's own spelling and
#: are never capitalised here: a lookup keyed on a capitalised value silently
#: misses, which has already cost this codebase three broken badge maps.
SUPPLY_SAID = {
    COUNTER: "Over the counter",
    WILL_CALL: "Collected later",
    DELIVERY: "Delivered",
}

#: How it was paid. `split` where a sale was settled with more than one.
PAYMENT_SAID = {
    "cash": "Cash",
    "card": "Card",
    "mobile_money": "Mobile money",
    "medical_aid": "Medical aid",
    "loyalty": "Loyalty points",
    "account": "On account",
    "split": "Split payment",
    "unpaid": "Not yet paid",
}


def supply_of(db: Session, d: Dispensing) -> str:
    """How this one reached the patient, from what the system already knows.

    A waybill against the same sale means it was driven. Otherwise the gap
    between dispensing and collection decides: handed over in the same visit
    is a counter supply, and anything that waited is the will-call shelf.
    """
    if d.sale_id:
        driven = (db.query(Waybill.id)
                  .filter(Waybill.sale_id == d.sale_id).first())
        if driven:
            return DELIVERY

    if d.collected_at and d.dispensed_at:
        # Half an hour, because a counter handover is the same visit and a
        # will-call bag is a second one. Anything in between is a queue.
        waited = (d.collected_at - d.dispensed_at).total_seconds()
        return COUNTER if waited < 1800 else WILL_CALL
    # Dispensed and not yet collected is the shelf, by definition: it is
    # sitting behind the counter waiting for somebody.
    return WILL_CALL


def payment_of(db: Session, d: Dispensing) -> str:
    """How the sale behind this was settled, in the sale's own words.

    Read from `sale_tenders` rather than asked for, because the money was
    already recorded properly at the till and a second answer is a second
    thing to be wrong.
    """
    if not d.sale_id:
        return ""
    sale = db.get(Sale, d.sale_id)
    if sale is None:
        return ""
    if sale.status in ("pending", "part_paid"):
        return "unpaid"

    methods = {t.method for t in
               db.query(SaleTender)
               .filter(SaleTender.sale_id == sale.id,
                       SaleTender.is_change.is_(False)).all()
               if t.method}
    if not methods:
        # Settled with no tender against it is an account sale: the money
        # moved to the patient's ledger rather than into a drawer.
        return "account"
    if len(methods) > 1:
        return "split"
    return methods.pop()


def settle(db: Session, d: Dispensing) -> bool:
    """Write down what the system worked out, if it has changed.

    Called wherever a dispensing's story moves on — collected, paid,
    dispatched — and cheap enough to call twice: it writes only on a change,
    because the happy path is somebody standing at a till waiting.
    """
    supply = supply_of(db, d)
    payment = payment_of(db, d)
    changed = False
    if supply and d.supply_type != supply:
        d.supply_type = supply
        changed = True
    if payment and d.payment_type != payment:
        d.payment_type = payment
        changed = True
    return changed


def settle_sale(db: Session, sale_id: int) -> int:
    """Every dispensing behind one sale. Returns how many changed."""
    if not sale_id:
        return 0
    rows = (db.query(Dispensing)
            .filter(Dispensing.sale_id == sale_id).all())
    touched = sum(1 for d in rows if settle(db, d))
    if touched:
        db.commit()
    return touched


def signature_for(db: Session, d: Dispensing) -> str:
    """The mark taken at the door for this one, or "".

    Reached through the sale the dispensing and the waybill share rather than
    copied onto the dispensing: it is shown and never sorted, so it belongs
    beside the name it is a signature of.
    """
    if not d.sale_id:
        return ""
    w = (db.query(Waybill)
         .filter(Waybill.sale_id == d.sale_id,
                 Waybill.signature != "")
         .order_by(Waybill.delivered_at.desc()).first())
    return (w.signature if w else "") or ""


class ReviewError(RuntimeError):
    """Refused, with the sentence to show the patient."""


def review(db: Session, rows: list[Dispensing], *, rating: int,
           note: str = "") -> int:
    """What the patient thought, written against everything in one handover.

    ONE PROMPT, NOT ONE PER MEDICINE.
    A script with four items is one visit and one opinion. Asking four times
    is how a rating prompt gets dismissed and never answered again, so the
    portal asks once about the collection and the answer is written to every
    line in it. Reports still group by it, because it is a column on each row.
    """
    if not 1 <= int(rating) <= 5:
        raise ReviewError("Choose between one and five.")
    now = datetime.utcnow()
    for d in rows:
        d.rating = int(rating)
        d.review_note = (note or "").strip()[:2000]
        d.reviewed_at = now
    db.commit()
    return len(rows)
