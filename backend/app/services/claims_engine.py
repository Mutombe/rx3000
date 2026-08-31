"""Realtime medical aid claiming.

This is a simulated switch with the same request/response shape a real
integration (e.g. MediSwitch / Healthbridge) would use — swap `submit_claim`
for a real HTTP call when credentials are available.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Claim, Patient, Sale


def _next_claim_number(db: Session) -> str:
    count = db.query(Claim).count() + 1
    return f"CLM{datetime.utcnow():%y%m}{count:05d}"


def claimable_lines(sale: Sale) -> list:
    """The lines a scheme is actually being asked to pay for.

    A script is not all-or-nothing. One line may be cash by the patient's choice
    or the scheme's rule, and another may not have been supplied at all. Sending
    those to the funder either overclaims — which is fraud, however accidental —
    or invites a rejection that holds up the whole claim. Both are avoided by
    asking the line, not the script.
    """
    out = []
    for item in sale.items:
        flags = _line_flags(item)
        if flags.get("not_dispensed") or flags.get("no_claim"):
            continue
        out.append(item)
    return out


def _line_flags(item) -> dict:
    """Read the per-line billing decisions off the script line behind a sale line.

    A POS sale has no script behind it, so the flags simply do not apply there.
    """
    link = getattr(item, "prescription_item", None)
    if link is None:
        return {}
    return {"no_claim": bool(getattr(link, "no_claim", False)),
            "not_dispensed": bool(getattr(link, "not_dispensed", False))}


def defer_claim(db: Session, sale: Sale, patient: Patient, reason: str) -> Claim:
    """Hold a claim rather than lose it.

    Created against the sale exactly as a submitted claim would be, so nothing
    downstream has to know it was held; it simply has not been sent yet. The
    patient is liable for the whole amount until it is, because promising them
    otherwise commits money the funder has not agreed to.
    """
    claim = Claim(
        claim_number=_next_claim_number(db),
        sale_id=sale.id,
        patient_id=patient.id,
        medical_aid_id=patient.medical_aid_id,
        amount_claimed=sale.total,
        amount_approved=0.0,
        patient_liable=sale.total,
        status="deferred",
        deferred_reason=reason[:200],
        deferred_at=datetime.utcnow(),
        response_message=f"Held for later submission: {reason}",
    )
    db.add(claim)
    return claim


def submit_deferred(db: Session, claim: Claim) -> Claim:
    """Send a claim that was held. The adjudication is the ordinary one."""
    if claim.status != "deferred":
        raise ValueError(f"{claim.claim_number} is {claim.status}, not deferred.")
    sale = claim.sale
    patient = claim.patient
    claim.submit_attempts = (claim.submit_attempts or 0) + 1
    _adjudicate(claim, sale, patient)
    claim.submitted_at = datetime.utcnow()
    db.commit()
    return claim


#: What a scheme covers, as one rule used in two places.
#:
#: It was written inline inside `_adjudicate`, which meant the only way to know
#: what a patient would owe was to dispense the medicine and find out. The
#: dispensary needs the same answer *before* that — a dispenser handing over a
#: bag says "that is four dollars at the till", and cannot say it from a figure
#: that does not exist yet.
#:
#: The obvious source for that estimate was `pricing.price_basket`, which
#: already computes a patient portion. It is the wrong number and would have
#: been a bad bug: that service models the scheme's *regulated* price — a fee
#: model, a professional fee, a levy and an MMAP cap — while the sale a claim is
#: raised against is billed at shelf price. Two coherent calculations of two
#: different things. Showing one as the other is arithmetic on mismatched data,
#: and it would have been wrong by a plausible-looking margin on every scheme
#: line, which is the kind of wrong nobody catches.
#:
#: So the estimate calls this, and so does the adjudication. They cannot drift,
#: because there is nothing to drift from.
#:
#: This remains a *simulated* funder. A real scheme's own adjudication is the
#: authority and will differ; the screens say so, and the reconciliation after
#: dispensing is where the difference lands.
MEDICINE_COVER = 1.0      # schemes pay medicine lines in full
FRONT_SHOP_COVER = 0.8    # and four fifths of everything else


def _apply_rule(lines: list[tuple]) -> tuple[float, float]:
    """(what was claimed, what a scheme would approve) for (product, amount) rows."""
    claimable_total = round(sum(amount for _, amount in lines), 2)
    medicine_total = sum(amount for product, amount in lines
                         if product and product.category == "medicine")
    other_total = round(claimable_total - medicine_total, 2)
    approved = round(medicine_total * MEDICINE_COVER
                     + other_total * FRONT_SHOP_COVER, 2)
    return claimable_total, approved


def estimate(db, patient, lines: list[tuple]) -> dict:
    """What the scheme will carry and what the patient will owe, before dispensing.

    `lines` are (product, quantity) as they stand on the script being built, and
    are priced the way the sale will be priced — at shelf price — because that
    is what the claim will be raised against.
    """
    priced = [(product, round((product.unit_price or 0.0) * max(1, int(qty or 1)), 2))
              for product, qty in lines]
    total = round(sum(amount for _, amount in priced), 2)

    # No membership is not a small shortfall, it is the whole bill. Said the
    # same way `_adjudicate` says it, so the estimate does not promise cover
    # that the claim will refuse three seconds later.
    if not patient or not patient.medical_aid_id or not patient.medical_aid_number:
        return {
            "total": total, "scheme_pays": 0.0, "patient_pays": total,
            "covered": False,
            "why": ("No active membership on file, so the patient pays the "
                    "whole amount." if patient and patient.medical_aid_id
                    else ""),
        }

    claimable_total, approved = _apply_rule(priced)
    approved = min(approved, claimable_total, total)
    return {
        "total": total,
        "scheme_pays": approved,
        "patient_pays": round(total - approved, 2),
        "covered": True,
        "scheme": patient.medical_aid.name if patient.medical_aid else "",
        "why": "",
    }


def _adjudicate(claim: Claim, sale: Sale, patient: Patient) -> None:
    if not patient.medical_aid_id or not patient.medical_aid_number:
        claim.status = "rejected"
        claim.amount_approved = 0.0
        claim.patient_liable = sale.total
        claim.response_message = "Rejected: member has no active medical aid membership on file."
    else:
        # One rule, applied here and by the estimate the dispensary shows.
        lines = claimable_lines(sale)
        claimable_total, approved = _apply_rule(
            [(i.product, i.line_total) for i in lines])
        # Never more than the scheme was asked for: lines flagged cash or
        # not dispensed are the patient's, not the funder's.
        claim.amount_approved = min(approved, claimable_total, sale.total)
        claim.patient_liable = round(sale.total - claim.amount_approved, 2)
        if claim.patient_liable <= 0.005:
            claim.status = "approved"
            claim.patient_liable = 0.0
            claim.response_message = f"Approved in full by {patient.medical_aid.name} ({patient.medical_aid.scheme_code})."
        else:
            claim.status = "partial"
            claim.response_message = (
                f"Partially approved by {patient.medical_aid.name}: "
                f"levy of {claim.patient_liable:.2f} payable by patient."
            )


def submit_claim(db: Session, sale: Sale, patient: Patient) -> Claim:
    claim = Claim(
        claim_number=_next_claim_number(db),
        sale_id=sale.id,
        patient_id=patient.id,
        medical_aid_id=patient.medical_aid_id,
        amount_claimed=sale.total,
    )
    _adjudicate(claim, sale, patient)
    claim.submitted_at = datetime.utcnow()
    claim.submit_attempts = 1
    db.add(claim)
    return claim


def reverse_claim(db: Session, claim: Claim) -> Claim:
    claim.status = "reversed"
    claim.response_message += " | Claim reversed."
    return claim
