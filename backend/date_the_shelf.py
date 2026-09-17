"""Put an expiry date on stock that has none, in one pass.

    python date_the_shelf.py --pharmacy 5 --months 24            # says what it would do
    python date_the_shelf.py --pharmacy 5 --months 24 --apply    # does it

An opening count says how many boxes are on each shelf. It never says what is
printed on them, so every batch it creates is undated — and undated stock cannot
be dispensed or sold, because First-Expiry-First-Out has nowhere to place a
batch with no date and selling one means selling a box nobody has looked at.

CareXpress opened with 841,574 units in that state. The counter can date them
one at a time, and does: the dispensary and the till both ask for the date off
the pack the first time a medicine goes out. But until a medicine has been
handed over once, it is unsellable, and on the first day that is everything in
the shop.

So this puts a holding date on the whole shelf at once, and is honest about
what that date is. It is NOT read off any pack. It is an assumption, recorded
as one, so that the shop can trade while the real dates are collected: every
batch it touches gets a stock movement saying it was dated in bulk, by whom and
on what assumption, and anybody reading the ledger afterwards can see exactly
which dates were assumed and which were read.

Two things it deliberately does not do:

  It never touches a batch that already has a date, right or wrong. A date
  somebody recorded is evidence; an assumption must not overwrite it.

  It never touches a batch with nothing left in it. An empty batch is history,
  and rewriting history to make a report tidier is how a ledger stops being one.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
from datetime import date, datetime


def _target() -> str:
    env = pathlib.Path(__file__).with_name(".env")
    if not env.exists():
        sys.exit("backend/.env not found; nothing to read the target from.")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SEED_TARGET_URL="):
            url = line.split("=", 1)[1].strip()
            if url:
                return url
    sys.exit("SEED_TARGET_URL is not set in backend/.env.")


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--pharmacy", type=int, default=5)
parser.add_argument("--months", type=int, default=24,
                    help="how far ahead the holding date sits (default 24)")
parser.add_argument("--branch", type=int, default=None, help="only this branch")
parser.add_argument("--apply", action="store_true",
                    help="write it. Without this, nothing is changed.")
parser.add_argument("--local", action="store_true",
                    help="run against backend/rx3000.db instead of the hosted database")
args = parser.parse_args()

if not args.local:
    os.environ["DATABASE_URL"] = _target()
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from sqlalchemy import func, text                                # noqa: E402
from app.database import SessionLocal                            # noqa: E402
from app import models as m                                      # noqa: E402
from app.tenancy import unscoped                                 # noqa: E402


def months_ahead(n: int) -> date:
    """The same day of the month, n months on. Clamped to the month's length so
    that 31 August plus six months is 28 February and not a crash."""
    today = date.today()
    month = today.month - 1 + n
    year = today.year + month // 12
    month = month % 12 + 1
    last = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(today.day, last))


HOLDING = months_ahead(args.months)
WHERE = (
    "b.expiry_date IS NULL AND b.quantity_remaining > 0 "
    "AND p.pharmacy_id = :pharmacy"
    + (" AND b.branch_id = :branch" if args.branch else "")
)
PARAMS: dict = {"pharmacy": args.pharmacy}
if args.branch:
    PARAMS["branch"] = args.branch

print(f"target:   {'local rx3000.db' if args.local else os.environ['DATABASE_URL'].split('@')[-1].split('/')[0]}")
print(f"holding:  {HOLDING:%d %B %Y}  ({args.months} months from today)")
print(f"mode:     {'APPLY, this writes' if args.apply else 'dry run, nothing is written'}\n")

db = SessionLocal()
with unscoped():
    pharmacy = db.get(m.Pharmacy, args.pharmacy)
    print(f"pharmacy: {pharmacy.name if pharmacy else args.pharmacy}")

    # What is about to change, per branch, before anything does.
    rows = db.execute(text(
        f"""SELECT b.branch_id, COUNT(*) AS batches,
                   COUNT(DISTINCT b.product_id) AS products,
                   COALESCE(SUM(b.quantity_remaining), 0) AS units
              FROM stock_batches b JOIN products p ON p.id = b.product_id
             WHERE {WHERE}
             GROUP BY b.branch_id ORDER BY b.branch_id"""), PARAMS).all()

    if not rows:
        print("\nNothing to do: every batch on this shelf already carries a date.")
        db.close()
        sys.exit(0)

    names = {b.id: b.name for b in db.query(m.Branch)
             .filter(m.Branch.pharmacy_id == args.pharmacy).all()}
    total_batches = total_units = 0
    print(f"\n{'branch':<28} {'batches':>9} {'products':>9} {'units':>12}")
    for branch_id, batches, products, units in rows:
        print(f"{names.get(branch_id, f'branch {branch_id}'):<28} "
              f"{batches:>9,} {products:>9,} {int(units):>12,}")
        total_batches += batches
        total_units += int(units)
    print(f"{'':<28} {'':>9} {'':>9} {'':>12}")
    print(f"{'to be dated':<28} {total_batches:>9,} {'':>9} {total_units:>12,}")

    # And what is deliberately left alone, so the two numbers can be compared.
    already = db.execute(text(
        """SELECT COUNT(*), COALESCE(SUM(b.quantity_remaining), 0)
             FROM stock_batches b JOIN products p ON p.id = b.product_id
            WHERE b.expiry_date IS NOT NULL AND b.quantity_remaining > 0
              AND p.pharmacy_id = :pharmacy"""), {"pharmacy": args.pharmacy}).first()
    print(f"{'left alone, already dated':<28} {already[0]:>9,} {'':>9} {int(already[1]):>12,}")

    if not args.apply:
        print("\nNothing was written. Run it again with --apply to do it.")
        db.close()
        sys.exit(0)

    # WHO did this, so the movement rows name somebody. The pharmacy's own
    # administrator rather than a system id: a ledger entry with no name on it
    # is the kind an inspector asks about and nobody can answer.
    who = (db.query(m.User)
           .filter(m.User.pharmacy_id == args.pharmacy, m.User.active.is_(True),
                   m.User.role == "admin")
           .order_by(m.User.id).first())
    note = (f"Expiry assumed in bulk at {args.months} months ({HOLDING:%d %b %Y}) "
            "so the shelf could be traded. NOT read off the pack. Correct it "
            "when the pack is next in hand.")

    print(f"\nwriting, as {who.username if who else 'nobody'}…", flush=True)

    # The audit trail FIRST, while the batches still identify themselves as
    # undated. Written server-side in one statement rather than a row at a time:
    # two and a half thousand inserts over a hosted connection is two and a half
    # thousand round trips, and this is exactly the shape that has already cost
    # this deployment a transfer quota.
    written = db.execute(text(
        f"""INSERT INTO stock_movements
              (product_id, movement_type, quantity_delta, balance_after,
               reference, notes, user_id, created_at, branch_id, pharmacy_id)
            SELECT b.product_id, 'adjustment', 0,
                   COALESCE(p.quantity_on_hand, 0),
                   CONCAT('EXPIRY BULK ', CAST(b.id AS VARCHAR)),
                   :note, :user_id, :now, b.branch_id, p.pharmacy_id
              FROM stock_batches b JOIN products p ON p.id = b.product_id
             WHERE {WHERE}"""),
        {**PARAMS, "note": note, "user_id": who.id if who else None,
         "now": datetime.utcnow()}).rowcount
    print(f"  {written:,} movement(s) recorded")

    dated = db.execute(text(
        f"""UPDATE stock_batches AS b
               SET expiry_date = :expiry
              FROM products p
             WHERE p.id = b.product_id AND {WHERE}"""),
        {**PARAMS, "expiry": HOLDING}).rowcount
    db.commit()
    print(f"  {dated:,} batch(es) dated {HOLDING:%d %b %Y}")

    # Read it back rather than trust the counter the statement returned.
    left = db.execute(text(
        f"""SELECT COUNT(*) FROM stock_batches b JOIN products p ON p.id = b.product_id
             WHERE {WHERE}"""), PARAMS).scalar()
    print(f"\n{left:,} batch(es) still undated "
          + ("— done." if left == 0 else "— run it again."))
db.close()
