"""Does the cash-up expect what is actually in the drawer?

A cashier is counted against one figure, and it has to be the money that
physically passed through their till. Everything else on a shift — the card
total, the claims, the takings report — can be argued about later. This one
either matches the notes in somebody's hand or it accuses them.

It did not match. The expected figure summed the full value of every sale on
the shift that was not void, which counts two kinds of money that never reached
the drawer:

  * a `pending` sale is a dispensing waiting to be paid for at the till. On a
    busy morning there are dozens, and the medicine goes out before the money
    comes in.
  * a `part_paid` sale took what the patient could find. Its total is wrong by
    exactly the balance still owing.

A shift with one pending sale of 80 and a part payment of 20 against 60
expected 190 from a drawer holding 70, and told the cashier they were 120
short. That is worse than no cash-up: real shortfalls disappear into the noise,
and staff learn to sign a variance off without reading it.

Nothing here goes through the API. The scenario is built directly and rolled
back, so it can be run against any database without leaving a shift behind.

    python qa/cashup-accuracy.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal                    # noqa: E402
from app import tenancy                                  # noqa: E402
from app.models import (Patient, Product, Sale, SaleItem,  # noqa: E402
                        SaleTender, Shift, User)
from app.services import cashup                          # noqa: E402

#: The scenario, and what each part actually puts in the drawer.
#: (status, sale total, tendered, what the till really took, why)
CASES = [
    ("paid", 50.0, 50.0, 50.0, "settled in full"),
    ("pending", 80.0, 0.0, 0.0,
     "dispensed and not paid for yet — the money is not here"),
    ("part_paid", 60.0, 20.0, 20.0,
     "the patient found 20 of 60; the balance is owed, not in the drawer"),
    ("void", 30.0, 30.0, 0.0, "reversed — it is not takings"),
]


def main() -> int:
    tenancy.set_current_pharmacy(1)
    db = SessionLocal()
    tenancy.stamp(db)
    failures = []

    try:
        user = db.query(User).first()
        patient = db.query(Patient).first()
        product = db.query(Product).filter(Product.unit_price > 0).first()
        if not (user and patient and product):
            print("FAIL: this database has no user, patient or priced product "
                  "to build a shift from")
            return 2

        shift = Shift(user_id=user.id, opened_at=datetime.utcnow(),
                      opening_float=100.0, till_no="QA", pharmacy_id=1)
        db.add(shift)
        db.flush()

        expected = 0.0
        for status, total, tendered, real, why in CASES:
            sale = Sale(sale_number=f"QA-CASHUP-{status}-{total}",
                        patient_id=patient.id, subtotal=total, total=total,
                        payment_method="cash", amount_tendered=tendered,
                        status=status, created_at=datetime.utcnow(),
                        shift_id=shift.id, pharmacy_id=1)
            db.add(sale)
            db.flush()
            db.add(SaleItem(sale_id=sale.id, product_id=product.id,
                            description=product.name, quantity=1,
                            unit_price=total, line_total=total, vat_rate=0.15))
            expected += real
        db.flush()

        totals = cashup.system_totals(db, shift)
        cash = round(totals.get("cash", 0.0), 2)

        print("  the drawer should hold, from these four sales:")
        for status, total, tendered, real, why in CASES:
            print(f"      {real:>8.2f}  a {status} sale of {total:.2f} — {why}")
        print(f"      {expected:>8.2f}  in total\n")

        ok = abs(cash - expected) < 0.005
        print(f"  {'ok  ' if ok else 'FAIL'} the cash-up expects {cash:.2f}")
        if not ok:
            failures.append(
                f"expected {expected:.2f}, the cash-up says {cash:.2f} — "
                f"{'over' if cash > expected else 'under'}stated by "
                f"{abs(cash - expected):.2f}")

        # And the same again where the money is recorded as tenders rather than
        # on the sale, since a till may send either.
        part = db.query(Sale).filter(
            Sale.sale_number == "QA-CASHUP-part_paid-60.0").first()
        db.add(SaleTender(sale_id=part.id, method="cash", currency_code="USD",
                          amount=20.0, rate_used=1.0, amount_in_base=20.0))
        db.flush()
        with_tenders = round(cashup.system_totals(db, shift).get("cash", 0.0), 2)
        # The part-paid sale now has a tender, so it is counted from that
        # instead — the figure must not move.
        ok2 = abs(with_tenders - expected) < 0.005
        print(f"  {'ok  ' if ok2 else 'FAIL'} and the same when the payment is "
              f"recorded as a tender: {with_tenders:.2f}")
        if not ok2:
            failures.append(
                f"a part payment counted differently depending on whether the "
                f"till sent a tender row: {with_tenders:.2f} against "
                f"{expected:.2f}")
    finally:
        # Nothing written. A QA script that leaves a shift on a real database
        # puts a fictional variance in front of a manager.
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("the cash-up expects what actually passed through the till")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
