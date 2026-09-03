"""Can the same document number be issued twice?

A pharmacy in production captured an ordinary prescription and got

    500  Something went wrong at our end.

immediately after finishing a draft. The cause was two documents being given
the same number, and a per-pharmacy UNIQUE index refusing the second.

WHY THE NUMBER REPEATED

`helpers.next_number` derived the next number from a count of rows:

    count = db.query(model).count() + 1

That is only correct while every row takes exactly one number, and this system
breaks that both ways.

  **Finalising a draft takes a number and creates no row.** The count does not
  move, so the very next caller is handed the number that was just used.

  **Saving a draft creates a row and takes no number.** The count runs ahead of
  what has been issued, so numbers are skipped. Harmless on its own, and it
  masks the first fault by keeping the count ahead for a while, which is why
  this survived so long and then failed suddenly.

Nineteen document types are numbered this way (`PER_TENANT_NUMBERS` in
migrate.py): sales, prescriptions, claims, batches, waybills, lay-bys, quotes,
tickets, journal entries and the rest. All of them carry the same unique index
and all of them had the same fault. A pharmacy would have met it as a failed
sale as readily as a failed script.

WHAT IS CHECKED

For every numbered document type, against real data:

  the number offered is not one already in use;
  taking it and asking again offers a different one, which is the exact
    sequence that failed: finalise, then create;
  the number is scoped to the pharmacy, because the unique index is.

Nothing is committed.

    python qa/document-numbers.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import logging                                          # noqa: E402
logging.disable(logging.CRITICAL)

from app.database import SessionLocal                   # noqa: E402
from app import tenancy, helpers                        # noqa: E402
from app.migrate import PER_TENANT_NUMBERS              # noqa: E402
from app import models                                  # noqa: E402

#: The prefix each type is issued under, keyed by table.
PREFIXES = {
    "sales": "INV", "prescriptions": "RX", "purchase_orders": "PO",
    "claims": "CLM", "claim_batches": "CB", "waybills": "WB",
    "laybys": "LAY", "quotes": "QT", "tickets": "TKT",
    "remittances": "REM", "journal_entries": "JE",
}


def model_for(table: str):
    for cls in models.Base.registry._class_registry.values():
        if hasattr(cls, "__tablename__") and cls.__tablename__ == table:
            return cls
    return None


def main() -> int:
    tenancy.set_current_pharmacy(1)
    db = SessionLocal()
    tenancy.stamp(db)
    failures: list[str] = []
    checked = 0

    def check(ok: bool, said: str, why: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {said}")
        if not ok:
            failures.append(why or said)

    try:
        for table, field in PER_TENANT_NUMBERS:
            prefix = PREFIXES.get(table)
            model = model_for(table)
            if model is None or prefix is None:
                continue
            column = getattr(model, field, None)
            if column is None:
                continue
            checked += 1

            offered = helpers.next_number(db, model, prefix, field)
            taken = db.query(model).filter(column == offered).first()
            check(taken is None,
                  f"{table:<18} offers {offered}, which is free",
                  f"{table}: {offered} is already in use, so the insert will be "
                  f"refused by the per-pharmacy unique index and the request "
                  f"will fail with a 500")

            # The sequence that broke production: something takes the number
            # without adding a row, then the next caller asks.
            row = db.query(model).filter(column.isnot(None)).first()
            if row is None:
                continue
            before = getattr(row, field)
            setattr(row, field, offered)
            db.flush()
            again = helpers.next_number(db, model, prefix, field)
            setattr(row, field, before)
            db.flush()

            check(again != offered,
                  f"{'':<18} and a different one once that is used ({again})",
                  f"{table}: after {offered} was issued, the next caller was "
                  f"offered {offered} again. That is the production failure: "
                  f"finalise a draft, then capture a script, and the second "
                  f"insert is refused.")
    finally:
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"{checked} numbered document type(s): no number is issued twice")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
