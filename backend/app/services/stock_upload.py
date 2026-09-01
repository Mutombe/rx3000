"""Load a catalogue, or a delivery, from a spreadsheet.

The price import that already exists only ever UPDATES: it matches a row to a
product and changes its prices. It cannot create one. So a pharmacy arriving
from another system, or opening a second shop, or taking on a new supplier's
range, had no way to get stock in except typing it product by product, and a
catalogue is four thousand lines.

This does the other half, and does it in the same two steps, for the same
reason: **nothing is written until somebody has read what would happen.** A
file that quietly created eight hundred duplicate products because its codes
were formatted differently is worse than one that was refused.

WHAT IT MATCHES ON

Stock code first, then NAPPI, then barcode, then name — in that order, and it
stops at the first that hits. Name is last because it is the only one that can
be wrong: two suppliers write the same medicine three ways, and matching on it
alone is how a catalogue grows a second copy of everything.

WHAT IT WILL NOT DO

  **It will not move stock without a batch.** A quantity on a row is an opening
  count, and an opening count with no batch behind it is a number that cannot be
  dispensed first-expiry-first or traced in a recall. Where a quantity is given
  without a batch number one is made from the reference, and the expiry is
  required — a medicine with no expiry date cannot be sold safely and should not
  be loadable.

  **It will not price at nothing.** A row with no cost and no selling price
  creates a product that a till will sell for nought. It is reported as a line
  to fix rather than loaded.

  **It will not overwrite a price with a blank.** An absent column means "not
  in this file", not "set it to zero". That distinction is the difference
  between a partial update and a wipe.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session

from ..models import Branch, Product, StockBatch, StockMovement, Supplier

#: What a column may be called. One canonical name per idea, so a file written
#: by a wholesaler, by an accountant or by the previous system all land.
ALIASES = {
    "stock_code": "code", "code": "code", "item_code": "code", "sku": "code",
    "product_code": "code", "itemcode": "code",
    "nappi": "nappi", "nappi_code": "nappi", "nappicode": "nappi",
    "barcode": "barcode", "ean": "barcode", "gtin": "barcode",
    "name": "name", "description": "name", "product": "name",
    "product_name": "name", "item_description": "name", "item": "name",
    "strength": "strength", "dosage_form": "form", "form": "form",
    "pack_size": "pack", "packsize": "pack", "pack": "pack",
    "cost": "cost", "cost_price": "cost", "trade_price": "cost",
    "nett": "cost", "net_price": "cost", "buying_price": "cost",
    "price": "price", "selling_price": "price", "retail": "price",
    "retail_price": "price", "sell": "price",
    "quantity": "quantity", "qty": "quantity", "on_hand": "quantity",
    "quantity_on_hand": "quantity", "stock": "quantity", "soh": "quantity",
    "batch": "batch", "batch_no": "batch", "batch_number": "batch",
    "lot": "batch", "lot_number": "batch",
    "expiry": "expiry", "expiry_date": "expiry", "expires": "expiry",
    "exp": "expiry", "expiry_dt": "expiry",
    "supplier": "supplier", "vendor": "supplier", "manufacturer": "maker",
    "schedule": "schedule", "sched": "schedule",
    "reorder_level": "reorder", "reorder": "reorder", "min_stock": "reorder",
    "vat": "vat", "vat_rate": "vat", "tax": "vat",
}

#: Anything above this is a typo, not a schedule. S0–S6 is the whole scale.
MAX_SCHEDULE = 6


@dataclass
class Line:
    row: int
    key: str = ""
    name: str = ""
    action: str = "skip"          # create | update | skip | refuse
    reason: str = ""
    product_id: int | None = None
    # What would change, old against new, so a preview is readable without
    # opening the product.
    changes: dict = field(default_factory=dict)
    quantity: int = 0
    batch: str = ""
    expiry: date | None = None


def _num(value) -> float | None:
    """A number, or None where the cell was empty.

    None and nought are different answers: an absent column means "not in this
    file", and treating it as zero turns a partial update into a wipe.
    """
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    text = re.sub(r"[^\d.\-]", "", text)
    if not text or text in ("-", ".", "-."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _when(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for shape in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%Y", "%Y/%m",
                  "%b %Y", "%d %b %Y", "%Y-%m"):
        try:
            when = datetime.strptime(text, shape)
        except ValueError:
            continue
        # A month with no day means the end of that month: a batch marked
        # "06/2027" is good until the last day of June, and reading it as the
        # first would write off a month of stock.
        if shape in ("%m/%Y", "%Y/%m", "%b %Y", "%Y-%m"):
            nxt = (when.replace(day=28) + __import__("datetime").timedelta(days=8))
            return (nxt.replace(day=1) - __import__("datetime").timedelta(days=1)).date()
        return when.date()
    return None


def read(text: str) -> tuple[list[dict], dict[str, str]]:
    """Rows and the columns that were understood."""
    text = text.strip()
    if not text:
        raise ValueError("The file is empty.")
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("The file has no header row, so no column can be read.")

    mapping: dict[str, str] = {}
    for column in reader.fieldnames:
        canonical = ALIASES.get((column or "").strip().lower().replace(" ", "_"))
        if canonical and canonical not in mapping:
            mapping[canonical] = column
    if not ({"code", "nappi", "barcode", "name"} & mapping.keys()):
        raise ValueError(
            "Nothing in this file identifies a product. It needs one of: "
            "stock code, NAPPI, barcode or name.")
    return list(reader), mapping


def plan(db: Session, rows: list[dict], mapping: dict[str, str], *,
         branch_id: int | None = None) -> list[Line]:
    """What each row would do, without doing any of it."""
    get = lambda row, key: (row.get(mapping.get(key, ""), "") or "")  # noqa: E731

    # The whole catalogue's keys, once. A lookup per row is a query per row,
    # and a catalogue file is thousands of rows.
    products = db.query(Product).all()
    by_code = {(p.stock_code or "").upper(): p for p in products if p.stock_code}
    by_nappi = {(p.nappi_code or "").upper(): p for p in products if p.nappi_code}
    by_barcode = {(p.barcode or "").upper(): p for p in products if p.barcode}
    by_name = {}
    for p in products:
        by_name.setdefault(f"{p.name} {p.strength or ''}".strip().upper(), p)

    # Batch numbers already on file, per product. A batch number is the one
    # natural key stock has: uploading the same delivery note twice should not
    # double the shelf, and on a busy morning somebody will.
    held = {(b.product_id, (b.batch_number or "").upper())
            for b in db.query(StockBatch.product_id, StockBatch.batch_number).all()}

    seen_keys: set[str] = set()
    out: list[Line] = []

    for index, row in enumerate(rows, start=2):
        code = str(get(row, "code")).strip()
        nappi = str(get(row, "nappi")).strip()
        barcode = str(get(row, "barcode")).strip()
        name = str(get(row, "name")).strip()
        strength = str(get(row, "strength")).strip()
        key = code or nappi or barcode or name
        line = Line(row=index, key=key, name=(f"{name} {strength}".strip() or key))

        if not key:
            line.action = "refuse"
            line.reason = "Nothing on this row identifies a product."
            out.append(line)
            continue

        # A file that names the same product twice is a file somebody exported
        # badly. Loading both makes a duplicate that nobody can tell apart.
        if key.upper() in seen_keys:
            line.action = "refuse"
            line.reason = "This row repeats a key already used earlier in the file."
            out.append(line)
            continue
        seen_keys.add(key.upper())

        # In order, stopping at the first that hits. Name is last because it is
        # the only one that can be wrong.
        found = (by_code.get(code.upper()) if code else None) \
            or (by_nappi.get(nappi.upper()) if nappi else None) \
            or (by_barcode.get(barcode.upper()) if barcode else None) \
            or (by_name.get(f"{name} {strength}".strip().upper()) if name else None)

        cost = _num(get(row, "cost"))
        price = _num(get(row, "price"))
        quantity = _num(get(row, "quantity"))
        batch = str(get(row, "batch")).strip()
        expiry = _when(get(row, "expiry"))
        schedule = _num(get(row, "schedule"))

        if schedule is not None and not (0 <= schedule <= MAX_SCHEDULE):
            line.action = "refuse"
            line.reason = (f"Schedule {schedule:g} is not a schedule. "
                           f"S0 to S{MAX_SCHEDULE} is the whole scale.")
            out.append(line)
            continue

        # Stock without an expiry cannot be dispensed first-expiry-first, and a
        # medicine with no expiry date on file cannot be sold safely.
        if quantity and quantity > 0 and expiry is None:
            line.action = "refuse"
            line.reason = ("A quantity was given with no expiry date. Stock "
                           "without one cannot be dispensed oldest-first or "
                           "found in a recall.")
            out.append(line)
            continue

        line.quantity = int(quantity or 0)
        line.batch = batch
        line.expiry = expiry

        if found is None:
            if not name:
                line.action = "refuse"
                line.reason = ("This is a new product and the row has no name "
                               "to give it.")
                out.append(line)
                continue
            if not price and not cost:
                line.action = "refuse"
                line.reason = ("A new product with no cost and no selling price "
                               "would be sold for nothing.")
                out.append(line)
                continue
            line.action = "create"
            line.changes = {
                "name": [None, name],
                "cost": [None, cost or 0.0],
                "price": [None, price or 0.0],
            }
            out.append(line)
            continue

        line.action = "update"
        line.product_id = found.id
        line.name = f"{found.name} {found.strength or ''}".strip()

        # Already received. The prices on the row are still applied — a
        # supplier may reissue a note with a corrected price, but the stock is
        # not counted in a second time.
        if line.quantity and batch and (found.id, batch.upper()) in held:
            line.quantity = 0
            line.reason = (f"Batch {batch} is already on this product, so the "
                           f"stock was not received again.")
        # Only what is actually in the file. An absent column is "not in this
        # file", never "set it to nought".
        for label, new, old in (("cost", cost, found.cost_price),
                                ("price", price, found.unit_price)):
            if new is not None and abs(new - (old or 0.0)) > 0.005:
                line.changes[label] = [round(old or 0.0, 2), round(new, 2)]
        if schedule is not None and int(schedule) != (found.schedule or 0):
            line.changes["schedule"] = [found.schedule or 0, int(schedule)]
        if not line.changes and not line.quantity:
            line.action = "skip"
            line.reason = "Nothing on this row differs from what is on file."
        out.append(line)

    return out


def apply(db: Session, rows: list[dict], mapping: dict[str, str], lines: list[Line],
          *, user_id: int | None, branch_id: int | None,
          reference: str = "") -> dict:
    """Write what the plan said, and nothing else."""
    get = lambda row, key: (row.get(mapping.get(key, ""), "") or "")  # noqa: E731
    by_row = {index: row for index, row in enumerate(rows, start=2)}

    if branch_id is None:
        branch = db.query(Branch).order_by(Branch.id).first()
        branch_id = branch.id if branch else None

    suppliers = {(s.name or "").upper(): s.id for s in db.query(Supplier).all()}
    created = updated = received = 0
    units = 0

    for line in lines:
        if line.action not in ("create", "update"):
            continue
        row = by_row.get(line.row)
        if row is None:
            continue

        if line.action == "create":
            supplier_name = str(get(row, "supplier")).strip()
            product = Product(
                name=str(get(row, "name")).strip()[:200],
                strength=str(get(row, "strength")).strip()[:60],
                dosage_form=str(get(row, "form")).strip()[:60],
                pack_size=str(get(row, "pack")).strip()[:40],
                stock_code=str(get(row, "code")).strip()[:40],
                nappi_code=str(get(row, "nappi")).strip()[:20],
                barcode=re.sub(r"\D", "", str(get(row, "barcode")))[:40],
                manufacturer=str(get(row, "maker")).strip()[:120],
                cost_price=_num(get(row, "cost")) or 0.0,
                unit_price=_num(get(row, "price")) or 0.0,
                vat_rate=(_num(get(row, "vat")) or 15.0) / 100
                if (_num(get(row, "vat")) or 0) > 1 else (_num(get(row, "vat")) or 0.15),
                schedule=int(_num(get(row, "schedule")) or 0),
                reorder_level=int(_num(get(row, "reorder")) or 10),
                supplier_id=suppliers.get(supplier_name.upper()),
                quantity_on_hand=0,
                active=True,
            )
            db.add(product)
            db.flush()
            line.product_id = product.id
            created += 1
        else:
            product = db.get(Product, line.product_id)
            if product is None:
                continue
            for label, (_old, new) in line.changes.items():
                if label == "cost":
                    product.cost_price = new
                elif label == "price":
                    product.unit_price = new
                elif label == "schedule":
                    product.schedule = new
            if line.changes:
                updated += 1

        # The stock itself, as a batch, so it can be dispensed oldest-first and
        # found again in a recall.
        if line.quantity > 0 and line.expiry:
            number = line.batch or f"{reference or 'UPLOAD'}-{line.row}"
            db.add(StockBatch(
                product_id=line.product_id,
                batch_number=number[:40],
                expiry_date=line.expiry,
                quantity_received=line.quantity,
                quantity_remaining=line.quantity,
                unit_cost=_num(get(row, "cost")) or (product.cost_price or 0.0),
                reference=reference or "Stock upload",
                branch_id=branch_id,
            ))
            product.quantity_on_hand = (product.quantity_on_hand or 0) + line.quantity
            db.add(StockMovement(
                product_id=line.product_id,
                movement_type="receive",
                quantity_delta=line.quantity,
                balance_after=product.quantity_on_hand,
                reference=reference or "Stock upload",
                notes=f"uploaded, batch {number} exp {line.expiry}",
                user_id=user_id,
                branch_id=branch_id,
            ))
            received += 1
            units += line.quantity

    db.commit()
    return {"created": created, "updated": updated,
            "batches": received, "units": units}
