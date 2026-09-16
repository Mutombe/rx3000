"""What the hosted database actually holds, after a job has run against it.

Same contract as `import_remote.py`: the target comes from `SEED_TARGET_URL` in
backend/.env, read before `app.config` is imported, because that module reads
`DATABASE_URL` once and never looks again.

Exists because a job's own summary is what it *meant* to do. After a long run
against a connection that drops, the only honest answer to "did that work" is a
count read back from the database.

    python check_remote.py            # CareXpress, pharmacy 5
    python check_remote.py 13
"""
from __future__ import annotations

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


os.environ["DATABASE_URL"] = _target()
PHARMACY = int(sys.argv[1]) if len(sys.argv) > 1 else 5

from sqlalchemy import func                                  # noqa: E402
from app.database import SessionLocal                        # noqa: E402
from app import models as m                                  # noqa: E402
from app.tenancy import unscoped                             # noqa: E402

print(f"target: {os.environ['DATABASE_URL'].split('@')[-1].split('/')[0]}")
print(f"pharmacy {PHARMACY}\n")

db = SessionLocal()
with unscoped():
    P = m.Product
    products = db.query(P).filter(P.pharmacy_id == PHARMACY)
    total = products.count()

    def count(where) -> str:
        n = products.filter(where).count()
        return f"{n:>7,}  ({100 * n / total:.0f}%)" if total else f"{n:>7,}"

    print(f"products            {total:>7,}")
    print(f"  still sold        {count(P.active.is_(True))}")
    print(f"  priced            {count(P.unit_price > 0)}")
    print(f"  with a cost       {count(P.cost_price > 0)}")
    print(f"  with a NAPPI      {count(P.nappi_code != '')}")
    print(f"  with a barcode    {count(P.barcode != '')}")
    print(f"  filed in a dept   {count(P.category_id.isnot(None))}")
    print(f"  on the shelf      {count(P.quantity_on_hand > 0)}")
    units = (db.query(func.sum(P.quantity_on_hand))
             .filter(P.pharmacy_id == PHARMACY).scalar() or 0)
    print(f"  units in all      {int(units):>7,}")

    D = m.Doctor
    doctors = db.query(D).filter(D.pharmacy_id == PHARMACY)
    print(f"\nprescribers         {doctors.count():>7,}")
    print(f"  not retired       {doctors.filter(D.active.is_(True)).count():>7,}")
    print(f"  with a practice no{doctors.filter(D.practice_number != '').count():>7,}")

    print(f"\ndepartments         {db.query(m.StockCategory)
                                   .filter(m.StockCategory.pharmacy_id == PHARMACY)
                                   .count():>7,}")
    print(f"  that dispense     {db.query(m.StockCategory)
                                   .filter(m.StockCategory.pharmacy_id == PHARMACY,
                                           m.StockCategory.dispensable.is_(True))
                                   .count():>7,}")
    try:
        codes = (db.query(m.SchemeProductCode)
                 .filter(m.SchemeProductCode.pharmacy_id == PHARMACY).count())
        print(f"\nscheme NAPPI codes  {codes:>7,}")
    except Exception as exc:                                  # noqa: BLE001
        print(f"\nscheme NAPPI codes  not on this database yet ({type(exc).__name__})")

    batches = (db.query(m.StockBatch)
               .filter(m.StockBatch.pharmacy_id == PHARMACY).count())
    undated = (db.query(m.StockBatch)
               .filter(m.StockBatch.pharmacy_id == PHARMACY,
                       m.StockBatch.expiry_date.is_(None)).count())
    print(f"stock batches       {batches:>7,}  of which undated {undated:,}")
db.close()
