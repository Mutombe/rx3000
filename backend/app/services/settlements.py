"""What each funder actually paid, against what was claimed and when.

A remittance answers "what did this deposit cover". A settlement report answers
the question above it: **is this funder paying us, in full, on time** — and if
not, which of those three is failing, because they have three different
answers.

    paying          the claimed-to-settled ratio. Below 100% and the difference
                    is either being billed, written off, or lost quietly
    in full         how much of what they agreed lands
    on time         days from submission to money, against the terms the
                    scheme itself states

A pharmacy carries a funder for sixty days without noticing, because each claim
is small and the delay is invisible one claim at a time. It becomes visible
when the working capital has gone, and by then the conversation with the funder
is about a number nobody has kept.

WHAT THIS DELIBERATELY DOES NOT DO

It does not net suspended claims into the shortfall. A held claim is money the
funder has not decided about — it pays when a query is answered — and counting
it as a loss makes a scheme look worse than it is, which is exactly the way to
lose an argument with them.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import (Claim, ClaimBatch, MedicalAid, Remittance,
                      RemittanceLine)


def _days(a, b) -> int | None:
    if not a or not b:
        return None
    a = a.date() if isinstance(a, datetime) else a
    b = b.date() if isinstance(b, datetime) else b
    return (b - a).days


def by_funder(db: Session, *, days: int = 180) -> dict:
    """One row per funder: claimed, settled, held, and how long it took.

    Read from remittances rather than from claim statuses, because a claim
    marked approved is the pharmacy's opinion and a remittance is the funder's
    money. Where the two disagree the money is right.
    """
    since = datetime.utcnow() - timedelta(days=max(1, days))

    advices = (db.query(Remittance)
               .options(joinedload(Remittance.lines))
               .filter(Remittance.created_at >= since).all())

    funders: dict[str, dict] = {}
    for advice in advices:
        key = (advice.funder_id or "—").upper()
        row = funders.setdefault(key, {
            "funder_id": key, "funder": key,
            "advices": 0, "lines": 0,
            "claimed": 0.0, "paid": 0.0,
            "short": 0.0, "rejected": 0.0, "held": 0.0,
            "held_lines": 0, "rejected_lines": 0, "short_lines": 0,
            "settlement_days": [],
            "last_paid": None,
        })
        row["advices"] += 1
        if advice.payment_date:
            if row["last_paid"] is None or advice.payment_date > row["last_paid"]:
                row["last_paid"] = advice.payment_date

        for line in advice.lines:
            row["lines"] += 1
            row["claimed"] = round(row["claimed"] + (line.amount_claimed or 0), 2)
            row["paid"] = round(row["paid"] + (line.amount_paid or 0), 2)
            if line.status == "short_paid":
                row["short"] = round(row["short"] + (line.variance or 0), 2)
                row["short_lines"] += 1
            elif line.status == "rejected":
                row["rejected"] = round(row["rejected"] + (line.variance or 0), 2)
                row["rejected_lines"] += 1
            elif line.status == "suspended":
                # Held, not lost. Kept apart from the shortfall for the reason
                # in the module docstring.
                row["held"] = round(row["held"] + (line.amount_claimed or 0), 2)
                row["held_lines"] += 1

            # How long the money took. From the claim's submission, because
            # that is when the pharmacy's money went out of its control.
            claim = line.claim
            if claim is not None and advice.payment_date:
                taken = _days(getattr(claim, "submitted_at", None), advice.payment_date)
                if taken is not None and 0 <= taken < 400:
                    row["settlement_days"].append(taken)

    # What each scheme says its own terms are, so "late" is measured against
    # their promise rather than against an opinion.
    # Keyed on the scheme code, which is what a remittance's `funder_id`
    # carries. A `getattr(aid, "funder_id")` fallback silently found nothing
    # and every scheme read as having no stated terms — so "late" would have
    # been measured against an opinion rather than against their promise.
    terms: dict[str, int] = {}
    names: dict[str, str] = {}
    for aid in db.query(MedicalAid).all():
        code = (aid.scheme_code or "").strip().upper()
        if not code:
            continue
        names[code] = aid.name
        # Terms first; a fixed settlement day is expressed as roughly a month.
        terms[code] = (aid.settlement_days or 0) or (30 if aid.settlement_day else 0)

    rows = []
    for row in funders.values():
        taken = row.pop("settlement_days")
        average = round(sum(taken) / len(taken)) if taken else None
        promised = terms.get(row["funder_id"], 0)
        row["funder"] = names.get(row["funder_id"], row["funder_id"])
        rows.append({
            **row,
            "average_days": average,
            "slowest_days": max(taken) if taken else None,
            "promised_days": promised or None,
            "late_by": (average - promised
                        if average is not None and promised else None),
            # The three questions, each its own number.
            "paying_rate": (round(100.0 * row["paid"] / row["claimed"], 1)
                            if row["claimed"] else None),
            "shortfall": round(row["short"] + row["rejected"], 2),
            "says": _says(row, average, promised),
        })

    rows.sort(key=lambda r: -(r["claimed"] or 0))
    total_claimed = round(sum(r["claimed"] for r in rows), 2)
    total_paid = round(sum(r["paid"] for r in rows), 2)
    total_held = round(sum(r["held"] for r in rows), 2)
    return {
        "days": days,
        "funders": rows,
        "claimed": total_claimed,
        "paid": total_paid,
        "shortfall": round(sum(r["shortfall"] for r in rows), 2),
        "held": total_held,
        "paying_rate": (round(100.0 * total_paid / total_claimed, 1)
                        if total_claimed else None),
        "headline": _headline(rows, total_claimed, total_paid, total_held),
    }


def _says(row: dict, average: int | None, promised: int) -> str:
    bits = []
    if row["claimed"]:
        rate = 100.0 * row["paid"] / row["claimed"]
        if rate < 90:
            bits.append(f"pays {rate:.0f}% of what is claimed")
    if average is not None:
        if promised and average > promised + 7:
            bits.append(f"takes {average} days against {promised} promised")
        elif not promised:
            bits.append(f"takes {average} days")
    if row["held_lines"]:
        bits.append(f"{row['held_lines']} claim(s) held pending a query")
    return "; ".join(bits) if bits else "paying in full, on time"


def _headline(rows, claimed, paid, held) -> str:
    if not rows:
        return "No remittances in this period."
    worst = min((r for r in rows if r["paying_rate"] is not None),
                key=lambda r: r["paying_rate"], default=None)
    slow = max((r for r in rows if r["late_by"] is not None),
               key=lambda r: r["late_by"], default=None)
    parts = [f"{paid:,.2f} settled of {claimed:,.2f} claimed"]
    if held:
        parts.append(f"{held:,.2f} held pending queries")
    if worst is not None and worst["paying_rate"] < 90:
        parts.append(f"{worst['funder']} pays {worst['paying_rate']:.0f}%")
    if slow is not None and (slow["late_by"] or 0) > 7:
        parts.append(f"{slow['funder']} is {slow['late_by']} days beyond its "
                     f"own terms")
    return " · ".join(parts) + "."


def held_lines(db: Session, *, funder_id: str = "", limit: int = 200) -> dict:
    """Every claim a funder is holding, so somebody can answer the query.

    This is the list that did not exist. A held claim was classified as a
    rejection and went into the write-off pile, which is the pharmacy giving
    away money the scheme had not refused.
    """
    query = (db.query(RemittanceLine)
             .options(joinedload(RemittanceLine.remittance))
             .filter(RemittanceLine.status == "suspended"))
    if funder_id:
        query = (query.join(Remittance)
                 .filter(Remittance.funder_id == funder_id.strip().upper()))
    rows = query.order_by(RemittanceLine.id.desc()).limit(limit).all()

    from .era import REASONS

    return {
        "count": len(rows),
        "value": round(sum(l.amount_claimed or 0.0 for l in rows), 2),
        "lines": [{
            "id": l.id,
            "remittance_number": l.remittance.remittance_number if l.remittance else "",
            "funder_id": l.remittance.funder_id if l.remittance else "",
            "claim_id": l.claim_id,
            "claim_reference": l.claim_reference,
            "member_name": l.member_name,
            "policy_number": l.policy_number,
            "service_date": l.service_date,
            "amount_claimed": round(l.amount_claimed or 0.0, 2),
            "reason_code": l.reason_code,
            "reason": REASONS.get(l.reason_code or "", l.reason or ""),
        } for l in rows],
    }
