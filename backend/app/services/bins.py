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

from sqlalchemy import func
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
    label = func.trim(Product.bin_location)
    rows = (
        db.query(
            label.label("bin"),
            func.count(Product.id).label("lines"),
            func.coalesce(func.sum(Product.quantity_on_hand), 0).label("units"),
            # Per UNIT, because quantity_on_hand is units and cost_price is
            # what a PACK costs. Written the wrong way round here first and
            # caught with the rest of them. See services/valuation.
            func.coalesce(func.sum(valuation.cost_column()), 0).label("value"),
        )
        .filter(Product.active, label != "")
        .group_by(label)
        .all()
    )

    # Fold case in Python rather than in SQL. `lower()` in a GROUP BY throws
    # away the index and differs between SQLite and Postgres on accented text,
    # and there are tens of bins, not thousands.
    folded: dict[str, dict] = {}
    for row in rows:
        key = row.bin.upper()
        seen = folded.get(key)
        if seen is None:
            folded[key] = {
                "bin": row.bin,
                "lines": row.lines,
                "units": int(row.units or 0),
                "value": round(float(row.value or 0), 2),
                "spellings": [row.bin],
            }
            continue
        seen["lines"] += row.lines
        seen["units"] += int(row.units or 0)
        seen["value"] = round(seen["value"] + float(row.value or 0), 2)
        # Said out loud rather than quietly merged. Two spellings of one bin
        # means two shelf labels, or a typing mistake, and either is worth
        # seeing.
        seen["spellings"].append(row.bin)

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
    products = (
        db.query(Product)
        .filter(Product.active, func.lower(func.trim(Product.bin_location)) == wanted.lower())
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
        "value": valuation.at_cost(p),
        "bin": p.bin_location or "",
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
    return (
        db.query(Product)
        .filter(Product.active,
                Product.quantity_on_hand > 0,
                func.coalesce(func.trim(Product.bin_location), "") == "")
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
           source: str = "form", reason: str = "") -> BinMove | None:
    """Write the trail, and only when something actually moved.

    Returns None on a no-op. The product form sends every field on every save,
    so without this every unrelated edit would file a bin move from B12 to B12
    and the history would be unreadable within a week. This is the same rule
    price history follows and for the same reason.
    """
    old = (was or "").strip()
    new = (product.bin_location or "").strip()
    if old.upper() == new.upper():
        return None

    move = BinMove(
        product_id=product.id, was=old[:BIN_MAX], now=new[:BIN_MAX],
        source=source, reason=(reason or "")[:200],
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
