"""What a driver is carrying, and what happens when they hand it in.

A delivery is a sale that leaves the building before it is paid for. Between
the counter and the door the money belongs to nobody yet: the till has not
received it and the patient has not handed it over. That gap is a driver's
account, and until now nothing in this system held one.

THE HOLE THIS FILLS

The pieces all existed. A waybill carries `cod_amount`; `deliveries.collect`
records what was taken at the door; `deliveries.settle` stamps the round as
handed in and lands it in a shift. What none of them did was **settle the
sale**. A driver could collect fifty dollars, hand it to a cashier, have it
counted into the drawer — and the sale stayed `pending` for ever, so the
patient still showed as owing fifty dollars they had already paid, and the
shop's debtors carried money that was sitting in its own till.

So the hand-in now writes the tender against the sale, through the same
`currency.record_tender` the counter uses, and moves the sale to paid or
part-paid on the same rule. One definition of "has this been paid", not two.

WHY THE ACCOUNT IS PER DRIVER AND NOT PER ROUND

Because that is who owes it. A driver takes three deliveries out, brings two
back paid and one refused, and goes out again before handing anything in. Their
balance is a running figure across rounds, and a supervisor asking "how much is
Tapiwa holding" is asking about the person, not about a batch.

Two figures, and they are different kinds of thing:

  **holding** is cash collected and not yet handed in — money the shop owns
    and does not have, which is a debt the driver owes;
  **to collect** is money still on the road, which nobody owes anybody yet
    because the medicine has not been handed over.

Adding them would produce a number that is neither, and that is exactly the
number somebody would put in a cash-up.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import Driver, Sale, SaleTender, Shift, Waybill
from . import currency


def paid_on(db: Session, sale_ids: list[int]) -> dict[int, float]:
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


def settle_sale(db: Session, sale: Sale, *, amount: float, method: str,
                reference: str = "", shift_id: int | None = None) -> dict:
    """Record money collected away from the counter against its sale.

    Returns what changed, because a hand-in that silently marks eight sales
    paid is a hand-in nobody can check afterwards.

    A collection larger than the balance is refused rather than trimmed. The
    driver taking more than the sale is owed is either a mistake or a second
    transaction, and both need a person — quietly writing off the difference
    turns an overpayment into a discount nobody authorised.
    """
    amount = round(float(amount or 0.0), 2)
    if amount <= 0:
        return {"sale_id": sale.id, "applied": 0.0, "status": sale.status}

    already = paid_on(db, [sale.id]).get(sale.id, 0.0)
    balance = round((sale.total or 0.0) - already, 2)
    if amount > balance + 0.005:
        raise ValueError(
            f"{sale.sale_number} has {balance:.2f} outstanding and "
            f"{amount:.2f} was collected against it. An overpayment is a "
            f"refund or a second sale, not a delivery.")

    currency.record_tender(db, sale, method=method or "cash",
                           currency_code=currency.base_code(),
                           amount=amount, reference=reference[:60])
    if shift_id and sale.shift_id is None:
        # The till that received the money, so a cash-up can account for it.
        sale.shift_id = shift_id

    now_paid = round(already + amount, 2)
    sale.status = "paid" if now_paid + 0.005 >= (sale.total or 0.0) else "part_paid"
    return {"sale_id": sale.id, "sale_number": sale.sale_number,
            "applied": amount, "outstanding": round((sale.total or 0.0) - now_paid, 2),
            "status": sale.status}


def account(db: Session, driver_id: int) -> dict:
    """One driver's balance, and everything behind it.

    `holding` and `to_collect` are kept apart — see the note at the top of this
    file. A supervisor reading one number would be reading neither.
    """
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise ValueError("That driver is not on file.")

    waybills = (db.query(Waybill)
                .options(joinedload(Waybill.patient))
                .filter(Waybill.driver_profile_id == driver_id)
                .order_by(Waybill.created_at.desc()).all())

    holding = [w for w in waybills
               if (w.cod_collected or 0) > 0 and w.cod_settled_at is None]
    on_road = [w for w in waybills if w.status == "out"]

    def row(w: Waybill) -> dict:
        patient = w.patient
        return {
            "id": w.id,
            "waybill_number": w.waybill_number,
            "recipient": w.recipient or (
                f"{patient.first_name} {patient.last_name}".strip()
                if patient else ""),
            "status": w.status,
            "sale_id": w.sale_id,
            "cod_amount": round(w.cod_amount or 0.0, 2),
            "cod_collected": round(w.cod_collected or 0.0, 2),
            "cod_instrument": w.cod_instrument or "",
            "delivery_fee": round(w.delivery_fee or 0.0, 2),
            "dispatched_at": w.dispatched_at,
            "delivered_at": w.delivered_at,
            "settled_at": w.cod_settled_at,
        }

    # What the driver has already handed in, most recent first. A balance with
    # no history behind it is a number somebody has to take on trust.
    handed = [w for w in waybills if w.cod_settled_at is not None]
    by_hand_in: dict = {}
    for w in handed:
        key = (w.cod_settled_at, w.cod_shift_id)
        entry = by_hand_in.setdefault(key, {
            "settled_at": w.cod_settled_at, "shift_id": w.cod_shift_id,
            "deliveries": 0, "amount": 0.0,
        })
        entry["deliveries"] += 1
        entry["amount"] = round(entry["amount"] + (w.cod_collected or 0.0), 2)

    holding_total = round(sum(w.cod_collected or 0.0 for w in holding), 2)
    to_collect = round(sum(w.cod_outstanding for w in on_road), 2)

    return {
        "driver_id": driver.id,
        "driver": driver.full_name,
        "phone": driver.phone or "",
        "active": bool(driver.active),
        # The debt. Cash the shop owns and does not have.
        "holding": holding_total,
        # Not a debt. The medicine has not been handed over yet.
        "to_collect": to_collect,
        "cod_limit": round(driver.cod_limit or 0.0, 2),
        # Stated rather than left to arithmetic on the screen: a driver already
        # carrying more than the shop said it would let them carry is a
        # decision to make before the next delivery is loaded, not after.
        "over_limit": bool(driver.cod_limit
                           and holding_total > driver.cod_limit + 0.005),
        "deliveries_out": len(on_road),
        "holding_rows": [row(w) for w in holding],
        "on_road_rows": [row(w) for w in on_road],
        "hand_ins": sorted(by_hand_in.values(),
                           key=lambda h: h["settled_at"], reverse=True)[:20],
        "says": _says(driver.full_name, holding_total, to_collect, len(on_road)),
    }


def _says(name: str, holding: float, to_collect: float, out: int) -> str:
    if not holding and not out:
        return f"{name} is carrying nothing and has nothing out."
    parts = []
    if holding:
        parts.append(f"holding {holding:.2f} that has not been handed in")
    if out:
        parts.append(f"{out} deliver{'y' if out == 1 else 'ies'} still out"
                     + (f" for {to_collect:.2f}" if to_collect else ""))
    return f"{name} is " + " and ".join(parts) + "."


def ledger(db: Session) -> dict:
    """Every driver with a balance, worst first.

    The figure a supervisor wants at four o'clock and a cash office wants at
    six. `on_the_road` already answers "what is out"; this answers "who owes
    us", which is a different question with a different answer for a driver
    who came back an hour ago and has not been to the office.
    """
    drivers = db.query(Driver).filter(Driver.active.is_(True)).all()
    rows = []
    for driver in drivers:
        acc = account(db, driver.id)
        if acc["holding"] or acc["deliveries_out"]:
            rows.append({k: acc[k] for k in
                         ("driver_id", "driver", "phone", "holding",
                          "to_collect", "deliveries_out", "cod_limit",
                          "over_limit", "says")})
    rows.sort(key=lambda r: -r["holding"])
    total = round(sum(r["holding"] for r in rows), 2)
    return {
        "drivers": rows,
        "holding": total,
        "to_collect": round(sum(r["to_collect"] for r in rows), 2),
        "headline": (
            f"{len(rows)} driver(s) between them are holding {total:.2f} that "
            f"has not reached a till."
            if total else "No driver is holding money for the shop."),
    }
