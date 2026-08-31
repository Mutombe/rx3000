"""Is the patient asked for their own money, and only their own money?

A script for a scheme member is settled in two places on purpose. The claim is
raised at the dispensary, where somebody knows the medicine and the membership;
the patient walks to the till and settles what is left. That split is right —
it is how a pharmacy works — and it has exactly one failure mode, which is
asking for the wrong half.

THE BUG THIS WAS WRITTEN FOR

Choosing "Take payment now" at the dispensary put the **gross** in front of the
dispenser as the amount owed. Collecting it takes the funder's money out of the
member's pocket, while the claim for that same money is raised half a second
later. The patient pays twice and the pharmacy is paid twice, and the person it
happens to is unwell and standing in a queue. The till had always been right;
the dispensary's own payment path had not.

THE SECOND BUG, WHICH WOULD HAVE BEEN WORSE

The obvious source for the correct figure was `pricing.price_basket`, which
computes a `patient_portion` and is right there on the screen already. It is
the wrong number. That service models the scheme's *regulated* price — a fee
model, a professional fee, a levy, an MMAP cap — while the sale a claim is
raised against is billed at shelf price. Two coherent calculations of two
different things, and quoting one as the other is arithmetic on mismatched
data: wrong by a plausible-looking margin on every scheme line, which is the
kind of wrong that ships.

So this checks the thing that actually matters, in both directions:

  the estimate the dispensary shows equals the adjudication the claim performs,
    on the same basket — they call one rule, and this proves they still do;
  the two halves add up to the whole, so no money is billed twice and none
    goes missing;
  a member with no membership number owes the whole amount rather than a
    flattering fraction of it.

Nothing is committed.

    python qa/shortfall-split.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal                     # noqa: E402
from app import tenancy                                   # noqa: E402
from app.models import Patient, Product, Sale, SaleItem   # noqa: E402
from app.services import claims_engine                    # noqa: E402


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
        member = (db.query(Patient)
                  .filter(Patient.medical_aid_id.isnot(None),
                          Patient.medical_aid_number != "").first())
        if member is None:
            print("FAIL: no scheme member on this database")
            return 2

        meds = db.query(Product).filter(Product.category == "medicine").limit(2).all()
        other = db.query(Product).filter(Product.category != "medicine").first()
        basket = [(m, 2) for m in meds] + ([(other, 1)] if other else [])
        if not basket:
            print("FAIL: no products to price")
            return 2

        estimate = claims_engine.estimate(db, member, basket)

        # The same basket as a sale, adjudicated the way a real dispensing
        # adjudicates it. Rolled back — nothing here is a real claim.
        sale = Sale(sale_number="QA-SPLIT", patient_id=member.id,
                    status="pending", subtotal=0.0, vat_amount=0.0,
                    total=estimate["total"])
        db.add(sale)
        db.flush()
        for product, qty in basket:
            db.add(SaleItem(sale_id=sale.id, product_id=product.id,
                            quantity=qty, unit_price=product.unit_price,
                            line_total=round((product.unit_price or 0.0) * qty, 2)))
        db.flush()
        db.refresh(sale)
        claim = claims_engine.submit_claim(db, sale, member)
        db.flush()

        print(f"  basket of {len(basket)} for {member.first_name} "
              f"on {member.medical_aid.name}\n")

        agree_scheme = abs(estimate["scheme_pays"] - claim.amount_approved) < 0.005
        agree_patient = abs(estimate["patient_pays"] - claim.patient_liable) < 0.005
        check(agree_scheme and agree_patient,
              f"the dispensary quotes {estimate['patient_pays']:.2f} and the "
              f"claim charges {claim.patient_liable:.2f}",
              f"the dispensary would quote {estimate['patient_pays']:.2f} and "
              f"the till would ask for {claim.patient_liable:.2f} — somebody is "
              f"told one number and charged another")

        closes = abs((claim.amount_approved + claim.patient_liable)
                     - sale.total) < 0.005
        check(closes,
              f"{claim.amount_approved:.2f} on the scheme plus "
              f"{claim.patient_liable:.2f} from the patient is "
              f"{sale.total:.2f}, the whole sale",
              f"the two halves come to "
              f"{claim.amount_approved + claim.patient_liable:.2f} against a "
              f"sale of {sale.total:.2f} — money is being billed twice or lost")

        check(claim.patient_liable <= sale.total + 0.005,
              "the patient is never asked for more than the sale",
              f"the patient would be asked for {claim.patient_liable:.2f} on a "
              f"sale of {sale.total:.2f}")

        # And the case that must not be flattered: filed as a member, but with
        # nothing the scheme will honour.
        number = member.medical_aid_number
        member.medical_aid_number = ""
        lapsed = claims_engine.estimate(db, member, basket)
        member.medical_aid_number = number
        check(not lapsed["covered"]
              and abs(lapsed["patient_pays"] - lapsed["total"]) < 0.005,
              "a member with no membership number owes the whole amount",
              f"a member with no membership number is quoted "
              f"{lapsed['patient_pays']:.2f} of {lapsed['total']:.2f} — the "
              f"claim will reject and the till will ask for the rest, after "
              f"they have been told otherwise")
        check(bool(lapsed["why"]),
              "and is told why, at the dispensary rather than at the till",
              "nothing explains why the whole amount is payable")
    finally:
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("the dispensary quotes what the till collects, and the two halves "
          "make one whole")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
