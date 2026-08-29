from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Sale, Shift, User
from ..services import currency
from .periods_router import require_step_up

router = APIRouter(prefix="/api/shifts", tags=["shifts"])

LOYALTY_POINT_VALUE = 1.0


def current_open_shift(db: Session, user_id: int) -> Shift | None:
    return (
        db.query(Shift)
        .filter(Shift.user_id == user_id, Shift.status == "open")
        .order_by(Shift.opened_at.desc())
        .first()
    )


def _shift_sales(db: Session, shift: Shift) -> list[Sale]:
    return db.query(Sale).filter(Sale.shift_id == shift.id, Sale.status == "paid").all()


def _totals(db: Session, shift: Shift) -> dict:
    """Cash expected in the drawer, plus card / medical-aid takings, in base currency.

    A sale settled with split tender has no single payment_method, so its
    tenders are used when present and the legacy fields only when it has none.
    """
    sales = _shift_sales(db, shift)
    cash = card = aid = 0.0
    for sale in sales:
        if sale.tenders:
            for tender in sale.tenders:
                # amount_in_base is already signed: change is negative
                if tender.method == "cash":
                    cash += tender.amount_in_base
                elif tender.method == "card":
                    card += tender.amount_in_base
                elif tender.method == "medical_aid":
                    aid += tender.amount_in_base
        elif sale.payment_method == "cash":
            cash += sale.total - sale.loyalty_points_redeemed * LOYALTY_POINT_VALUE
        elif sale.payment_method == "card":
            card += sale.total
        elif sale.payment_method == "medical_aid":
            aid += sale.total
    return {
        "expected_cash": round(shift.opening_float + cash, 2),
        "card_total": round(card, 2),
        "medical_aid_total": round(aid, 2),
        "sales_count": len(sales),
    }


@router.get("/{shift_id}/takings")
def takings(shift_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Takings split by currency — what each drawer should physically hold.

    Cash is net of change, because change leaves the drawer in whichever
    currency it was handed over.
    """
    shift = db.get(Shift, shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    sales = _shift_sales(db, shift)
    by_currency = currency.takings_by_currency(sales)

    # Sales with no tender rows predate split tender — fold them into the base
    # currency so the totals still reconcile.
    legacy = [s for s in sales if not s.tenders]
    if legacy:
        bucket = by_currency.setdefault(currency.base_code(), {
            "currency": currency.base_code(), "cash": 0.0, "card": 0.0,
            "mobile_money": 0.0, "medical_aid": 0.0, "other": 0.0,
            "total": 0.0, "in_base": 0.0,
        })
        for sale in legacy:
            method = sale.payment_method if sale.payment_method in bucket else "other"
            net = sale.total - sale.loyalty_points_redeemed * LOYALTY_POINT_VALUE \
                if sale.payment_method == "cash" else sale.total
            bucket[method] = round(bucket[method] + net, 2)
            bucket["total"] = round(bucket["total"] + net, 2)
            bucket["in_base"] = round(bucket["in_base"] + net, 2)

    base = currency.base_code()
    for code, bucket in by_currency.items():
        bucket["is_base"] = code == base
        if code == base:
            bucket["opening_float"] = shift.opening_float
            bucket["expected_cash"] = round(shift.opening_float + bucket["cash"], 2)
        else:
            bucket["opening_float"] = 0.0
            bucket["expected_cash"] = bucket["cash"]

    # The same rule as /current: what should be in the drawer is not knowable
    # from the browser until a count exists. This endpoint computes it per
    # currency, which made it the more useful back door of the two.
    if not getattr(shift, "counted_at", None):
        for bucket in by_currency.values():
            bucket.pop("expected_cash", None)

    # ---- what the money actually came in on ------------------------------
    #
    # "Mobile money 119.00" is not something a teller can reconcile. Their own
    # cash-up sheet has five columns — USD, EcoCash USD, Swipe USD, Swipe ZWG,
    # EcoCash ZWG — because EcoCash and Omari settle separately, on their own
    # timetables, and so do the banks behind a swipe. The tender rows already
    # carry which one: the till writes the wallet and the bank into the
    # reference. This groups by it, so the screen can be read against the sheet
    # they fill in by hand.
    instruments: dict[tuple, dict] = {}
    for sale in sales:
        for tender in sale.tenders:
            if tender.is_change:
                continue
            # The first word of the reference is the wallet or the bank —
            # "EcoCash 0779…", "Stanbic ••4417". Anything else is left as the
            # method itself rather than guessed at.
            first = (tender.reference or "").strip().split(" ")[0]
            named = first if first and not first[0].isdigit() else ""
            key = (tender.method, named, tender.currency_code)
            row = instruments.setdefault(key, {
                "method": tender.method, "instrument": named,
                "currency": tender.currency_code, "amount": 0.0,
                "in_base": 0.0, "count": 0,
            })
            row["amount"] = round(row["amount"] + (tender.amount or 0.0), 2)
            row["in_base"] = round(row["in_base"] + (tender.amount_in_base or 0.0), 2)
            row["count"] += 1

    return {
        "shift_id": shift.id,
        "base_currency": base,
        "sales_count": len(sales),
        "currencies": sorted(by_currency.values(), key=lambda b: (not b["is_base"], b["currency"])),
        "instruments": sorted(instruments.values(),
                              key=lambda r: (-r["in_base"], r["method"])),
    }


@router.get("/current", response_model=schemas.ShiftOut | None)
def get_current(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    shift = current_open_shift(db, user.id)
    if shift:
        for key, value in _totals(db, shift).items():
            setattr(shift, key, value)
        # The blind count only works if the expected figure is genuinely not in
        # the browser. This endpoint was sending it, which meant the count screen
        # could show a live variance as the operator typed — and a count that can
        # be adjusted until it balances is not a count.
        #
        # Withheld until a count has been committed. Everything else the shift
        # knows stays: how many sales, how long it has been open, the float.
        # None of those tell you what should be in the drawer.
        if not getattr(shift, "counted_at", None):
            shift.expected_cash = 0.0
            shift.variance = 0.0
    return shift


def _next_run_number(db: Session, till_no: str) -> int:
    """The next run number for a till.

    A run is one till's trading between two cash-ups, and it is what the whole
    cash-up is keyed on: Till / Run / Draw. Numbered per till rather than
    globally, because "till 2, run 47" is a thing a person can find, while a
    global counter tells you only how many runs the shop has ever had.

    Allocated when the shift opens. The system this replaces increments it when
    the cash-up is saved, which means nothing that happens *during* the run can
    carry the number — no invoice, no reprint, no query. Allocating up front
    costs nothing and makes the run identifiable while it is still open.

    The column existed and was reported by the cash-up before this, and nothing
    ever assigned it, so every run in the system was run 0 and the screen showed
    it as though it meant something.
    """
    highest = (
        db.query(func.max(Shift.run_number))
        .filter(func.coalesce(Shift.till_no, "") == (till_no or ""))
        .scalar()
    )
    return int(highest or 0) + 1


@router.post("/open", response_model=schemas.ShiftOut)
def open_shift(body: schemas.ShiftOpen, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if current_open_shift(db, user.id):
        raise HTTPException(status_code=400, detail="You already have an open shift, close it first")
    shift = Shift(
        user_id=user.id, opening_float=body.opening_float, status="open",
        till_no=body.till_no.strip(), draw_no=body.draw_no.strip(),
        run_number=_next_run_number(db, body.till_no.strip()),
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


@router.post("/close", response_model=schemas.ShiftOut)
def close_shift(body: schemas.ShiftClose, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    shift = current_open_shift(db, user.id)
    if not shift:
        raise HTTPException(status_code=400, detail="No open shift to close")

    totals = _totals(db, shift)
    shift.expected_cash = totals["expected_cash"]
    shift.card_total = totals["card_total"]
    shift.medical_aid_total = totals["medical_aid_total"]
    shift.sales_count = totals["sales_count"]
    shift.counted_cash = body.counted_cash
    shift.variance = round(body.counted_cash - shift.expected_cash, 2)
    shift.notes = body.notes
    shift.closed_at = datetime.utcnow()
    shift.status = "closed"
    db.commit()
    db.refresh(shift)
    return shift


@router.get("", response_model=list[schemas.ShiftOut])
def list_shifts(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Shift).order_by(Shift.opened_at.desc()).limit(limit).all()


# ------------------------------------------------------------------ cash-up
#
# The contract here is the whole point: there is no endpoint that returns the
# expected figure before a count has been submitted. Not "we choose not to show
# it" — it is not obtainable. A control that depends on the front end declining
# to display something it was given is not a control.
from pydantic import BaseModel, Field  # noqa: E402

from ..services import cashup as cashup_svc  # noqa: E402


class CountIn(BaseModel):
    """A committed count. Submitting this is what makes the expected visible."""
    counted: dict[str, float] = Field(default_factory=dict)
    # {"100": 3, "20": 5, "0.5": 2} — what was physically in the drawer.
    coinage: dict[str, int] = Field(default_factory=dict)
    currency: str = "USD"
    notes: str = ""
    till_no: str = ""
    draw_no: str = ""


@router.get("/cashup/denominations")
def cashup_denominations(currency: str = ""):
    """The notes and coins to count, biggest first.

    From the jurisdiction pack rather than hard-coded. The system we are
    replacing lists pounds, which is a locale default nobody ever changed, and
    a Zimbabwean drawer holds neither pounds nor a single currency.
    """
    from ..config import settings

    pack = settings.jurisdiction
    codes = [c.code for c in pack.currencies]
    chosen = (currency or pack.base_currency.code).upper()
    return {
        "currencies": codes,
        "currency": chosen,
        "denominations": cashup_svc.denominations(chosen),
        "tenders": [{"method": m, "label": l} for m, l in cashup_svc.TENDERS],
    }


@router.post("/{shift_id}/cashup")
def submit_cashup(
    shift_id: int, body: CountIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Commit a count and get the reconciliation back.

    One shot. Re-counting after seeing the variance is exactly the behaviour a
    blind count exists to prevent, so a shift that has been counted is refused
    rather than quietly overwritten — a correction is a supervisor's job and
    leaves its own record.
    """
    shift = db.query(Shift).get(shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="That shift no longer exists.")
    if getattr(shift, "counted_at", None):
        raise HTTPException(
            status_code=409,
            detail=(
                "This till has already been cashed up. Counting again after the "
                "variance is known would defeat the point of the count; ask a "
                "manager to record a correction instead."
            ),
        )

    counted = dict(body.counted or {})
    # Where a denomination count was entered, it wins. It is the only figure in
    # the whole exercise that was produced by counting objects rather than by
    # someone doing arithmetic in their head.
    if body.coinage:
        counted["cash"] = cashup_svc.count_from_coinage(body.coinage)

    result = cashup_svc.reconcile(db, shift, counted)
    result["currency"] = body.currency

    if body.till_no and body.till_no.strip() != (shift.till_no or ""):
        # The run number was allocated against whichever till the shift opened
        # on. Moving the cash-up to a different till without re-allocating would
        # leave it numbered in the old till's sequence — a run 47 on till 2 that
        # collides with till 2's real run 47.
        shift.till_no = body.till_no.strip()
        shift.run_number = _next_run_number(db, shift.till_no)
    if body.draw_no:
        shift.draw_no = body.draw_no.strip()
    shift.counted_by_id = user.id
    shift.counted_at = datetime.utcnow()
    cashup_svc.store(shift, result, body.coinage, body.notes)

    # Counting the drawer is what ends the shift. Leaving it open afterwards
    # would mean sales could land in a run that has already been reconciled,
    # and the count would silently stop being true.
    if shift.status == "open":
        shift.status = "closed"
        shift.closed_at = datetime.utcnow()
    db.commit()
    result["shift_closed"] = True
    return result


@router.get("/{shift_id}/invoices")
def run_invoices(shift_id: int, db: Session = Depends(get_db),
                 _: User = Depends(get_current_user)):
    """Every document in the run — sales, voids and credits.

    Available only once the drawer has been counted, and that is not a detail.
    The system this replaces puts the invoice list on the cash-up screen next to
    the count boxes, which hands the counter the expected figure in a form they
    only have to add up. Withholding the expected total while publishing its
    addends is not a blind count.

    Voids and credits are listed rather than filtered out, because they are what
    a supervisor is looking for: a void is the standard way to make a sale
    disappear after the money has been taken, and it leaves no trace in a list
    that only shows what was paid.
    """
    shift = db.get(Shift, shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="That shift no longer exists.")
    if not getattr(shift, "counted_at", None):
        raise HTTPException(
            status_code=409,
            detail=(
                "The invoices for a run can be listed once the drawer has been "
                "counted. Until then they would add up to the figure the count "
                "is meant to arrive at independently."
            ),
        )

    end = shift.closed_at or datetime.utcnow()
    sales = (
        db.query(Sale)
        .filter(Sale.created_at >= shift.opened_at, Sale.created_at <= end)
        .order_by(Sale.created_at)
        .all()
    )

    rows = []
    for sale in sales:
        methods = sorted({t.method for t in sale.tenders}) if sale.tenders \
            else ([sale.payment_method] if sale.payment_method else [])
        rows.append({
            "id": sale.id,
            "sale_number": sale.sale_number,
            "at": sale.created_at.isoformat() if sale.created_at else None,
            "status": sale.status,
            "total": round(float(sale.total or 0), 2),
            "methods": methods,
            "cashier_id": sale.cashier_id,
        })

    def summed(status: str) -> dict:
        picked = [r for r in rows if r["status"] == status]
        return {"count": len(picked),
                "total": round(sum(r["total"] for r in picked), 2)}

    # A run is normally a day at one till, but a till left open over a weekend is
    # not rare and there is no reason for one screen to carry thousands of rows.
    # The totals and counts are computed over everything and only the list is
    # shortened, with `showing` saying so — a truncated list reported as the whole
    # thing is the failure this codebase has made five times.
    LIMIT = 500
    return {
        "shift_id": shift.id,
        "till_no": shift.till_no,
        "run_number": shift.run_number,
        "draw_no": shift.draw_no,
        "documents": len(rows),
        "showing": min(len(rows), LIMIT),
        "paid": summed("paid"),
        "void": summed("void"),
        "credited": summed("credited"),
        "pending": summed("pending"),
        "invoices": rows[:LIMIT],
    }


@router.get("/{shift_id}/cashup")
def read_cashup(shift_id: int, db: Session = Depends(get_db)):
    """Read a cash-up back, after it has been committed."""
    shift = db.query(Shift).get(shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="That shift no longer exists.")
    if not getattr(shift, "counted_at", None):
        # Deliberately not the figures. Until a count exists there is nothing
        # to report, and answering with the expected total here would be a
        # back door around the blind count.
        raise HTTPException(
            status_code=404,
            detail="This till has not been cashed up yet.",
        )
    import json as _json

    stored = _json.loads(shift.cashup_json or "{}")
    return {
        "counted_at": shift.counted_at.isoformat(),
        "counted_by": shift.counted_by_id,
        **stored,
    }


# ---------------------------------------------------------------- petty cash
class PettyCashIn(BaseModel):
    """Money out of the drawer, or into it.

    Signed: negative is a payout, positive is a top-up. One field and a sign
    beats two fields and a rule about which one to use.
    """
    amount: float
    #: Which drawer it came out of. The column has been on the record since it
    #: was written and nothing ever sent one, so every payout in a pharmacy
    #: running two currencies was an amount with no currency — and a ZiG taxi
    #: fare taken off the USD drawer is a variance nobody can explain.
    currency_code: str = ""
    category: str = ""
    description: str = ""
    reference: str = ""
    receipt_seen: bool = False


@router.post("/petty-cash")
def add_petty_cash(
    body: PettyCashIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
    _grant=Depends(require_step_up("pettycash.record")),
):
    from ..models import PettyCash

    if not body.amount:
        raise HTTPException(status_code=400, detail="Enter an amount.")
    if not body.description.strip():
        # The whole value of this record is what the money was for. An entry
        # reading "-20.00" and nothing else is not a record, it is a hole with
        # a number beside it.
        raise HTTPException(
            status_code=400,
            detail="Say what the money was for. That is the point of the record.",
        )

    shift = current_open_shift(db, user.id)
    row = PettyCash(
        shift_id=shift.id if shift else None,
        branch_id=getattr(shift, "branch_id", None) if shift else None,
        amount=round(body.amount, 2),
        currency_code=(body.currency_code or "").strip().upper()[:5],
        category=body.category.strip(),
        description=body.description.strip(),
        reference=body.reference.strip(),
        receipt_seen=body.receipt_seen,
        user_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    direction = "out of" if row.amount < 0 else "into"
    return {
        "id": row.id,
        "amount": row.amount,
        "message": f"{abs(row.amount):.2f} recorded {direction} the drawer.",
    }


@router.get("/petty-cash")
def list_petty_cash(
    limit: int = 50, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """This shift's entries, so the person at the till can see what they logged."""
    from ..models import PettyCash

    shift = current_open_shift(db, user.id)
    query = db.query(PettyCash)
    if shift:
        query = query.filter(PettyCash.shift_id == shift.id)
    rows = query.order_by(PettyCash.created_at.desc()).limit(max(1, min(limit, 200))).all()
    return {
        "net": round(sum(r.amount for r in rows), 2),
        "entries": [
            {
                "id": r.id, "amount": r.amount, "category": r.category,
                "description": r.description, "reference": r.reference,
                "receipt_seen": r.receipt_seen,
                # Who took the money out. The relationship existed and was never
                # returned, so a screen could show every payout without showing
                # who made it — which is most of what a petty-cash control is for.
                "user": r.user.full_name if r.user else "",
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }
