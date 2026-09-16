"""Is every line of an export actually on the hosted database?

    python audit_remote.py "C:/path/STOCK.xlsx" --pharmacy 5

Same contract as `import_remote.py`: the target comes from `SEED_TARGET_URL` in
backend/.env, read before `app.config` is imported.

Exists because an importer's summary says what it MEANT to do. After a run that
was interrupted twice, killed once and re-run, the only answer worth having to
"is it all there" is one read back from the database, row by row, against the
file itself.

Checks each line for the four things that make a product usable: it exists, it
is still sold, it carries a price, and the shelf agrees with the count.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys


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
parser.add_argument("file")
parser.add_argument("--pharmacy", type=int, default=5)
parser.add_argument("--branch", type=int, default=None,
                    help="which shelf the count speaks for (default: matched from the file)")
parser.add_argument("--missing-out", help="write every line that is not there to this CSV")
args = parser.parse_args()

os.environ["DATABASE_URL"] = _target()

from sqlalchemy import func                                      # noqa: E402
from app.database import SessionLocal                            # noqa: E402
from app import models as m                                      # noqa: E402
from app.tenancy import unscoped                                 # noqa: E402
from app.importers.carexpress_stock_on_hand import read, whose_shelf, _num  # noqa: E402

heading, rows = read(args.file)
print(f"target: {os.environ['DATABASE_URL'].split('@')[-1].split('/')[0]}")
print(f"file:   {pathlib.Path(args.file).name}  ({len(rows):,} lines)")
for line in heading[:2]:
    print(f"        {line}")

db = SessionLocal()
with unscoped():
    branch = None
    if args.branch:
        branch = db.get(m.Branch, args.branch)
    else:
        branch = whose_shelf(db, heading, args.pharmacy)
    print(f"shelf:  {branch.name if branch else 'not matched'}\n")

    catalogue = {(p.stock_code or "").strip().upper(): p
                 for p in db.query(m.Product).filter(m.Product.pharmacy_id == args.pharmacy).all()
                 if (p.stock_code or "").strip()}

    held = {}
    if branch is not None:
        held = dict(db.query(m.StockBatch.product_id,
                             func.coalesce(func.sum(m.StockBatch.quantity_remaining), 0))
                    .filter(m.StockBatch.branch_id == branch.id)
                    .group_by(m.StockBatch.product_id).all())

    missing, unpriced, retired, short, blank, fine = [], [], [], [], [], 0
    for row in rows:
        code = row["StockCd"].strip().upper()
        name = " ".join((row["Descr"] or "").split())
        pack = max(1, int(_num(row["Pack Size"]) or 1))
        want = int(round(_num(row["StockOH"]) * pack))
        product = catalogue.get(code)
        if product is None:
            (blank if not name else missing).append((code, name, want))
            continue
        if not product.active:
            retired.append((code, product.name))
        if not (product.unit_price or 0) > 0:
            unpriced.append((code, product.name))
        if want > 0:
            there = int(held.get(product.id, 0) or 0)
            if there < want:
                short.append((code, product.name, want, there))
                continue
        fine += 1

    def block(title, items, fmt):
        print(f"{len(items):>6,}  {title}")
        for item in items[:8]:
            print(f"          {fmt(item)}")
        if len(items) > 8:
            print(f"          ... and {len(items) - 8:,} more")

    print(f"{len(rows):,} line(s) in the file")
    print(f"{len(rows) - len(missing) - len(blank):>6,}  are in the catalogue")
    block("are NOT in the catalogue", missing, lambda i: f"{i[0]:<12} {i[1][:46]}")
    block("carry a code and no description, so there is nothing to create", blank,
          lambda i: f"{i[0]:<12} (no description)")
    block("are in the catalogue but switched off", retired, lambda i: f"{i[0]:<12} {i[1][:46]}")
    block("have no price", unpriced, lambda i: f"{i[0]:<12} {i[1][:46]}")
    block("have less on this shelf than the count says", short,
          lambda i: f"{i[0]:<12} {i[1][:34]:<36} wants {i[2]:>8,}  has {i[3]:>8,}")
    print(f"\n{fine:,} of {len(rows):,} line(s) are present, priced and stocked as counted.")

    if args.missing_out and (missing or short):
        import csv
        with open(args.missing_out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["stock_code", "description", "problem", "wanted", "has"])
            for code, name, want in missing:
                writer.writerow([code, name, "not in the catalogue", want, 0])
            for code, name, want, there in short:
                writer.writerow([code, name, "short on this shelf", want, there])
        print(f"every problem line written to {args.missing_out}")
db.close()
