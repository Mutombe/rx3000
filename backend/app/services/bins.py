"""Shelf locations as something a pharmacy can run, rather than a text box.

A bin was already on the product record and already came in on the client's
own export, sixty four of them. What did not exist was any way to work with
them: no list of bins, no way to see what is in one, no way to find the stock
that is not in any, and no record of a line moving from one shelf to another.
So the field was filled in by an import and then never looked at again, which
is the same as not having it.

WHAT A BIN IS FOR, IN A PHARMACY

Three jobs, and they are the three things this answers.

Picking. A script is dispensed by walking to the shelf. A list in bin order is
walked once; the same list in product order is walked three times, which is
why the bin report was written in the first place.

Counting. Nobody counts a whole dispensary. They count bin 14 on Tuesday and
bin 15 on Wednesday, and the count is only possible if the software can say
what bin 14 is supposed to hold.

Finding. The expensive failure is stock that exists, is paid for, is in date,
and cannot be found, so it is ordered again. Every line with quantity on hand
and no bin is that failure waiting, and `unbinned` is the list of them.

WHY BINS ARE NOT PER BRANCH

Because the data says they are not. `bin_location` is one column on the
product, the client's export has one BINLOCATION per line, and a pharmacy
running two shops with different shelf layouts would tell us so. Building a
per branch bin table now would be building for a problem nobody has reported,
and it would put a join in front of every picking list. If a branch ever needs
its own layout the table goes in then, and this module is where it lands.

WHY MATCHING IS CASE INSENSITIVE BUT STORAGE IS NOT

"a3", "A3" and "A3 " are one shelf to the person standing in front of it, and
three bins to a GROUP BY. So grouping folds case and trims, and the label
shown is the form the pharmacy actually typed. Rewriting their stored values
to a house style is a different decision, and not one to take silently on
sixteen thousand rows.
"""
from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import BIN_MAX, BinMove, Product, User
from . import valuation

#: A bin that sorts as a number sorts as a number. The client's bins are 0 to
#: 145, and "10" before "2" is the kind of small wrongness that makes a
#: pharmacist stop trusting a screen.
def sort_key(bin_name: str):
    raw = (bin_name or "").strip()
    head = ""
    for ch in raw:
        if ch.isdigit():
            head += ch
        else:
            break
    # (is-not-numeric, number, text) so numeric bins come first and in order,
    # and anything else sorts alphabetically after them.
    return (not head, int(head) if head else 0, raw.upper())


def normalise(raw: str) -> str:
    """What gets stored when a person types a bin.

    Trimmed and cut to the column's width, and nothing else. Not uppercased:
    a pharmacy that labels its shelves "a3" is not wrong, and a form that
    silently shouts back what somebody typed is a form they stop trusting.
    """
    return " ".join(str(raw or "").split())[:BIN_MAX]


def directory(db: Session, *, q: str = "") -> dict:
    """Every bin, with what it holds. The front page of the module.

    Counted in the database rather than by walking products in Python: a
    catalogue of sixteen thousand lines is the normal case here, not the large
    one, and pulling all of it back to count it is how a page that should take
    a moment takes ten seconds.
    """
    # WALKED IN PYTHON NOW, BECAUSE A LINE CAN BE IN THREE PLACES.
    #
    # This was a GROUP BY on the single bin column, which was right when there
    # was one. With three, the same product appears under each place it is
    # kept, and summing its stock under all three would report the shelf as
    # worth three times what it is — the exact error that took a whole commit
    # to get out of twenty two other places.
    #
    # So the money is attributed to the PRIMARY bin only, and the others
    # count the line as "also kept here" without its value. That keeps the
    # directory's total equal to the stock valuation, which is the property
    # that makes the figure trustworthy. A pharmacy that wants to know how
    # much is in each of three places would have to tell us how the stock is
    # split between them, and nothing in this system knows that.
    #
    # Sixteen thousand products in Python rather than in SQL is the cost, and
    # it is one pass over rows already being read for the unbinned count.
    products = (db.query(Product)
                .filter(Product.active)
                .options()
                .all())
    folded: dict[str, dict] = {}
    for product in products:
        places = product.bins()
        for index, place in enumerate(places):
            key = place.upper()
            row = folded.get(key)
            if row is None:
                row = folded[key] = {
                    "bin": place, "lines": 0, "units": 0, "value": 0.0,
                    "spellings": [place], "also": 0,
                }
            elif place not in row["spellings"]:
                # Said out loud rather than quietly merged. Two spellings of
                # one bin means two shelf labels, or a typing mistake.
                row["spellings"].append(place)
            row["lines"] += 1
            if index == 0:
                row["units"] += int(product.quantity_on_hand or 0)
                row["value"] = round(row["value"] + valuation.at_cost(product), 2)
            else:
                # Kept here as well. Counted as a line to walk and not as
                # stock to value, or the same units are worth money twice.
                row["also"] += 1

    out = list(folded.values())
    term = (q or "").strip().upper()
    if term:
        out = [b for b in out if term in b["bin"].upper()]
    out.sort(key=lambda b: sort_key(b["bin"]))

    loose = _unbinned_query(db)
    return {
        "bins": out,
        "lines": sum(b["lines"] for b in out),
        "units": sum(b["units"] for b in out),
        "value": round(sum(b["value"] for b in out), 2),
        # The number that makes the page worth opening. Not a footnote.
        "unbinned": loose.count(),
        "unbinned_units": int(
            loose.with_entities(
                func.coalesce(func.sum(Product.quantity_on_hand), 0)).scalar() or 0),
    }


def contents(db: Session, bin_name: str) -> dict:
    """What is on one shelf, in the order somebody would read the labels."""
    wanted = (bin_name or "").strip()
    folded = wanted.lower()
    # Any of the three, because a line kept in the back store as well is on
    # the back store's picking list too. Matched in SQL on all three columns
    # rather than walking the catalogue: this one IS a shelf walk and wants
    # to be quick.
    products = (
        db.query(Product)
        .filter(Product.active)
        .filter(or_(func.lower(func.trim(Product.bin_location)) == folded,
                    func.lower(func.trim(Product.bin_location_2)) == folded,
                    func.lower(func.trim(Product.bin_location_3)) == folded))
        .all()
    )
    products.sort(key=lambda p: (p.name or "").upper())

    lines = [{
        "product_id": p.id,
        "name": p.name,
        "stock_code": p.stock_code or "",
        "pack_size": p.pack_size or "",
        "on_hand": p.quantity_on_hand or 0,
        "reorder_level": p.reorder_level or 0,
        # Flagged here because a shelf walk is exactly when somebody can do
        # something about it: they are standing in front of the gap.
        "short": bool((p.quantity_on_hand or 0) <= (p.reorder_level or 0)),
        "empty": not (p.quantity_on_hand or 0),
        # Money belongs to the line's MAIN shelf, here as in the directory.
        #
        # Nothing in this system knows how the stock is split between the two
        # or three places a line is kept, so attributing it to one of them is
        # the only answer that does not invent a division. The primary shelf
        # carries it; a secondary shelf shows zero and says where the value
        # is counted, which keeps every bin total adding up to the stock
        # valuation. A shelf that claimed the whole line's worth would make
        # the directory sum to more than the pharmacy owns.
        "value": valuation.at_cost(p) if (p.bin_location or "").strip().lower() == folded else 0.0,
        "bin": p.bin_location or "",
        "primary": (p.bin_location or "").strip().lower() == folded,
        "also_in": [b for b in p.bins() if b.lower() != folded],
    } for p in products]

    return {
        "bin": wanted,
        "lines": lines,
        "units": sum(line["on_hand"] for line in lines),
        "value": round(sum(line["value"] for line in lines), 2),
        "short": sum(1 for line in lines if line["short"]),
    }


def _unbinned_query(db: Session):
    """Active stock with no shelf recorded.

    Restricted to lines that HAVE stock, deliberately. A discontinued line
    sitting at zero with no bin is not a problem anybody needs to solve, and
    putting four thousand of them on this list is how the list gets ignored.
    """
    blank = ""
    return (
        db.query(Product)
        .filter(Product.active,
                Product.quantity_on_hand > 0,
                func.coalesce(func.trim(Product.bin_location), blank) == blank,
                func.coalesce(func.trim(Product.bin_location_2), blank) == blank,
                func.coalesce(func.trim(Product.bin_location_3), blank) == blank)
    )


def unbinned(db: Session, limit: int = 300) -> list[dict]:
    """The stock that cannot be found, dearest first.

    Ordered by what it is worth rather than alphabetically, because this is a
    list somebody works down until they run out of afternoon, and the money
    should be at the top of it.
    """
    products = _unbinned_query(db).all()
    products.sort(key=lambda p: -valuation.at_cost(p))
    return [{
        "product_id": p.id,
        "name": p.name,
        "stock_code": p.stock_code or "",
        "on_hand": p.quantity_on_hand or 0,
        "value": valuation.at_cost(p),
    } for p in products[:limit]]


def record(db: Session, product: Product, was: str, *, user: User | None = None,
           source: str = "form", reason: str = "", slot: int = 1) -> BinMove | None:
    """Write the trail, and only when something actually moved.

    Returns None on a no-op. The product form sends every field on every save,
    so without this every unrelated edit would file a bin move from B12 to B12
    and the history would be unreadable within a week. This is the same rule
    price history follows and for the same reason.
    """
    old = (was or "").strip()
    field = "bin_location" if slot == 1 else f"bin_location_{slot}"
    new = (getattr(product, field, "") or "").strip()
    if old.upper() == new.upper():
        return None

    move = BinMove(
        product_id=product.id, was=old[:BIN_MAX], now=new[:BIN_MAX],
        source=source, reason=(reason or "")[:200], slot=slot,
        moved_by_id=getattr(user, "id", None),
    )
    db.add(move)
    return move


def history(db: Session, product_id: int, limit: int = 20) -> list[dict]:
    """Where this line has lived, newest first."""
    rows = (
        db.query(BinMove)
        .filter(BinMove.product_id == product_id)
        .order_by(BinMove.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{
        "id": row.id,
        "was": row.was or "",
        "now": row.now or "",
        "slot": row.slot or 1,
        # Said in words so the screen does not have to decide what an empty
        # "was" means every time it renders one.
        "says": (f"Put in bin {row.now}" if not row.was
                 else "Taken off the shelf" if not row.now
                 else f"Moved from bin {row.was} to bin {row.now}"),
        "source": row.source or "form",
        "reason": row.reason or "",
        "by": row.moved_by.username if row.moved_by else "",
        "at": row.created_at.isoformat() if row.created_at else "",
    } for row in rows]
