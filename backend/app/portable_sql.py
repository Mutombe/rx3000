"""SQL that means the same thing on both databases the system runs on.

The server runs on PostgreSQL and the desktop install runs on SQLite, from one
codebase. Most of SQLAlchemy hides the difference; a few functions do not, and
the ones that do not fail at the worst moment — not at startup, not in a test
that runs on the developer's Postgres, but on a pharmacist's laptop, on one
screen, as a 500.

`func.greatest` was the first: three reporting queries divided by it to turn a
pack price into a unit price, and every one of them answered "no such function:
greatest" on SQLite. The dashboard of the desktop build did not load at all.
"""
from __future__ import annotations

from sqlalchemy import case, func


def at_least(column, floor: int = 1):
    """`column`, or `floor` where it is smaller, missing or nought.

    Written as a CASE because that is the one spelling both databases read.
    SQLite has `max(a, b)`, PostgreSQL spells the same thing `greatest`, and
    each rejects the other's name.
    """
    value = func.coalesce(column, floor)
    return case((value > floor, value), else_=floor)
