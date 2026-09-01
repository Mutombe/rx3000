"""Server-side paging, with the total always reported.

The rule this exists to enforce: **a truncated list must say that it is
truncated.** A `.limit(100)` on its own is the most dangerous line in a query,
because it returns something that looks complete. A pharmacy with 5,000
patients sees 100 and no error — the software appears to work, and the answer is
simply wrong. We have already been bitten by exactly this once, when a running
balance limited to 200 rows closed 10,000 short.

So `page()` never returns rows without also returning how many there are. The
count is a second query rather than `len(rows)`, because `len(rows)` of a
limited query is the limit, which is the very lie being guarded against.
"""
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Query

# A page nobody chose. Large enough that most screens need one page, small
# enough that a slow connection is not asked for a megabyte of JSON.
DEFAULT_PER_PAGE = 50
# An upper bound, because `per_page=1000000` is how a paged endpoint quietly
# becomes an unpaged one again.
MAX_PER_PAGE = 200


@dataclass
class Page:
    items: list[Any]
    total: int
    page: int
    per_page: int

    @property
    def pages(self) -> int:
        # An empty list is one (empty) page, not zero — "page 1 of 0" is not a
        # thing anyone can read.
        return max(1, -(-self.total // self.per_page))

    def envelope(self, serialise=None) -> dict:
        rows = [serialise(i) for i in self.items] if serialise else self.items
        return {
            "items": rows,
            "total": self.total,
            "page": self.page,
            "per_page": self.per_page,
            "pages": self.pages,
            # Stated rather than left for the client to derive, so every
            # consumer agrees about it.
            "has_more": self.page < self.pages,
            "showing_from": 0 if not self.total else (self.page - 1) * self.per_page + 1,
            "showing_to": min(self.page * self.per_page, self.total),
        }


def page(query: Query, *, page: int = 1, per_page: int = DEFAULT_PER_PAGE) -> Page:
    """Slice a query and report the size of the whole set.

    `page` and `per_page` are clamped rather than rejected. A page number past
    the end is a stale bookmark or a deleted record, not an error worth showing
    someone: the last page is the useful answer.
    """
    per_page = max(1, min(int(per_page or DEFAULT_PER_PAGE), MAX_PER_PAGE))
    total = query.order_by(None).count()
    last = max(1, -(-total // per_page))
    page = max(1, min(int(page or 1), last))
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    return Page(items=items, total=total, page=page, per_page=per_page)
