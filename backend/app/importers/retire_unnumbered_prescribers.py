"""Put away the prescribers nobody can bill against.

    python -m app.importers.retire_unnumbered_prescribers --pharmacy 13
    python -m app.importers.retire_unnumbered_prescribers --pharmacy 13 --apply

WHY RETIRED AND NOT DELETED

The ask was to remove every prescriber with no practice number. Deleting them
is the one thing that cannot be done, and not for a technical reason: every one
of them is named on scripts this pharmacy has dispensed — locally 539
prescribers across 3,298 scripts, in production 689 across some 26,500. A
dispensing record is a legal record of who prescribed what to whom, and a
delete either fails on the foreign key or blanks the prescriber on all of them,
which turns a bad prescriber list into a bad *dispensing history*. The second is
unrecoverable and would be found months later by a funder or an inspector.

Retiring does what removing was meant to do. `Doctor.active` has existed since
the model was written — "Retired, never deleted" — and `DELETE /doctors/{id}`
has always set it rather than deleting. What was missing is that the picker read
the whole table regardless, so retiring somebody changed nothing on screen. With
that fixed (patients_router.list_doctors), this hides them from capture and
leaves every script they wrote naming them.

WHAT IT REPORTS BEFORE IT DOES ANYTHING

How many would go, how many of those have written recently, and the ones with
the most scripts. A prescriber who wrote last week and has no number is not a
dead record — it is a number somebody has not typed in yet, and putting them
away silently is how a busy practice gets locked out of the system. `--keep-days`
leaves those alone.

It is reversible: `--restore` brings back every prescriber this put away that
still has no number, so a pharmacy that decides against it is not stuck.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from sqlalchemy import func, or_

from ..database import SessionLocal
from ..models import Doctor, Prescription
from ..tenancy import reset_current_pharmacy, set_current_pharmacy, unscoped

#: What "has no practice number" means, in one place. A prescriber whose number
#: is a blank string and one whose number is null are the same problem, and a
#: check that only caught one of them left half the list behind.
def unnumbered():
    return or_(Doctor.practice_number.is_(None),
               func.trim(Doctor.practice_number) == "")


def plan(db, keep_days: int = 0) -> dict:
    """Who would be put away, and what it would cost to put them away."""
    rows = (db.query(Doctor)
            .filter(unnumbered(), Doctor.active.is_(True))
            .order_by(Doctor.name).all())
    if not rows:
        return {"retire": [], "keep": [], "scripts": {}, "last": {}}

    ids = [d.id for d in rows]
    counted = dict(db.query(Prescription.doctor_id, func.count(Prescription.id))
                   .filter(Prescription.doctor_id.in_(ids))
                   .group_by(Prescription.doctor_id).all())
    latest = dict(db.query(Prescription.doctor_id, func.max(Prescription.date_prescribed))
                  .filter(Prescription.doctor_id.in_(ids))
                  .group_by(Prescription.doctor_id).all())

    cutoff = date.today() - timedelta(days=keep_days) if keep_days else None
    retire, keep = [], []
    for doctor in rows:
        wrote = latest.get(doctor.id)
        # A prescriber writing this month with no number is a number nobody has
        # typed yet, not a dead record.
        if cutoff and wrote and wrote >= cutoff:
            keep.append(doctor)
        else:
            retire.append(doctor)
    return {"retire": retire, "keep": keep, "scripts": counted, "last": latest}


def apply(db, doctors) -> int:
    for doctor in doctors:
        doctor.active = False
    db.commit()
    return len(doctors)


def restore(db) -> int:
    """Bring back every retired prescriber that still has no number.

    Deliberately not "every prescriber this run retired": there is no marker on
    the row saying which run put somebody away, and inventing one to support an
    undo would be a column on a table for the sake of a script. A prescriber
    retired for any other reason usually HAS a number, so this leaves them.
    """
    rows = (db.query(Doctor)
            .filter(unnumbered(), Doctor.active.is_(False)).all())
    for doctor in rows:
        doctor.active = True
    db.commit()
    return len(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pharmacy", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", action="store_true",
                        help="bring back every unnumbered prescriber that was put away")
    parser.add_argument("--keep-days", type=int, default=0,
                        help="leave alone anyone who has written a script in this many days")
    args = parser.parse_args(argv)

    token = set_current_pharmacy(args.pharmacy)
    db = SessionLocal()
    try:
        if args.restore:
            if not args.apply:
                waiting = (db.query(func.count(Doctor.id))
                           .filter(unnumbered(), Doctor.active.is_(False)).scalar())
                print(f"{waiting:,} unnumbered prescriber(s) are put away and would come back"
                      " — nothing written, this is a preview")
                return 0
            print(f"{restore(db):,} prescriber(s) brought back.")
            return 0

        found = plan(db, args.keep_days)
        total = db.query(func.count(Doctor.id)).scalar()
        going, staying = found["retire"], found["keep"]
        scripts = sum(found["scripts"].get(d.id, 0) for d in going)

        print(f"\n{total:,} prescriber(s) on file for pharmacy {args.pharmacy}")
        print(f"{len(going):,} have no practice number and would be retired"
              + ("" if args.apply else " — nothing written, this is a preview"))
        print(f"    they are named on {scripts:,} script(s), which keep naming them")
        if staying:
            print(f"{len(staying):,} left alone: they wrote in the last {args.keep_days} days, "
                  "so the number is probably just untyped")
            for doctor in staying[:8]:
                print(f"    {doctor.name[:34]:<36} last wrote {found['last'].get(doctor.id)}")

        busiest = sorted(going, key=lambda d: -found["scripts"].get(d.id, 0))[:10]
        if busiest:
            print("\n  the busiest of the ones going:")
            for doctor in busiest:
                print(f"    {doctor.name[:34]:<36} "
                      f"{found['scripts'].get(doctor.id, 0):>5} script(s)   "
                      f"last {found['last'].get(doctor.id) or 'never'}")

        if args.apply:
            print(f"\n  {apply(db, going):,} prescriber(s) retired. They no longer appear when a "
                  "script is captured; every script they wrote still names them.")
            print("  Reversible: --restore brings them back.")
        return 0
    finally:
        db.close()
        reset_current_pharmacy(token)


if __name__ == "__main__":
    with unscoped():
        sys.exit(main())
