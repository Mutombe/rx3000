"""Deliveries, drivers, and the money that leaves the shop with them.

A delivery is the only point in the day where the pharmacy's medicine and the
pharmacy's money are both out of the building and in one person's hands, and
the system recorded neither. A waybill knew where it was going and who signed
for it; it did not know what the shop charged to take it there, what the driver
was to collect at the door, or what came back.

That gap is not academic. A shop running twenty deliveries a day cannot say
what delivering costs it, cannot charge for it consistently, and — the part
that matters — cannot tell a cashier why their drawer is short.

THE DRAWER PROBLEM

Cash on delivery is cash. Left as an ordinary cash tender it lands in the
counter's cash-up, and at four o'clock the cashier is told they are a hundred
and forty short by money that is on a motorbike somewhere on Samora Machel.
People stop reading variances they know are wrong, and then they stop reading
the real ones too.

So COD is its own instrument, flagged `is_delivery`, and the cash-up shows it
beside the variance rather than inside it: *on the road, 140.00, three
deliveries*. It moves into a drawer when the driver hands it in, against the
shift that receives it, and not before.

WHAT A DRIVER IS

A driver used to be a foreign key to `users`, which meant a driver needed a
login. Most do not have one and should not: the runner on the motorbike never
touches the dispensing system, and the courier used on Saturdays is not staff.
`Driver` is a person the pharmacy sends out — with a vehicle, a licence that
expires, a phone number for when a patient has been waiting two hours, and a
running account of what they are holding.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import Driver, PaymentInstrument, Sale, Shift, Waybill

#: An instrument flagged this way is money a driver holds, not money in a till.
DELIVERY_CODES = ("cod", "delivery_fee")


def _instrument(db: Session, code: str) -> PaymentInstrument | None:
    return db.query(PaymentInstrument).filter(
        PaymentInstrument.code == code).first()


# --------------------------------------------------------------------------
# Drivers
# --------------------------------------------------------------------------

def driver_row(db: Session, driver: Driver, *, deep: bool = False) -> dict:
    """A driver, with what they are actually carrying.

    The outstanding figure is the reason this exists. "Driver: T. Moyo" is a
    label; "T. Moyo, out with four deliveries and 214.00 uncollected, licence
    expired 11 days ago" is something somebody acts on.
    """
    row = {
        "id": driver.id, "code": driver.code, "full_name": driver.full_name,
        "phone": driver.phone, "alternate_phone": driver.alternate_phone,
        "national_id": driver.national_id,
        "user_id": driver.user_id, "branch_id": driver.branch_id,
        "branch": driver.branch.name if driver.branch else "",
        "vehicle_type": driver.vehicle_type,
        "vehicle_registration": driver.vehicle_registration,
        "licence_number": driver.licence_number,
        "licence_expiry": driver.licence_expiry,
        "cash_float": round(driver.cash_float or 0.0, 2),
        "cod_limit": round(driver.cod_limit or 0.0, 2),
        "active": bool(driver.active), "notes": driver.notes or "",
    }

    expiry = driver.licence_expiry
    row["licence_expired"] = bool(expiry and expiry < date.today())
    row["licence_days_left"] = (expiry - date.today()).days if expiry else None

    counts = dict(
        db.query(Waybill.status, func.count(Waybill.id))
        .filter(Waybill.driver_profile_id == driver.id)
        .group_by(Waybill.status).all())
    row["out"] = int(counts.get("out", 0))
    row["delivered"] = int(counts.get("delivered", 0))
    row["failed"] = int(counts.get("failed", 0))
    row["total_runs"] = sum(int(v) for v in counts.values())
    attempted = row["delivered"] + row["failed"]
    row["failure_rate"] = round(row["failed"] / attempted * 100, 1) if attempted else None

    # Money on the road: collected but not handed in, plus still to collect.
    holding = (
        db.query(func.coalesce(func.sum(Waybill.cod_collected), 0.0))
        .filter(Waybill.driver_profile_id == driver.id,
                Waybill.cod_settled_at.is_(None)).scalar())
    to_collect = (
        db.query(func.coalesce(func.sum(Waybill.cod_amount - Waybill.cod_collected), 0.0))
        .filter(Waybill.driver_profile_id == driver.id,
                Waybill.status == "out",
                Waybill.cod_settled_at.is_(None)).scalar())
    row["cash_holding"] = round(float(holding or 0), 2)
    row["cod_to_collect"] = round(float(to_collect or 0), 2)
    row["over_cod_limit"] = bool(
        driver.cod_limit and row["cash_holding"] > driver.cod_limit)

    if deep:
        row["waybills"] = [
            waybill_row(w) for w in
            db.query(Waybill)
            .options(joinedload(Waybill.patient),
                     joinedload(Waybill.driver_profile),
                     joinedload(Waybill.created_by))
            .filter(Waybill.driver_profile_id == driver.id)
            .order_by(Waybill.created_at.desc()).limit(100).all()]
        row["fees_earned"] = round(float(
            db.query(func.coalesce(func.sum(Waybill.delivery_fee), 0.0))
            .filter(Waybill.driver_profile_id == driver.id,
                    Waybill.status == "delivered").scalar() or 0), 2)
    return row


def drivers(db: Session, *, include_retired: bool = False) -> list[dict]:
    q = db.query(Driver).options(joinedload(Driver.branch))
    if not include_retired:
        q = q.filter(Driver.active.is_(True))
    return [driver_row(db, d) for d in q.order_by(Driver.full_name).all()]


def save_driver(db: Session, driver: Driver, data: dict) -> Driver:
    """Apply an edit, refusing the ones that would make the record a lie."""
    name = (data.get("full_name") or driver.full_name or "").strip()
    if not name:
        raise ValueError("A driver needs a name — somebody has to be findable "
                         "when a delivery goes missing.")
    phone = (data.get("phone") if "phone" in data else driver.phone) or ""
    if not str(phone).strip():
        raise ValueError("A driver needs a phone number. Half of what this "
                         "record is for is ringing them.")

    driver.full_name = name
    for field in ("code", "phone", "alternate_phone", "national_id",
                  "vehicle_type", "vehicle_registration", "licence_number",
                  "notes"):
        if field in data and data[field] is not None:
            setattr(driver, field, str(data[field]).strip())
    for field in ("cash_float", "cod_limit"):
        if field in data and data[field] is not None:
            setattr(driver, field, round(float(data[field]), 2))
    for field in ("user_id", "branch_id"):
        if field in data:
            setattr(driver, field, data[field] or None)
    if "licence_expiry" in data:
        value = data["licence_expiry"]
        driver.licence_expiry = (
            date.fromisoformat(value) if isinstance(value, str) and value else
            value if isinstance(value, date) else None)
    if "active" in data:
        driver.active = bool(data["active"])
    return driver


# --------------------------------------------------------------------------
# Deliveries
# --------------------------------------------------------------------------

def waybill_row(w: Waybill) -> dict:
    return {
        "id": w.id, "waybill_number": w.waybill_number, "status": w.status,
        "sale_id": w.sale_id, "patient_id": w.patient_id,
        "recipient": w.recipient, "address": w.address, "phone": w.phone,
        "instructions": w.instructions,
        "driver_profile_id": w.driver_profile_id,
        "driver": (w.driver_profile.full_name if w.driver_profile
                   else w.driver.full_name if w.driver else ""),
        "driver_phone": w.driver_profile.phone if w.driver_profile else "",
        "received_by": w.received_by, "failure_reason": w.failure_reason,
        "requires_id_check": w.requires_id_check,
        "id_number_seen": w.id_number_seen,
        "delivery_fee": round(w.delivery_fee or 0.0, 2),
        "cod_amount": round(w.cod_amount or 0.0, 2),
        "cod_collected": round(w.cod_collected or 0.0, 2),
        "cod_outstanding": w.cod_outstanding,
        "cod_instrument": w.cod_instrument or "",
        "cod_reference": w.cod_reference or "",
        "cod_settled_at": w.cod_settled_at,
        "created_at": w.created_at, "dispatched_at": w.dispatched_at,
        "delivered_at": w.delivered_at,
        "created_by": w.created_by.full_name if w.created_by else "",
        "patient": (f"{w.patient.first_name} {w.patient.last_name}".strip()
                    if w.patient else ""),
    }


def collect(db: Session, waybill: Waybill, *, amount: float, instrument: str,
            reference: str = "") -> None:
    """Record what the driver took at the door.

    Written onto the waybill, not into a till: the money is on the road until
    somebody hands it in. `settle` is what moves it.
    """
    amount = round(float(amount or 0), 2)
    if amount < 0:
        raise ValueError("A collection cannot be negative. Reverse the sale "
                         "instead — a delivery is not a refund counter.")
    due = round(waybill.cod_amount or 0.0, 2)
    if due and amount > due + 0.005:
        raise ValueError(
            f"This delivery is to collect {due:.2f}. Taking {amount:.2f} at the "
            f"door means the patient has overpaid by {amount - due:.2f}, which "
            f"needs a sale, not a delivery note.")
    waybill.cod_collected = amount
    waybill.cod_instrument = (instrument or "cod")[:30]
    waybill.cod_reference = (reference or "")[:60]


def settle(db: Session, waybills: list[Waybill], shift: Shift,
           *, counted: float | None = None) -> dict:
    """The driver hands the round in. The money becomes the till's.

    Every delivery in the batch is stamped with the shift that received it, so
    "which cash-up did Tuesday's round land in" has an answer. A short hand-in
    is recorded as a short hand-in rather than silently accepted — the whole
    reason to count money at a hand-over is that the two figures sometimes
    differ, and a system that overwrites one with the other has thrown away the
    only fact worth keeping.
    """
    from . import driver_account

    expected = round(sum(w.cod_collected or 0.0 for w in waybills), 2)
    now = datetime.utcnow()

    # The money reaching the till is when the SALE is paid, and nothing used to
    # do this.
    #
    # A driver could collect fifty dollars at a door, hand it to a cashier and
    # have it counted into the drawer, and the sale stayed `pending` for ever:
    # the patient still showed as owing money they had already paid, and the
    # shop's debtors carried cash that was sitting in its own till. The waybill
    # knew, the sale did not, and nobody was ever going to reconcile the two by
    # hand.
    #
    # Written through the same tender path the counter uses, so there is one
    # definition of "has this been paid" rather than two that drift.
    settled: list[dict] = []
    refused: list[str] = []
    for w in waybills:
        w.cod_settled_at = now
        w.cod_shift_id = shift.id
        if not w.sale_id or not (w.cod_collected or 0):
            continue
        sale = db.get(Sale, w.sale_id)
        if sale is None or sale.status in ("paid", "reversed", "cancelled"):
            continue
        try:
            settled.append(driver_account.settle_sale(
                db, sale, amount=w.cod_collected,
                method=w.cod_instrument or "cash",
                reference=w.waybill_number or "", shift_id=shift.id))
        except ValueError as exc:
            # A collection that does not fit its sale is reported, not
            # swallowed and not allowed to stop the rest of the round being
            # handed in. The driver has already given the money over.
            refused.append(f"{w.waybill_number}: {exc}")

    handed_in = expected if counted is None else round(float(counted), 2)
    return {
        "deliveries": len(waybills),
        "expected": expected,
        "handed_in": handed_in,
        "variance": round(handed_in - expected, 2),
        "shift_id": shift.id,
        "fees": round(sum(w.delivery_fee or 0.0 for w in waybills), 2),
        # What this hand-in actually closed. A round that marks eight sales
        # paid without saying which is a round nobody can check afterwards.
        "sales_settled": settled,
        "could_not_settle": refused,
    }


def on_the_road(db: Session) -> dict:
    """Every delivery still out, and what it is carrying.

    The figure a supervisor needs at four o'clock, and the one the cash-up
    shows beside the drawer variance so a short till is not confused with a
    driver who has not come back yet.
    """
    rows = (
        db.query(Waybill)
        .options(joinedload(Waybill.driver_profile))
        .filter(Waybill.status == "out")
        .order_by(Waybill.dispatched_at).all())
    by_driver: dict = {}
    for w in rows:
        key = w.driver_profile_id
        entry = by_driver.setdefault(key, {
            "driver_id": key,
            "driver": (w.driver_profile.full_name if w.driver_profile
                       else "Not assigned"),
            "phone": w.driver_profile.phone if w.driver_profile else "",
            "deliveries": 0, "to_collect": 0.0, "holding": 0.0, "fees": 0.0,
            "oldest": None,
        })
        entry["deliveries"] += 1
        entry["to_collect"] = round(entry["to_collect"] + w.cod_outstanding, 2)
        entry["holding"] = round(entry["holding"] + (w.cod_collected or 0.0), 2)
        entry["fees"] = round(entry["fees"] + (w.delivery_fee or 0.0), 2)
        if w.dispatched_at and (entry["oldest"] is None
                                or w.dispatched_at < entry["oldest"]):
            entry["oldest"] = w.dispatched_at

    unsettled = (
        db.query(func.coalesce(func.sum(Waybill.cod_collected), 0.0))
        .filter(Waybill.cod_settled_at.is_(None),
                Waybill.cod_collected > 0).scalar())
    return {
        "drivers": sorted(by_driver.values(),
                          key=lambda d: -(d["holding"] + d["to_collect"])),
        "deliveries": len(rows),
        "to_collect": round(sum(w.cod_outstanding for w in rows), 2),
        # Collected and not yet handed in — including from rounds that are
        # already back. This is what the shop is owed by its own drivers, and
        # nothing was tracking it.
        "uncollected_cash": round(float(unsettled or 0), 2),
        "fees_out": round(sum(w.delivery_fee or 0.0 for w in rows), 2),
    }
