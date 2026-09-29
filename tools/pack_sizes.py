"""Count the packs that say a count, after showing you every price it moves.

    python tools/pack_sizes.py --pharmacy 1                 # dry run, changes nothing
    python tools/pack_sizes.py --pharmacy 1 --apply         # writes, and journals
    python tools/pack_sizes.py --pharmacy 1 --undo FILE     # puts it all back

WHY THIS IS A TOOL AND NOT A MIGRATION

A migration runs on every deployment, for every pharmacy, without anybody
present. This changes what patients are charged, and whether it is a fix or a
fresh fault depends on how one particular pharmacy entered its prices. That is
a decision somebody makes about their own catalogue, with the figures in front
of them, which is the opposite of a thing that happens automatically at three
in the morning.

WHAT IT DOES

`Product.pack_size` is free text off a supplier's file: "30s", "21s", "1000s".
`Product.units_per_pack` is the integer everything divides by, and it defaults
to 1, meaning "the pack IS the unit". A product with the first and not the
second is priced per pack per tablet, because dispensing charges
`per_unit() * quantity` and `per_unit()` is the pack price over
`units_per_pack`. A box of paracetamol labelled 1000s at $9.00 bills $9,000.

This reads the label, and where it plainly names a count, sets the integer to
match. It touches `units_per_pack` and NOTHING else: no price is edited, no
stock figure is moved. The prices change only in the sense that a division
finally has the right denominator.

WHAT IT DELIBERATELY WILL NOT TOUCH

  a measured pack   "10ml", "100g". A bottle IS one unit and dividing by the
                    millilitres would price a dose at a fraction of a cent.
  a silent pack     no label at all. There is nothing to read and guessing is
                    how this fault was created in the first place.
  a pack that       already counts. If somebody has set 20 against a label of
  disagrees         "30s", they know something this does not, and overwriting a
                    human decision with a regex is not a fix. Reported, never
                    changed.

WHAT IT DOES NOT FIX, AND YOU SHOULD KNOW BEFORE RUNNING IT

The shelf figures. `quantity_on_hand` is in units, and if staff have been
typing counts while the catalogue said one unit per pack, a shelf of twenty
boxes may be recorded as twenty. This corrects the pricing and leaves that
reading as it was: after it runs, a shelf of "20" against a pack of thirty
reads as twenty loose tablets. If that is wrong it is wrong now too, silently,
and the answer is a stock take rather than a script.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

from app.database import SessionLocal            # noqa: E402
from app.models import Product                   # noqa: E402
from app import tenancy                          # noqa: E402

#: "30s", "30 s", "30's", "100 tabs", "1000". The trailing letter is the
#: supplier's shorthand for "of these" and the number in front is the count.
COUNTED = re.compile(r"^\s*(\d{1,5})\s*(?:'?s|tabs?|caps?|pcs?|units?)?\s*$", re.I)
#: A volume or a weight. A bottle of 10ml is one unit, not ten.
MEASURED = re.compile(r"\d\s*(ml|l|g|mg|kg|mcg|iu|%)\b", re.I)
#: Above this a "pack size" is almost certainly not a pack. Ten thousand
#: capsules is a drum and a real one; a hundred thousand is a typo.
SANE = 10_000


def implied(pack_size: str) -> int | None:
    """The count the label names, or None where it names none."""
    said = (pack_size or "").strip()
    if not said or MEASURED.search(said):
        return None
    m = COUNTED.match(said)
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 < n <= SANE else None


def money(n: float) -> str:
    return f"{n:,.4f}".rstrip("0").rstrip(".") or "0"


def look(db, pharmacy_id: int):
    """Three lists: what would change, what disagrees, what is already right."""
    rows = (db.query(Product)
            .filter(Product.pharmacy_id == pharmacy_id)
            .order_by(Product.name)
            .all())
    change, disagrees, already = [], [], 0
    for p in rows:
        want = implied(p.pack_size or "")
        if want is None:
            continue
        has = int(p.units_per_pack or 1)
        if has == want:
            already += 1
        elif has == 1:
            change.append((p, want))
        else:
            disagrees.append((p, want, has))
    return rows, change, disagrees, already


def show(change, disagrees, already, total):
    print(f"\n  {total} product(s) in this pharmacy")
    print(f"  {already:>5}  name a count and already count it")
    print(f"  {len(disagrees):>5}  name a count and count something else "
          f"(left alone, listed below)")
    print(f"  {len(change):>5}  name a count and do not count it\n")

    if disagrees:
        print("  LEFT ALONE. Somebody set these by hand and knows something a")
        print("  regular expression does not.")
        for p, want, has in disagrees[:10]:
            print(f"      {str(p.name)[:38]:<40} label {p.pack_size!r} "
                  f"says {want}, catalogue says {has}")
        if len(disagrees) > 10:
            print(f"      and {len(disagrees) - 10} more")
        print()

    if not change:
        print("  Nothing to do.\n")
        return

    print(f"  {'product':<36} {'label':>7} {'holds':>6} "
          f"{'a unit costs now':>17} {'a unit would cost':>18} "
          f"{'a full pack bills now':>22}")
    print("  " + "-" * 112)
    for p, want in change[:40]:
        price = float(p.unit_price or 0.0)
        print(f"  {str(p.name)[:35]:<36} {str(p.pack_size):>7} {want:>6} "
              f"{money(price):>17} {money(price / want):>18} "
              f"{price * want:>22,.2f}")
    if len(change) > 40:
        print(f"  and {len(change) - 40} more")
    print("\n  The price column is NOT edited. What changes is the number the")
    print("  price is divided by, so a unit finally costs a share of the pack")
    print("  instead of the whole of it.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pharmacy", type=int, required=True,
                    help="which pharmacy's catalogue to read")
    ap.add_argument("--apply", action="store_true",
                    help="write the changes, after journalling the old values")
    ap.add_argument("--undo", metavar="FILE",
                    help="put back exactly what a journal recorded")
    args = ap.parse_args()

    db = SessionLocal()
    token = tenancy.set_current_pharmacy(args.pharmacy)
    try:
        if args.undo:
            journal = json.loads(pathlib.Path(args.undo).read_text("utf-8"))
            if journal.get("pharmacy") != args.pharmacy:
                print(f"That journal is for pharmacy {journal.get('pharmacy')}, "
                      f"not {args.pharmacy}. Refusing.")
                return 1
            put_back = 0
            for row in journal["changed"]:
                p = db.get(Product, row["product_id"])
                if p is None or p.pharmacy_id != args.pharmacy:
                    continue
                p.units_per_pack = row["was"]
                put_back += 1
            db.commit()
            print(f"  put {put_back} product(s) back to what they were")
            return 0

        rows, change, disagrees, already = look(db, args.pharmacy)
        show(change, disagrees, already, len(rows))
        if not change:
            return 0

        if not args.apply:
            print("\n  DRY RUN. Nothing was written. Add --apply to write it,")
            print("  and a journal will be left beside it so it can be undone.")
            return 0

        at = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = pathlib.Path(f"pack-sizes-{args.pharmacy}-{at}.json")
        journal = {
            "pharmacy": args.pharmacy,
            "at": datetime.now().isoformat(timespec="seconds"),
            "changed": [{"product_id": p.id, "name": p.name,
                         "pack_size": p.pack_size, "was": int(p.units_per_pack or 1),
                         "now": want} for p, want in change],
        }
        # Written BEFORE the commit. A journal that only exists once the write
        # succeeded is no use for the write that half succeeded.
        out.write_text(json.dumps(journal, indent=2), encoding="utf-8")
        for p, want in change:
            p.units_per_pack = want
        db.commit()
        print(f"\n  wrote {len(change)} product(s)")
        print(f"  journal: {out}")
        print(f"  to put it all back: python tools/pack_sizes.py "
              f"--pharmacy {args.pharmacy} --undo {out}")
        return 0
    finally:
        tenancy.reset_current_pharmacy(token)
        db.close()


if __name__ == "__main__":
    sys.exit(main())
