"""Which pharmacy the current request belongs to, and how that is enforced.

The system was built for one pharmacy and is being sold to many. Every patient,
sale, script and stock batch in the database presently belongs to whoever
happens to be logged in, because there is nothing to say otherwise, so two
pharmacies on one deployment would read each other's patient records.

The obvious fix is to add `pharmacy_id` to every table and a `WHERE` to every
query. That is also the fix that fails: there are eighty-six tables and several
hundred queries, a missed one leaks a patient list rather than raising an error,
and nothing about the code that leaks looks different from the code that does
not. A rule enforced by remembering is not enforced.

So the scoping is applied by the session itself. Any model carrying `TenantMixin`
gets a filter added to every ORM query automatically, before it reaches the
database. Forgetting is no longer possible; the failure mode of a new query
written by somebody who has never read this file is that it returns their own
pharmacy's rows, which is the right answer.

Two things this deliberately does not do:

* It does not filter raw `text()` SQL. Nothing can — the ORM cannot see inside a
  string. `assert_no_raw_tenant_sql` in the test suite is what covers that.
* It does not scope reference data that every pharmacy shares: diagnosis codes,
  dosage abbreviations, the jurisdiction's fee models. Those are the same book
  for everybody and copying them per tenant would mean a hundred pharmacies each
  maintaining their own ICD-10.
"""
from __future__ import annotations

import contextvars
from typing import Iterator

from sqlalchemy import Column, ForeignKey, Integer, event
from sqlalchemy.orm import Mapped, Session, declared_attr, with_loader_criteria

#: The pharmacy whose data the current request may see.
#:
#: A context variable rather than a global, because a server handles many
#: requests at once and a module-level "current pharmacy" would be whichever
#: request set it last, which is precisely the bug this file exists to prevent,
#: reintroduced one level down.
_current: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_pharmacy_id", default=None)

#: Set while trusted, tenant-crossing work runs: migrations, seeding, the
#: platform owner's own reporting. Never set from a request handler.
_unscoped: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "tenancy_unscoped", default=False)


class TenantMixin:
    """Marks a table as belonging to one pharmacy.

    Inheriting this is the whole opt-in: it declares the column and enrols the
    model in the automatic filter below. A table that does not carry it is
    either shared reference data or reachable only through one that does.

    The column is declared here rather than written out on each model, so that
    "is this table scoped" is answered by one word in the class line instead of
    by reading for a column that might have been left out. Seventy hand-copied
    declarations is seventy chances to omit the index, or the foreign key, or
    the column.

    Indexed because every query in the system is about to filter on it, and
    nullable because existing rows must be backfilled before it can be
    tightened — a NOT NULL added ahead of the backfill takes the deployment
    down rather than the data with it.
    """

    @declared_attr
    def pharmacy_id(cls) -> Mapped[int | None]:
        return Column(Integer, ForeignKey("pharmacies.id"),
                      nullable=True, index=True)


def current_pharmacy_id() -> int | None:
    """The pharmacy in force, or None outside a request."""
    return _current.get()


def set_current_pharmacy(pharmacy_id: int | None) -> contextvars.Token:
    return _current.set(pharmacy_id)


def reset_current_pharmacy(token: contextvars.Token) -> None:
    _current.reset(token)


class unscoped:
    """Run trusted work across every pharmacy.

    Used by migrations, the seeder and platform-level reporting. It is a context
    manager rather than a flag so the widening is visibly bounded — the risk with
    an escape hatch is not that it exists but that somebody opens it and forgets
    to close it.
    """

    def __enter__(self) -> "unscoped":
        self._token = _unscoped.set(True)
        return self

    def __exit__(self, *exc) -> None:
        _unscoped.reset(self._token)


def is_unscoped() -> bool:
    return _unscoped.get()


def install(session_class: type[Session]) -> None:
    """Make every ORM query on this session class filter by pharmacy.

    `with_loader_criteria` applies to the entity wherever it appears — the query
    root, an eager load, a relationship traversal, so a patient reached through
    a sale is scoped exactly as a patient queried directly. `include_aliases`
    covers the joins the reporting queries build.
    """

    @event.listens_for(session_class, "do_orm_execute")
    def _scope(state) -> None:
        if not state.is_select or state.is_column_load or state.is_relationship_load:
            return
        if is_unscoped():
            return
        pharmacy_id = current_pharmacy_id()
        if pharmacy_id is None:
            # Nothing has said which pharmacy this is. Rather than quietly
            # showing everything, the failure that loses a patient list, the
            # query is narrowed to nothing. A screen that is empty when it
            # should not be gets reported in an afternoon; a screen showing
            # somebody else's patients might never be.
            state.statement = state.statement.options(
                with_loader_criteria(TenantMixin,
                                     lambda cls: cls.pharmacy_id.is_(None),
                                     include_aliases=True))
            return
        state.statement = state.statement.options(
            with_loader_criteria(TenantMixin,
                                 lambda cls: cls.pharmacy_id == pharmacy_id,
                                 include_aliases=True))


def stamp(session: Session) -> None:
    """Give new rows the current pharmacy before they are written.

    The filter above governs reading. Writing needs the other half: a row saved
    without a pharmacy is invisible to the tenant that created it, which reads
    as "the save failed" and produces a duplicate a minute later.
    """

    @event.listens_for(session, "before_flush")
    def _fill(sess, flush_context, instances) -> None:
        pharmacy_id = current_pharmacy_id()
        if pharmacy_id is None:
            return
        for obj in sess.new:
            if isinstance(obj, TenantMixin) and getattr(obj, "pharmacy_id", None) is None:
                obj.pharmacy_id = pharmacy_id
