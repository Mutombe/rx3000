"""One CareXpress teller cash-up, and what it says about how they take money.

A single shift — Chinamano, 27 August 2026, 8am to 5pm — so the value is not
the figures. It is the shape of the sheet, which is the pharmacy's own
description of its counter:

    USD ($)   EcoCash USD   Swipe USD   Swipe ZWG   EcoCash ZWG

Five tenders across two currencies, counted separately, reconciled to one USD
equivalent. That is exactly what the split-tender work was built for, and it is
worth having one real shift in the system that proves the model holds against
the sheet they actually fill in rather than against an invented one.

The expenses are the other half. A teller pays for a taxi and a nail cutter out
of the drawer during the day, and a cash-up that ignores petty cash reports a
variance that is not one — the drawer is short by exactly what was spent out of
it, and the teller gets asked about money that is sitting in a receipt.

    python -m app.importers.carexpress_cashup "C:/path/carexpress -teller ….xlsm"
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

from ..database import SessionLocal
from ..models import Branch, PettyCash, Pharmacy, Shift, User
from ..tenancy import unscoped

TENANT = "CareXpress Pharmacy"

#: Where each tender is written on the sheet, by column.
TENDERS = [
    (2, "cash", "USD"), (3, "mobile_money", "USD"), (4, "card", "USD"),
    (5, "card", "ZWG"), (6, "mobile_money", "ZWG"),
]


def _num(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _text(v) -> str:
    return str(v).strip() if v is not None else ""


def run(path: str) -> dict:
    import openpyxl

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = book.worksheets[0]
    grid = [list(r) for r in sheet.iter_rows(max_row=45, values_only=True)]
    book.close()

    def cell(row, col):
        try:
            return grid[row - 1][col]
        except IndexError:
            return None

    branch_name = _text(cell(8, 2))
    when = cell(8, 6)
    if not isinstance(when, datetime):
        when = datetime.utcnow()
    teller = _text(cell(9, 2)) or "teller"
    shift_time = _text(cell(9, 6))
    supervisor = _text(cell(10, 6))

    # Row 15 is the day's takings, by tender.
    takings = []
    for col, method, currency in TENDERS:
        amount = _num(cell(15, col))
        if amount:
            takings.append({"method": method, "currency_code": currency,
                            "amount": amount})

    opening = _num(cell(14, 2))
    counted = _num(cell(31, 2))
    expected = _num(cell(30, 2))

    # Rows 21 onwards, until the total: what was spent out of the drawer.
    expenses = []
    for row in range(21, 27):
        # The expense block puts the description where the tender block puts
        # its first figure — one column to the left of everything above it.
        what = _text(cell(row, 1))
        amount = _num(cell(row, 2))
        if what and amount and not what.upper().startswith("TOTAL"):
            expenses.append({"what": what.title(), "amount": amount})

    db = SessionLocal()
    with unscoped():
        pharmacy = db.query(Pharmacy).filter(Pharmacy.name == TENANT).first()
        if pharmacy is None:
            raise SystemExit(f"No tenant named {TENANT!r}. Nothing was written.")
        branch = (db.query(Branch)
                  .filter(Branch.pharmacy_id == pharmacy.id,
                          Branch.name.ilike(f"%{branch_name}%")).first()
                  or db.query(Branch)
                  .filter(Branch.pharmacy_id == pharmacy.id).first())

        # The teller as a user, so the shift belongs to somebody. Named as the
        # sheet names them: a cash-up signed by "nyaradzo" is evidence, and
        # renaming them to fit our conventions would break the link to the
        # paper it came from.
        user = (db.query(User)
                .filter(User.pharmacy_id == pharmacy.id,
                        User.full_name.ilike(teller)).first())
        if user is None:
            user = (db.query(User)
                    .filter(User.pharmacy_id == pharmacy.id).first())
        if user is None:
            raise SystemExit("No user on this tenant to attribute the shift to.")

        existing = (db.query(Shift)
                    .filter(Shift.user_id == user.id,
                            Shift.opened_at == when).first())
        if existing:
            db.close()
            return {"created": False, "shift_id": existing.id}

        cash_taken = sum(t["amount"] for t in takings if t["method"] == "cash")
        card_total = sum(t["amount"] for t in takings if t["method"] == "card")
        mobile = sum(t["amount"] for t in takings if t["method"] == "mobile_money")
        spent = sum(e["amount"] for e in expenses)

        shift = Shift(
            user_id=user.id,
            opened_at=when,
            closed_at=when,
            opening_float=opening,
            counted_cash=counted,
            expected_cash=expected,
            variance=round(counted - expected, 2),
            card_total=card_total,
            status="closed",
            branch_id=branch.id if branch else None,
            pharmacy_id=pharmacy.id,
            notes=(f"Imported from the teller sheet. {shift_time}, "
                   f"teller {teller}, supervisor {supervisor or 'not named'}. "
                   f"Cash {cash_taken:.2f}, card {card_total:.2f}, "
                   f"mobile {mobile:.2f}, spent from the drawer {spent:.2f}."),
            # The tender split is kept verbatim: five columns across two
            # currencies is the whole reason the drawer reconciles, and a
            # single "counted cash" figure throws it away.
            cashup_json=json.dumps({"source": "teller sheet",
                                    "shift": shift_time,
                                    "supervisor": supervisor,
                                    "tenders": takings}),
        )
        db.add(shift)
        db.flush()

        for item in expenses:
            db.add(PettyCash(
                shift_id=shift.id,
                branch_id=branch.id if branch else None,
                amount=item["amount"],
                currency_code="USD",
                category="counter",
                pharmacy_id=pharmacy.id,
            ))

        db.commit()
        result = {"created": True, "shift_id": shift.id, "branch": branch.name,
                  "teller": teller, "tenders": takings, "expenses": expenses,
                  "variance": shift.variance}
    db.close()
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Give me the path to the teller cash-up .xlsm")
    out = run(sys.argv[1])
    if not out.get("created"):
        print(f"Already loaded as shift {out['shift_id']}.")
        raise SystemExit(0)
    print(f"shift {out['shift_id']} at {out['branch']}, teller {out['teller']}")
    for t in out["tenders"]:
        print(f"   {t['method']:14} {t['currency_code']}  {t['amount']:>10,.2f}")
    for e in out["expenses"]:
        print(f"   spent: {e['what'][:34]:34} {e['amount']:>10,.2f}")
    print(f"   variance {out['variance']:,.2f}")
