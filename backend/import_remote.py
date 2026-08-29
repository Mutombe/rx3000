"""Run a CareXpress importer against the hosted database.

The importers themselves are database-agnostic — they talk to whatever
`DATABASE_URL` names. Locally that is a SQLite file, deliberately: a mistake at
a keyboard should not be a mistake in production. Which is why the first run of
the CareXpress data went into the local file and was invisible on the hosted
site, and why this exists rather than an environment variable somebody has to
remember to set.

Same contract as `seed_remote.py`: the URL is read from `SEED_TARGET_URL` in
backend/.env before anything imports `app.config`, because that module reads
`DATABASE_URL` once at import and never looks again.

    python import_remote.py patients  "C:/path/patient detail.xlsx"
    python import_remote.py invoices  "C:/path/Invoice Report ….xlsx"
    python import_remote.py cashup    "C:/path/carexpress -teller ….xlsm"
    python import_remote.py status

Every importer is idempotent, so an interrupted run is resumed by running it
again — which matters, because this connection drops.
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

from sqlalchemy import func                                  # noqa: E402
from app.database import SessionLocal                        # noqa: E402
from app import models                                       # noqa: E402
from app.tenancy import unscoped                             # noqa: E402

WHAT = sys.argv[1]
host = os.environ["DATABASE_URL"].split("@")[-1].split("/")[0]
print(f"target: {host}\n")


def status() -> None:
    db = SessionLocal()
    with unscoped():
        cx = (db.query(models.Pharmacy)
              .filter(models.Pharmacy.name == "CareXpress Pharmacy").first())
        if cx is None:
            print("CareXpress Pharmacy does not exist on this database.")
            return
        S, P = models.Sale, models.Patient
        print(f"CareXpress (pharmacy {cx.id})")
        print(f"  branches  {db.query(models.Branch).filter(models.Branch.pharmacy_id == cx.id).count():,}")
        print(f"  products  {db.query(models.Product).filter(models.Product.pharmacy_id == cx.id).count():,}")
        print(f"  patients  {db.query(P).filter(P.pharmacy_id == cx.id).count():,}")
        print(f"  doctors   {db.query(models.Doctor).filter(models.Doctor.pharmacy_id == cx.id).count():,}")
        sales = db.query(S).filter(S.pharmacy_id == cx.id).count()
        value = db.query(func.sum(S.total)).filter(S.pharmacy_id == cx.id).scalar() or 0
        print(f"  sales     {sales:,} worth {value:,.2f}")
        print(f"  shifts    {db.query(models.Shift).filter(models.Shift.pharmacy_id == cx.id).count():,}")
    db.close()


if WHAT == "status":
    status()
    raise SystemExit(0)

if len(sys.argv) < 3:
    raise SystemExit(f"Give me the file to import for {WHAT!r}.")
path = sys.argv[2]

if WHAT == "patients":
    from app.importers import carexpress_patients as importer
elif WHAT == "invoices":
    from app.importers import carexpress_invoices as importer
elif WHAT == "cashup":
    from app.importers import carexpress_cashup as importer
else:
    raise SystemExit(f"Unknown importer {WHAT!r}. One of: patients, invoices, cashup.")

result = importer.run(path)
print(f"\n{WHAT}: {result}")
print("\nafter:")
status()
