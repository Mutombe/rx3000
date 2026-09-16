"""Refresh the catalogue from the pharmacy's own stock totals export.

    python -m app.importers.carexpress_stock_totals --file "Stock totals.xlsx" --pharmacy 13
    python -m app.importers.carexpress_stock_totals --file … --pharmacy 13 --apply
    python -m app.importers.carexpress_stock_totals --file … --pharmacy 13 --apply --rename

WHAT THIS IS FOR

The catalogue was built from two files that each knew half of it: a stock report
whose description column came across empty, and nineteen months of invoices,
which know what a thing sold for and nothing else about it. The result was
sixteen thousand products of which ten thousand had no price, none had a NAPPI
code, none had a manufacturer, and every single one was schedule 0.

This reads the pharmacy's full export — the one with the descriptions in it —
and fills in what the pharmacy already knows:

    the name, the pack size, the department, the shelf location
    what it retails and costs, and the published SEP where there is one
    the barcode, and the AHFoZ/NAPPI code
    whether the shop still sells it at all

MATCHED ON THE STOCK CODE, WHICH IS THE PHARMACY'S OWN

Not on the name: the name is the thing being corrected. 15,936 of 16,019 lines
match straight across.

WHAT IT WILL NOT DO WITHOUT BEING ASKED

Rename a product to something unrecognisable. Stock codes get reused — code
10405 is an eye shadow here and tea tree oil in the newer export — and a rename
carries the sales history of the old product onto the new name. Differences of
spacing and case are applied silently because they are the same product; a
substantive rename is listed and left alone unless `--rename` says otherwise.

SCHEDULES ARE DELIBERATELY NOT TAKEN FROM THIS FILE

The export has a SCHEDULENO column and it cannot be trusted as a legal
schedule: its `3` contains an air freshener, and abacavir — an antiretroviral —
sits in its `0`. A schedule decides whether a pharmacist must hand something
over and whether it enters the controlled register, so it is set by
`classify_schedules`, which reads the medicine's name against the MCAZ
schedules, and never by a column that has a room spray in it.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field

from ..database import SessionLocal
from ..models import Product, StockCategory
from ..tenancy import set_current_pharmacy, unscoped

HEADERS = ("STOCKCD", "DESCR", "PACKSIZE", "PACKS", "STOCKOH", "DEPCD", "DEPDESCR",
           "BINLOCATION", "RETAIL", "COST", "AVGCOST", "Supplier", "Manufacturer",
           "TOTALCOST", "TOTALRETAIL", "TOTALAVGCOST", "STOCKID", "BARCODE", "NAPCD",
           "BLUEBOOKRETAIL", "SEP", "ITEMTAX", "SCHEDULENO", "GP", "ISACTIV", "ISDISCONT")

#: Departments whose lines the dispensary searches. Everything else in this
#: pharmacy's export is shop: cosmetics, sundries, the miscellaneous bucket.
DISPENSES = ("DISPENSARY", "OTC")


@dataclass
class Summary:
    rows: int = 0
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)
    changed: int = 0
    fields: dict[str, int] = field(default_factory=dict)
    renames: list[tuple[str, str, str]] = field(default_factory=list)
    retired: int = 0
    restored: int = 0
    departments: dict[str, int] = field(default_factory=dict)

    def note(self, name: str) -> None:
        self.fields[name] = self.fields.get(name, 0) + 1


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _number(value) -> float | None:
    text = _text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _squashed(name: str) -> str:
    """A name with its spacing and case taken out, for comparing two spellings."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def read(path: str) -> list[dict]:
    """The export's rows, as dictionaries, whatever row the header sits on."""
    import openpyxl

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = book[book.sheetnames[0]]
    rows: list[dict] = []
    columns: list[str] | None = None
    for raw in sheet.iter_rows(values_only=True):
        values = [_text(cell) for cell in raw]
        if columns is None:
            # The report carries the pharmacy's name, address and date above the
            # table, so the header is found rather than assumed.
            if "STOCKCD" in values and "DESCR" in values:
                columns = values
            continue
        if not any(values):
            continue
        row = dict(zip(columns, raw))
        if _text(row.get("STOCKCD")):
            rows.append(row)
    if columns is None:
        raise SystemExit(f"{path} has no STOCKCD/DESCR header row — is it the stock totals export?")
    return rows


def plan(db, rows: list[dict], *, rename: bool,
         retire: bool = False) -> tuple[Summary, list[tuple]]:
    """What would change, without changing anything."""
    summary = Summary(rows=len(rows))
    products = {(p.stock_code or "").strip().upper(): p
                for p in db.query(Product).all() if (p.stock_code or "").strip()}
    departments = {c.name.strip().upper(): c for c in db.query(StockCategory).all()}
    edits: list[tuple] = []

    for row in rows:
        code = _text(row.get("STOCKCD")).upper()
        product = products.get(code)
        if product is None:
            summary.unmatched.append(code)
            continue
        summary.matched += 1
        changes: dict = {}

        # Their export is full of double spaces — "BETADINE SOLUTION  750ML" —
        # which are nothing to do with the product and look like a fault on a
        # label. Taken tidied.
        descr = " ".join(_text(row.get("DESCR")).split())
        if descr and descr != (product.name or "").strip():
            if _squashed(descr) == _squashed(product.name or ""):
                changes["name"] = descr[:200]            # spacing only
            else:
                summary.renames.append((code, product.name or "", descr))
                if rename:
                    changes["name"] = descr[:200]

        pack = _number(row.get("PACKSIZE"))
        if pack and pack >= 1 and int(pack) != (product.units_per_pack or 1):
            changes["units_per_pack"] = int(pack)
            changes["pack_size"] = str(int(pack))

        retail = _number(row.get("RETAIL"))
        if retail is not None and retail > 0 and abs(retail - (product.unit_price or 0)) > 0.005:
            changes["unit_price"] = round(retail, 2)
        cost = _number(row.get("COST"))
        if cost is not None and cost > 0 and abs(cost - (product.cost_price or 0)) > 0.005:
            changes["cost_price"] = round(cost, 2)
        sep = _number(row.get("SEP"))
        if sep is not None and sep > 0 and abs(sep - (product.sep_price or 0)) > 0.005:
            changes["sep_price"] = round(sep, 2)

        for column, attribute, width in (("BARCODE", "barcode", 40),
                                         ("NAPCD", "nappi_code", 30),
                                         ("BINLOCATION", "bin_location", 20),
                                         ("Manufacturer", "manufacturer", 120)):
            value = _text(row.get(column))
            if value and value != (getattr(product, attribute) or "").strip():
                changes[attribute] = value[:width]

        department = _text(row.get("DEPDESCR")).upper()
        if department:
            existing = departments.get(department)
            if existing is None:
                changes["_new_department"] = department
                summary.departments[department] = summary.departments.get(department, 0) + 1
            elif product.category_id != existing.id:
                changes["category_id"] = existing.id

        # Still sold, or not. Their export knows: 14,092 of 16,037 lines are
        # already switched off in the system the pharmacy uses every day, and a
        # catalogue that offers all of them is one nobody can search.
        #
        # Opt-in, though, and that is the point of `retire`. `active` is not a
        # field like the others: false takes a medicine out of the dispensary
        # search AND the stock list, so a run that refreshed prices would also,
        # silently, have put 14,065 of 16,407 products beyond reach — 86% of the
        # catalogue, as a side effect of a price update nobody thought was
        # destructive. It is reported either way, and only written when asked.
        active = _text(row.get("ISACTIV")).upper() == "Y"
        discontinued = _text(row.get("ISDISCONT")).upper() == "Y"
        should_be = active and not discontinued
        if bool(product.active) != should_be:
            if retire:
                changes["active"] = should_be
            if should_be:
                summary.restored += 1
            else:
                summary.retired += 1

        if changes:
            summary.changed += 1
            for name in changes:
                summary.note(name.lstrip("_"))
            edits.append((product, changes))

    return summary, edits


def apply(db, edits: list[tuple]) -> int:
    """Write the planned changes, creating any department the file names."""
    departments = {c.name.strip().upper(): c for c in db.query(StockCategory).all()}
    written = 0
    for product, changes in edits:
        new_department = changes.pop("_new_department", None)
        if new_department:
            category = departments.get(new_department)
            if category is None:
                category = StockCategory(
                    # Spelt as the pharmacy spells it. Their departments are in
                    # capitals and the ones already here match; title-casing the
                    # new ones would make OTC read as Otc beside its own kind.
                    name=new_department, code="",
                    # The dispensary searches the dispensary and the OTC
                    # shelves; cosmetics and sundries are shop.
                    dispensable=any(new_department.startswith(d) for d in DISPENSES),
                    active=True, pharmacy_id=product.pharmacy_id)
                db.add(category)
                db.flush()
                departments[new_department] = category
            changes["category_id"] = category.id
        for attribute, value in changes.items():
            setattr(product, attribute, value)
        written += 1
    db.commit()
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="the stock totals export (.xlsx)")
    parser.add_argument("--pharmacy", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--rename", action="store_true",
                        help="also take names that differ by more than spacing")
    parser.add_argument("--retire-unsold", action="store_true",
                        help="also switch off the lines the export says are no longer "
                             "sold — this hides them from the dispensary and the stock "
                             "list, so it is never done as a side effect of a refresh")
    parser.add_argument("--report", help="write every planned change to this CSV")
    args = parser.parse_args(argv)

    rows = read(args.file)
    token = set_current_pharmacy(args.pharmacy)
    db = SessionLocal()
    try:
        summary, edits = plan(db, rows, rename=args.rename,
                              retire=args.retire_unsold)
        print(f"\n{summary.rows:,} rows read, {summary.matched:,} matched, "
              f"{len(summary.unmatched):,} not in the catalogue")
        print(f"{summary.changed:,} product(s) would change"
              + ("" if args.apply else " — nothing written, this is a preview"))
        for name, count in sorted(summary.fields.items(), key=lambda kv: -kv[1]):
            print(f"    {count:>6,}  {name}")
        if summary.retired or summary.restored:
            print(f"    {summary.retired:>6,}  no longer sold, per the export"
                  + ("  — RETIRED" if args.retire_unsold else
                     "  — left alone; --retire-unsold hides them"))
            print(f"    {summary.restored:>6,}  brought back")
        if summary.departments:
            print("  departments this file names that we do not have:")
            for name, count in summary.departments.items():
                print(f"    {count:>6,}  {name}")
        if summary.renames:
            print(f"\n  {len(summary.renames):,} name(s) differ by more than spacing"
                  + (" — taken, because --rename was given:" if args.rename
                     else " — left alone; pass --rename to take them:"))
            for code, was, now in summary.renames[:10]:
                print(f"    {code:<12} {was[:34]!r} -> {now[:34]!r}")

        if args.report:
            import csv
            with open(args.report, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["stock_code", "product", "field", "from", "to"])
                for product, changes in edits:
                    for name, value in changes.items():
                        writer.writerow([product.stock_code, product.name, name,
                                         getattr(product, name, ""), value])
            print(f"\n  every change written to {args.report}")

        if args.apply:
            written = apply(db, edits)
            print(f"\n  {written:,} product(s) updated.")
        return 0
    finally:
        db.close()
        from ..tenancy import reset_current_pharmacy
        reset_current_pharmacy(token)


if __name__ == "__main__":
    with unscoped():
        sys.exit(main())
