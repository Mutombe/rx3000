"""What is actually on the shelf, and what it sells for, from the pharmacy's own count.

    python -m app.importers.carexpress_stock_on_hand --file STOCK.xlsx --pharmacy 13
    python -m app.importers.carexpress_stock_on_hand --file … --pharmacy 13 --apply
    python -m app.importers.carexpress_stock_on_hand --file … --pharmacy 13 --apply --rename

WHAT THIS IS FOR

The catalogue knows sixteen thousand products and the shelf is empty: every one
of them reads zero on hand, so nothing can be dispensed without the counter
first being told there is none. This is the pharmacy's own twelve-month stock
usage export — the count they work from — and it carries four things worth
having: what is on the shelf, the pack size, what it retails, and what it cost.

A COUNT, NOT A DELIVERY

This is the distinction the whole file turns on. A delivery ADDS; a count SAYS
WHAT IS THERE. Run twice, a delivery doubles the shelf — and this will be run
again, because the pharmacy will send a fresher count next month. So it sets
rather than adds, and the movement it writes is an adjustment carrying the
difference, which is what a stock take does and what an auditor expects to see.

STOCK ON HAND IS IN PACKS, AND IT IS FRACTIONAL

`StockOH` counts packs, not units: ACRIPTEGA 30s at 0.667 is twenty tablets,
not two-thirds of a tablet, and ACETAZOLAMIDE 100s at 4.62 is four hundred and
sixty-two. The shelf here is counted in units, because a script quantity counts
tablets, so every figure is multiplied by its pack size. Reading these as units
would have put 4 tablets where there are 462, and 368 of the 1,936 lines are
fractional.

Five lines count below zero. There cannot be minus two tubes on a shelf; it
means their system is out by two. They are set to zero and listed.

UNDATED, BECAUSE NOBODY HAS READ THE PACKS

The count says how many, never which batch or when it expires. So this lands as
one `OPENING` batch per product with no expiry date, which is the shape the
first CareXpress import used and which the counter already knows how to handle:
dispensing refuses stock it cannot show is in date, says exactly that, and asks
for the date off the pack in hand — after which the batch is dated for good.
Inventing a plausible expiry here would be worse than leaving it blank, because
it would be a date nobody checked, printed on a label.

Stock received since, in real dated batches, is left alone. Only the opening
batch is counted up or down to make the total agree with the file.

A PRICE THE FILE CANNOT MEAN IS NOT IMPORTED

One line reads $3,145,500,000.00 against a cost of $14.60. That is a keying slip
in their system, and loading it would put it on a label and a claim. Anything
above a thousand times its own cost is refused and listed for somebody to fix at
source. The threshold is relative on purpose: a real oncology line here retails
at $2,500, and a fixed ceiling would eventually refuse one of those.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime

from ..database import SessionLocal
from ..models import Product, StockBatch, StockCategory, StockMovement
from ..tenancy import reset_current_pharmacy, set_current_pharmacy, unscoped

HEADER = ("StockCd", "Descr", "Pack Size", "StockOH", "TP0Retail", "TP0Cost")

#: A retail price this many times its own cost is a slipped decimal point, not
#: a margin. Relative rather than a fixed ceiling: see the module note.
ABSURD_MARKUP = 1000
#: For the rows that carry no cost to compare against.
ABSURD_PRICE = 100_000


@dataclass
class Summary:
    rows: int = 0
    matched: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    absurd: list = field(default_factory=list)
    negative: list = field(default_factory=list)
    renames: list = field(default_factory=list)


def _num(value) -> float:
    try:
        return float(str(value or "").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def _tidy(name: str) -> str:
    """Their spacing, not their wording. Leading spaces and doubled ones only."""
    return re.sub(r"\s+", " ", (name or "").strip())


def _same_product(a: str, b: str) -> bool:
    """Whether two names are the same thing written differently.

    Spacing and case are noise. Anything else is a different product wearing a
    reused stock code, and renaming carries the old one's sales history onto it.
    """
    squash = lambda s: re.sub(r"[^A-Z0-9]", "", (s or "").upper())
    return squash(a) == squash(b)


def read(path: str) -> tuple[list[str], list[dict]]:
    """The lines, and the few header rows that say whose shelf they are.

    The heading is not decoration. It reads "CARE XPRESS PHARMACY CHINAMANO",
    "52 J CHINAMANO AVE, HARARE" — the shop this count was taken in. A pharmacy
    with three branches has three different shelves, and stock put on the wrong
    one is worse than no stock at all: the counter is told it has something it
    cannot reach, and the branch that really holds it reads empty.
    """
    import openpyxl

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = book[book.sheetnames[0]]
    columns: list[str] | None = None
    heading: list[str] = []
    rows: list[dict] = []
    for raw in sheet.iter_rows(values_only=True):
        values = ["" if v is None else str(v).strip() for v in raw]
        if columns is None:
            if all(h in values for h in HEADER):
                columns = values
            elif values and values[0]:
                heading.append(values[0])
            continue
        if not any(values):
            continue
        row = dict(zip(columns, values))
        if row.get("StockCd"):
            rows.append(row)
    if columns is None:
        raise SystemExit(f"{path} has no {'/'.join(HEADER[:2])} header — is it the stock export?")
    return heading, rows


def whose_shelf(db, heading: list[str], pharmacy_id: int):
    """Which branch this count was taken in, from what the file calls itself.

    Matched on the branch's own name or address, squashed — "CAREXPRESS
    CHINAMANO" against "CARE XPRESS PHARMACY CHINAMANO", and "52 J Chinamano
    Ave, Harare" against the same in capitals. Returns None rather than guessing:
    a whole shop's stock on the wrong shelf is not a thing to get 80% right.
    """
    from ..models import Branch

    squash = lambda s: re.sub(r"[^A-Z0-9]", "", (s or "").upper())
    said = [squash(line) for line in heading if line]
    branches = db.query(Branch).filter(Branch.pharmacy_id == pharmacy_id).all()
    for branch in branches:
        for field_value in (branch.address, branch.name):
            key = squash(field_value)
            # Long enough to mean something: "MAIN" would match half a heading.
            if len(key) >= 8 and any(key in line or line in key for line in said):
                return branch
    return None


def plan(db, rows: list[dict], rename: bool = False) -> Summary:
    """What each line would do, decided before anything is written."""
    found = Summary(rows=len(rows))
    catalogue = {(p.stock_code or "").strip().upper(): p
                 for p in db.query(Product).all() if (p.stock_code or "").strip()}

    for row in rows:
        code = row["StockCd"].strip().upper()
        name = _tidy(row["Descr"])
        pack = max(1, int(_num(row["Pack Size"]) or 1))
        retail = _num(row["TP0Retail"])
        cost = _num(row["TP0Cost"])
        packs = _num(row["StockOH"])

        # A price the file cannot mean. Kept out of the catalogue and named, so
        # it is fixed where it is wrong rather than carried forward for ever.
        if (cost > 0 and retail > cost * ABSURD_MARKUP) or retail > ABSURD_PRICE:
            found.absurd.append((code, name, retail, cost))
            retail = None

        if packs < 0:
            found.negative.append((code, name, packs))
            packs = 0

        product = catalogue.get(code)
        if product is None:
            found.missing.append((code, name, pack, retail, cost, packs))
            continue

        # Packs to units, which is what the shelf is counted in.
        units = int(round(packs * pack))
        changes: dict = {}
        if name and not _same_product(product.name, name):
            found.renames.append((product, product.name, name))
            if rename:
                changes["name"] = name
        elif name and product.name != name:
            changes["name"] = name                      # spacing only
        if pack and (product.units_per_pack or 1) != pack:
            changes["units_per_pack"] = pack
        if retail is not None and abs((product.unit_price or 0) - retail) > 0.004:
            changes["unit_price"] = retail
        if cost and abs((product.cost_price or 0) - cost) > 0.004:
            changes["cost_price"] = cost
        found.matched.append((product, changes, units, packs, cost))
    return found


def apply(db, found: Summary, branch_id: int, pharmacy_id: int,
          user_id: int | None = None) -> dict:
    """Write it. Prices and names first, then the shelf.

    Every row created here is stamped with the pharmacy by hand. These jobs run
    inside `unscoped()` so they can see one tenant's catalogue from outside it,
    and unscoped means the stamping that normally happens on the way in is off
    too — so a batch written without this belongs to nobody, which is how 70,305
    sale lines once ended up in the wrong pharmacy.
    """
    done = {"priced": 0, "counted": 0, "up": 0, "down": 0, "batches": 0, "units": 0}

    # Every batch this pharmacy holds, in ONE query.
    #
    # This used to ask the database three questions per product — what stands
    # elsewhere, what is dated here, is there an opening batch — which is fine
    # against a SQLite file on the same disk and ruinous against a database in
    # another country: 1,569 products became about 4,700 round trips, and at a
    # tenth of a second each the run took long enough that the connection
    # dropped before it reached the single commit at the end. It then had
    # nothing to show for twenty minutes of work.
    wanted = {p.id for p, _c, _u, _pk, _co in found.matched}
    held: dict[int, list] = {}
    if wanted:
        for batch in (db.query(StockBatch)
                      .filter(StockBatch.product_id.in_(wanted)).all()):
            held.setdefault(batch.product_id, []).append(batch)

    for at, (product, changes, units, _packs, cost) in enumerate(found.matched, start=1):
        for field_name, value in changes.items():
            setattr(product, field_name, value)
        if changes:
            done["priced"] += 1

        # This count speaks for ONE shop, and `quantity_on_hand` is the whole
        # pharmacy's total. Stock standing in the other branches has to be added
        # back or the total contradicts the batches behind it — a product
        # reading 100 with 150 on the ledger promises the counter stock it
        # cannot allocate, and one reading 150 with 100 refuses stock it has.
        # CareXpress has three branches and 235 products stood in two of them.
        mine = held.get(product.id, ())
        elsewhere = sum(b.quantity_remaining or 0 for b in mine
                        if b.branch_id != branch_id)
        # Stock received since the count, in batches somebody dated, is real and
        # is left where it is. The opening batch is the part this file speaks
        # for, so it is the part that moves.
        dated = sum(b.quantity_remaining or 0 for b in mine
                    if b.branch_id == branch_id and b.expiry_date is not None)
        opening = next((b for b in mine if b.branch_id == branch_id
                        and b.batch_number == "OPENING"), None)
        was = (product.quantity_on_hand or 0)
        keep = max(0, units - dated)

        if keep == 0 and opening is None:
            # Nothing here and nothing recorded here. The product may still
            # stand in another branch, so its total is left exactly as it is.
            continue
        if opening is None:
            opening = StockBatch(product_id=product.id, branch_id=branch_id,
                                 batch_number="OPENING", expiry_date=None,
                                 pharmacy_id=pharmacy_id,
                                 reference="counted from the pharmacy's export")
            db.add(opening)
            done["batches"] += 1
        opening.quantity_received = keep
        opening.quantity_remaining = keep
        if cost:
            opening.unit_cost = round(cost / max(1, product.units_per_pack or 1), 4)
        product.quantity_on_hand = elsewhere + dated + keep

        delta = product.quantity_on_hand - was
        if delta:
            # An adjustment, not a receipt: this is a count being made to agree,
            # and a receipt would read as goods arriving that never did.
            db.add(StockMovement(
                product_id=product.id, movement_type="adjustment",
                quantity_delta=delta, balance_after=product.quantity_on_hand,
                user_id=user_id, branch_id=branch_id, pharmacy_id=pharmacy_id,
                reference="stock count",
                notes=f"Counted to {product.quantity_on_hand} from the pharmacy's "
                      f"own export ({'+' if delta > 0 else ''}{delta})"))
            done["up" if delta > 0 else "down"] += 1
        done["counted"] += 1
        done["units"] += product.quantity_on_hand

        # Committed in chunks, not once at the end. A count is idempotent — it
        # sets the shelf rather than adding to it — so a run cut off half way
        # can simply be run again, and what it had already written stands. With
        # one commit at the end, a dropped connection threw all of it away.
        if at % 250 == 0:
            db.commit()
            # Said out loud. A job that writes for minutes and prints nothing is
            # indistinguishable from one that has hung, and the honest answer to
            # "is it working" should not be "wait and see".
            print(f"    {at:,} of {len(found.matched):,} counted…", flush=True)
    db.commit()
    return done


def create_missing(db, found: Summary, pharmacy_id: int, branch_id: int,
                   user_id: int | None = None) -> int:
    """Write down the lines the catalogue has never heard of.

    They are on the shelf whether or not this system knows about them, and a
    product that cannot be found cannot be sold. Filed under the department the
    pharmacy's own export would have put them in — unknown, until somebody says
    otherwise — rather than guessed into the dispensary, because a guess there
    puts a toothpaste on a prescription.
    """
    made = 0
    for code, name, pack, retail, cost, packs in found.missing:
        if not name:
            continue                      # two rows carry a code and nothing else
        product = Product(
            stock_code=code, name=name, units_per_pack=pack,
            unit_price=retail or 0.0, cost_price=cost or 0.0,
            pharmacy_id=pharmacy_id,
        )
        db.add(product)
        db.flush()
        units = int(round(packs * pack))
        if units > 0:
            db.add(StockBatch(product_id=product.id, branch_id=branch_id,
                              batch_number="OPENING", expiry_date=None,
                              quantity_received=units, quantity_remaining=units,
                              unit_cost=round((cost or 0) / max(1, pack), 4),
                              pharmacy_id=pharmacy_id,
                              reference="counted from the pharmacy's export"))
            product.quantity_on_hand = units
            db.add(StockMovement(
                product_id=product.id, movement_type="adjustment",
                quantity_delta=units, balance_after=units, pharmacy_id=pharmacy_id,
                user_id=user_id, branch_id=branch_id, reference="stock count",
                notes="First counted from the pharmacy's own export"))
        made += 1
    db.commit()
    return made


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", required=True, help="the stock export (.xlsx)")
    parser.add_argument("--pharmacy", type=int, required=True)
    parser.add_argument("--branch", type=int, default=None,
                        help="which branch holds it (default: the pharmacy's own)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rename", action="store_true",
                        help="also apply substantive renames, not just spacing")
    parser.add_argument("--create-missing", action="store_true",
                        help="also write down products the catalogue has never heard of")
    args = parser.parse_args(argv)

    heading, rows = read(args.file)
    token = set_current_pharmacy(args.pharmacy)
    db = SessionLocal()
    try:
        # Never `default_branch`: these jobs run unscoped, so it would hand
        # back the first branch in the whole database — another pharmacy's.
        from ..models import Branch
        if args.branch:
            branch = db.get(Branch, args.branch)
            if branch is None or branch.pharmacy_id != args.pharmacy:
                raise SystemExit(f"Branch {args.branch} does not belong to pharmacy "
                                 f"{args.pharmacy}.")
        else:
            branch = whose_shelf(db, heading, args.pharmacy)
        if branch is None:
            named = "\n    ".join(
                f"{b.id:<4} {b.name} {b.address or ''}".rstrip()
                for b in db.query(Branch)
                .filter(Branch.pharmacy_id == args.pharmacy).all())
            called = "\n    ".join(heading[:3])
            raise SystemExit(
                "This count does not say which branch it was taken in, and guessing "
                "would put a whole shop's stock on the wrong shelf.\n"
                f"  The file calls itself:\n    {called}\n"
                f"  Pass --branch with one of:\n    {named}")
        branch_id = branch.id
        print(f"\n  {heading[0] if heading else args.file}")
        print(f"  counted in: {branch.name}"
              + (f" — {branch.address}" if branch.address else ""))
        found = plan(db, rows, rename=args.rename)

        on_shelf = [m for m in found.matched if m[2] > 0]
        print(f"\n{found.rows:,} line(s) counted, {len(found.matched):,} matched on stock code"
              + ("" if args.apply else " — nothing written, this is a preview"))
        print(f"{len(on_shelf):,} of them have stock on the shelf, "
              f"{sum(m[2] for m in on_shelf):,} units in all")
        print(f"{sum(1 for m in found.matched if m[1]):,} would have a price, "
              f"pack size or name corrected")
        print(f"{len(found.missing):,} are not in the catalogue at all"
              + (" — --create-missing writes them down" if not args.create_missing else ""))

        if found.absurd:
            print(f"\n  {len(found.absurd)} price(s) the file cannot mean, left alone:")
            for code, name, retail, cost in found.absurd:
                print(f"    {code:<12} {name[:34]:<36} {retail:>18,.2f} against a cost of {cost:,.2f}")
        if found.negative:
            print(f"\n  {len(found.negative)} line(s) count below zero, set to nothing:")
            for code, name, packs in found.negative:
                print(f"    {code:<12} {name[:34]:<36} {packs:,.2f} pack(s)")
        if found.renames:
            print(f"\n  {len(found.renames)} substantive rename(s)"
                  + (" — applied" if args.rename else " — left alone, --rename applies them") + ":")
            for _p, was, now in found.renames[:10]:
                print(f"    {was[:36]:<38} -> {now[:36]}")
            if len(found.renames) > 10:
                print(f"    … and {len(found.renames) - 10:,} more")

        biggest = sorted(on_shelf, key=lambda m: -m[2])[:8]
        if biggest:
            print("\n  the fullest shelves:")
            for product, _c, units, packs, _cost in biggest:
                print(f"    {product.name[:34]:<36} {units:>8,} units "
                      f"({packs:,.2f} pack(s) of {product.units_per_pack or 1})")

        if args.apply:
            done = apply(db, found, branch_id, args.pharmacy)
            print(f"\n  {branch.name}: {done['counted']:,} product(s) counted, "
                  f"{done['up']:,} up, {done['down']:,} down, "
                  f"{done['batches']:,} opening batch(es) written")
            print(f"  {done['priced']:,} product(s) corrected on price, pack size or spelling")
            if args.create_missing:
                print(f"  {create_missing(db, found, args.pharmacy, branch_id):,} "
                      "product(s) written down for the first time")
            print("\n  The opening stock carries no expiry date, because the count does not "
                  "say one.\n  The counter asks for it off the pack the first time each line "
                  "is dispensed.")
        return 0
    finally:
        db.close()
        reset_current_pharmacy(token)


if __name__ == "__main__":
    with unscoped():
        sys.exit(main())
