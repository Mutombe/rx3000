"""Short-dated stock, valued at what it is actually worth.

Inventory is carried at the lower of cost and what it will realistically fetch.
A shelf of amoxicillin expiring in three weeks will not fetch cost: some of it
sells, the rest is destroyed, and the pharmacy has already lost the difference
whether or not anybody has written it down. Until now the ledger carried every
batch at full cost right up to the day it expired, and then took the whole loss
at once — so the accounts said the pharmacy was worth more than it was, every
month, and then took a lump on the month somebody happened to write off.

**What is posted is the movement, not the balance.** The provision required today
is a stock figure; the journal entry is the difference between that and what is
already provided. Posting the full requirement every month would charge the same
loss again and again, which is the mistake this kind of routine most often makes
and the hardest to spot afterwards, because each entry looks correct on its own.

**It reverses on its own.** Stock that sells, or is written off properly, leaves
the batch table; the requirement recomputes lower next time and the entry is a
credit. Nothing has to remember to release it.

The bands are judgement, not law. IAS 2 says lower of cost and net realisable
value and does not say what a Zimbabwean pharmacy can shift in sixty days, so the
figures are stated here, in one place, for an accountant to argue with.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..models import Account, JournalEntry, Product, StockBatch
from . import ledger

#: The provision account pair. Added to the chart if a pharmacy predates them.
PROVISION_ACCOUNT = ("1250", "Provision for short-dated stock", "asset", "stock")
EXPENSE_ACCOUNT = ("5110", "Short-dated stock provision", "expense", "")

#: How much of cost is provided against, by days remaining. Ordered tightest
#: first, and read as "at or under this many days".
#:
#: Past expiry is 100% because it cannot legally be sold at all. Inside a month
#: is most of it: a chronic line might move, an antibiotic will not. Beyond
#: ninety days nothing is provided — that is ordinary stock.
BANDS: list[tuple[int, float, str]] = [
    (0, 1.00, "Expired. It cannot be sold and is worth nothing."),
    (30, 0.75, "Under a month. Most of this will not move in time."),
    (60, 0.40, "Under two months. Some will sell, much of it will not."),
    (90, 0.15, "Under three months. Worth watching and worth discounting."),
]

#: The reference every entry from this routine carries, so it can be found,
#: recognised and reversed as a group.
REFERENCE_PREFIX = "PROV-EXPIRY"


@dataclass
class BatchExposure:
    batch_id: int
    product: str
    batch_number: str
    expiry: date | None
    quantity: int
    unit_cost: float
    days_left: int
    rate: float
    reason: str

    @property
    def at_cost(self) -> float:
        return round(self.quantity * self.unit_cost, 2)

    @property
    def provision(self) -> float:
        return round(self.at_cost * self.rate, 2)


def _rate(days_left: int) -> tuple[float, str]:
    for limit, rate, reason in BANDS:
        if days_left <= limit:
            return rate, reason
    return 0.0, ""


def exposure(db: Session, *, asof: date | None = None) -> dict:
    """What the provision should be today, batch by batch.

    Reads stock rather than the ledger, because the question is about what is on
    the shelf. The ledger answers the second question, which is how much of this
    has already been recognised.
    """
    asof = asof or date.today()
    horizon = asof + timedelta(days=BANDS[-1][0])

    rows = (db.query(StockBatch, Product)
              .join(Product, StockBatch.product_id == Product.id)
              .filter(StockBatch.quantity_remaining > 0,
                      StockBatch.expiry_date.isnot(None),
                      StockBatch.expiry_date <= horizon)
              .order_by(StockBatch.expiry_date.asc())
              .all())

    items: list[BatchExposure] = []
    for batch, product in rows:
        days = (batch.expiry_date - asof).days
        rate, reason = _rate(days)
        if rate <= 0:
            continue
        # The batch's own cost where it has one, the product's otherwise. A
        # batch received at a different price is the whole reason batch costing
        # exists, so its figure wins.
        cost = batch.unit_cost or product.cost_price or 0.0
        items.append(BatchExposure(
            batch_id=batch.id,
            product=f"{product.name} {product.strength or ''}".strip(),
            batch_number=batch.batch_number or "",
            expiry=batch.expiry_date,
            quantity=batch.quantity_remaining or 0,
            unit_cost=cost,
            days_left=days,
            rate=rate,
            reason=reason,
        ))

    required = round(sum(i.provision for i in items), 2)
    bands: dict[str, dict] = {}
    for limit, rate, reason in BANDS:
        label = ("Already expired" if limit == 0 else f"Within {limit} days")
        band = [i for i in items if i.rate == rate]
        bands[label] = {
            "rate": rate,
            "batches": len(band),
            "at_cost": round(sum(i.at_cost for i in band), 2),
            "provision": round(sum(i.provision for i in band), 2),
            "reason": reason,
        }

    return {
        "asof": asof,
        "items": [{
            "batch_id": i.batch_id, "product": i.product,
            "batch_number": i.batch_number, "expiry": i.expiry,
            "quantity": i.quantity, "unit_cost": round(i.unit_cost, 2),
            "days_left": i.days_left, "rate": i.rate,
            "at_cost": i.at_cost, "provision": i.provision, "reason": i.reason,
        } for i in items],
        "bands": bands,
        "stock_at_risk": round(sum(i.at_cost for i in items), 2),
        "required": required,
        "carried": carried(db),
        # The number that would actually be posted. Said before anybody presses
        # anything, because an accounting routine whose effect is only visible
        # afterwards is one nobody runs twice.
        "movement": round(required - carried(db), 2),
    }


def carried(db: Session) -> float:
    """What is already provided, from the ledger rather than from memory.

    Nothing provided is zero, not an error. A pharmacy that has never run this
    has no provision account yet, and asking what its exposure is should answer
    the question rather than refuse because of a chart entry that has not been
    needed until now.
    """
    try:
        return round(abs(ledger.balance(db, PROVISION_ACCOUNT[0])), 2)
    except ledger.LedgerError:
        return 0.0


def _ensure_accounts(db: Session) -> None:
    """Add the provision pair to a chart that predates this routine."""
    for code, name, kind, subledger in (PROVISION_ACCOUNT, EXPENSE_ACCOUNT):
        if not db.query(Account).filter(Account.code == code).first():
            db.add(Account(code=code, name=name, type=kind, subledger=subledger))
    db.commit()


def post(db: Session, *, asof: date | None = None, user_id: int | None = None) -> dict:
    """Post the movement in the provision, and nothing if there is none.

    Returns what it did rather than raising when there is nothing to do: "the
    provision is already right" is a successful outcome and should not read as a
    failure on a screen somebody runs monthly.
    """
    _ensure_accounts(db)
    asof = asof or date.today()
    state = exposure(db, asof=asof)
    movement = state["movement"]

    if abs(movement) < 0.01:
        return {"posted": False, "movement": 0.0,
                "message": "The provision already matches the stock on hand. "
                           "Nothing to post.",
                **{k: state[k] for k in ("required", "carried", "stock_at_risk")}}

    # A rise charges the expense and increases the contra-asset; a fall does the
    # reverse. Written as one signed pair rather than two branches, because two
    # branches is where the sign gets flipped.
    lines = [
        ledger.Line(account_code=EXPENSE_ACCOUNT[0], debit=max(movement, 0.0),
                    credit=max(-movement, 0.0),
                    description="Provision against short-dated stock"),
        ledger.Line(account_code=PROVISION_ACCOUNT[0], debit=max(-movement, 0.0),
                    credit=max(movement, 0.0),
                    description="Provision against short-dated stock"),
    ]
    entry = ledger.post(
        db, entry_date=asof,
        description=(f"Short-dated stock provision to {asof:%d %b %Y}: "
                     f"{'increase' if movement > 0 else 'release'} of "
                     f"{abs(movement):.2f}"),
        lines=lines,
        source=REFERENCE_PREFIX,
        user_id=user_id,
    )
    return {
        "posted": True,
        "movement": movement,
        "entry_id": entry.id,
        "reference": entry.reference,
        "message": (f"Charged {movement:.2f} to the provision."
                    if movement > 0 else
                    f"Released {abs(movement):.2f} back; the stock at risk has fallen."),
        **{k: state[k] for k in ("required", "carried", "stock_at_risk")},
    }


def history(db: Session, limit: int = 24) -> list[dict]:
    """Every provision entry, newest first, so the running charge is visible."""
    rows = (db.query(JournalEntry)
              .filter(JournalEntry.source == REFERENCE_PREFIX)
              .order_by(JournalEntry.entry_date.desc())
              .limit(limit).all())
    out = []
    for e in rows:
        charge = sum((l.debit or 0) for l in e.lines
                     if l.account_code == EXPENSE_ACCOUNT[0])
        release = sum((l.credit or 0) for l in e.lines
                      if l.account_code == EXPENSE_ACCOUNT[0])
        out.append({
            "id": e.id, "reference": e.reference, "entry_date": e.entry_date,
            "description": e.description,
            "movement": round(charge - release, 2),
        })
    return out
