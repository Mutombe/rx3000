"""Is this patient's scheme actually paying, and does this patient have cover?

Two different questions get confused under the word "insurance", and a
dispenser needs both answered before handing anything over:

  **Does the patient have benefit left?**  A member with an exhausted annual
  limit is a cash patient who does not know it yet. Only the funder can answer
  this, over the switch, per member — so until NH263 is connected this reports
  honestly that it does not know rather than implying cover exists.

  **Is the scheme paying us?**  This one we can answer today, out of our own
  claims, and it is the question nobody was asking. A funder that has taken
  eleven thousand dollars of medicine in ninety days and settled two is not a
  payment problem to discover at the year end; it is a decision to make at the
  counter, one script at a time. The pharmacy is extending credit either way —
  the only choice is whether it does so knowingly.

The verdict is deliberately advisory. Blocking a dispense because a funder is
slow would turn a commercial dispute into a clinical one, and the person at the
counter is not the person who can resolve it. What this does is make sure that
whoever hands the medicine over knows what they are handing over, and that the
decision is recorded as theirs.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..models import Claim, MedicalAid, Patient

#: Claims older than this that remain unsettled are what "lagging" means. A
#: month is generous — most Zimbabwean schemes work to a monthly cycle with
#: payment in the following month — so anything beyond it is genuinely late
#: rather than merely in the post.
LATE_AFTER_DAYS = 45

#: Below this share settled, a scheme is not paying its way. Expressed as a
#: proportion of what has been claimed long enough to have been paid.
POOR_RECOVERY = 0.60

#: What one patient may quietly accumulate before it is worth saying out loud.
PATIENT_EXPOSURE_WARN = 200.0


def _money(value) -> float:
    return round(float(value or 0.0), 2)


def scheme_standing(db: Session, medical_aid_id: int) -> dict:
    """How this funder has behaved, out of our own claim history.

    Everything here is a fact about what we sent and what came back. No
    estimate, no projection — a dispenser deciding whether to supply on credit
    is owed figures they could check themselves.
    """
    aid = db.get(MedicalAid, medical_aid_id)
    if aid is None:
        return {}

    rows = (
        db.query(
            func.count(Claim.id),
            func.coalesce(func.sum(Claim.amount_claimed), 0.0),
            func.coalesce(func.sum(Claim.settled_amount), 0.0),
            func.coalesce(
                func.sum(case((Claim.status == "rejected", 1), else_=0)), 0),
        )
        .filter(Claim.medical_aid_id == medical_aid_id)
        .first()
    )
    count, claimed, settled, rejected = rows or (0, 0.0, 0.0, 0)

    cutoff = datetime.utcnow() - timedelta(days=LATE_AFTER_DAYS)
    overdue_rows = (
        db.query(func.count(Claim.id),
                 func.coalesce(func.sum(Claim.amount_claimed - Claim.settled_amount), 0.0),
                 func.min(Claim.created_at))
        .filter(Claim.medical_aid_id == medical_aid_id,
                Claim.status.notin_(("rejected", "reversed", "settled")),
                Claim.created_at < cutoff,
                Claim.amount_claimed > Claim.settled_amount)
        .first()
    )
    overdue_count, overdue_value, oldest = overdue_rows or (0, 0.0, None)

    claimed = _money(claimed)
    settled = _money(settled)
    outstanding = _money(claimed - settled)
    # Only claims old enough to have been paid count towards the recovery rate.
    # Judging a scheme on invoices sent yesterday would mark every funder as
    # failing on the first of the month.
    recovery = round(settled / claimed, 4) if claimed > 0.005 else None

    oldest_days = (datetime.utcnow() - oldest).days if oldest else 0

    if count == 0:
        verdict, why = "unknown", "Nothing has been claimed from this scheme yet."
    elif overdue_count and _money(overdue_value) > 0.005:
        verdict = "lagging"
        # With its currency. A bare "20.90 has been outstanding" beside a
        # scheme that settles in ZiG reads as dollars to everybody who sees it,
        # and the two are not the same money.
        why = (f"{aid.currency_code or 'USD'} {_money(overdue_value):,.2f} has "
               f"been outstanding for more than "
               f"{LATE_AFTER_DAYS} days across {int(overdue_count)} claim"
               f"{'' if overdue_count == 1 else 's'}"
               + (f", the oldest {oldest_days} days old." if oldest_days else "."))
    elif recovery is not None and recovery < POOR_RECOVERY:
        verdict = "watch"
        why = (f"Only {recovery * 100:.0f}% of what has been claimed from this "
               f"scheme has been settled.")
    else:
        verdict = "paying"
        why = (f"{recovery * 100:.0f}% of claims settled."
               if recovery is not None else "Settling normally.")

    return {
        "medical_aid_id": aid.id,
        "scheme": aid.name,
        "scheme_code": aid.scheme_code,
        # A scheme that settles in ZiG against a USD sale is its own kind of
        # exposure, so the currency it pays in is stated rather than assumed.
        "settles_in": aid.currency_code or "",
        "claims": int(count or 0),
        "claimed": claimed,
        "settled": settled,
        "outstanding": outstanding,
        "rejected": int(rejected or 0),
        "recovery": recovery,
        "overdue_claims": int(overdue_count or 0),
        "overdue_value": _money(overdue_value),
        "oldest_overdue_days": oldest_days,
        "late_after_days": LATE_AFTER_DAYS,
        "verdict": verdict,
        "why": why,
    }


def patient_standing(db: Session, patient_id: int) -> dict:
    """What this particular member is carrying, and what their scheme is.

    The per-patient half matters separately: a scheme can be settling well in
    general while one member's claims are all being refused, and the second
    fact is invisible in the first.
    """
    patient = db.get(Patient, patient_id)
    if patient is None:
        return {}

    if not patient.medical_aid_id:
        return {
            "patient_id": patient.id,
            "has_cover": False,
            "verdict": "cash",
            "why": "No medical aid on file — this is a cash patient.",
            "scheme": None,
            "benefit": _benefit_unknown(connected=False),
        }

    rows = (
        db.query(
            func.count(Claim.id),
            func.coalesce(func.sum(Claim.amount_claimed), 0.0),
            func.coalesce(func.sum(Claim.settled_amount), 0.0),
            func.coalesce(
                func.sum(case((Claim.status == "rejected", 1), else_=0)), 0),
        )
        .filter(Claim.patient_id == patient_id)
        .first()
    )
    count, claimed, settled, rejected = rows or (0, 0.0, 0.0, 0)
    exposure = _money((claimed or 0.0) - (settled or 0.0))

    scheme = scheme_standing(db, patient.medical_aid_id)

    # The patient's own verdict is the worse of the two readings: their scheme's
    # behaviour, and their own refusals. Reporting only the scheme's average
    # would wave through a member whose every claim comes back rejected.
    verdict = scheme.get("verdict", "unknown")
    why = scheme.get("why", "")
    if count and rejected and rejected / count >= 0.5:
        verdict = "watch"
        why = (f"{int(rejected)} of this member's {int(count)} claims have been "
               f"refused. Check the membership before supplying on the scheme.")
    elif exposure > PATIENT_EXPOSURE_WARN and verdict == "paying":
        why = (f"{exposure:,.2f} of this member's claims are still unsettled, "
               f"though the scheme is settling normally.")

    return {
        "patient_id": patient.id,
        "has_cover": True,
        "member_number": patient.medical_aid_number or "",
        "claims": int(count or 0),
        "claimed": _money(claimed),
        "settled": _money(settled),
        "outstanding": exposure,
        "rejected": int(rejected or 0),
        "verdict": verdict,
        "why": why,
        "scheme": scheme,
        "benefit": _benefit_unknown(connected=False),
    }


def _benefit_unknown(*, connected: bool) -> dict:
    """What is left on the member's annual limit — which only the funder knows.

    Reported as an explicit "not known" rather than omitted. A screen that
    simply shows nothing where a balance would be invites the reader to assume
    there is cover, and an exhausted member turned into a cash sale at the till
    is exactly the surprise this whole feature exists to prevent.
    """
    if connected:
        return {}
    return {
        "known": False,
        "available": None,
        "note": ("Benefit balances come from the scheme over the switch. This "
                 "pharmacy is not connected to it yet, so what is left on this "
                 "member's limit is not known here — treat a clear screen as "
                 "'unchecked', not as 'covered'."),
    }
