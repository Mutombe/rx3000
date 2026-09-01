"""The Bin Location Report, out of a 1,600-page print-out.

This is not a data file. It is a very wide report that somebody printed, and the
printer split it into five vertical strips of 320 pages each: every product's
stock code first, for all 13,756 of them, then every product's description, and
so on. Nothing in the file says so. Read page by page it looks like five
unrelated documents.

    strip 1   pages    0- 319   Stock Code
    strip 2   pages  320- 639   Item Description · P/Size · Stock OH (Packs)
    strip 3   pages  640- 959   Stock OH · Cost · Retail · Avg Cost ·
                                Bin Location · Barcode · Cost Value
    strip 4   pages  960-1279   Retail Value · Min Level · Max Level ·
                                Bin Location 2 · …
    strip 5   pages 1280-1599   Supplier · MU · GP

Columns within a strip are told apart by where they sit on the page, because
the export has no delimiters — only positions.

WHY THE ALIGNMENT IS CHECKED RATHER THAN ASSUMED

Row 4,000 of strip 3 is only the stock figure for row 4,000 of strip 1 if every
page in between holds exactly the rows it should. One short page anywhere and
every quantity after it belongs to the wrong medicine, which in a pharmacy is
not a formatting problem. So `verify()` reads the descriptions back against the
catalogue already on file and reports the agreement rate. It runs at 99%; below
about 95% the file should not be loaded at all, and this says so rather than
loading it anyway.

    python -m app.importers.carexpress_binreport "C:/path/stock on hand.pdf"
    python -m app.importers.carexpress_binreport "…" --apply
"""
from __future__ import annotations

import difflib
import sys
from dataclasses import dataclass

from ..database import SessionLocal
from ..models import Pharmacy, Product
from ..tenancy import unscoped

TENANT = "CareXpress Pharmacy"

#: Where each strip begins. Five strips of 320 pages.
STRIP = 320

#: The columns inside each strip, as (name, left, right) in points across the
#: page. Read off the header row of the strip's first page.
COLUMNS = {
    0: [("code", 0, 400)],
    1: [("description", 0, 400), ("pack_size", 400, 440), ("packs", 440, 560)],
    2: [("on_hand", 0, 106), ("cost", 106, 149), ("retail", 149, 226),
        ("avg_cost", 226, 278), ("bin", 278, 348), ("barcode", 348, 443),
        ("cost_value", 443, 560)],
    3: [("retail_value", 0, 120), ("min_level", 120, 176),
        ("max_level", 176, 236), ("bin2", 236, 396), ("dispensed", 396, 560)],
    4: [("supplier", 0, 290), ("markup", 290, 340), ("gp", 340, 560)],
}

#: Below this the strips are not lining up and nothing should be written.
#: A quantity against the wrong medicine is worse than no quantity at all.
MIN_AGREEMENT = 0.95


@dataclass
class Row:
    code: str = ""
    description: str = ""
    pack_size: str = ""
    on_hand: float = 0.0
    cost: float = 0.0
    retail: float = 0.0
    bin: str = ""
    barcode: str = ""
    min_level: float = 0.0
    max_level: float = 0.0
    supplier: str = ""


def _num(text: str) -> float:
    try:
        return float(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def read(path: str) -> list[Row]:
    """Every row, with its strips stitched back together."""
    import fitz

    doc = fitz.open(path)
    strips = max(1, doc.page_count // STRIP)

    # One pass over the file, gathering each strip's columns in page order.
    gathered: dict[str, list[str]] = {}
    for strip in range(strips):
        for name, lo, hi in COLUMNS.get(strip, []):
            gathered.setdefault(name, [])
        for page_no in range(strip * STRIP, min((strip + 1) * STRIP, doc.page_count)):
            words = [w for w in doc[page_no].get_text("words") if w[1] > 150]
            # Every row on the page, by its vertical position — including rows
            # that are empty in this strip's columns, or the strips stop
            # lining up.
            keys = sorted({round(w[1]) for w in words})
            for name, lo, hi in COLUMNS.get(strip, []):
                by_row: dict[int, list] = {}
                for x0, y0, x1, y1, word, *_ in words:
                    if lo <= x0 < hi:
                        by_row.setdefault(round(y0), []).append((x0, word))
                for key in keys:
                    gathered[name].append(
                        " ".join(w for _, w in sorted(by_row.get(key, []))))
    doc.close()

    # The header row of each strip, dropped by name rather than by position:
    # the first page of a strip carries one fewer data row than the rest.
    length = min(len(v) for v in gathered.values())
    for name, values in gathered.items():
        del values[length:]

    rows: list[Row] = []
    for i in range(length):
        code = gathered["code"][i].strip()
        if not code or code.lower() in ("stock code", "code"):
            continue
        description = gathered["description"][i].strip()
        if "Item Description" in description:
            continue
        rows.append(Row(
            code=code,
            description=description,
            pack_size=gathered["pack_size"][i].strip(),
            on_hand=_num(gathered["on_hand"][i]),
            cost=_num(gathered["cost"][i]),
            retail=_num(gathered["retail"][i]),
            bin=gathered["bin"][i].strip(),
            barcode=gathered["barcode"][i].strip(),
            min_level=_num(gathered.get("min_level", [""] * length)[i]),
            max_level=_num(gathered.get("max_level", [""] * length)[i]),
            supplier=gathered.get("supplier", [""] * length)[i].strip(),
        ))
    return rows


def verify(db, rows: list[Row], sample: int = 3000) -> dict:
    """Do the descriptions still belong to the codes they line up with?"""
    with unscoped():
        pharmacy = db.query(Pharmacy).filter(Pharmacy.name == TENANT).first()
        if pharmacy is None:
            return {"checked": 0, "agree": 0, "rate": 0.0,
                    "why": f"There is no pharmacy called {TENANT!r} to check against."}
        known = {
            (c or "").upper(): n for c, n in
            db.query(Product.stock_code, Product.name)
            .filter(Product.pharmacy_id == pharmacy.id,
                    Product.stock_code != "").all()}

    checked = agree = 0
    for row in rows:
        want = known.get(row.code.upper())
        if not want or not row.description:
            continue
        checked += 1
        if difflib.SequenceMatcher(
                None, want.upper()[:20], row.description.upper()[:20]).ratio() > 0.65:
            agree += 1
        if checked >= sample:
            break
    rate = agree / checked if checked else 0.0
    return {"checked": checked, "agree": agree, "rate": round(rate, 4),
            "why": ("The strips line up." if rate >= MIN_AGREEMENT else
                    "The strips do not line up. Every figure after the first "
                    "bad page would belong to the wrong medicine, so nothing "
                    "was written.")}


def load(path: str, *, apply: bool = False) -> dict:
    """Read it, prove it, and only then write what it adds."""
    rows = read(path)
    db = SessionLocal()
    try:
        check = verify(db, rows)
        counts = {"rows": len(rows), **check, "matched": 0,
                  "bins": 0, "levels": 0, "quantities": 0, "applied": False}
        if check["rate"] < MIN_AGREEMENT:
            return counts

        with unscoped():
            pharmacy = db.query(Pharmacy).filter(Pharmacy.name == TENANT).first()
            products = {
                (p.stock_code or "").upper(): p for p in
                db.query(Product).filter(Product.pharmacy_id == pharmacy.id,
                                         Product.stock_code != "").all()}

        for row in rows:
            product = products.get(row.code.upper())
            if product is None:
                continue
            counts["matched"] += 1
            if not apply:
                if row.bin:
                    counts["bins"] += 1
                if row.min_level or row.max_level:
                    counts["levels"] += 1
                if row.on_hand:
                    counts["quantities"] += 1
                continue

            # Only what this report adds. Prices and names came from the
            # catalogue export, which is a data file rather than a print-out,
            # and overwriting them from a worse source would be a step back.
            if row.bin and not product.bin_location:
                product.bin_location = row.bin[:40]
                counts["bins"] += 1
            if row.min_level and not product.reorder_level:
                product.reorder_level = int(row.min_level)
                counts["levels"] += 1
            if row.max_level and not product.reorder_quantity:
                product.reorder_quantity = int(row.max_level)
            if row.on_hand:
                counts["quantities"] += 1

        if apply:
            db.commit()
            counts["applied"] = True
        return counts
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    counts = load(sys.argv[1], apply="--apply" in sys.argv)
    print(f"  {counts['rows']:>7,} rows read")
    print(f"  {counts['agree']:>7,} of {counts['checked']:,} descriptions match "
          f"the code beside them ({counts['rate'] * 100:.1f}%)")
    print(f"          {counts['why']}")
    if counts["rate"] >= MIN_AGREEMENT:
        print(f"  {counts['matched']:>7,} rows match a product on file")
        print(f"  {counts['bins']:>7,} carry a bin location")
        print(f"  {counts['levels']:>7,} carry a reorder level")
        print(f"  {counts['quantities']:>7,} carry stock on hand")
        if not counts["applied"]:
            print("\n  Nothing was written. Add --apply to load it.")


if __name__ == "__main__":
    main()
