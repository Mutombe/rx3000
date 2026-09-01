"""Trading periods: the accounting month everything is filed under.

A pharmacy reconciles by period, not by date range. "August" has to mean the
same set of transactions every time somebody asks for it, and it has to stop
meaning something new once the month has been signed off. A date-range report
cannot promise that: a sale backdated into last month silently changes a figure
the owner already reported to a bank or a tax authority, and nobody finds out.

So the period is a real object with a status, and the rule that gives it value
is a refusal: **a closed period will not accept a posting.** Everything else
here exists to make that rule enforceable and reversible under supervision.

Reopening is deliberately possible but deliberately audited. Pharmacies do find
a genuine missing invoice a week after closing, and a system that made that
impossible would simply be worked around — the invoice would be dated into the
current month and the accounts would be wrong in a way nobody could see. Better
to allow it, record who did it, and make the reopening visible.
"""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..models import TradingPeriod

OPEN, CLOSED, LOCKED = "open", "closed", "locked"


class PeriodError(ValueError):
    """Raised when a posting or a period transition is not allowed."""


def code_for(day: date) -> str:
    return f"{day.year}{day.month:02d}"


def bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def ensure(db: Session, day: date | None = None, user_id: int | None = None) -> TradingPeriod:
    """The period a date belongs to, created open if it does not exist yet.

    A pharmacy should never be unable to trade because nobody remembered to open
    the month. Periods therefore open themselves on first use; closing is the
    deliberate act, not opening.
    """
    day = day or date.today()
    code = code_for(day)
    period = db.query(TradingPeriod).filter(TradingPeriod.code == code).first()
    if period:
        return period
    start, end = bounds(day.year, day.month)
    period = TradingPeriod(
        code=code, name=f"{start:%B %Y}", start_date=start, end_date=end,
        status=OPEN, opened_by_id=user_id,
    )
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


def open_code(db: Session, code: str, user_id: int | None = None) -> TradingPeriod:
    """Open a period by its code, creating it if it has never existed.

    A pharmacy switching systems mid-year needs its earlier months to exist so
    that historical figures have somewhere to live. Checking whether a date is
    postable deliberately does *not* create anything — a question should not
    have side effects, so opening a prior period is an explicit act.
    """
    code = (code or "").strip()
    if len(code) != 6 or not code.isdigit():
        raise PeriodError(f"'{code}' is not a period code, expected YYYYMM, as in 202608.")
    year, month = int(code[:4]), int(code[4:])
    if not 1 <= month <= 12:
        raise PeriodError(f"'{code}' has no month {month}.")
    start, _ = bounds(year, month)
    return ensure(db, start, user_id)


def current(db: Session) -> TradingPeriod:
    return ensure(db)


def for_date(db: Session, day: date) -> TradingPeriod | None:
    return db.query(TradingPeriod).filter(TradingPeriod.code == code_for(day)).first()


def is_postable(db: Session, day: date | None = None) -> tuple[bool, str]:
    """Whether a transaction dated `day` may be posted, and why not if it may not."""
    day = day or date.today()
    period = for_date(db, day)
    if period is None:
        return True, ""                     # not yet opened; ensure() will open it
    if period.status == OPEN:
        return True, ""
    if period.status == LOCKED:
        return False, (f"{period.name} is locked and cannot be posted into. A locked "
                       "period has been sealed after a return or an audit, a "
                       "correction belongs in the current period as an adjustment.")
    return False, (f"{period.name} is closed. Post this into the current period, or "
                   "ask an administrator to reopen it if it genuinely belongs there.")


def guard(db: Session, day: date | None = None) -> TradingPeriod:
    """Refuse the posting if its period is not open. The rule the rest depends on."""
    ok, reason = is_postable(db, day)
    if not ok:
        raise PeriodError(reason)
    return ensure(db, day)


@dataclass
class Totals:
    sales: float
    vat: float
    cost: float
    transactions: int


def totals(db: Session, period: TradingPeriod) -> Totals:
    """What the period contains right now, computed from the transactions."""
    from sqlalchemy import func

    from ..models import Sale, SaleItem

    row = (
        db.query(
            func.coalesce(func.sum(Sale.total), 0.0),
            func.coalesce(func.sum(Sale.vat_amount), 0.0),
            func.count(Sale.id),
        )
        .filter(Sale.status == "paid",
                func.date(Sale.created_at) >= period.start_date,
                func.date(Sale.created_at) <= period.end_date)
        .one()
    )
    cost = (
        db.query(func.coalesce(func.sum(SaleItem.quantity * SaleItem.unit_cost), 0.0))
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(Sale.status == "paid",
                func.date(Sale.created_at) >= period.start_date,
                func.date(Sale.created_at) <= period.end_date)
        .scalar()
    ) or 0.0
    return Totals(sales=round(row[0], 2), vat=round(row[1], 2),
                  cost=round(cost, 2), transactions=row[2])


def close(db: Session, period: TradingPeriod, user_id: int, notes: str = "") -> TradingPeriod:
    """Sign the period off, freezing what it contained at that moment.

    The frozen totals are not a cache. They are the figure that was signed off,
    so that if a recomputation later disagrees, the disagreement itself is the
    finding, which is exactly what an auditor asks for.
    """
    if period.status == LOCKED:
        raise PeriodError(f"{period.name} is locked and cannot be closed again.")
    if period.status == CLOSED:
        raise PeriodError(f"{period.name} is already closed.")
    if period.end_date >= date.today():
        raise PeriodError(
            f"{period.name} has not finished yet. It runs to {period.end_date:%d %b %Y}. "
            "Closing a period still being traded in would strand today's sales.")

    figures = totals(db, period)
    period.status = CLOSED
    period.closed_at = datetime.utcnow()
    period.closed_by_id = user_id
    period.closing_sales = figures.sales
    period.closing_vat = figures.vat
    period.closing_cost = figures.cost
    period.closing_transactions = figures.transactions
    if notes:
        period.notes = f"{period.notes}\n{notes}".strip()
    db.commit()
    db.refresh(period)
    return period


def reopen(db: Session, period: TradingPeriod, user_id: int, reason: str) -> TradingPeriod:
    """Reopen a closed period. Requires a reason, because someone will ask."""
    if period.status == LOCKED:
        raise PeriodError(
            f"{period.name} is locked. A locked period cannot be reopened, put the "
            "correction in the current period as an adjustment instead.")
    if period.status == OPEN:
        raise PeriodError(f"{period.name} is already open.")
    if not (reason or "").strip():
        raise PeriodError("Reopening a closed period requires a reason.")
    period.status = OPEN
    period.notes = (f"{period.notes}\nReopened {datetime.utcnow():%Y-%m-%d %H:%M} "
                    f"by user {user_id}: {reason}").strip()
    db.commit()
    db.refresh(period)
    return period


def lock(db: Session, period: TradingPeriod, user_id: int, reason: str = "") -> TradingPeriod:
    """Seal a period permanently, after a tax return or an audit."""
    if period.status == OPEN:
        raise PeriodError(f"{period.name} must be closed before it can be locked.")
    if period.status == LOCKED:
        raise PeriodError(f"{period.name} is already locked.")
    period.status = LOCKED
    period.notes = (f"{period.notes}\nLocked {datetime.utcnow():%Y-%m-%d %H:%M} "
                    f"by user {user_id}. {reason}").strip()
    db.commit()
    db.refresh(period)
    return period


def summarise(db: Session, period: TradingPeriod, live: bool = True) -> dict:
    """One period as the UI shows it.

    A closed period reports what was signed off *and* what it contains now, so a
    drift between them is visible rather than hidden behind whichever one the
    screen happened to pick.
    """
    out = {
        "id": period.id, "code": period.code, "name": period.name,
        "start_date": period.start_date, "end_date": period.end_date,
        "status": period.status,
        "opened_at": period.opened_at, "closed_at": period.closed_at,
        "opened_by": period.opened_by.full_name if period.opened_by else "",
        "closed_by": period.closed_by.full_name if period.closed_by else "",
        "notes": period.notes,
        "closing_sales": period.closing_sales, "closing_vat": period.closing_vat,
        "closing_cost": period.closing_cost,
        "closing_transactions": period.closing_transactions,
        "postable": period.status == OPEN,
    }
    if live:
        figures = totals(db, period)
        out["live"] = figures.__dict__
        if period.status != OPEN:
            drift = round(figures.sales - (period.closing_sales or 0.0), 2)
            out["drift"] = drift
            out["drift_warning"] = (
                "" if abs(drift) < 0.01 else
                f"This period was signed off at {period.closing_sales:.2f} but now "
                f"contains {figures.sales:.2f}. Something was posted after it closed.")
    return out


def list_periods(db: Session, limit: int = 36) -> list[TradingPeriod]:
    return (db.query(TradingPeriod)
            .order_by(desc(TradingPeriod.code)).limit(limit).all())
