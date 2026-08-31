"""Can a customer bring one of four things back?

They could not. Both ways to reverse a sale — void, and the fiscal credit
note — take back the whole thing. So a customer returning one item meant the
till reversed all four and rang three up again, which changes the receipt
number, reverses the claim, earns the loyalty points twice and counts the day's
sales wrong in both directions. In practice it was done on paper and the stock
drifted, which is exactly the drift `/stock/reconcile` reports and nobody could
account for.

It matters more here than in most shops. Dispensed medicine largely cannot come
back, but this catalogue is mostly front shop — cosmetics, toiletries, baby,
surgical, gifts — where returns are ordinary.

The cases below are the ones a till actually sees, including the two it must
refuse: a controlled medicine cannot go back on the shelf, and a whole sale
coming back is a reversal with its own route.

Built directly and rolled back.

    python qa/part-return.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal                       # noqa: E402
from app import tenancy                                     # noqa: E402
from app.models import (Patient, Product, Sale, SaleItem,    # noqa: E402
                        StockBatch, User)
from app.services import returns                            # noqa: E402


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
        patient = db.query(Patient).first()
        user = db.query(User).first()
        goods = (db.query(Product)
                 .filter(Product.unit_price > 0, Product.schedule == 0)
                 .first())
        controlled = (db.query(Product)
                      .filter(Product.unit_price > 0, Product.schedule >= 5)
                      .first())
        if not (patient and user and goods):
            print("FAIL: no patient, user or priced product to build a sale")
            return 2

        # A four-line sale, the ordinary shape of a front-shop basket.
        sale = Sale(sale_number="QA-RET-1", patient_id=patient.id,
                    subtotal=100.0, vat_amount=15.0, total=115.0,
                    payment_method="cash", amount_tendered=115.0,
                    status="paid", created_at=datetime.utcnow(), pharmacy_id=1)
        db.add(sale)
        db.flush()
        items = []
        for n, qty, price in ((1, 3, 30.0), (2, 1, 25.0), (3, 2, 40.0)):
            item = SaleItem(sale_id=sale.id, product_id=goods.id,
                            description=f"{goods.name} line {n}", quantity=qty,
                            unit_price=price, line_total=price * qty,
                            vat_rate=0.15, pharmacy_id=1)
            db.add(item)
            items.append(item)
        db.flush()

        before = goods.quantity_on_hand or 0
        print(f"  a sale of three lines, {sale.total:.2f}; "
              f"{goods.name} shows {before} on hand\n")

        # ---- one of three, part quantity ---------------------------------
        preview = returns.plan(db, sale, [{"sale_item_id": items[0].id,
                                           "quantity": 2}])
        check(abs(preview["refund"] - 60.0) < 0.005,
              f"returning 2 of 3 at 30.00 refunds {preview['refund']:.2f}",
              f"the refund came to {preview['refund']:.2f}, not 60.00 — a part "
              f"line must be valued at what was charged, not today's price")
        check(not preview["is_whole_sale"],
              "and it is not treated as a whole-sale reversal")

        result = returns.apply(db, sale, [{"sale_item_id": items[0].id,
                                           "quantity": 2}], user_id=user.id)
        db.flush()
        check(abs(result["sale_total_now"] - 55.0) < 0.005,
              f"the sale is now {result['sale_total_now']:.2f}, down from 115.00",
              f"the sale total is {result['sale_total_now']:.2f} — the return "
              f"did not come off it correctly")
        check((goods.quantity_on_hand or 0) == before + 2,
              f"2 units went back on the shelf ({goods.quantity_on_hand})",
              "the stock did not come back, which is the drift that made "
              "people do this on paper")
        check(sale.status == "paid",
              "and the sale is still paid — it was not wholly reversed")

        # ---- the same line cannot come back twice -------------------------
        second = returns.plan(db, sale, [{"sale_item_id": items[0].id,
                                          "quantity": 2}])
        check(bool(second["refused"]) and not second["lines"],
              "a second return of the same line is refused — only 1 is left",
              "a line could be returned more times than it was sold, which is "
              "a refund the shop pays out of nothing")

        # ---- VAT moves with the money ------------------------------------
        check(sale.vat_amount < 15.0,
              f"VAT came down with the refund ({sale.vat_amount:.2f})",
              "VAT did not move, so the sale's own arithmetic no longer adds "
              "up and every report drawn from it inherits that")

        # ---- a controlled medicine is not restocked -----------------------
        if controlled is not None:
            rx_sale = Sale(sale_number="QA-RET-2", patient_id=patient.id,
                           subtotal=50.0, total=50.0, payment_method="cash",
                           status="paid", created_at=datetime.utcnow(),
                           pharmacy_id=1)
            db.add(rx_sale)
            db.flush()
            rx_item = SaleItem(sale_id=rx_sale.id, product_id=controlled.id,
                               description=controlled.name, quantity=1,
                               unit_price=50.0, line_total=50.0,
                               vat_rate=0.15, pharmacy_id=1)
            filler = SaleItem(sale_id=rx_sale.id, product_id=goods.id,
                              description="something else", quantity=1,
                              unit_price=10.0, line_total=10.0,
                              vat_rate=0.15, pharmacy_id=1)
            db.add_all([rx_item, filler])
            db.flush()
            plan = returns.plan(db, rx_sale,
                                [{"sale_item_id": rx_item.id, "quantity": 1}])
            row = plan["lines"][0]
            check(not row["restock"],
                  f"a schedule {row['schedule']} medicine is not put back on "
                  f"the shelf",
                  "a controlled medicine would be returned to saleable stock, "
                  "which is worse than not supporting returns at all")
            check("destruction" in row["why_not"].lower(),
                  "and the screen is told why, and what happens instead")

            held = controlled.quantity_on_hand or 0
            returns.apply(db, rx_sale,
                          [{"sale_item_id": rx_item.id, "quantity": 1}],
                          user_id=user.id)
            db.flush()
            check((controlled.quantity_on_hand or 0) == held,
                  "after the return it is still not saleable stock",
                  f"saleable stock moved from {held} to "
                  f"{controlled.quantity_on_hand} on a controlled return")
        else:
            print("  ––   no scheduled product stocked here; "
                  "the controlled case was not run")

        # ---- everything back is a reversal, not a return ------------------
        whole = Sale(sale_number="QA-RET-3", patient_id=patient.id,
                     subtotal=20.0, total=20.0, payment_method="cash",
                     status="paid", created_at=datetime.utcnow(), pharmacy_id=1)
        db.add(whole)
        db.flush()
        only = SaleItem(sale_id=whole.id, product_id=goods.id,
                        description=goods.name, quantity=1, unit_price=20.0,
                        line_total=20.0, vat_rate=0.15, pharmacy_id=1)
        db.add(only)
        db.flush()
        p = returns.plan(db, whole, [{"sale_item_id": only.id, "quantity": 1}])
        check(p["is_whole_sale"],
              "a sale with everything coming back is recognised as a full "
              "reversal, which has its own route",
              "a whole-sale return would go through the line-by-line path, "
              "which does not reverse the claim or the loyalty points")
    finally:
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("one line of a sale can come back without reversing the other three")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
