"""Taking a lot other than the one the rotation says, and what that costs.

FEFO decides which batch leaves the shelf, and it is right almost always.
Almost is the word this module is about. A dispenser standing at the shelf
sometimes has a good reason to take a different lot, and until now there was
no way to say so: the picker took the earliest expiry and nothing else was
possible. So the override happened anyway, off the system, by the dispenser
handing over the pack in their hand while the software recorded a different
one. The shelf figure stayed right in total and every batch number on every
record was wrong, which is worse than either.

A recall is what makes that matter. The one question a recall asks is which
patients got lot ABC1234, and it can only be answered from records of what
actually went out of the door.

WHAT AN OVERRIDE IS PERMISSION TO DO, AND WHAT IT IS NOT

It is permission to break the ROTATION rule. It is not permission to break
the safety rules, and those are checked exactly as hard as before: the lot
must be at this branch, must not be expired, must not be quarantined, and
must actually hold stock. A supervisor cannot authorise dispensing expired
medicine, because no supervisor has that authority in the first place.

WHY NAMING THE FRONT LOT IS NOT AN OVERRIDE

Because nothing was overridden. A dispenser who scans the pack in their hand
and it turns out to be the lot FEFO would have taken anyway has followed the
rotation, and stopping to demand a supervisor's password for that is friction
that teaches people to route around the system, which is the behaviour this
module exists to stop.

WHY A REASON IS COMPULSORY

An override with no reason recorded is indistinguishable from a mistake, and
the report that matters is the one showing a dispenser who overrides forty
times a month. That is either a shelf that needs reorganising or something
worse, and neither is visible if the column is empty.
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Product, StockBatch

#: Why somebody is taking a lot other than the front one. Deliberately short
#: and concrete: a long list gets answered with whatever is first.
REASONS: tuple[tuple[str, str], ...] = (
    ("pack_in_hand",
     "The pack already off the shelf is from another lot"),
    ("part_pack",
     "Finishing an opened pack before starting a sealed one"),
    ("patient_lot",
     "The patient is to stay on the lot they started"),
    ("front_unusable",
     "The earliest lot is damaged, unlabelled or cannot be found"),
    ("other",
     "Something else, written down"),
)
BY_CODE = {code: label for code, label in REASONS}


def label(code: str) -> str:
    return BY_CODE.get(code or "", "")


def would_take(db: Session, product: Product, branch_id: int | None,
               allow_expired: bool = False) -> StockBatch | None:
    """The lot the rotation would have chosen. The same query the picker runs."""
    query = (db.query(StockBatch)
             .filter(StockBatch.product_id == product.id,
                     StockBatch.quantity_remaining > 0,
                     StockBatch.branch_id == branch_id))
    if not allow_expired:
        query = query.filter(StockBatch.expiry_date >= date.today(),
                             StockBatch.status != "quarantined")
    return query.order_by(StockBatch.expiry_date.asc(),
                          StockBatch.id.asc()).first()


def is_override(db: Session, product: Product, batch_id: int | None,
                branch_id: int | None, allow_expired: bool = False) -> bool:
    """Whether naming this lot actually departs from the rotation."""
    if not batch_id:
        return False
    front = would_take(db, product, branch_id, allow_expired)
    return front is None or front.id != int(batch_id)


def check(db: Session, product: Product, batch_id: int, branch_id: int | None,
          *, allow_expired: bool = False) -> StockBatch:
    """The named lot, or a refusal saying which rule it broke.

    Every refusal here is a rule an override does not lift. They are phrased
    as what to do next, because the person reading them is standing at a
    shelf with a patient waiting.
    """
    batch = db.get(StockBatch, int(batch_id))
    if batch is None or batch.product_id != product.id:
        raise HTTPException(
            400, f"{product.name}: that lot is not one of this medicine's. "
                 "Scan the pack again.")
    if branch_id is not None and batch.branch_id != branch_id:
        raise HTTPException(
            400, f"{product.name}: batch {batch.batch_number} is held at "
                 "another branch. Raise a transfer for it rather than "
                 "dispensing against it here.")
    if (batch.quantity_remaining or 0) <= 0:
        raise HTTPException(
            400, f"{product.name}: batch {batch.batch_number} has nothing "
                 "left on it. The shelf disagrees with the pack in your hand, "
                 "which is worth a count.")
    if not allow_expired:
        if batch.expiry_date and batch.expiry_date < date.today():
            raise HTTPException(
                400,
                f"{product.name}: batch {batch.batch_number} expired on "
                f"{batch.expiry_date.isoformat()}. No authorisation covers "
                "dispensing it. Take it off the shelf.")
        if (batch.status or "") == "quarantined":
            raise HTTPException(
                400,
                f"{product.name}: batch {batch.batch_number} is held and may "
                "not be dispensed. Release it first if the hold was a "
                "mistake.")
    return batch


def authorise(db: Session, *, product: Product, batch_id: int | None,
              branch_id: int | None, reason: str = "", note: str = "",
              user=None, token: str = "",
              allow_expired: bool = False) -> tuple[int | None, str]:
    """Settle a named lot before any stock moves. The one door in.

    Returns the batch to prefer and the sentence to record against it, or
    (None, "") where nothing was named. Raises where the lot is not one that
    may be dispensed, where no reason was given, or where the rotation is
    being stepped past without a supervisor.

    Called BEFORE the shelf is touched, deliberately: every refusal in here
    should leave the stock exactly where it was.
    """
    if not batch_id:
        return None, ""
    # RESOLVED THE SAME WAY THE PICKER RESOLVES IT.
    #
    # `consume_stock_fefo` falls back to the user's branch and then to the
    # default one. If this checked against None while the walk filtered on the
    # default branch, a lot at another shop would pass every check here, fail
    # to appear in the walk's list, and be quietly ignored: the supervisor
    # would have typed a password to authorise nothing, and the record would
    # say a lot went out that never did.
    if branch_id is None:
        from . import branches as _branches
        branch_id = (_branches.branch_of(db, getattr(user, "id", None))
                     or _branches.default_branch(db).id)
    batch = check(db, product, int(batch_id), branch_id,
                  allow_expired=allow_expired)
    if not is_override(db, product, batch.id, branch_id,
                       allow_expired=allow_expired):
        # The lot in hand is the lot the rotation wanted. Nothing to authorise
        # and nothing to explain: this is somebody following the rule, and
        # charging them a password for it is how a system gets routed around.
        return batch.id, ""

    said = why_refused(reason, note)
    from . import stepup
    stepup.demand(db, action_key="stock.batch_override", token=token,
                  actor=user)
    return batch.id, f"{said} [batch {batch.batch_number}]"


def why_refused(reason: str, note: str) -> str:
    """The reason, as it will read on the movement a year from now."""
    if reason not in BY_CODE:
        raise HTTPException(
            400, "Say why this lot is being taken ahead of the rotation. One "
                 "of: " + ", ".join(c for c, _ in REASONS) + ".")
    if reason == "other" and not (note or "").strip():
        raise HTTPException(
            400, "Write down what the reason is. An override with nothing "
                 "against it cannot be told from a mistake.")
    said = label(reason)
    return f"{said}. {note.strip()}" if (note or "").strip() else said
