"""Is a held claim being written off as a rejection?

A funder can do three things with a claim, not two. It can pay it, refuse it,
or **hold** it — pending a document, a query, a clinical review. Everything in
this system read the money to decide which, and to money a held claim looks
exactly like a refused one: nothing arrived.

So a suspended claim was classified `rejected`, and a rejected claim has
exactly two destinations — billed to the patient, or written off. Both give
away money the scheme had not refused, and one of them also sends a bill to a
patient whose scheme is going to pay.

That is not a reporting nicety. On a book where suspensions run at a few per
cent, it is a standing leak that looks like ordinary claim attrition.

The other half matters as much: a genuine rejection must still read as a
rejection. A checker that called everything "held" would be the same failure
with the sign reversed — a pharmacy waiting forever on money nobody is going
to send.

    python qa/suspended-claims.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.services import era  # noqa: E402

#: (what the funder sent, claimed, paid, the status it must be given, why)
CASES = [
    ("SUSPENDED", 100.0, 0.0, "suspended",
     "the funder is holding it, and it pays when the query is answered"),
    ("HELD", 100.0, 0.0, "suspended", "the same thing, spelt differently"),
    ("PENDING_DOCS", 80.0, 0.0, "suspended",
     "waiting on a document the pharmacy can actually send"),
    ("UNDER REVIEW", 60.0, 0.0, "suspended",
     "clinical review — a decision has not been made"),
    ("QUERY", 45.0, 0.0, "suspended", "queried, not refused"),

    # And the ones that must NOT be softened into a hold.
    ("BENEFIT_EXHAUSTED", 100.0, 0.0, "rejected",
     "the benefit is gone; this is the patient's to pay and waiting for the "
     "funder would be waiting forever"),
    ("NOT_COVERED", 100.0, 0.0, "rejected", "the scheme does not cover it"),
    ("NO_AUTH", 100.0, 0.0, "rejected", "no authorisation was held"),
    ("LEVY", 100.0, 80.0, "short_paid", "a co-payment, and the 20 is billable"),
    ("PAID", 100.0, 100.0, "matched", "settled in full"),
    ("", 100.0, 100.0, "matched", "no reason code, and the money agrees"),
]


def main() -> int:
    failures: list[str] = []
    print(f"  {len(era.SUSPENDED_CODES)} spellings of 'held' are recognised, "
          f"because funders do not agree on one\n")

    for code, claimed, paid, want, why in CASES:
        status, _reason = era.classify({
            "amount_claimed": claimed, "amount_paid": paid, "reason_code": code,
        })
        ok = status == want
        print(f"  {'ok  ' if ok else 'FAIL'} {code or '(none)':<20} "
              f"{claimed:>7.2f} claimed, {paid:>7.2f} paid  ->  {status:<11} "
              f"{why}")
        if not ok:
            failures.append(
                f"{code or 'a line with no reason code'} was classified "
                f"{status!r} and must be {want!r}: {why}")

    # The consequence, stated rather than implied: a held line must not be in
    # the shortfall, because the shortfall is what gets billed or written off.
    print()
    held_in_shortfall = "suspended" in _shortfall_statuses()
    print(f"  {'FAIL' if held_in_shortfall else 'ok  '} a held claim is kept "
          f"out of the shortfall — it is not the patient's to pay")
    if held_in_shortfall:
        failures.append(
            "held claims are counted in the shortfall, so they go to a patient "
            "or a write-off, which gives away money the funder had not refused")

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("held, refused and short-paid are three different findings, and the "
          "money cannot tell them apart on its own")
    return 0


def _shortfall_statuses() -> set:
    """Which statuses the shortfall is summed over, read from the source."""
    import inspect
    import re

    source = inspect.getsource(era.reconcile)
    found = set()
    for match in re.finditer(r'l\.status in \(([^)]*)\)', source):
        found |= {s.strip().strip('"\'') for s in match.group(1).split(",")}
    return found


if __name__ == "__main__":
    raise SystemExit(main())
