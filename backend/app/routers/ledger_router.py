"""General ledger: chart, journal, trial balance, subledger reconciliation."""
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..services import paging
from ..models import Account, JournalEntry, User
from ..services import bank_recon, ledger, posting, reporting, statements

router = APIRouter(prefix="/api/ledger", tags=["ledger"],
                   dependencies=[Depends(get_current_user)])


@router.get("/accounts")
def accounts(subledger: str = "", db: Session = Depends(get_db)):
    ledger.ensure_chart(db)
    query = db.query(Account).filter(Account.active)
    if subledger:
        query = query.filter(Account.subledger == subledger)
    return [{"code": a.code, "name": a.name, "type": a.type,
             "subledger": a.subledger,
             "balance": ledger.balance(db, a.code)}
            for a in query.order_by(Account.code).all()]


@router.post("/entries")
def create_entry(description: str = Body(...),
                 lines: list[dict] = Body(...),
                 entry_date: date | None = Body(default=None),
                 source: str = Body(default="manual"),
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Post a journal entry. It balances or it does not post."""
    ledger.ensure_chart(db)
    try:
        entry = ledger.post(
            db, entry_date=entry_date or date.today(), description=description,
            lines=[ledger.Line(
                account_code=str(l.get("account_code", "")),
                debit=float(l.get("debit") or 0), credit=float(l.get("credit") or 0),
                description=str(l.get("description", "")),
                party_type=str(l.get("party_type", "")),
                party_id=l.get("party_id"),
            ) for l in lines],
            source=source, user_id=user.id)
    except ledger.LedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _entry(entry)


def _entry(entry: JournalEntry) -> dict:
    return {
        "id": entry.id, "reference": entry.reference,
        "period_code": entry.period_code, "entry_date": entry.entry_date,
        "description": entry.description, "source": entry.source,
        "source_id": entry.source_id, "status": entry.status,
        "reverses_id": entry.reverses_id,
        "created_by": entry.created_by.full_name if entry.created_by else "",
        "lines": [{"account_code": l.account_code, "debit": l.debit,
                   "credit": l.credit, "description": l.description,
                   "party_type": l.party_type, "party_id": l.party_id}
                  for l in entry.lines],
        "total": round(sum(l.debit for l in entry.lines), 2),
    }


@router.get("/entries")
def entries(period_code: str = "", source: str = "", limit: int = 100,
            db: Session = Depends(get_db)):
    query = db.query(JournalEntry)
    if period_code:
        query = query.filter(JournalEntry.period_code == period_code)
    if source:
        query = query.filter(JournalEntry.source == source)
    return [_entry(e) for e in
            query.order_by(desc(JournalEntry.entry_date),
                           desc(JournalEntry.id)).limit(limit).all()]


@router.get("/entries/paged")
def entries_paged(period_code: str = "", source: str = "",
                  page: int = 1, per_page: int = paging.DEFAULT_PER_PAGE,
                  db: Session = Depends(get_db)):
    """The journal, paged. 2,129 entries behind a cap of 100.

    A ledger that cannot show its own history is not a ledger anyone can audit,
    and "the most recent hundred" is the wrong hundred whenever the question is
    about last quarter.
    """
    query = db.query(JournalEntry)
    if period_code:
        query = query.filter(JournalEntry.period_code == period_code)
    if source:
        query = query.filter(JournalEntry.source == source)
    result = paging.page(query.order_by(desc(JournalEntry.entry_date),
                                        desc(JournalEntry.id)),
                         page=page, per_page=per_page)
    return result.envelope(_entry)


@router.get("/entries/{entry_id}")
def entry(entry_id: int, db: Session = Depends(get_db)):
    found = db.get(JournalEntry, entry_id)
    if not found:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return _entry(found)


@router.post("/entries/{entry_id}/reverse")
def reverse(entry_id: int, reason: str = Body(default="", embed=True),
            on: date | None = Body(default=None, embed=True),
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Reverse an entry. A posted entry is never edited or deleted."""
    found = db.get(JournalEntry, entry_id)
    if not found:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    try:
        reversal = ledger.reverse(db, found, on=on, reason=reason, user_id=user.id)
    except ledger.LedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"reversed": found.reference, "reversal": _entry(reversal)}


@router.get("/trial-balance")
def trial_balance(period_code: str = "", upto: date | None = None,
                  db: Session = Depends(get_db)):
    ledger.ensure_chart(db)
    return ledger.trial_balance(db, period_code=period_code, upto=upto)


@router.get("/subledgers/{name}")
def subledger(name: str, period_code: str = "", db: Session = Depends(get_db)):
    try:
        return ledger.subledger(db, name, period_code=period_code)
    except ledger.LedgerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/subledgers/{name}/reconcile")
def reconcile(name: str, period_code: str = "", db: Session = Depends(get_db)):
    """Does the control account agree with the subledger behind it?

    The most useful check in a ledger, because it catches what nothing else can:
    a posting made around the subledger rather than through it.
    """
    try:
        return ledger.reconcile_control(db, name, period_code=period_code)
    except ledger.LedgerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/unposted")
def unposted(limit: int = 200, db: Session = Depends(get_db)):
    """Sales the ledger has not caught up with.

    Posting is deliberately non-fatal — a till must not refuse to sell medicine
    because the bookkeeping is unhappy — so this queue is what stops "briefly
    behind" becoming "quietly wrong". It is the first thing to read when the
    trial balance does not agree with the till.
    """
    rows = posting.unposted_sales(db, limit)
    return {"count": len(rows), "sales": rows,
            "message": "" if not rows else
                       f"{len(rows)} settled sale(s) have not reached the ledger."}


@router.post("/post-sale/{sale_id}")
def post_sale(sale_id: int, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """Post a sale that did not reach the ledger. Idempotent."""
    from ..models import Sale
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    return posting.post_sale(db, sale, user.id)


@router.get("/accounts/{code}")
def account_detail(code: str, period_code: str = "", limit: int = 200,
                   db: Session = Depends(get_db)):
    """One account, and every line that moved it.

    The page an accountant reaches from a trial-balance figure that looks wrong.
    A running balance is carried down the rows, because "what was this account
    at on the 14th" is the question that gets asked and it cannot be answered by
    a list of movements alone.
    """
    from ..models import JournalLine

    account = db.query(Account).filter(Account.code == code).first()
    if not account:
        raise HTTPException(status_code=404, detail=f"No account {code}")

    query = (db.query(JournalLine, JournalEntry)
             .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
             .filter(JournalLine.account_code == code))
    if period_code:
        query = query.filter(JournalEntry.period_code == period_code)
    # The most recent movements, then reversed for reading — an account with
    # thousands of lines is asked "what has happened lately", not "what happened
    # first". Crucially the window is carried on an OPENING BALANCE rather than
    # started from zero: running the column from zero over a truncated window
    # produces a closing figure that disagrees with the account, and a balance
    # column that does not end where the account does is worse than no column.
    total_movement = 0.0
    rows = (query.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
            .limit(limit).all())
    rows = list(reversed(rows))

    debit_positive = account.type in ledger.DEBIT_POSITIVE
    closing = ledger.balance(db, code, period_code=period_code)
    for line, _entry in rows:
        movement = line.debit - line.credit
        total_movement += movement if debit_positive else -movement
    running = round(closing - total_movement, 2)   # opening balance
    opening = running
    lines = []
    for line, entry in rows:
        movement = line.debit - line.credit
        running += movement if debit_positive else -movement
        lines.append({
            "entry_id": entry.id, "reference": entry.reference,
            "entry_date": entry.entry_date, "period_code": entry.period_code,
            "description": line.description or entry.description,
            "source": entry.source, "source_id": entry.source_id,
            "status": entry.status,
            "party_type": line.party_type, "party_id": line.party_id,
            "debit": round(line.debit, 2), "credit": round(line.credit, 2),
            "balance": round(running, 2),
        })

    return {
        "code": account.code, "name": account.name, "type": account.type,
        "subledger": account.subledger,
        "balance": closing,
        "opening_balance": opening,
        "truncated": len(rows) >= limit,
        "line_count": len(lines),
        "lines": lines,
    }


@router.get("/unposted-receipts")
def unposted_receipts(limit: int = 200, db: Session = Depends(get_db)):
    """Received orders the ledger has not caught up with.

    The purchase-side twin of /unposted. Between them they answer "is the ledger
    a complete picture of the business", which is the only question that makes a
    trial balance worth reading.
    """
    rows = posting.unposted_receipts(db, limit)
    return {"count": len(rows), "orders": rows,
            "message": "" if not rows else
                       f"{len(rows)} received order(s) have not reached the ledger."}


@router.post("/post-receipt/{order_id}")
def post_receipt(order_id: int, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    from ..models import PurchaseOrder
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return posting.post_stock_receipt(db, order, user.id)


# ---------------------------------------------------------------------------
# Financial reports — every figure off the ledger, none off the transactions
# ---------------------------------------------------------------------------

@router.get("/ageing/{subledger}")
def ageing(subledger: str, asof: date | None = None, db: Session = Depends(get_db)):
    """How old the money is, by who owes it. The buckets are the report."""
    try:
        return reporting.ageing(db, subledger, asof=asof)
    except ledger.LedgerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/vat-return/{period_code}")
def vat_return(period_code: str, db: Session = Depends(get_db)):
    try:
        return reporting.vat_return(db, period_code)
    except ledger.LedgerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _year_start(upto: date) -> date:
    """The start of the financial year `upto` falls in.

    Taken from the jurisdiction pack rather than assumed to be January. A
    year-end in the wrong month puts the whole of the current year's profit in
    the wrong period, and the balance sheet still balances while being wrong.
    """
    from ..config import settings

    j = settings.jurisdiction
    month = getattr(j, "tax_year_start_month", 1) or 1
    day = getattr(j, "tax_year_start_day", 1) or 1
    start = date(upto.year, month, day)
    return start if start <= upto else date(upto.year - 1, month, day)


@router.get("/income-statement")
def income_statement(
    start: date | None = None, upto: date | None = None,
    period_code: str = "", hide_zero: bool = False,
    db: Session = Depends(get_db),
):
    """Revenue through to profit, with cost of sales separated out.

    `period_code` is still accepted so existing callers keep working, but the
    window is what actually drives this: the old report summed all time, which
    quietly folded every previous year's trading into "profit".
    """
    upto = upto or date.today()
    return statements.income_statement(
        db, start=start or _year_start(upto), upto=upto, hide_zero=hide_zero)


@router.get("/balance-sheet")
def balance_sheet(
    asof: date | None = None, upto: date | None = None,
    hide_zero: bool = False, db: Session = Depends(get_db),
):
    """Position at a date, split current and non-current.

    `asof` is the original parameter name and still works.
    """
    at = upto or asof or date.today()
    return statements.balance_sheet(
        db, upto=at, year_start=_year_start(at), hide_zero=hide_zero)


@router.post("/backfill")
def backfill(limit: int = Body(default=500, embed=True),
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Post the history that predates the posting logic.

    Deliberately explicit and deliberately capped. Backfilling silently on
    startup would mean a pharmacy's opening ledger appeared from nowhere one
    morning; making it an action means somebody chose the moment and can say
    which figures moved.

    Idempotent throughout — every posting checks whether its source already
    posted — so running it twice is safe and running it in batches is the
    expected way to work through a large history.
    """
    from ..models import PurchaseOrder, Sale

    sales = posting.unposted_sales(db, limit)
    receipts = posting.unposted_receipts(db, limit)
    posted_sales = posted_receipts = 0
    refused: list[dict] = []

    for row in sales:
        sale = db.get(Sale, row["sale_id"])
        result = posting.post_sale(db, sale, user.id) if sale else {"posted": False}
        if result.get("posted"):
            posted_sales += 1
        elif result.get("reason"):
            refused.append({"kind": "sale", "ref": row["sale_number"],
                            "reason": result["reason"][:160]})

    for row in receipts:
        order = db.get(PurchaseOrder, row["order_id"])
        result = posting.post_stock_receipt(db, order, user.id) if order else {"posted": False}
        if result.get("posted"):
            posted_receipts += 1
        elif result.get("reason"):
            refused.append({"kind": "receipt", "ref": row["order_number"],
                            "reason": result["reason"][:160]})

    tb = ledger.trial_balance(db)
    return {
        "sales_posted": posted_sales,
        "receipts_posted": posted_receipts,
        "refused": refused[:50],
        "refused_count": len(refused),
        "still_unposted_sales": len(posting.unposted_sales(db, limit)),
        "still_unposted_receipts": len(posting.unposted_receipts(db, limit)),
        "trial_balance_balanced": tb["balanced"],
    }


@router.post("/bank-reconciliation")
def bank_reconciliation(account_code: str = Body(default="1010"),
                        content: str = Body(...),
                        db: Session = Depends(get_db)):
    """Reconcile a bank statement against an account.

    The point is the difference, not the match: a list of specific things to
    chase, rather than a balance that "looks wrong". Nothing is posted — an
    unmatched line is reported with the entry that would fix it proposed, and
    somebody decides.
    """
    try:
        lines = bank_recon.parse_statement(content)
        return bank_recon.reconcile(db, account_code=account_code, lines=lines)
    except bank_recon.ReconError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
