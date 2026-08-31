"""Does cash on delivery reach the till, and only when it actually has?

A delivery is the one point in the day where the pharmacy's money is out of the
building and in one person's hands. Two ways to get that wrong, and the second
is the one that quietly destroys the cash-up:

  * **Counting it too early.** Cash on delivery is cash, and left as an
    ordinary cash tender it lands in the counter's drawer figure the moment the
    sale is rung up. At four o'clock the cashier is told they are a hundred and
    forty short by money on a motorbike on Samora Machel. People stop reading
    variances they know are wrong, and then they stop reading the real ones.

  * **Never counting it at all.** Money handed to a driver and not tracked is
    money the shop cannot ask for. "How much are my drivers holding" had no
    answer at all.

So this walks one delivery from raised to handed in and asserts the money is in
exactly one place at each step. Nothing is committed.

    python qa/delivery-money.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal                      # noqa: E402
from app import tenancy                                    # noqa: E402
from app.models import Driver, Patient, Shift, User, Waybill  # noqa: E402
from app.services import cashup, deliveries, instruments    # noqa: E402

FEE = 5.00
GOODS = 135.00


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
        instruments.ensure(db, 1)
        user = db.query(User).first()
        patient = db.query(Patient).first()
        if not (user and patient):
            print("FAIL: no user or patient to build a delivery from")
            return 2

        shift = Shift(user_id=user.id, opened_at=datetime.utcnow(),
                      opening_float=0.0, till_no="QA", status="open",
                      pharmacy_id=1)
        driver = Driver(full_name="QA Runner", phone="0779000000",
                        vehicle_type="motorbike", cod_limit=500.0,
                        active=True, pharmacy_id=1)
        db.add_all([shift, driver])
        db.flush()

        waybill = Waybill(
            waybill_number="QA-WB-1", patient_id=patient.id,
            recipient="QA", address="12 Samora Machel", status="out",
            driver_profile_id=driver.id, dispatched_at=datetime.utcnow(),
            delivery_fee=FEE, cod_amount=GOODS + FEE, pharmacy_id=1)
        db.add(waybill)
        db.flush()

        print(f"  a delivery goes out to collect {GOODS + FEE:.2f} "
              f"({GOODS:.2f} of medicine plus a {FEE:.2f} delivery fee)\n")

        # ---- out on the road ---------------------------------------------
        road = deliveries.on_the_road(db)
        check(abs(road["to_collect"] - (GOODS + FEE)) < 0.005,
              f"while it is out, {road['to_collect']:.2f} shows as still to "
              f"collect")
        check(abs(road["fees_out"] - FEE) < 0.005,
              f"and {road['fees_out']:.2f} of delivery fee is riding on it")

        counted = cashup.reconcile(db, shift, {})
        check(abs(counted["expected_cash"]) < 0.005,
              f"the counter's drawer is expected to hold "
              f"{counted['expected_cash']:.2f} — nothing, which is correct: "
              f"the money has not been collected yet",
              f"the drawer expects {counted['expected_cash']:.2f} before the "
              f"driver has collected anything")

        # ---- collected at the door ---------------------------------------
        deliveries.collect(db, waybill, amount=GOODS + FEE, instrument="cod")
        waybill.status = "delivered"
        waybill.received_by = "QA"
        waybill.delivered_at = datetime.utcnow()
        db.flush()

        row = deliveries.driver_row(db, driver)
        check(abs(row["cash_holding"] - (GOODS + FEE)) < 0.005,
              f"once collected, the driver is holding "
              f"{row['cash_holding']:.2f}")

        after = cashup.reconcile(db, shift, {})
        check(abs(after["expected_cash"]) < 0.005,
              f"and the counter's drawer STILL expects "
              f"{after['expected_cash']:.2f} — the money is on a motorbike, "
              f"not in the till",
              f"the drawer expects {after['expected_cash']:.2f} while the cash "
              f"is still with the driver — the cashier would be accused of it")

        # ---- over-collection is refused ----------------------------------
        try:
            deliveries.collect(db, waybill, amount=GOODS + FEE + 40,
                               instrument="cod")
            check(False, "collecting more than the delivery is for is refused",
                  "a driver could record collecting more than the delivery was "
                  "for, which is an overpayment with no sale behind it")
        except ValueError:
            check(True, "collecting more than the delivery is for is refused")

        # ---- handed in ----------------------------------------------------
        result = deliveries.settle(db, [waybill], shift, counted=GOODS + FEE)
        db.flush()
        check(abs(result["handed_in"] - (GOODS + FEE)) < 0.005,
              f"handed in: {result['handed_in']:.2f} against "
              f"{result['expected']:.2f} expected, variance "
              f"{result['variance']:.2f}")
        check(waybill.cod_shift_id == shift.id,
              f"and the delivery is stamped with the till that received it "
              f"(shift {waybill.cod_shift_id})",
              "the hand-in did not record which cash-up received the money")

        settled = deliveries.driver_row(db, driver)
        check(abs(settled["cash_holding"]) < 0.005,
              f"the driver is now holding {settled['cash_holding']:.2f}",
              f"the driver still shows {settled['cash_holding']:.2f} after "
              f"handing the round in")

        # ---- a short hand-in is recorded, not absorbed --------------------
        second = Waybill(waybill_number="QA-WB-2", patient_id=patient.id,
                         recipient="QA", address="4 Second Street",
                         status="delivered", driver_profile_id=driver.id,
                         cod_amount=60.0, cod_collected=60.0, pharmacy_id=1)
        db.add(second)
        db.flush()
        short = deliveries.settle(db, [second], shift, counted=52.0)
        check(abs(short["variance"] + 8.0) < 0.005,
              f"a driver handing in 52.00 against 60.00 collected is recorded "
              f"as {short['variance']:.2f}, not quietly accepted",
              f"a short hand-in recorded a variance of {short['variance']:.2f} "
              f"instead of -8.00 — the difference was thrown away")
    finally:
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("delivery money is in exactly one place at every step, and the "
          "counter is never accused of it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
