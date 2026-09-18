"""Give the lines that actually move a ceiling, from what they actually sell.

    python set_max_levels.py --pharmacy 5                  # says what it would do
    python set_max_levels.py --pharmacy 5 --apply          # does it

A reorder level is a floor: at or below it, order. It answers "order now" and
says nothing about "how much", and it cannot catch the opposite mistake at all —
a line nobody is selling, reordered to the same level every month until there is
a year of it on the shelf and a write-off at the end.

THE RULE, AND WHY IT IS THIS ONE.

A maximum is a number of days of stock, not a number of units. Twenty is a lot
of one medicine and a fortnight of another, and the only thing that tells them
apart is what actually leaves the shelf. So:

    max = what goes out in a day  x  the cover wanted  rounded UP to whole packs

Rounded up to packs because a pharmacy orders packs. A ceiling of 47 on a line
that comes in 30s is a ceiling nobody can buy to, and it would be hit and
breached on every single order.

WHAT IT WILL NOT TOUCH.

A line with no movement gets no ceiling. That is not caution, it is the honest
answer: a maximum derived from no demand is a guess dressed as a figure, and
this system already has one of those in every stock count. Those lines are
reported rather than filled in, so somebody can set them by hand where they
know something the data does not.

A line that already has a maximum is left alone unless --replace is given. It
was set by somebody, and this has less information than they did.
"""
from __future__ import annotations

import argparse
import math
import os
import pathlib
import sys
from datetime import datetime, timedelta


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
parser.add_argument("--cover", type=int, default=60,
                    help="days of stock the ceiling allows (default 60)")
parser.add_argument("--days", type=int, default=90,
                    help="how far back demand is measured (default 90)")
parser.add_argument("--min-out", type=int, default=1,
                    help="units that must have gone out to count as moving")
parser.add_argument("--from-stock", type=float, default=0.0, metavar="MULTIPLE",
                    help="no demand yet: set the ceiling to this multiple of what "
                         "is on hand now, which is the pharmacy's own opening "
                         "judgement of how much of each line it carries")
parser.add_argument("--replace", action="store_true",
                    help="also overwrite maximums somebody has already set")
parser.add_argument("--apply", action="store_true",
                    help="write it. Without this, nothing is changed.")
parser.add_argument("--local", action="store_true")
args = parser.parse_args()

if not args.local:
    os.environ["DATABASE_URL"] = _target()
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from sqlalchemy import text                                      # noqa: E402
from app.database import SessionLocal                            # noqa: E402
from app import models as m                                      # noqa: E402
from app.tenancy import unscoped                                 # noqa: E402

print(f"target:   {'local' if args.local else os.environ['DATABASE_URL'].split('@')[-1].split('/')[0]}")
print(f"rule:     {args.cover} days of cover, from {args.days} days of demand, "
      "rounded up to whole packs")
print(f"mode:     {'APPLY, this writes' if args.apply else 'dry run, nothing is written'}\n")

db = SessionLocal()
with unscoped():
    pharmacy = db.get(m.Pharmacy, args.pharmacy)
    print(f"pharmacy: {pharmacy.name if pharmacy else args.pharmacy}")

    since = datetime.utcnow() - timedelta(days=args.days)
    # What left the shelf, per product, in one pass. Sales only: a write-off is
    # not demand, and a transfer between branches is the same units moving.
    rows = db.execute(text("""
        SELECT p.id, p.name, p.units_per_pack, p.reorder_level, p.max_level,
               p.quantity_on_hand,
               COALESCE(SUM(-sm.quantity_delta), 0) AS went_out
          FROM products p
          JOIN stock_movements sm ON sm.product_id = p.id
         WHERE p.pharmacy_id = :pharmacy
           AND p.active = TRUE
           AND sm.movement_type = 'sale'
           AND sm.created_at >= :since
         GROUP BY p.id, p.name, p.units_per_pack, p.reorder_level, p.max_level,
                  p.quantity_on_hand
        HAVING COALESCE(SUM(-sm.quantity_delta), 0) >= :min_out
         ORDER BY went_out DESC
    """), {"pharmacy": args.pharmacy, "since": since, "min_out": args.min_out}).all()

    # A SHOP THAT HAS NOT TRADED YET HAS NO DEMAND TO MEASURE.
    #
    # Everything above works off what has left the shelf, which is the right
    # basis and the only honest one, once there is some. On a pharmacy that
    # opened last month it produces a ceiling from one or two units, which is a
    # guess wearing a figure's clothes, and the whole point of a maximum is to
    # be a number somebody trusts enough to act on.
    #
    # The opening count is the other thing that exists, and it is not nothing:
    # it is the pharmacy's own judgement of how much of each line it carries,
    # made by whoever bought it. A multiple of that catches the runaway case
    # without pretending to know demand, and the rule above replaces it the
    # moment there is trading to measure.
    if args.from_stock > 0:
        rows = db.execute(text("""
            SELECT p.id, p.name, p.units_per_pack, p.reorder_level, p.max_level,
                   p.quantity_on_hand, 0 AS went_out
              FROM products p
             WHERE p.pharmacy_id = :pharmacy AND p.active = TRUE
               AND COALESCE(p.quantity_on_hand, 0) > 0
             ORDER BY p.quantity_on_hand DESC
        """), {"pharmacy": args.pharmacy}).all()
        print(f"\nno demand to measure yet, so the ceiling is "
              f"{args.from_stock:g}x what is on hand, which is the shop's own "
              "opening judgement of how much of each line it carries")

    if not rows:
        print(f"\nNothing has been sold in the last {args.days} days, so there is "
              "no demand to set a ceiling from.")
        db.close()
        sys.exit(0)

    plan: list[tuple[int, int]] = []
    skipped_set = 0
    print(f"\n{len(rows):,} line(s) have moved in {args.days} days\n")
    print(f"{'medicine':<42} {'out':>7} {'a day':>7} {'pack':>5} "
          f"{'now':>7} {'max':>7}")
    shown = 0
    for pid, name, per_pack, floor, ceiling, on_hand, went_out in rows:
        pack = max(1, int(per_pack or 1))
        a_day = float(went_out) / args.days
        want = (math.ceil(int(on_hand or 0) * args.from_stock / pack) * pack
                if args.from_stock > 0
                else max(pack, math.ceil(a_day * args.cover / pack) * pack))
        want = max(pack, want)
        # A ceiling under the floor is not a ceiling, it is a contradiction that
        # would put the line permanently both below its minimum and above its
        # maximum. The floor wins and the ceiling clears it by a pack.
        if floor and want <= floor:
            want = (math.floor(floor / pack) + 1) * pack
        if ceiling and not args.replace:
            skipped_set += 1
            continue
        if ceiling == want:
            continue
        plan.append((pid, want))
        if shown < 25:
            print(f"{name[:40]:<42} {int(went_out):>7,} {a_day:>7.2f} {pack:>5} "
                  f"{int(on_hand or 0):>7,} {want:>7,}")
            shown += 1
    if len(plan) > shown:
        print(f"{'... and ' + format(len(plan) - shown, ',') + ' more':<42}")

    print(f"\n{len(plan):,} line(s) would be given a ceiling")
    if skipped_set:
        print(f"{skipped_set:,} already have one, left alone (--replace to change them)")

    # And the ones this cannot speak for, said out loud rather than left out.
    quiet = db.execute(text("""
        SELECT COUNT(*) FROM products p
         WHERE p.pharmacy_id = :pharmacy AND p.active = TRUE
           AND COALESCE(p.max_level, 0) = 0
           AND p.id NOT IN (
               SELECT DISTINCT sm.product_id FROM stock_movements sm
                WHERE sm.movement_type = 'sale' AND sm.created_at >= :since)
    """), {"pharmacy": args.pharmacy, "since": since}).scalar() or 0
    print(f"{quiet:,} line(s) have not moved at all, so they get no ceiling from "
          "this. Set those by hand where you know something the sales do not.")

    if not args.apply:
        print("\nNothing was written. Run it again with --apply to do it.")
        db.close()
        sys.exit(0)

    print(f"\nwriting {len(plan):,}…", flush=True)
    written = 0
    # In chunks, and set-based within each: a round trip a product is what cost
    # this deployment its data transfer once already.
    for at in range(0, len(plan), 500):
        chunk = plan[at:at + 500]
        values = ", ".join(f"({pid}, {level})" for pid, level in chunk)
        written += db.execute(text(
            f"""UPDATE products AS p SET max_level = v.level
                  FROM (VALUES {values}) AS v(id, level)
                 WHERE p.id = v.id"""), {}).rowcount
        db.commit()
        print(f"  {written:,}", flush=True)
    print(f"\n{written:,} line(s) now carry a ceiling.")
db.close()
