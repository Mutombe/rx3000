"""Look a medicine up on the hosted database, by name.

Same contract as `import_remote.py`: the target comes from `SEED_TARGET_URL` in
backend/.env, read before `app.config` is imported.

Exists because "why does X say zero in stock" is asked about a NAME, and the
answer is almost always about a stock CODE — the catalogue holds two spellings
of the same medicine under two codes, and the count only ever spoke for one.

    python find_remote.py amox
    python find_remote.py amox 5
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


if len(sys.argv) < 2:
    raise SystemExit(__doc__)

os.environ["DATABASE_URL"] = _target()
TERM = sys.argv[1]
PHARMACY = int(sys.argv[2]) if len(sys.argv) > 2 else 5

from app.database import SessionLocal                        # noqa: E402
from app import models as m                                  # noqa: E402
from app.tenancy import unscoped                             # noqa: E402

db = SessionLocal()
with unscoped():
    rows = (db.query(m.Product)
            .filter(m.Product.pharmacy_id == PHARMACY,
                    m.Product.name.ilike(f"%{TERM}%"))
            .order_by(m.Product.name).all())
    print(f"{len(rows)} product(s) matching {TERM!r} in pharmacy {PHARMACY}\n")
    print(f"{'stock_code':<14} {'name':<44} {'pack':>5} {'on hand':>9} {'price':>8}")
    print("-" * 85)
    for p in rows:
        print(f"{(p.stock_code or '-'):<14} {p.name[:43]:<44} "
              f"{p.units_per_pack or 1:>5} {p.quantity_on_hand or 0:>9,} "
              f"{p.unit_price or 0:>8,.2f}")

    ids = [p.id for p in rows]
    if ids:
        batches = (db.query(m.StockBatch)
                   .filter(m.StockBatch.product_id.in_(ids)).all())
        print(f"\n{len(batches)} batch(es) behind them")
        for b in batches[:12]:
            name = next((p.name for p in rows if p.id == b.product_id), "?")
            print(f"    {name[:36]:<38} {b.batch_number:<12} "
                  f"branch {b.branch_id}  {b.quantity_remaining:>7,} left  "
                  f"expiry {b.expiry_date or 'none'}")
db.close()
