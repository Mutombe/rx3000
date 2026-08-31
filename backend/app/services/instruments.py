"""The one list of what money can arrive on.

The till and the cash-up used to hold their own idea of this, and the two did
not match. The till knew the customer paid on EcoCash and wrote it into the
front of a free-text reference; the takings screen read it back out by
splitting on a space; the cash-up did not read it at all and reconciled seven
hard-coded families instead. So a shift could show five instrument rows on one
screen and a single "Mobile money" line on another, and nobody could say which
was right.

Worse, the cash-up built its reconciliation lines from a constant. Money taken
on any method outside that constant was counted into the totals and then never
printed, because the lines were built from the list rather than from what
actually moved. A till taking 30 on EcoCash, 20 on InnBucks and 45 cash on
delivery reconciled to 50 and said nothing about the other 45.

Both come from here now. The cash-up cannot disagree with the register about
what the columns are, because there is one list and it is a table.

DEFAULTS

The seed below is Zimbabwe as it actually trades: USD and ZiG side by side,
three mobile wallets that settle separately, swipe split by acquiring bank
because that is what the statements look like, and cash on delivery, which is
money the shop is owed by a driver rather than money in a drawer.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import PaymentInstrument

#: (code, name, method, currencies, drawer?, delivery?, order)
#:
#: `drawer` means it is physically in the till at close of trade and somebody
#: counts it. `delivery` means a driver is holding it and the round is out.
DEFAULTS = [
    ("cash_usd",   "Cash (USD)",        "cash",         "USD",     True,  False, 10),
    ("cash_zwg",   "Cash (ZiG)",        "cash",         "ZWG",     True,  False, 20),
    ("ecocash",    "EcoCash",           "mobile_money", "USD,ZWG", False, False, 30),
    ("omari",      "Omari",             "mobile_money", "ZWG,USD", False, False, 40),
    ("innbucks",   "InnBucks",          "mobile_money", "USD",     False, False, 50),
    ("swipe",      "Swipe (card)",      "card",         "USD,ZWG", False, False, 60),
    ("medical_aid", "Medical aid",      "medical_aid",  "USD",     False, False, 70),
    ("cod",        "Cash on delivery",  "cash",         "USD,ZWG", False, True,  80),
    ("delivery_fee", "Delivery fee",    "cash",         "USD,ZWG", False, True,  85),
    ("voucher",    "Voucher",           "voucher",      "USD",     False, False, 90),
    ("direct",     "Direct deposit",    "direct",       "USD,ZWG", False, False, 100),
]

#: What the coarse families are called where an instrument cannot be named.
#: Kept because the ledger and the older reports group on the method.
METHOD_LABELS = {
    "cash": "Cash", "card": "Card", "mobile_money": "Mobile money",
    "medical_aid": "Medical aid", "voucher": "Vouchers", "cheque": "Cheques",
    "direct": "Direct deposit", "account": "On account", "loyalty": "Loyalty",
}


def ensure(db: Session, pharmacy_id: int) -> int:
    """Give a pharmacy the default list if it has none.

    Only ever adds what is missing. A pharmacy that has renamed "Swipe" to
    "Card machine" or retired InnBucks keeps its own list — this is a starting
    point, not a definition.
    """
    have = {i.code for i in db.query(PaymentInstrument)
            .filter(PaymentInstrument.pharmacy_id == pharmacy_id).all()}
    added = 0
    for code, name, method, currencies, drawer, delivery, order in DEFAULTS:
        if code in have:
            continue
        db.add(PaymentInstrument(
            pharmacy_id=pharmacy_id, code=code, name=name, method=method,
            currencies=currencies, is_cash_drawer=drawer, is_delivery=delivery,
            sort_order=order, active=True))
        added += 1
    if added:
        db.flush()
    return added


def listing(db: Session, *, include_retired: bool = False) -> list[PaymentInstrument]:
    q = db.query(PaymentInstrument)
    if not include_retired:
        q = q.filter(PaymentInstrument.active.is_(True))
    return q.order_by(PaymentInstrument.sort_order, PaymentInstrument.name).all()


def by_code(db: Session) -> dict[str, PaymentInstrument]:
    return {i.code: i for i in db.query(PaymentInstrument).all()}


def resolve(db: Session, *, instrument: str = "", method: str = "",
            currency_code: str = "", reference: str = "") -> str:
    """The instrument code for a payment, from whatever the caller knew.

    A till that names the instrument outright is believed. One that does not —
    an older client, an import, a script — has it inferred, in this order:

      1. the reference, because the till used to write the wallet into the
         front of it and there are years of rows shaped that way;
      2. the method and currency, which is enough for cash and for anything
         with only one instrument behind it.

    Returns "" rather than guessing where the answer is genuinely not there.
    An unnamed instrument shows up in the cash-up as its method — visible and
    reconcilable but not attributed, which is honest. Inventing an attribution
    puts money against a wallet nobody will find it in.
    """
    known = by_code(db)
    if instrument and instrument in known:
        return instrument

    first = (reference or "").strip().split(" ")[0].strip("-:").lower()
    if first:
        # "EcoCash 0779…", "Ecocash-0779", "InnBucks".
        squashed = first.replace("-", "").replace("_", "")
        for code, inst in known.items():
            if squashed == code.replace("_", "") or squashed == inst.name.lower().replace(" ", ""):
                return code

    code = (currency_code or "").upper()
    if method == "cash" and code:
        want = f"cash_{code.lower()}"
        if want in known:
            return want
    candidates = [c for c, i in known.items()
                  if i.method == method and i.active and not i.is_delivery]
    if len(candidates) == 1:
        return candidates[0]
    return ""
