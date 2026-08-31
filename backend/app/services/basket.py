"""What a repeat is really worth: the basket, not the line.

A repeat's own value is what the pharmacy has been measuring — the tablets on
the script, at the shelf price. That figure is right and it is not the number
the business runs on.

A patient collecting a chronic repeat buys other things while they are in the
shop. Plasters, a toothbrush, the baby's formula, a headache tablet for their
mother. The repeat is the **reason they walked in**; the basket is what they
spent. A shop that measures only the line is deciding whether to chase a
fifteen-dollar repeat when what it is really chasing is a forty-eight-dollar
visit, twelve times a year, for as long as that patient lives nearby.

That is the entire commercial case for a repeat book, and nothing here
calculated it.

HOW THE VISIT IS FOUND, AND WHY IT IS NOT THE OBVIOUS WAY

`Dispensing.sale_id` exists and is the direct link. In this estate it is
populated on 27 rows out of 55,742 — the dispensing flow sets it, the historic
import never did. Reading basket value off that column would produce a
confident figure computed from a twentieth of a percent of the history.

So a visit is a patient and a day: every sale that patient made on the day the
repeat went out. That is what a basket *is* in retail, it survives a patient
paying for two things at two tills, and it works on the data that exists. Where
the direct link is present it is preferred and the answer says so, because a
figure derived from a fallback should admit it.

BRANCH AND GROUP

Reported per branch and consolidated. The two answer different questions: a
branch manager asks whether their repeat patients spend, and an owner asks
which branch converts a repeat visit into a basket and which merely hands over
tablets. The second is the actionable one and needs both numbers side by side.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Branch, Dispensing, Prescription, PrescriptionItem,
                      Product, Sale)

#: Sales this many hours either side of the dispensing count as the same visit
#: where the direct link is missing. A day, not an hour: a patient who collects
#: at nine and comes back at four for something they forgot has made one visit
#: as far as the shop's relationship with them is concerned.
SAME_VISIT_DAYS = 0


def _period(days: int) -> tuple[datetime, datetime]:
    end = datetime.utcnow()
    return end - timedelta(days=max(1, days)), end


def repeat_baskets(db: Session, *, days: int = 90,
                   branch_id: int | None = None) -> dict:
    """What a repeat collection is worth once the rest of the basket is counted.

    Returns the repeat's own value, the visit's value, and the difference —
    which is the number that decides whether chasing repeats is worth a
    pharmacist's morning.
    """
    start, end = _period(days)

    # Every repeat that went out in the window, with what the line was worth.
    rows = (
        db.query(Dispensing.id, Dispensing.dispensed_at, Dispensing.sale_id,
                 Dispensing.quantity, Prescription.patient_id,
                 Product.unit_price, Product.id)
        .join(PrescriptionItem,
              PrescriptionItem.id == Dispensing.prescription_item_id)
        .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
        .join(Product, Product.id == PrescriptionItem.product_id)
        .filter(Dispensing.dispensed_at >= start,
                Dispensing.dispensed_at <= end,
                Dispensing.is_repeat.is_(True))
        .all())

    if not rows:
        return _empty(days, branch_id,
                      "No repeats were dispensed in this period.")

    # The sales those patients made on those days, in one query rather than one
    # per dispensing. Fifty thousand repeats would otherwise be fifty thousand
    # round trips, which is not a report anybody waits for.
    patient_days = {(p, d.date()) for _i, d, _s, _q, p, _u, _pid in rows if p and d}
    if not patient_days:
        return _empty(days, branch_id,
                      "The repeats in this period are not linked to a patient, "
                      "so no visit can be identified.")

    patients = {p for p, _ in patient_days}
    sale_query = (
        db.query(Sale.id, Sale.patient_id, Sale.created_at, Sale.total,
                 Sale.branch_id)
        .filter(Sale.patient_id.in_(patients),
                Sale.created_at >= start - timedelta(days=1),
                Sale.created_at <= end + timedelta(days=1),
                Sale.status.in_(("paid", "part_paid"))))
    if branch_id:
        sale_query = sale_query.filter(Sale.branch_id == branch_id)

    visits: dict[tuple, dict] = {}
    for sale_id, patient_id, at, total, sale_branch in sale_query.all():
        key = (patient_id, at.date())
        v = visits.setdefault(key, {"total": 0.0, "sales": 0,
                                    "branch_id": sale_branch})
        v["total"] = round(v["total"] + float(total or 0), 2)
        v["sales"] += 1

    direct = 0
    matched = 0
    unmatched = 0
    per_branch: dict[int | None, dict] = {}

    for _id, at, sale_id, quantity, patient_id, price, _pid in rows:
        line = round(float(price or 0) * (quantity or 0), 2)
        if not patient_id or not at:
            unmatched += 1
            continue
        visit = visits.get((patient_id, at.date()))
        if visit is None:
            # A repeat handed over with no sale that day. Real and worth
            # counting: it is a collection that took no money, which is either
            # a scheme script settled elsewhere or a bag nobody paid for.
            unmatched += 1
            continue
        if sale_id:
            direct += 1
        matched += 1

        b = per_branch.setdefault(visit["branch_id"], {
            "branch_id": visit["branch_id"],
            "repeats": 0, "repeat_value": 0.0, "basket_value": 0.0,
            "with_extras": 0,
        })
        b["repeats"] += 1
        b["repeat_value"] = round(b["repeat_value"] + line, 2)
        b["basket_value"] = round(b["basket_value"] + visit["total"], 2)
        # Did they buy anything beyond the repeat itself? The share that do is
        # the number a shop can actually move — by what is near the counter,
        # and by whether anybody asks.
        if visit["total"] > line + 0.005:
            b["with_extras"] += 1

    names = {b.id: b.name for b in db.query(Branch).all()}
    branches = []
    for entry in per_branch.values():
        n = entry["repeats"] or 1
        uplift = round(entry["basket_value"] - entry["repeat_value"], 2)
        branches.append({
            **entry,
            "branch": names.get(entry["branch_id"], "Not recorded"),
            "average_repeat": round(entry["repeat_value"] / n, 2),
            "average_basket": round(entry["basket_value"] / n, 2),
            "uplift": uplift,
            "average_uplift": round(uplift / n, 2),
            # How many dollars of basket each dollar of repeat brings with it.
            # The one figure that compares a branch fairly regardless of which
            # medicines it happens to dispense.
            "multiple": (round(entry["basket_value"] / entry["repeat_value"], 2)
                         if entry["repeat_value"] else None),
            "attach_rate": round(100.0 * entry["with_extras"] / n, 1),
        })
    branches.sort(key=lambda b: -b["basket_value"])

    total_repeat = round(sum(b["repeat_value"] for b in branches), 2)
    total_basket = round(sum(b["basket_value"] for b in branches), 2)
    total_n = sum(b["repeats"] for b in branches)
    extras = sum(b["with_extras"] for b in branches)

    # ---- does the basket actually contain the repeat? --------------------
    #
    # It must. The basket is the whole visit and the repeat is one line of it,
    # so the multiple cannot be below 1. When it is, the two figures are not
    # describing the same transaction — which happens when dispensings and
    # sales were loaded from different exports and never tied together, as they
    # were here: 27 of 55,742 dispensings carry a sale.
    #
    # Publishing "0.1 times" would be arithmetic performed correctly on numbers
    # that do not belong together, and somebody would read it as "repeat
    # patients spend nothing" and stop chasing repeats. So it is refused and
    # the reason is given. A metric that cannot be trusted is worse than one
    # that is absent, because the absent one does not get acted on.
    trustworthy = not total_repeat or total_basket >= total_repeat * 0.95
    if not trustworthy:
        return {
            **_empty(days, branch_id, ""),
            "repeats": total_n,
            "unmatched": unmatched,
            "linked_directly": direct,
            "untrustworthy": True,
            "headline": (
                "Basket value cannot be measured on this data yet. The visits "
                "found are worth less than the repeats they are supposed to "
                "contain, which means the dispensings and the sales were "
                "loaded from different exports and never tied together — "
                f"only {direct:,} of {matched:,} repeats carry the sale they "
                f"were paid on. Every repeat dispensed through the till from "
                f"now on records it, so this fills in as the shop trades."),
            "diagnosis": {
                "repeat_value": total_repeat,
                "basket_value": total_basket,
                "matched": matched,
                "linked_directly": direct,
            },
        }

    return {
        "days": days,
        "branch_id": branch_id,
        "untrustworthy": False,
        "repeats": total_n,
        "unmatched": unmatched,
        # Said plainly. A repeat with no sale on the day is not a failure of the
        # report, it is a collection that took no money, and hiding it would
        # flatter every average below.
        "unmatched_note": (
            f"{unmatched:,} repeat(s) had no sale on the day they went out — "
            f"a scheme script settled elsewhere, or a bag nobody paid for. "
            f"They are excluded from the averages rather than counted as zero."
            if unmatched else ""),
        "linked_directly": direct,
        "link_note": (
            f"{direct:,} of {matched:,} were matched by the sale recorded on the "
            f"dispensing itself; the rest by the patient's sales on the same day."
            if matched else ""),
        "repeat_value": total_repeat,
        "basket_value": total_basket,
        "uplift": round(total_basket - total_repeat, 2),
        "average_repeat": round(total_repeat / total_n, 2) if total_n else 0.0,
        "average_basket": round(total_basket / total_n, 2) if total_n else 0.0,
        "average_uplift": (round((total_basket - total_repeat) / total_n, 2)
                           if total_n else 0.0),
        "multiple": (round(total_basket / total_repeat, 2)
                     if total_repeat else None),
        "attach_rate": round(100.0 * extras / total_n, 1) if total_n else 0.0,
        "branches": branches,
        "headline": _headline(total_n, total_repeat, total_basket, extras),
    }


def _headline(n: int, repeat: float, basket: float, extras: int) -> str:
    if not n:
        return "No repeats to measure in this period."
    avg_repeat = repeat / n
    avg_basket = basket / n
    multiple = basket / repeat if repeat else 0
    return (
        f"A repeat collection is worth {avg_repeat:,.2f} on the line and "
        f"{avg_basket:,.2f} in the basket — {multiple:.1f} times. "
        f"{100.0 * extras / n:.0f}% of repeat visits buy something else.")


def _empty(days: int, branch_id: int | None, why: str) -> dict:
    return {
        "days": days, "branch_id": branch_id, "repeats": 0, "unmatched": 0,
        "unmatched_note": "", "linked_directly": 0, "link_note": "",
        "repeat_value": 0.0, "basket_value": 0.0, "uplift": 0.0,
        "average_repeat": 0.0, "average_basket": 0.0, "average_uplift": 0.0,
        "multiple": None, "attach_rate": 0.0, "branches": [],
        "untrustworthy": False,
        "headline": why,
    }
