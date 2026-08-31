"""One line of a sale coming back, rather than the whole thing.

A customer buys four things and brings one back. It is the wrong size, it is
damaged, it was rung up twice, they were given the wrong one. This happens at
every till in the world every day, and the system could not do it: both ways to
reverse a sale — void, and the fiscal credit note — take back **all** of it.

The pharmacy's answer was therefore to reverse the whole sale and ring the
other three items up again. That is not a workaround, it is four new problems:
the receipt number changes, the claim is reversed and has to be re-submitted,
loyalty points are earned twice, and the day's sale count is wrong by one in
each direction. So in practice it is done on paper and the stock silently
drifts — which is exactly the drift `/stock/reconcile` reports and nobody could
explain.

It matters more here than in most shops. Dispensed medicine largely cannot be
taken back, but the CareXpress catalogue is mostly front shop — cosmetics,
toiletries, baby, surgical, gifts — where returns are ordinary.

WHAT COMES BACK, AND WHAT DOES NOT

Stock goes to the exact batches it was drawn from, so it keeps its expiry date.
A returned line that cannot be resold is recorded as returned and then written
off, as two facts, rather than one fact that quietly loses the money: "we took
it back" and "we cannot sell it" are different, and a shop needs to know how
often the second happens.

A scheduled medicine is **refused**. Once a controlled substance has left the
premises it cannot re-enter saleable stock, and a system that lets a till
operator put it back on the shelf is worse than one that cannot do returns at
all. It is destroyed under the destruction procedure, which is a different
document with different signatures.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .. import helpers
from ..models import (BatchAllocation, Patient, Product, Sale, SaleItem,
                      StockMovement)

#: Above this schedule a return cannot go back on the shelf.
#: S5 and S6 are the register items — once out of the pharmacy they are
#: destroyed, not restocked.
NO_RESTOCK_SCHEDULE = 5


def _line_value(item: SaleItem, quantity: int) -> float:
    """What this many units of the line are worth, at what was actually charged.

    From the line total rather than the product's price today. A price that has
    moved since the sale is not the customer's problem, and refunding today's
    price on something bought last month gives away money in one direction or
    short-changes them in the other.
    """
    if not item.quantity:
        return 0.0
    return round((item.line_total or 0.0) * quantity / item.quantity, 2)


def plan(db: Session, sale: Sale, lines: list[dict]) -> dict:
    """What returning these lines would do. Nothing is written.

    Two steps, because a return moves money and stock at once and both are
    awkward to undo. The operator reads what would happen — how much comes off,
    what goes back on the shelf, what cannot — before it does.
    """
    wanted = {int(l["sale_item_id"]): int(l.get("quantity") or 0)
              for l in lines if l.get("sale_item_id")}
    by_id = {i.id: i for i in sale.items}

    rows: list[dict] = []
    refund = 0.0
    refused: list[str] = []

    for item_id, quantity in wanted.items():
        item = by_id.get(item_id)
        if item is None:
            refused.append(f"Line {item_id} is not on this sale.")
            continue
        if quantity <= 0:
            continue

        already = int(getattr(item, "quantity_returned", 0) or 0)
        left = (item.quantity or 0) - already
        if quantity > left:
            refused.append(
                f"{item.description}: {quantity} asked for, {left} left to "
                f"return"
                + (f" ({already} already came back)" if already else ""))
            continue

        product = item.product
        schedule = (product.schedule or 0) if product else 0
        restock = schedule < NO_RESTOCK_SCHEDULE
        value = _line_value(item, quantity)
        refund += value

        rows.append({
            "sale_item_id": item.id,
            "product_id": item.product_id,
            "description": item.description,
            "sold": item.quantity,
            "already_returned": already,
            "returning": quantity,
            "value": value,
            "schedule": schedule,
            "restock": restock,
            "why_not": ("" if restock else
                        f"Schedule {schedule}. Once a controlled medicine has "
                        f"left the pharmacy it cannot go back into saleable "
                        f"stock — it is recorded as returned and destroyed "
                        f"under the destruction procedure."),
        })

    return {
        "sale_id": sale.id,
        "sale_number": sale.sale_number,
        "sale_total": round(sale.total or 0.0, 2),
        "lines": rows,
        "refund": round(refund, 2),
        "refused": refused,
        # Everything coming back means this is a full reversal, and a full
        # reversal has its own route: void it, or credit-note it if it has been
        # filed. Said rather than silently doing something subtly different.
        "is_whole_sale": bool(rows) and all(
            r["returning"] + r["already_returned"] == r["sold"]
            for r in rows) and len(rows) == len(sale.items),
    }


def apply(db: Session, sale: Sale, lines: list[dict], *, user_id: int | None,
          reason: str = "", restock: bool = True) -> dict:
    """Take the lines back. Stock to its own batches, money off the sale.

    `restock=False` records the return and writes the goods off in the same
    movement — damaged, opened, past its date. Two facts kept apart: the
    customer returned it, and it cannot be sold again.
    """
    result = plan(db, sale, lines)
    if not result["lines"]:
        raise ValueError(
            "Nothing to return. "
            + (" ".join(result["refused"]) if result["refused"] else
               "No line was named."))

    reference = f"RETURN {sale.sale_number}"
    by_id = {i.id: i for i in sale.items}
    restocked = written_off = 0

    for row in result["lines"]:
        item = by_id[row["sale_item_id"]]
        product = item.product
        quantity = row["returning"]

        # What the line has given back so far, so a second return of the same
        # line cannot take more than was sold.
        item.quantity_returned = int(getattr(item, "quantity_returned", 0) or 0) + quantity

        if product is None or (product.category or "") == "airtime":
            continue

        goes_back = restock and row["restock"]
        if goes_back:
            restocked += _restore(db, product, item, quantity, user_id, reference)
        else:
            # Recorded as coming back and then written off, as two movements,
            # so the shop can see how much of what it takes back it cannot
            # resell. One netting movement hides that entirely.
            _restore(db, product, item, quantity, user_id, reference)
            helpers.move_stock(
                db, product, -quantity, "write-off", user_id,
                reference=reference,
                notes=(row["why_not"] or reason
                       or "returned and not fit for resale"))
            written_off += quantity

        helpers.record_register_entry(db, product, quantity, "adjustment",
                                      user_id, reference=reference)

    refund = result["refund"]
    sale.total = round(max(0.0, (sale.total or 0.0) - refund), 2)
    # VAT and the subtotal move with it, or the sale's own arithmetic stops
    # adding up and every report drawn from it inherits the error.
    if result["sale_total"]:
        share = refund / result["sale_total"]
        sale.subtotal = round((sale.subtotal or 0.0) * (1 - share), 2)
        sale.vat_amount = round((sale.vat_amount or 0.0) * (1 - share), 2)

    note = (f"Returned {len(result['lines'])} line(s), {refund:.2f}"
            + (f" — {reason}" if reason else ""))
    sale.notes = ((getattr(sale, "notes", "") or "") + "\n" + note).strip()

    # Nothing left on the sale means it is fully returned, and a sale of
    # nothing is not "paid".
    if all((i.quantity or 0) <= int(getattr(i, "quantity_returned", 0) or 0)
           for i in sale.items):
        sale.status = "credited"

    return {
        **result,
        "applied": True,
        "restocked": restocked,
        "written_off": written_off,
        "sale_total_now": round(sale.total or 0.0, 2),
        "message": (
            f"{refund:.2f} returned on {sale.sale_number}. "
            + (f"{restocked} unit(s) back on the shelf. " if restocked else "")
            + (f"{written_off} unit(s) written off. " if written_off else "")
            + (f"The sale is now {sale.total:.2f}."
               if sale.status != "credited" else
               "Everything on the sale has now come back.")),
    }


def _restore(db: Session, product: Product, item: SaleItem, quantity: int,
             user_id: int | None, reference: str) -> int:
    """Put `quantity` back into the batches this line was drawn from.

    Newest allocation first, so a part return of a line drawn across two
    batches puts stock back where it is least likely to expire before it sells
    — the opposite order to FEFO, which is the correct opposite.
    """
    allocations = (
        db.query(BatchAllocation)
        .filter(BatchAllocation.sale_item_id == item.id)
        .order_by(BatchAllocation.id.desc()).all())

    left = quantity
    restored = 0
    for allocation in allocations:
        if left <= 0:
            break
        take = min(left, allocation.quantity)
        allocation.batch.quantity_remaining += take
        product.quantity_on_hand = (product.quantity_on_hand or 0) + take
        allocation.quantity -= take
        left -= take
        restored += take
        db.add(StockMovement(
            product_id=product.id, movement_type="return",
            quantity_delta=take, balance_after=product.quantity_on_hand,
            reference=reference,
            notes=f"part return, to batch {allocation.batch.batch_number}",
            user_id=user_id))
        if allocation.quantity <= 0:
            db.delete(allocation)

    if left > 0:
        # A sale that predates batch tracking has no allocations to restore to.
        helpers.move_stock(db, product, left, "return", user_id,
                           reference=reference,
                           notes="part return (untracked sale)")
        restored += left
    return restored
