"""The repeat book: what it is worth, and how much of it the pharmacy keeps.

A chronic repeat is the most valuable line in a pharmacy and the easiest to
lose. The patient has already chosen you, the prescriber has already written
it, and the money arrives every month without anybody selling anything. Which
is exactly why losing one is invisible: nothing happens. No complaint, no
cancellation — the patient simply goes somewhere else next month and the line
quietly stops appearing.

So the questions this answers are the ones nobody can answer by looking at
sales, because a sale that did not happen leaves no record:

  **What is the book worth?**  Everything due in the period, priced.

  **How much did we keep?**  Repeats that came due and were actually
  dispensed, against those that came due at all. This is the number: a
  pharmacy filling 60% of its own repeat book is losing forty per cent of the
  most reliable revenue it has, and would never see it on a takings report.

  **Where does it go?**  Split three ways, because the answers are different
  jobs. Late but still ours is a telephone call. Never collected is a lapsed
  patient. **Could not supply** is the pharmacy's own doing — the patient came,
  or would have, and the shelf was empty. That last one is the only category
  the pharmacy controls completely, and it is the one worth reading first.

Everything is computed from what was dispensed against what fell due. No
estimates: a repeat is captured when a dispensing exists against its line
inside the window, and it is lost when one does not.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import (Dispensing, Patient, Prescription, PrescriptionItem,
                      Product)

#: How long after the due date a repeat is still plausibly "coming in". Beyond
#: it, a patient who has not appeared has almost certainly been served
#: elsewhere or has stopped taking the medicine, and both are worth knowing.
GRACE_DAYS = 7

#: Past this, treat the patient as lapsed rather than late.
LAPSED_DAYS = 45


def _money(v) -> float:
    return round(float(v or 0.0), 2)


def performance(db: Session, *, days: int = 30) -> dict:
    """What fell due in the window, and what became of it."""
    today = date.today()
    since = today - timedelta(days=max(1, days))

    # Every repeat line that came due inside the window. `next_repeat_date`
    # moves forward each time one is dispensed, so this is read against the
    # dispensing history rather than the current value of that column —
    # otherwise a repeat that was filled on time would look as though it was
    # never due at all.
    rows = (
        db.query(PrescriptionItem, Product, Prescription)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .outerjoin(Product, PrescriptionItem.product_id == Product.id)
        # The patient comes with the script. The at-risk list below reads a
        # name and a telephone number off every overdue line, and without this
        # that is a query each — ninety-two of them to draw one panel, which is
        # eight seconds against the hosted database on a screen somebody opens
        # first thing every morning.
        .options(joinedload(Prescription.patient))
        .filter(PrescriptionItem.repeats_allowed > 0,
                Prescription.status.notin_(("draft", "cancelled")))
        .all()
    )

    # What was handed over in the window, and *when* — not merely whether.
    #
    # "Captured" on its own flatters the pharmacy. A repeat due on the first and
    # collected on the twenty-eighth was kept, but the patient went most of a
    # month without their medicine, and a pharmacy that fills everything three
    # weeks late is one bad month away from losing the lot. On time is the
    # number worth managing; filled late is the early warning.
    filled = {
        item_id: (int(n), first)
        for item_id, n, first in
        db.query(Dispensing.prescription_item_id,
                 func.count(Dispensing.id),
                 func.min(Dispensing.dispensed_at))
        .filter(Dispensing.dispensed_at >= datetime.combine(since, datetime.min.time()))
        .group_by(Dispensing.prescription_item_id)
        .all()
    }

    due = captured = late = lapsed = blocked = waiting = 0
    due_value = captured_value = late_value = lapsed_value = blocked_value = 0.0
    waiting_value = 0.0
    on_time = filled_late = 0
    on_time_value = filled_late_value = 0.0
    at_risk: list[dict] = []

    for item, product, rx in rows:
        when = item.next_repeat_date
        if when is None:
            continue
        line_value = _money((product.unit_price or 0.0) * (item.quantity or 0)) \
            if product else 0.0

        hit = filled.get(item.id)
        was_filled = bool(hit and hit[0] > 0)
        filled_on = hit[1].date() if hit and hit[1] else None

        # Due in the window: either the date fell inside it, or it is already
        # past and still outstanding.
        fell_due = since <= when <= today
        outstanding = when < today and item.repeats_used < item.repeats_allowed

        if not (fell_due or outstanding):
            continue

        due += 1
        due_value += line_value

        if was_filled:
            captured += 1
            captured_value += line_value
            # Within the grace period counts as on time: a repeat due on a
            # Sunday and collected on the Monday was not late in any sense the
            # patient would recognise.
            if filled_on is not None and (filled_on - when).days > GRACE_DAYS:
                filled_late += 1
                filled_late_value += line_value
            else:
                on_time += 1
                on_time_value += line_value
            continue

        overdue_days = (today - when).days if when < today else 0
        can_supply = bool(product and (product.quantity_on_hand or 0) >= (item.quantity or 0))

        if not can_supply:
            # The pharmacy's own doing, and counted separately from a patient
            # who simply did not come — the fix is an order, not a telephone
            # call.
            blocked += 1
            blocked_value += line_value
        elif overdue_days > LAPSED_DAYS:
            lapsed += 1
            lapsed_value += line_value
        elif overdue_days > GRACE_DAYS:
            late += 1
            late_value += line_value
        else:
            # Due, unfilled, and not yet late enough to chase. Counted so the
            # split adds up: a breakdown that accounts for 85% of a loss and
            # says nothing about the rest is a breakdown nobody trusts.
            waiting += 1
            waiting_value += line_value

        if overdue_days > GRACE_DAYS:
            at_risk.append({
                "item_id": item.id,
                "patient_id": rx.patient_id,
                "patient": (f"{rx.patient.first_name} {rx.patient.last_name}".strip()
                            if rx.patient else ""),
                "phone": rx.patient.phone if rx.patient else "",
                "product": product.name if product else "",
                "due_on": when,
                "days_overdue": overdue_days,
                "value": line_value,
                "can_supply": can_supply,
                "state": ("cannot supply" if not can_supply
                          else "lapsed" if overdue_days > LAPSED_DAYS else "late"),
            })

    # Worth most first: this list is worked down a telephone, and the order is
    # the only thing that decides what gets rung before the shop gets busy.
    at_risk.sort(key=lambda r: (-r["value"], -r["days_overdue"]))

    rate = round(captured / due, 4) if due else None
    value_rate = round(captured_value / due_value, 4) if due_value > 0.005 else None

    lost = due - captured
    lost_value = _money(due_value - captured_value)

    # What is due today, on its own. A pharmacy plans the morning against this
    # one figure and it is buried inside a thirty-day total otherwise.
    today_rows = [r for r in rows
                  if r[0].next_repeat_date == today
                  and r[2].status not in ("draft", "cancelled")]
    today_value = _money(sum(
        (product.unit_price or 0.0) * (item.quantity or 0)
        for item, product, _ in today_rows if product))

    return {
        "as_at": today,
        "days": days,
        "due": due,
        "captured": captured,
        "capture_rate": rate,
        "due_value": _money(due_value),
        "captured_value": _money(captured_value),
        "value_capture_rate": value_rate,

        # ---- what was lost, said as its own thing -----------------------
        #
        # "We lose about ten per cent" is a sentence nobody can act on. Ten per
        # cent of what, worth what, and lost how? These are the same figures
        # from the other side, because a loss rate without the money behind it
        # is a statistic and the money is the argument.
        "lost": lost,
        "lost_value": lost_value,
        "loss_rate": round(lost / due, 4) if due else None,
        "value_loss_rate": (round((due_value - captured_value) / due_value, 4)
                            if due_value > 0.005 else None),

        # What one repeat is worth on average, which is what turns a count into
        # a decision: forty missed repeats matters differently at four dollars
        # than at forty.
        "average_value": _money(due_value / due) if due else 0.0,
        "average_captured": _money(captured_value / captured) if captured else 0.0,

        # Of what was kept, how much was kept *on time*, which is what the
        # patient experienced and what decides whether they come back.
        "on_time": on_time,
        "on_time_value": _money(on_time_value),
        "on_time_rate": round(on_time / captured, 4) if captured else None,
        "filled_late": filled_late,
        "filled_late_value": _money(filled_late_value),

        # Today, on its own.
        "due_today": len(today_rows),
        "due_today_value": today_value,

        # The three different jobs.
        "late": late, "late_value": _money(late_value),
        "lapsed": lapsed, "lapsed_value": _money(lapsed_value),
        "cannot_supply": blocked, "cannot_supply_value": _money(blocked_value),

        # Where the loss went, as a share of the loss rather than of the book —
        # a manager choosing what to fix first needs the split of what is
        # actually going wrong, not each piece against a total that dwarfs it.
        "still_in_hand": waiting, "still_in_hand_value": _money(waiting_value),
        "loss_split": ([
            {"reason": "still in hand", "count": waiting,
             "value": _money(waiting_value),
             "share": round(waiting_value / (due_value - captured_value), 4),
             "fix": f"Due but not yet {GRACE_DAYS} days late. Nothing to do "
                    f"except be open when they come."},
            {"reason": "late", "count": late, "value": _money(late_value),
             "share": round(late_value / (due_value - captured_value), 4),
             "fix": "A telephone call, today."},
            {"reason": "cannot supply", "count": blocked,
             "value": _money(blocked_value),
             "share": round(blocked_value / (due_value - captured_value), 4),
             "fix": "An order. The only one the pharmacy causes itself."},
            {"reason": "lapsed", "count": lapsed, "value": _money(lapsed_value),
             "share": round(lapsed_value / (due_value - captured_value), 4),
             "fix": f"More than {LAPSED_DAYS} days past due. Assume they are "
                    f"being served elsewhere, and ask why."},
        ] if (due_value - captured_value) > 0.005 else []),

        "at_risk": at_risk[:100],
        "at_risk_total": len(at_risk),
        "grace_days": GRACE_DAYS,
        "lapsed_after_days": LAPSED_DAYS,
    }


def daily(db: Session, *, days: int = 14) -> list[dict]:
    """What the repeat book is worth day by day, and what was taken of it.

    A fortnight of this is what tells a pharmacy whether Monday is quietly
    worse than Thursday, and whether the gap is the patients or the shelf.
    """
    today = date.today()
    out: list[dict] = []

    rows = (
        db.query(PrescriptionItem.next_repeat_date,
                 func.count(PrescriptionItem.id),
                 func.coalesce(func.sum(Product.unit_price * PrescriptionItem.quantity), 0.0))
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .outerjoin(Product, PrescriptionItem.product_id == Product.id)
        .filter(PrescriptionItem.next_repeat_date.isnot(None),
                PrescriptionItem.next_repeat_date >= today - timedelta(days=days),
                PrescriptionItem.next_repeat_date <= today + timedelta(days=days),
                Prescription.status.notin_(("draft", "cancelled")))
        .group_by(PrescriptionItem.next_repeat_date)
        .all()
    )
    by_day = {when: (int(n), _money(v)) for when, n, v in rows if when}

    for offset in range(-days, days + 1):
        when = today + timedelta(days=offset)
        count, value = by_day.get(when, (0, 0.0))
        out.append({
            "date": when,
            "due": count,
            "value": value,
            "past": when < today,
            "today": when == today,
        })
    return out


def weekly(db: Session, *, weeks: int = 8) -> list[dict]:
    """How many repeats the pharmacy filled each week, and what they were worth.

    A week is the unit a pharmacy orders in, staffs to and is paid on. A day is
    too short: a repeat due on a Saturday is collected on the Monday, and the
    daily chart shows a hole and a spike where nothing went wrong.

    **This counts what was filled, not what fell due**, and the distinction is
    not a detail. `next_repeat_date` moves forward every time a repeat is
    handed over, so the database does not remember what was due in July — only
    what is due next. A first version of this compared dispensings in a week
    against the due dates still on file for that week and produced weeks
    reading "140 filled against 0 due", and a capture rate of 100% for a book
    it was in fact losing. Two unrelated populations divided by one another.

    So the honest weekly figure is the one that is actually recorded: repeats
    that went out, counted and priced. The capture rate — what fell due against
    what was kept — is computed line by line in `performance()` above, which
    reads each line's own due date against its own dispensing history, and that
    is where it should be read.
    """
    weeks = max(1, min(weeks, 52))
    today = date.today()
    starts = [today - timedelta(days=7 * (n + 1) - 1) for n in range(weeks)][::-1]
    since = starts[0]

    rows = (
        db.query(func.date(Dispensing.dispensed_at),
                 func.count(Dispensing.id),
                 func.coalesce(func.sum(Product.unit_price * Dispensing.quantity), 0.0))
        .join(PrescriptionItem,
              Dispensing.prescription_item_id == PrescriptionItem.id)
        .outerjoin(Product, PrescriptionItem.product_id == Product.id)
        .filter(Dispensing.dispensed_at >= datetime.combine(since, datetime.min.time()),
                Dispensing.is_repeat.is_(True))
        .group_by(func.date(Dispensing.dispensed_at))
        .all())

    def as_date(v):
        return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])

    by_day = {as_date(d): (int(n), _money(v)) for d, n, v in rows if d}

    out = []
    for start in starts:
        end = start + timedelta(days=6)
        filled = 0
        value = 0.0
        for offset in range(7):
            n, v = by_day.get(start + timedelta(days=offset), (0, 0.0))
            filled += n
            value += v
        out.append({
            "from": start,
            "to": end,
            "filled": filled,
            "value": _money(value),
            "average": _money(value / filled) if filled else 0.0,
            # The current week is short — it is however many days have happened
            # so far, so a bar shorter than last week's may mean nothing at
            # all. Said, rather than left for somebody to work out.
            "current": end >= today,
            "days_so_far": min(7, (today - start).days + 1) if end >= today else 7,
        })
    return out
