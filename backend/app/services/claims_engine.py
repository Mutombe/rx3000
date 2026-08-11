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


def _adjudicate(claim: Claim, sale: Sale, patient: Patient) -> None:
    if not patient.medical_aid_id or not patient.medical_aid_number:
        claim.status = "rejected"
        claim.amount_approved = 0.0
        claim.patient_liable = sale.total
        claim.response_message = "Rejected: member has no active medical aid membership on file."
    else:
        # Simulated scheme adjudication: schemes pay 100% of medicine lines,
        # 80% of front-shop lines; remainder is a patient levy.
        lines = claimable_lines(sale)
        claimable_total = round(sum(i.line_total for i in lines), 2)
        medicine_total = sum(i.line_total for i in lines
                             if i.product and i.product.category == "medicine")
        other_total = round(claimable_total - medicine_total, 2)
        approved = round(medicine_total + other_total * 0.8, 2)
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
