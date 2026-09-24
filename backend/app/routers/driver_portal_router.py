"""The driver's own round, read off the driver's own phone.

WHAT THIS REPLACES

Nothing, which is the problem. A delivery was closed from the back office by
somebody who was not at the door: a dispenser ticking "delivered" and typing a
name the driver read down the telephone an hour later, or at the end of the
shift from memory. Every fact on a waybill — who took it, whether identity was
checked on a controlled substance, what was collected at the door — was one
person's account of another person's afternoon.

The driver is at the door with a phone in their hand. So the round is on the
phone, the recipient signs on the phone, and the waybill is closed at the
moment and place it was actually closed.

WHY A LINK AND NOT AN ACCOUNT

The runner on the motorbike is not staff, does not use the dispensing system,
and in half of these pharmacies is a contractor the shop uses on Saturdays. A
seat licence and a password for somebody who needs one screen for one afternoon
is how this ends up unused and the deliveries go on being closed from the
office. The link is signed and scoped to one driver, the code is theirs, and
the link's life is a shift rather than the patient link's week: a phone left in
a taxi should not still open tomorrow's round.

WHAT A DRIVER CAN SEE, AND WHAT THEY CANNOT

Their own run and nothing else. The address, the recipient, the telephone
number, what to collect and whether identity must be checked. Not the
medicine, not the diagnosis, not the patient's record: a driver needs to find
a house and hand over a bag, and a parcel's contents are between the pharmacy
and the patient. `driver_account.account` was the nearest existing shape and
it returns rows built for a supervisor; this uses its own narrow projection
for exactly that reason.
"""
from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from .. import tenancy
from ..database import get_db
from ..models import Driver, Waybill
from ..services import deliveries as delivery_svc
from ..services import portal_pins, portal_tokens

router = APIRouter(prefix="/api/portal/driver", tags=["portals"])

#: A shift, not a week. A driver's link names live deliveries with addresses
#: and telephone numbers on them, so a phone left in a taxi stops opening
#: anything by the next morning.
SHIFT_TTL = 16 * 3600


def driver_from(token: str, db: Session, x_portal_pass: str = "", *,
                require_code: bool = True) -> Driver:
    """The driver a signed link names, their pharmacy in force, and the round
    theirs to close.

    Expressed as one function every route calls rather than as four separate
    checks, so a route added later cannot forget one. The refusals are the
    same ones `dispatch` makes when a driver is sent out in the first place: a
    retired driver and an expired licence are both people who should not be on
    the road, and finding that out at the door is better than not at all.
    """
    try:
        did = portal_tokens.read(token, expect="driver")
    except portal_tokens.TokenError as e:
        raise HTTPException(401, str(e))

    # Read unscoped exactly once, for the reason `_patient_from` gives: a
    # portal request carries no session, so no pharmacy is in force and the
    # ordinary tenant filter matches nothing.
    with tenancy.unscoped():
        driver = db.get(Driver, did)
    if not driver:
        raise HTTPException(404, "This link is no longer available.")
    if driver.pharmacy_id:
        tenancy.set_current_pharmacy(driver.pharmacy_id)
        tenancy.stamp(db)

    if not driver.active:
        raise HTTPException(
            403, "You are no longer on the driver list. Ring the pharmacy.")
    if driver.licence_expiry and driver.licence_expiry < date.today():
        raise HTTPException(
            403,
            f"Your licence expired on {driver.licence_expiry:%d %b %Y}, so "
            f"this round cannot be signed off from here. Ring the pharmacy.")

    # `require_code=False` for the two callers that ARE the door: the brand a
    # locked page draws itself with, and the unlock endpoint. Asking somebody
    # to already be through the door in order to knock is a locked room, and
    # it was one until this line said so.
    if require_code:
        _unlocked(driver, x_portal_pass)
    return driver


def _unlocked(driver: Driver, pass_token: str) -> None:
    """Refuse unless the four digits were entered on this phone.

    Same shape as the other portals' gate — see `portal_router._unlocked` —
    and the same exemption for a link issued before there were codes.
    """
    if not portal_pins.has_pin(driver):
        return
    if not pass_token:
        raise HTTPException(401, "Enter the code the pharmacy gave you.")
    try:
        named = portal_tokens.read(pass_token, expect="driver-in")
    except portal_tokens.TokenError as e:
        raise HTTPException(401, str(e))
    if named != driver.id:
        raise HTTPException(401, "That code was entered for a different link.")


def _drop(w: Waybill) -> dict:
    """One stop on the round, in the words the person at the door needs.

    Deliberately narrow. `driver_account.row` is the closest existing shape
    and it carries the patient record behind it; a driver needs an address and
    a name, and what they cannot see they cannot leave on a phone in a taxi.
    """
    patient = w.patient
    return {
        "id": w.id,
        "waybill_number": w.waybill_number,
        "recipient": w.recipient or (
            f"{patient.first_name} {patient.last_name}".strip()
            if patient else ""),
        "address": w.address or "",
        "phone": w.phone or (patient.phone if patient else "") or "",
        "instructions": w.instructions or "",
        "status": w.status,
        #: Identity checked at the door, because a controlled substance never
        #: reached the counter where it would have been checked.
        "requires_id_check": bool(w.requires_id_check),
        "to_collect": round(w.cod_amount or 0.0, 2),
        "dispatched_at": w.dispatched_at,
        "delivered_at": w.delivered_at,
        "received_by": w.received_by or "",
        "signed": bool(w.signature),
    }


@router.get("/{token}")
def my_round(token: str, db: Session = Depends(get_db),
             x_portal_pass: str = Header(default="", alias="X-Portal-Pass")):
    """Everything still out with this driver, oldest first.

    Oldest first, not newest: the parcel that left the shop two hours ago is
    the one somebody is ringing about. Every other list in this product is
    newest first because it is being read as a record; this one is being
    worked down.
    """
    driver = driver_from(token, db, x_portal_pass)

    out = (db.query(Waybill)
           .options(joinedload(Waybill.patient))
           .filter(Waybill.driver_profile_id == driver.id,
                   Waybill.status.in_(("pending", "out")))
           .order_by(Waybill.dispatched_at.asc().nullslast(),
                     Waybill.created_at.asc())
           .all())
    done_today = (db.query(Waybill)
                  .filter(Waybill.driver_profile_id == driver.id,
                          Waybill.status == "delivered",
                          Waybill.delivered_at >= datetime.combine(
                              date.today(), datetime.min.time()))
                  .count())
    holding = delivery_svc.driver_row(db, driver)["cash_holding"]

    return {
        "driver": driver.full_name,
        "drops": [_drop(w) for w in out],
        "left": len(out),
        "done_today": int(done_today),
        # What is in their pocket. A driver who knows the figure is a driver
        # who can be handed a receipt for it, and it is the one number the
        # shop and the driver argue about at the end of a round.
        "holding": round(holding, 2),
        "cod_limit": round(driver.cod_limit or 0.0, 2),
        "says": _how_it_is_going(len(out), int(done_today)),
    }


def _how_it_is_going(left: int, done: int) -> str:
    """The round in one sentence, so the number is not the only thing there."""
    if left == 0 and done == 0:
        return "Nothing is out with you at the moment."
    if left == 0:
        return (f"All done. {done} "
                f"{'delivery' if done == 1 else 'deliveries'} today.")
    return (f"{left} still to go" + (f", {done} done today." if done else "."))


class Signed(BaseModel):
    """What comes back from the door."""
    received_by: str = Field(default="", max_length=120)
    id_number_seen: str = Field(default="", max_length=30)
    #: A PNG data URI drawn on the phone. Capped because a signature is a few
    #: hundred strokes on a small canvas, and anything larger is not one.
    signature: str = Field(default="", max_length=400_000)
    collected: float | None = None
    cod_instrument: str = Field(default="cod", max_length=30)


@router.post("/{token}/drops/{waybill_id}/delivered")
def delivered(token: str, waybill_id: int, body: Signed,
              db: Session = Depends(get_db),
              x_portal_pass: str = Header(default="", alias="X-Portal-Pass")):
    """Close a drop from the doorstep, with the recipient's own signature."""
    driver = driver_from(token, db, x_portal_pass)
    w = _mine(db, driver, waybill_id)

    if not body.received_by.strip():
        raise HTTPException(
            400,
            "Write down who took it. A parcel signed for by nobody is not a "
            "delivery, it is a missing parcel with a tick against it.")
    if w.requires_id_check and not body.id_number_seen.strip():
        raise HTTPException(
            400,
            "This one contains a controlled medicine. Check the recipient's "
            "identity document at the door and write the number down.")
    signature = (body.signature or "").strip()
    if signature and not signature.startswith("data:image/"):
        raise HTTPException(400, "That signature did not come through.")

    if w.cod_amount or body.collected is not None:
        try:
            delivery_svc.collect(
                db, w,
                amount=(w.cod_amount if body.collected is None
                        else body.collected),
                instrument=body.cod_instrument, reference="")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    w.status = "delivered"
    w.received_by = body.received_by.strip()
    w.id_number_seen = body.id_number_seen.strip()
    w.signature = signature
    w.delivered_at = datetime.utcnow()
    db.commit()

    # THE BAG IS NO LONGER ON THE SHELF.
    #
    # It was. A delivery closed at the door marked the waybill and stopped
    # there, so every dispensing behind it still read "on the shelf" on the
    # dispensing history and still counted on the will-call ageing tiles —
    # medicine the patient had signed for in front of the driver, which the
    # shop believed was sitting behind the counter. Somebody would eventually
    # ring the patient about a bag they had had for a fortnight.
    delivery_svc.off_the_shelf(db, w)
    return {"drop": _drop(w), "message": f"{w.waybill_number} is done."}


@router.post("/{token}/drops/{waybill_id}/failed")
def not_in(token: str, waybill_id: int,
           reason: str = Body(default="", embed=True, max_length=200),
           db: Session = Depends(get_db),
           x_portal_pass: str = Header(default="", alias="X-Portal-Pass")):
    """Nobody was there, or they would not take it.

    A separate answer from delivered, and a required reason, because "failed"
    on its own tells whoever rings the patient back nothing at all.
    """
    driver = driver_from(token, db, x_portal_pass)
    w = _mine(db, driver, waybill_id)
    if not reason.strip():
        raise HTTPException(
            400, "Say what happened. Somebody has to ring this patient back "
                 "and they need to know what to say.")
    w.status = "failed"
    w.failure_reason = reason.strip()
    db.commit()
    return {"drop": _drop(w),
            "message": f"{w.waybill_number} marked as not delivered."}


def _mine(db: Session, driver: Driver, waybill_id: int) -> Waybill:
    """This driver's own drop, still open.

    The waybill is checked against the driver rather than read by id alone: a
    signed link names one driver, and a driver closing somebody else's
    delivery is exactly what the signature exists to prevent.
    """
    w = db.get(Waybill, waybill_id)
    if not w or w.driver_profile_id != driver.id:
        raise HTTPException(404, "That delivery is not on your round.")
    if w.status not in ("pending", "out"):
        raise HTTPException(
            400,
            f"That one is already {w.status}. Ring the pharmacy if that is "
            f"wrong.")
    return w
