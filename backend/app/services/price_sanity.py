"""Prices that cannot be right, caught while a file is still a preview.

CareXpress's own stock export carries a selling price of 3,145,500,000.00 for
PHENOBARBITONE 30MG TABS (VAR) 1000S, against a cost of 14.60. Their own
system totals that line at 629,100,000 and carries it forward into their stock
value. One row in 16,038, and 99.96 per cent of the retail total of the whole
pharmacy.

We imported it faithfully, which is right: an importer that quietly corrects
what a pharmacy's own system says is an importer nobody can reconcile against.
What was missing is anybody being TOLD. The row went in, the valuation screen
read six hundred and twenty nine billion, and nothing anywhere said why.

WHY NOT A FIXED CEILING

Because there is no number to pick. This is Zimbabwe, where a currency has
been redenominated three times inside twenty years, and the product is also
sold into South Africa. "No medicine costs more than a thousand" is a
sentence that is wrong somewhere today and wrong everywhere eventually.

So the file is measured against itself. The median price in the import is the
yardstick, which costs nothing to compute and carries no assumption about the
currency, the country or the decade.

WHY TWO SIGNALS, BOTH REQUIRED

Measured on that real file, with a median price of 4.35:

  at  100x the median   24 rows, including real oncology drugs at 3,660
  at  500x the median    6 rows, still including those
  at 1000x the median    1 row, the phenobarbitone, and nothing else

A thousand times the median separates it cleanly here. It would not
everywhere: a pharmacy whose median line is a 4.00 lozenge and which stocks
one 50,000.00 oncology course would see that course flagged, and there is
nothing wrong with it.

The second signal settles those. A genuinely expensive medicine is expensive
to BUY: it is priced a little above a large cost. A typed price is priced
absurdly above a small one. Phesgo at 3,660 sits near its cost; the
phenobarbitone sits at 215 million times its own. Both signals have to fire,
so an expensive line with a sane margin is never flagged however dear it is.

WHY A NUMBER THIS BIG IS STILL NOT REFUSED

Because it is the pharmacy's own record, the quantity beside it is real, and
refusing the row would leave the stock uncounted to punish a price. The row
goes in and the preview says which rows to look at. A pharmacist can then fix
it in the system it came from, which is the only place fixing it lasts.

AND WHY IT IS RAISED EVEN ON A ROW THAT IS NOT BEING LOADED

The first version of this skipped refused rows, on the reasoning that a row
nothing is written from cannot do any harm. It then found nothing at all on
the file it was written for: that phenobarbitone row is refused for an
unrelated fault, a quantity with no expiry date beside it.

The reasoning was wrong anyway. The price is not wrong because we are about to
load it. It is wrong in the pharmacy's own system, where it is already
producing their own total of 629,100,000, and it will still be wrong after
this upload is abandoned. The finding is about their data, not about our
write, so the sentence states the fact and leaves the disposition to the row's
own action.
"""
from __future__ import annotations

from statistics import median

#: How far above the file's own median a price has to sit before it is worth
#: a second look. Set from the evidence above: 500 still caught real oncology
#: drugs, 1000 caught only the impossible row.
OUTLIER = 1000

#: And how far above its own cost. A pharmacy's markup is tens of per cent; a
#: hundred times over is not a margin, it is a typing mistake. Only applied
#: where the cost is big enough to divide by, because a placeholder cost of
#: 0.01 makes an ordinary 8.00 lozenge look like an 800 times markup, and
#: there are five of those in this one file.
MARKUP = 100

#: Below this a cost is a placeholder rather than a price paid.
REAL_COST = 0.05


def _sane_median(values: list[float]) -> float:
    """The middle price, or 0 when there is nothing to measure against."""
    real = [v for v in values if v and v > 0]
    return median(real) if real else 0.0


def screen(rows: list[dict]) -> dict[int, str]:
    """Which rows carry a price that cannot be right, and why.

    `rows` are dicts with `row` (the line number a person sees), `price` and
    `cost`. Returns {row number: a sentence}, empty when nothing is wrong,
    which is the ordinary case and costs one pass over the prices.
    """
    prices = [float(r.get("price") or 0) for r in rows]
    middle = _sane_median(prices)
    if not middle:
        return {}

    ceiling = middle * OUTLIER
    found: dict[int, str] = {}
    for r in rows:
        price = float(r.get("price") or 0)
        if price <= ceiling:
            continue
        cost = float(r.get("cost") or 0)
        # An expensive medicine is expensive to buy. Where the cost stands
        # behind the price, the price is believed however large it is.
        if cost >= REAL_COST and price <= cost * MARKUP:
            continue
        times = f"{price / middle:,.0f}"
        against = (f" and {price / cost:,.0f} times its own cost of {cost:,.2f}"
                   if cost >= REAL_COST else ", with no cost recorded to stand behind it")
        found[int(r.get("row") or 0)] = (
            f"{price:,.2f} is {times} times the middle price in this file"
            f"{against}. Check it in the system it came from.")
    return found
