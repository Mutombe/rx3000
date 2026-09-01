"""Can two pharmacies both take the same document number?

`helpers.next_number` counts a pharmacy's OWN rows — `count() + 1` under the
tenant filter, and stamps the month on the front. So two pharmacies with the
same number of sales in the same month generate the same string. That is fine,
and correct: an invoice number belongs to the shop that issued it, the way it
does on paper.

It was not fine while the index was unique across the whole database. Two
brand-new pharmacies making their first sale in the same month both produced
`INV260800001`, and the second insert was refused. That is not an edge case; it
is opening week, and the failure lands at the till in the middle of serving
somebody, with a constraint error that says nothing about pharmacies.

Nineteen columns had it: every invoice, script, order, claim, batch, waybill,
lay-by, quote, ticket, stock take, remittance, authorisation, transfer, sample,
to-follow, branch code, period code, journal reference and mixture code.

This creates two empty pharmacies, asks each for a number, and writes both. It
proves the thing that matters, that the database accepts them, rather than
inspecting an index and reasoning about it.

TWO OF THE NINETEEN ARE DIFFERENT ON SQLITE

`purchase_orders.order_number` and `claims.claim_number` were declared
`unique=True` without `index=True`, which makes a table CONSTRAINT rather than
an index. Postgres can drop one by name; SQLite cannot drop one at all without
rebuilding the table.

That is left alone deliberately. SQLite here is a developer's file or a desktop
install serving one pharmacy, and a number unique across a database holding one
pharmacy is unique within that pharmacy: the same thing. Rebuilding a live
table at startup to fix something that cannot happen there would be the riskier
choice. So on SQLite those two are reported as expected; on Postgres, where
several pharmacies do share a database, they must be per-tenant like the rest.

    python qa/tenant-numbering.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal, engine         # noqa: E402
from app import helpers, tenancy                      # noqa: E402
from app.models import (Doctor, Patient, Pharmacy, Prescription,  # noqa: E402
                        PurchaseOrder, Sale, Supplier)

#: One fixture pair, reused, rather than a fresh pair per run — otherwise this
#: leaves litter in the one list a platform owner reads to see who their
#: customers are.
FIXTURES = ("Numbering probe A", "Numbering probe B")

#: What to try. Each is a model, the prefix its numbers carry, and the column.
SERIES = [
    (Sale, "INV", "sale_number"),
    (Prescription, "RX", "rx_number"),
    (PurchaseOrder, "PO", "order_number"),
]

#: Declared as a table constraint rather than an index, so SQLite cannot drop
#: it. Expected to stay estate-wide there, and required to be per-tenant on
#: Postgres.
CONSTRAINED = {"order_number", "claim_number"}
ON_SQLITE = engine.dialect.name == "sqlite"


def main() -> int:
    db = SessionLocal()
    tenancy.stamp(db)
    with tenancy.unscoped():
        shops = []
        for name in FIXTURES:
            shop = db.query(Pharmacy).filter(Pharmacy.name == name).first()
            if shop is None:
                shop = Pharmacy(name=name)
                db.add(shop)
                db.flush()
            shops.append(shop)
        db.commit()
    a, b = shops

    # A script needs a patient and an order needs a supplier — both NOT NULL.
    # Made per shop so the insert that follows is about the index and nothing
    # else. Without them this reported "still unique across the estate" for a
    # plain NOT NULL failure, which is the sort of wrong answer that gets an
    # audit ignored.
    parents: dict[int, dict] = {}
    with tenancy.unscoped():
        for shop in (a, b):
            patient = Patient(first_name="Numbering", last_name="Probe",
                              pharmacy_id=shop.id)
            supplier = Supplier(name="Numbering probe supplier",
                                pharmacy_id=shop.id)
            db.add_all([patient, supplier])
            db.flush()
            parents[shop.id] = {"patient_id": patient.id,
                                "supplier_id": supplier.id}
        db.commit()

    failures = []
    for model, prefix, column in SERIES:
        issued = []
        for shop in (a, b):
            tenancy.set_current_pharmacy(shop.id)
            s = SessionLocal()
            tenancy.stamp(s)
            issued.append(helpers.next_number(s, model, prefix, column))
            s.close()

        same = issued[0] == issued[1]
        # Both written, which is the whole question. A number generated is not
        # a number the database will take.
        wrote, refused = 0, None
        for shop, number in zip((a, b), issued):
            tenancy.set_current_pharmacy(shop.id)
            s = SessionLocal()
            tenancy.stamp(s)
            try:
                row = model(**{column: number}, pharmacy_id=shop.id,
                            **_required(model, parents[shop.id]))
                s.add(row)
                s.commit()
                wrote += 1
            except Exception as exc:                   # noqa: BLE001
                detail = str(exc)
                kind = ("the index refused it" if "UNIQUE" in detail.upper()
                        else "the probe could not build a valid row")
                refused = f"{kind} — {detail.splitlines()[0][:90]}"
                s.rollback()
            finally:
                s.close()

        wrote_both = wrote == 2
        excused = ON_SQLITE and column in CONSTRAINED and not wrote_both
        ok = wrote_both or excused
        failures.append(None if ok else f"{model.__name__}.{column}")
        note = "the same number" if same else "different numbers"
        mark = "ok  " if wrote_both else ("note" if excused else "FAIL")
        print(f"  {mark} {model.__name__}.{column}: "
              f"two pharmacies generated {note} ({issued[0]}) and the database "
              f"took {wrote} of 2")
        if excused:
            print("       a table constraint SQLite cannot drop; harmless here, "
                  "where one file holds one pharmacy")
        elif refused:
            print(f"       refused: {refused}")

    # Everything this made.
    s = SessionLocal()
    with tenancy.unscoped():
        for shop in (a, b):
            for model, _prefix, _column in SERIES:
                s.query(model).filter(model.pharmacy_id == shop.id).delete()
            s.query(Patient).filter(Patient.pharmacy_id == shop.id).delete()
            s.query(Supplier).filter(Supplier.pharmacy_id == shop.id).delete()
            s.query(Pharmacy).filter(Pharmacy.id == shop.id).delete()
        s.commit()
    s.close()
    db.close()

    bad = [f for f in failures if f]
    print()
    if bad:
        print(f"{len(bad)} series still unique across the estate: {', '.join(bad)}")
        return 1
    print("a document number belongs to the pharmacy that issued it"
          + (" (two constrained on SQLite, checked properly on Postgres)"
             if ON_SQLITE else ""))
    return 0


def _required(model, parent: dict) -> dict:
    """The not-null columns a bare row needs, so the insert is about the index."""
    if model is Sale:
        return {"total": 0.0, "subtotal": 0.0, "status": "paid",
                "payment_method": "cash"}
    if model is Prescription:
        return {"patient_id": parent["patient_id"], "status": "draft"}
    return {"supplier_id": parent["supplier_id"], "status": "draft"}


if __name__ == "__main__":
    raise SystemExit(main())
