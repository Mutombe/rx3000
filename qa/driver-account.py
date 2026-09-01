"""Does money collected at a door ever reach the sale it was collected for?

A delivery is a sale that leaves the building before it is paid for. Between
the counter and the door the money belongs to nobody yet — the till has not
received it and the patient has not handed it over — and that gap is the
driver's account.

THE HOLE THIS WAS WRITTEN FOR

Every piece existed. A waybill carried `cod_amount`, `deliveries.collect`
recorded what was taken at the door, `deliveries.settle` stamped the round as
handed in and landed it in a shift. None of them settled the **sale**.

So a driver could collect fifty dollars, hand it to a cashier, and have it
counted into the drawer — and the sale stayed `pending` for ever. The patient
went on showing as owing fifty dollars they had already paid. The shop's
debtors carried money that was sitting in its own till. Two records of one
payment, disagreeing, with nothing to reconcile them by hand.

WHAT IS CHECKED

The whole round, in the order it happens, against a real driver and a real
sale, and rolled back:

  out on the road    — the money is owed by nobody; the medicine has not been
                       handed over, so it is "to collect", not "holding";
  paid at the door   — it becomes the driver's debt, and the sale is still
                       unpaid, because a motorbike is not a till;
  handed in          — the sale is settled, once, for the amount collected,
                       and the driver's balance goes to nothing.

And the two figures are checked for the thing that makes them useful: they are
never added together. A driver holding cash and a driver owed money by patients
are different facts, and one number covering both is the number somebody puts
in a cash-up.

    python qa/driver-account.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal                              # noqa: E402
from app import tenancy                                           # noqa: E402
from app.models import (Driver, Patient, Product, Sale, SaleItem,  # noqa: E402
                        Shift, User, Waybill)
from app.services import deliveries, driver_account                # noqa: E402


def main() -> int:
    tenancy.set_current_pharmacy(1)
    db = SessionLocal()
    tenancy.stamp(db)
    failures: list[str] = []

    def check(ok: bool, said: str, why: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {said}")
        if not ok:
            failures.append(why or said)

    try:
        user = db.query(User).first()
        driver = db.query(Driver).first()
        patient = db.query(Patient).first()
        product = db.query(Product).filter(Product.unit_price > 0).first()
        if not all((user, driver, patient, product)):
            print("FAIL: this database has no driver, patient or priced product")
            return 2

        driver.active = True
        total = round((product.unit_price or 0.0) * 2, 2)

        sale = Sale(sale_number="QA-DRIVER", patient_id=patient.id,
                    status="pending", subtotal=0.0, vat_amount=0.0, total=total)
        db.add(sale)
        db.flush()
        db.add(SaleItem(sale_id=sale.id, product_id=product.id, quantity=2,
                        unit_price=product.unit_price, line_total=total))
        waybill = Waybill(waybill_number="QA-DRIVER-WB", sale_id=sale.id,
                          patient_id=patient.id, recipient="Test",
                          address="1 Road", driver_profile_id=driver.id,
                          status="out", dispatched_at=datetime.utcnow(),
                          cod_amount=total, created_by_id=user.id)
        db.add(waybill)
        db.flush()
        print(f"  {driver.full_name} out with one delivery for {total:.2f}\n")

        # --- on the road -------------------------------------------------
        acc = driver_account.account(db, driver.id)
        check(acc["holding"] == 0 and acc["to_collect"] == total,
              f"on the road: holding {acc['holding']:.2f}, "
              f"to collect {acc['to_collect']:.2f}",
              "money still on the road is counted as the driver's debt — it is "
              "owed by nobody until the medicine changes hands")

        # --- paid at the door --------------------------------------------
        deliveries.collect(db, waybill, amount=total, instrument="cash")
        waybill.status = "delivered"
        waybill.delivered_at = datetime.utcnow()
        db.flush()

        acc = driver_account.account(db, driver.id)
        check(acc["holding"] == total and acc["to_collect"] == 0,
              f"paid at the door: the driver is holding {acc['holding']:.2f}",
              "cash taken at a door is not showing as the driver's to hand in")
        check(db.get(Sale, sale.id).status == "pending",
              "and the sale is still unpaid — a motorbike is not a till",
              "the sale was settled before anybody handed the money in, so the "
              "books show money the shop does not have yet")

        # --- handed in ----------------------------------------------------
        shift = db.query(Shift).filter(Shift.status == "open").first()
        if shift is None:
            shift = Shift(user_id=user.id, status="open",
                          opened_at=datetime.utcnow(), till_no="QA")
            db.add(shift)
            db.flush()

        result = deliveries.settle(db, [waybill], shift)
        db.flush()

        check(len(result["sales_settled"]) == 1
              and not result["could_not_settle"],
              f"handed in: {len(result['sales_settled'])} sale settled",
              "handing the round in settled no sale — the money reached the "
              "till and the patient still owes it")
        check(db.get(Sale, sale.id).status == "paid",
              "the sale is paid",
              f"the sale is {db.get(Sale, sale.id).status} after the money was "
              f"counted into a drawer")
        check(driver_account.paid_on(db, [sale.id]).get(sale.id) == total,
              f"and {total:.2f} is recorded against it as a tender",
              "the status changed without a tender behind it, so the cash-up "
              "will not see the money")

        acc = driver_account.account(db, driver.id)
        check(acc["holding"] == 0,
              "the driver's balance is clear",
              f"the driver still shows {acc['holding']:.2f} after handing in")

        # --- settling twice ------------------------------------------------
        try:
            driver_account.settle_sale(db, db.get(Sale, sale.id),
                                       amount=total, method="cash")
            check(False, "a second settlement is refused",
                  "the same collection can be applied twice, which pays a sale "
                  "into credit and puts money in the books that nobody handed "
                  "over")
        except ValueError:
            check(True, "settling the same sale twice is refused")
    finally:
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("money collected at a door reaches the sale it was collected for, "
          "and only when somebody hands it in")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
