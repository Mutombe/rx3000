"""Load CareXpress Pharmacy's own catalogue, as their system exports it.

Their stock totals report is a CSV of six thousand lines with the columns a
pharmacy actually keeps: their stock code, the description, pack size, what is
on the shelf, the department, the bin, retail and cost and average cost, the
supplier, the manufacturer, a barcode and the gross margin.

Three things about the file are worth knowing before reading the code, because
each of them broke a first attempt.

**The quoting is malformed.** Rows look like `"684","",28.00,...,684",,40.10` —
a field opens with a quote and closes without one. `csv.DictReader` silently
mis-aligns on those, and the first parse produced six thousand products with no
names at all, which looked like an empty column rather than a parsing fault.
`csv.reader` on the raw lines reads them correctly.

**Most lines have no stock.** Six thousand one hundred and forty-two products,
six hundred and fifty-nine with anything on the shelf. That is normal for a
pharmacy catalogue — the rest are lines they can order — and it means the
catalogue and the stock on hand are two separate imports, not one.

**The departments are the categories.** MISC, OTC, COSMETICS, DISPENSARY,
CONSIGNMENT STOCK. They arrive as free text repeated on every row and become
`StockCategory` rows, because "COSMETICS" typed six different ways is six
departments and no total is right.
"""
from __future__ import annotations

import csv
import logging
import pathlib
import re

from sqlalchemy.orm import Session

from ..models import (
    Branch, Pharmacy, Product, StockBatch, StockCategory, Supplier, User,
)
from .. import auth
from .. import tenancy

log = logging.getLogger("rx5000.import")

#: Their three shops, from their own documents: the stock totals report is
#: headed CENTRAL, the bin location report CHINAMANO, and LOBENGULA appears
#: throughout the second. The addresses and telephone are theirs where the
#: documents give them.
BRANCHES = [
    {"code": "CX-CEN", "name": "CareXpress Central", "city": "Harare",
     "address": "", "phone": ""},
    {"code": "CX-CHI", "name": "CareXpress Chinamano", "city": "Harare",
     "address": "52 J Chinamano Ave, Harare", "phone": "0732 307 400"},
    {"code": "CX-LOB", "name": "CareXpress Lobengula", "city": "Harare",
     "address": "", "phone": ""},
]

#: Which of the system's three hard categories a department belongs to.
#:
#: `Product.category` drives behaviour — airtime is kept out of stocktakes, only
#: medicines reach the dispensing routes — so it cannot simply be set to the
#: department name. Mapped explicitly rather than guessed, and anything
#: unrecognised falls to front_shop, which is the safe end: a front-shop item
#: mistakenly treated as a medicine would offer to be dispensed on a script.
ROUTE = {
    "DISPENSARY": "medicine",
    "OTC": "medicine",
    "CONSIGNMENT STOCK": "medicine",
    "COSMETICS": "front_shop",
    "MISC": "front_shop",
    "COS": "front_shop",
    "NEW DEPARTMENT": "front_shop",
}


def _num(value: str) -> float:
    try:
        return float((value or "").strip() or 0)
    except ValueError:
        return 0.0


def read_rows(path: pathlib.Path) -> list[dict]:
    """Parse the export, tolerating its unbalanced quotes."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    # Three lines of letterhead before the header row.
    start = 0
    for i, line in enumerate(lines[:10]):
        if line.startswith("Stock Cd,"):
            start = i + 1
            break
    out = []
    for row in csv.reader(lines[start:]):
        if len(row) < 15:
            continue
        out.append({
            "stock_code": (row[0] or "").strip().strip('"'),
            "name": " ".join((row[1] or "").split()),
            "pack_size": _num(row[2]),
            "on_hand": _num(row[3]),
            "dep_code": (row[4] or "").strip().strip('"'),
            "dep_name": " ".join((row[5] or "").split()).upper(),
            "bin": (row[6] or "").strip().strip('"'),
            "retail": _num(row[7]),
            "cost": _num(row[8]),
            "average_cost": _num(row[9]),
            "supplier": " ".join((row[10] or "").split()),
            "manufacturer": " ".join((row[11] or "").split()),
            "barcode": re.sub(r"\D", "", (row[13] or "")),
            "gp": _num(row[14]),
        })
    return out


def load(db: Session, path: pathlib.Path, *, pharmacy_name: str = "CareXpress Pharmacy",
         stock_branch_code: str = "CX-CEN",
         admin_username: str = "carexpress",
         admin_password: str = "carexpress123",
         admin_name: str = "CareXpress Administrator") -> dict[str, int]:
    """Create the pharmacy, its branches, its departments and its catalogue.

    Runs unscoped and sets the tenant itself, because it creates the tenant it
    then writes into — there is no pharmacy in force until this makes one.

    Idempotent by stock code within the pharmacy: running it again updates
    prices and stock rather than producing a second catalogue. A stock file is
    re-exported and re-imported routinely, and an importer that only works once
    is one somebody runs twice by accident.
    """
    made: dict[str, int] = {"categories": 0, "products": 0, "updated": 0,
                            "suppliers": 0, "batches": 0}

    with tenancy.unscoped():
        pharmacy = (db.query(Pharmacy)
                    .filter(Pharmacy.name == pharmacy_name).first())
        if pharmacy is None:
            pharmacy = Pharmacy(name=pharmacy_name, trading_name="CareXpress",
                                city="Harare", active=True)
            db.add(pharmacy)
            db.flush()
            made["pharmacy_created"] = 1

        have = {b.code for b in db.query(Branch)
                .filter(Branch.pharmacy_id == pharmacy.id).all()}
        for n, spec in enumerate(BRANCHES):
            if spec["code"] in have:
                continue
            db.add(Branch(pharmacy_id=pharmacy.id, is_default=(n == 0),
                          active=True, **spec))
            made["branches"] = made.get("branches", 0) + 1

        # A pharmacy nobody can sign into is a half-built tenant, which is the
        # same rule the pharmacies screen enforces when one is created by hand.
        # Importing a catalogue into a shop with no users would leave six
        # thousand products nobody can reach.
        if not db.query(User).filter(User.pharmacy_id == pharmacy.id).first():
            db.add(User(
                pharmacy_id=pharmacy.id,
                username=admin_username,
                full_name=admin_name,
                role="admin",
                password_hash=auth.hash_password(admin_password),
                active=True,
            ))
            made["admin_created"] = 1
        db.commit()

    # Everything below is this pharmacy's own, so it runs scoped like any
    # ordinary request would — which also means the rows are stamped for free.
    token = tenancy.set_current_pharmacy(pharmacy.id)
    try:
        tenancy.stamp(db)
        rows = read_rows(path)

        categories: dict[str, StockCategory] = {
            c.name: c for c in db.query(StockCategory).all()}
        for name in sorted({r["dep_name"] for r in rows if r["dep_name"]}):
            if name in categories:
                continue
            code = next((r["dep_code"] for r in rows if r["dep_name"] == name), "")
            cat = StockCategory(code=code, name=name, active=True)
            db.add(cat)
            categories[name] = cat
            made["categories"] += 1
        db.commit()

        suppliers: dict[str, Supplier] = {
            s.name.upper(): s for s in db.query(Supplier).all()}
        for name in sorted({r["supplier"] for r in rows if r["supplier"]}):
            if name.upper() in suppliers:
                continue
            sup = Supplier(name=name)
            db.add(sup)
            suppliers[name.upper()] = sup
            made["suppliers"] += 1
        db.commit()

        existing = {p.stock_code: p for p in db.query(Product).all() if p.stock_code}
        branch = (db.query(Branch)
                  .filter(Branch.code == stock_branch_code).first())

        for n, row in enumerate(rows):
            if not row["name"]:
                # A line with no description is one nobody can pick off a shelf.
                # Skipped and counted rather than imported as a blank product.
                made["unnamed_skipped"] = made.get("unnamed_skipped", 0) + 1
                continue
            product = existing.get(row["stock_code"])
            if product is None:
                product = Product(stock_code=row["stock_code"])
                db.add(product)
                existing[row["stock_code"]] = product
                made["products"] += 1
            else:
                made["updated"] += 1

            product.name = row["name"][:200]
            product.category_id = (categories[row["dep_name"]].id
                                   if row["dep_name"] in categories else None)
            product.category = ROUTE.get(row["dep_name"], "front_shop")
            product.pack_size = int(row["pack_size"]) or 1
            product.bin_location = row["bin"][:20]
            product.unit_price = round(row["retail"], 2)
            product.cost_price = round(row["cost"], 2)
            product.average_cost = round(row["average_cost"], 2)
            product.manufacturer = row["manufacturer"][:120]
            product.barcode = row["barcode"][:40]
            product.active = True
            if row["supplier"]:
                product.supplier_id = suppliers[row["supplier"].upper()].id
            if n % 500 == 0:
                db.flush()
        db.commit()

        # What is actually on the shelf, at the branch the report was run for.
        #
        # Written as a batch rather than only onto the product, because stock is
        # held per branch: the Central shelf says nothing about Chinamano's, and
        # a quantity on the product alone cannot tell them apart.
        if branch is not None:
            for row in rows:
                if row["on_hand"] <= 0 or not row["name"]:
                    continue
                product = existing.get(row["stock_code"])
                if product is None:
                    continue
                batch = (db.query(StockBatch)
                         .filter(StockBatch.product_id == product.id,
                                 StockBatch.branch_id == branch.id,
                                 StockBatch.batch_number == "OPENING").first())
                if batch is None:
                    batch = StockBatch(product_id=product.id, branch_id=branch.id,
                                       batch_number="OPENING",
                                       reference="imported stock on hand")
                    db.add(batch)
                    made["batches"] += 1
                batch.quantity_received = int(row["on_hand"])
                batch.quantity_remaining = int(row["on_hand"])
                batch.unit_cost = round(row["average_cost"] or row["cost"], 2)
                product.quantity_on_hand = int(row["on_hand"])
            db.commit()
    finally:
        tenancy.reset_current_pharmacy(token)

    made["pharmacy_id"] = pharmacy.id
    return made
