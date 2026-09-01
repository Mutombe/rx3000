"""Does the cash-up show every payment the register took?

The register and the cash-up used to hold separate ideas of what money can
arrive on, and the two did not match.

The register knew. A cashier taking a mobile payment picks EcoCash, Omari or
InnBucks on a screen built for exactly that, and the till wrote the wallet into
the front of the tender's free-text reference because there was no column for
it. The takings screen then read it back out by splitting on the first space.

The cash-up did not read it at all. It reconciled seven hard-coded families —
cash, card, mobile money, medical aid, vouchers, cheques, direct, and built
its lines from that constant. Two consequences, both bad:

  * EcoCash and InnBucks arrived as one undifferentiated "Mobile money" line.
    They are different businesses, settling into different accounts on
    different timetables, and the bank statements do not merge them either. A
    column that cannot be ticked off against a statement is not reconciliation.

  * Money taken on anything NOT in that list was added to the totals and then
    never printed, because the lines came from the list rather than from the
    movements. A till taking 30 on EcoCash, 20 on InnBucks and 45 cash on
    delivery reconciled to 50 and said nothing at all about the missing 45.

This builds a shift with money on several instruments — including one the
constant never had, and asserts that every cent shows up somewhere a person
can read. Nothing is committed.

    python qa/register-cashup-alignment.py
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
from app.models import (Patient, Sale, SaleTender, Shift,   # noqa: E402
                        User, Waybill)
from app.services import cashup, instruments               # noqa: E402

#: (instrument, method, currency, amount, what it is)
TAKINGS = [
    ("cash_usd",  "cash",         "USD",  120.00, "notes in the drawer"),
    ("ecocash",   "mobile_money", "USD",   30.00, "EcoCash, settles to the Econet wallet"),
    ("innbucks",  "mobile_money", "USD",   20.00, "InnBucks, a different business entirely"),
    ("swipe",     "card",         "USD",   64.50, "a card, settling through the acquiring bank"),
    ("cod",       "cash",         "USD",   45.00, "cash on delivery, on a motorbike"),
]


def main() -> int:
    tenancy.set_current_pharmacy(1)
    db = SessionLocal()
    tenancy.stamp(db)
    failures: list[str] = []

    try:
        instruments.ensure(db, 1)
        db.flush()

        user = db.query(User).first()
        patient = db.query(Patient).first()
        if not (user and patient):
            print("FAIL: this database has no user or patient to build a shift from")
            return 2

        shift = Shift(user_id=user.id, opened_at=datetime.utcnow(),
                      opening_float=0.0, till_no="QA", pharmacy_id=1)
        db.add(shift)
        db.flush()

        for i, (code, method, currency, amount, _why) in enumerate(TAKINGS):
            sale = Sale(sale_number=f"QA-ALIGN-{i}", patient_id=patient.id,
                        subtotal=amount, total=amount, payment_method=method,
                        amount_tendered=amount, status="paid",
                        created_at=datetime.utcnow(), shift_id=shift.id,
                        pharmacy_id=1)
            db.add(sale)
            db.flush()
            db.add(SaleTender(sale_id=sale.id, method=method,
                              currency_code=currency, amount=amount,
                              rate_used=1.0, amount_in_base=amount,
                              instrument=code, pharmacy_id=1))
        db.flush()

        took = round(sum(a for _, _, _, a, _ in TAKINGS), 2)
        print("  the register took:")
        for code, _m, _c, amount, why in TAKINGS:
            print(f"      {amount:>8.2f}  {code:<14} {why}")
        print(f"      {took:>8.2f}  in total\n")

        result = cashup.reconcile(db, shift, {})
        shown = [l for l in result["lines"] if l["system"]]
        print("  the cash-up shows:")
        for line in shown:
            flag = ""
            if line["is_delivery"]:
                flag = "   (on the road, not in this drawer)"
            elif line["unnamed"]:
                flag = "   (instrument not named)"
            print(f"      {line['system']:>8.2f}  {line['label']} "
                  f"[{line['currency']}]{flag}")
        print(f"      {result['total_system']:>8.2f}  in total\n")

        # 1. Nothing may go missing.
        if abs(result["total_system"] - took) > 0.005:
            failures.append(
                f"the cash-up totals {result['total_system']:.2f} against "
                f"{took:.2f} taken — {abs(took - result['total_system']):.2f} "
                f"is not on the sheet anywhere")

        # 2. Every instrument the register used must be its own line.
        labelled = {l["instrument"] for l in shown}
        for code, _m, _c, amount, _why in TAKINGS:
            if code not in labelled:
                failures.append(
                    f"{amount:.2f} was taken on {code} and there is no "
                    f"{code} line on the cash-up to tick off against its "
                    f"statement")

        # 3. Cash on delivery must not be counted against this drawer.
        expected_cash = result["expected_cash"]
        drawer_cash = round(sum(a for c, _m, _cur, a, _w in TAKINGS
                                if c == "cash_usd"), 2)
        if abs(expected_cash - drawer_cash) > 0.005:
            failures.append(
                f"the drawer is expected to hold {expected_cash:.2f} when only "
                f"{drawer_cash:.2f} was taken across the counter — cash on "
                f"delivery is on a motorbike and the cashier would be accused "
                f"of the difference")
        print(f"  ok   the drawer is expected to hold {expected_cash:.2f}, and "
              f"{result['on_the_road_total']:.2f} is shown separately as on "
              f"the road")

        # 4. The register's own list and the cash-up's must be the same list.
        register = {i.code for i in instruments.listing(db)}
        sheet = {l["instrument"] for l in result["lines"] if l["instrument"]}
        missing = register - sheet
        if missing:
            failures.append(
                f"the register offers {', '.join(sorted(missing))} and the "
                f"cash-up sheet has no column for them — a cashier can take "
                f"money on a tender they cannot then count")
        else:
            print(f"  ok   all {len(register)} instruments the register offers "
                  f"have a column on the sheet")
    finally:
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  FAIL {f}")
        return 1
    print("the cash-up shows every payment the register took, split the way "
          "the bank statements are")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
