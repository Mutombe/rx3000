"""The pharmacy a demo visitor is shown, and how it gets its data.

WHAT WAS WRONG

A demo account was created with no pharmacy at all. Tenancy scopes every query
to the pharmacy in force, and a user with none is narrowed to rows that have
none — of which, after the tenancy backfill, there are none. So a prospect
who asked to try the product got a complete, working, entirely empty pharmacy:
no patients, no stock, no trade, nothing on any screen.

That is the worst first impression the product can make, and it is the one it
was making to everybody who clicked "Try it for 4 hours".

WHY THE DEMO IS SHARED, AND WHAT THAT COSTS

Seeding a pharmacy takes 36,000 statements for sixty days of trade — about two
minutes against a database in another region, and thirteen seconds for even a
ten-day slice. Nobody waits two minutes at a sign-up button, so a demo cannot
be seeded per visitor on demand.

So there is one demonstration pharmacy and every demo visitor is placed in it.
The honest cost: two prospects demonstrating at the same time see each other's
work. That is unlikely at the volumes this product will see for a while, and it
looks like a busy shop rather than like a fault, but it IS a real limitation
and it is written down here rather than discovered later. The way out, when
demo traffic justifies the machinery, is a pool of pharmacies seeded in advance
and claimed one per visitor.

WHAT IT IS NOT

It is not the customer's data. The demonstration pharmacy is its own tenant, so
a demo visitor is scoped away from every real pharmacy by exactly the mechanism
that scopes real pharmacies away from each other — there is no second rule to
get wrong.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import branch_scope, tenancy
from ..models import Pharmacy

log = logging.getLogger("rx5000.demo")

#: How this pharmacy is recognised again on the next boot. A name rather than a
#: flag column: it is the only row that will ever be called this, and a column
#: would have to be migrated onto every existing deployment to say one thing.
DEMO_PHARMACY = "RX5000 Demonstration Pharmacy"

#: Days of trade in the demonstration data. The full sixty gives a fuller set
#: of screens — a claim cycle, a month of takings, repeats coming due — and it
#: is seeded once rather than per visitor, so the cost is paid at deployment.
DEMO_DAYS = 60


def get(db: Session) -> Pharmacy:
    """The demonstration pharmacy, created if this deployment has none.

    Deliberately outside the tenant scope: this is looked up before any
    pharmacy is in force, which is the same reason `get_current_user` reads the
    user unscoped.
    """
    with tenancy.unscoped():
        existing = (db.query(Pharmacy)
                    .filter(Pharmacy.name == DEMO_PHARMACY).first())
        if existing is not None:
            return existing

        made = Pharmacy(
            name=DEMO_PHARMACY,
            trading_name="RX5000 Demo",
            city="Harare",
            active=True,
        )
        db.add(made)
        db.commit()
        db.refresh(made)
        log.info("Created the demonstration pharmacy (id=%s)", made.id)
        return made


#: Written on the demonstration pharmacy to say how far the seed got. The row
#: has no registration number of its own — it is not a real pharmacy — so the
#: column is free, and using it avoids migrating a flag onto every deployment
#: to record something only one row will ever say.
MARK_RUNNING = "SEEDING"
MARK_DONE = "SEEDED"


def state(db: Session) -> str:
    """"", "SEEDING" or "SEEDED"."""
    with tenancy.unscoped():
        return (get(db).registration_no or "").strip()


def _mark(db: Session, value: str) -> None:
    with tenancy.unscoped():
        pharmacy = get(db)
        pharmacy.registration_no = value
        db.commit()


def is_seeded(db: Session) -> bool:
    """Did a seed run to the end?

    The mark, not the row count. `run_if_thin` asks whether there are two
    hundred sales, which answers "is this a fresh install" and not "did the
    last attempt finish" — and a run interrupted at a hundred and fifty sales
    answers the first question wrongly, so the next attempt writes the whole
    dataset again on top of the half that survived.
    """
    return state(db) == MARK_DONE


def seed(db: Session, *, days: int = DEMO_DAYS) -> dict[str, int]:
    """Fill the demonstration pharmacy, once.

    Runs the same generator the development database uses, so what a prospect
    sees is what the product was built and tested against rather than a second,
    thinner dataset written to look convincing.

    Scoped INTO the demonstration pharmacy for the duration: every row the
    generator writes is stamped with it by the same mechanism that stamps a
    real pharmacy's rows, so nothing can land in a customer's tenant by
    accident.
    """
    from .. import realseed

    pharmacy = get(db)
    if is_seeded(db):
        log.info("The demonstration pharmacy is already seeded.")
        return {}
    if state(db) == MARK_RUNNING:
        # Either another process is doing it, or one died trying. Neither is a
        # reason to write a second copy on top; both are a reason for somebody
        # to look. Cleared by hand, or by deleting the pharmacy and starting
        # again, which is a decision rather than a retry.
        log.warning("The demonstration pharmacy is marked as still seeding. "
                    "Refusing to seed again; clear its registration_no to "
                    "retry from scratch.")
        return {}

    log.info("Seeding the demonstration pharmacy (id=%s, %s days)…",
             pharmacy.id, days)

    # New rows need stamping with the pharmacy in force, and that handler is
    # registered by `get_db` on the session it hands to a request. This runs on
    # its own session, so it registers its own — without it the generator wrote
    # seven hundred sales with no pharmacy on them, which is to say into the
    # same nowhere the demo accounts were already looking at.
    tenancy.stamp(db)

    _mark(db, MARK_RUNNING)
    token = tenancy.set_current_pharmacy(pharmacy.id)
    try:
        # Branch scoping off: the generator creates the branch it then writes
        # against, and there is no branch in force while it does.
        with branch_scope.every_branch():
            made = realseed.run_if_thin(db, days=days)
    except Exception:
        # The mark stays at SEEDING, which is the honest state: something is in
        # there and it is not the whole dataset. Somebody decides what to do
        # with it rather than the next boot deciding for them.
        log.exception("Seeding the demonstration pharmacy failed part way.")
        raise
    finally:
        tenancy.reset_current_pharmacy(token)

    _mark(db, MARK_DONE)
    log.info("Demonstration pharmacy seeded: %s", made)
    return made
