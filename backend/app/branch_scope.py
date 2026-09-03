"""Which shop's data the signed-in person may see, and how that is enforced.

Tenancy answers "which pharmacy group". This answers the question inside it:
of the four shops in that group, which ones is this person working in. A
dispenser at Avondale should open the stock screen and see Avondale's stock,
not a group total she cannot act on and cannot correct.

WHY THIS IS NOT A `WHERE` IN EVERY QUERY

The same reason tenancy is not. There are hundreds of queries across sixty
routers, a missed one shows somebody another shop's takings rather than
raising, and the code that leaks looks exactly like the code that does not.
`tenancy.py` settled this argument once already, and this file is deliberately
its twin so that anybody who has read one has read both.

HOW IT DIFFERS FROM TENANCY, AND WHY IT MUST

Tenancy is binary: you are in one pharmacy or you see nothing. A branch scope
cannot be, because three true situations exist at once:

  one branch      the dispenser, the cashier, the branch manager
  several         the relief pharmacist covering two shops, the area manager
  all of them     the owner, the group pharmacist, head office, the bookkeeper

So the filter takes a set rather than a value, and `None` means unrestricted.

AND THE DIRECTION OF THE DEFAULT IS THE OPPOSITE OF TENANCY'S

Tenancy narrows to nothing when nobody has said which pharmacy, because a
screen wrongly empty is reported in an afternoon and a screen showing another
pharmacy's patients might never be.

Here the unset case is the reverse: every user in the database predates the
column, so narrowing them to nothing would blank the product for every existing
customer on the morning this ships. Nobody would report that as a scoping bug;
they would report that the system is broken, and it would be. A user with no
branch assigned therefore sees everything, exactly as they did yesterday, and
the narrowing begins for a person the moment somebody gives them a branch.

That is a weaker default, chosen deliberately, and it is why
`qa/branch-scope.py` asserts the assignment actually bites rather than
asserting the filter exists.

WHAT IS SCOPED, AND WHAT IS NOT

Only records that belong to a place: a sale rung up at a till, stock on a
shelf, a cash-up, a shift, a stock take, the licences pinned to a branch wall.

Not the catalogue, not patients, not schemes or funders. A product code means
the same thing in every shop, and a patient who registered at Avondale and
collects at Borrowdale on her way home is one patient, not two. Scoping those
would not be stricter, it would be wrong: it would hide her repeat from the
pharmacist standing in front of her.

The list is explicit, in `branch_scoped_models`, with a reason each.
"""
from __future__ import annotations

import contextvars
from datetime import date

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

#: The branches the current request may see, or None for all of them.
#:
#: A context variable for the same reason tenancy uses one: a server handles
#: many requests at once, and a module-level "current branch" would be
#: whichever request set it last.
_visible: contextvars.ContextVar[frozenset[int] | None] = contextvars.ContextVar(
    "visible_branch_ids", default=None)

#: Set while trusted work that must cross branches runs: the group scorecard,
#: a stock transfer between two shops, head office reporting, the seeder.
_unscoped: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "branch_unscoped", default=False)


class BranchScoped:
    """Marks a table as belonging to one shop.

    A marker only. Unlike `TenantMixin` it does not declare the column, because
    `branch_id` already exists on every model that needs it and rewriting
    fifteen declarations to inherit it would be a large change that alters no
    behaviour. Inheriting this enrols the model in the filter below and nothing
    else.
    """


def visible_branch_ids() -> frozenset[int] | None:
    return _visible.get()


def set_visible_branches(ids: frozenset[int] | None) -> contextvars.Token:
    return _visible.set(ids)


def reset_visible_branches(token: contextvars.Token) -> None:
    _visible.reset(token)


class every_branch:
    """Run work that legitimately spans the group.

    A context manager rather than a flag, for the reason `tenancy.unscoped`
    is: the risk with an escape hatch is not that it exists, it is that
    somebody opens it and forgets to close it.
    """

    def __enter__(self) -> "every_branch":
        self._token = _unscoped.set(True)
        return self

    def __exit__(self, *exc) -> None:
        _unscoped.reset(self._token)


def is_unscoped() -> bool:
    return _unscoped.get()


def for_user(db: Session, user) -> frozenset[int] | None:
    """The branches this person may see.

    None means all of them, and is returned for three different people: the
    one whose `all_branches` flag is set, the platform administrator, and the
    one nobody has assigned a branch to yet. They are the same answer for
    different reasons, and only the third is a default rather than a decision.
    """
    if user is None:
        return None
    if getattr(user, "is_platform_admin", False):
        return None
    if getattr(user, "all_branches", False):
        return None

    home = getattr(user, "branch_id", None)
    if home is None:
        # Nobody has placed them. See the note at the top: this is the
        # backwards-compatible reading, not an oversight.
        return None

    ids = {home}

    # Extra shops they cover. An expired cover is not a cover, which is the
    # whole reason `until` exists — a locum's reach should end with the locum
    # rather than when somebody remembers to tidy the row up.
    from .models import UserBranch

    today = date.today()
    with every_branch():
        extra = db.query(UserBranch).filter(UserBranch.user_id == user.id).all()
    ids.update(row.branch_id for row in extra
               if row.branch_id and (row.until is None or row.until >= today))
    return frozenset(ids)


def branch_scoped_models() -> list[type]:
    """The models the filter governs, each because it belongs to a place.

    Listed by import rather than by scanning for a `branch_id` column, because
    several tables carry one for a different reason. A purchase order records
    the branch that will receive the goods, and a buyer at head office raising
    it for Avondale must still be able to see it.
    """
    from . import models as m

    wanted = [
        # Money taken, or paid out, at one counter.
        "Sale", "PettyCash", "LayBy", "Shift",
        # Stock physically on one shelf.
        "StockBatch", "StockTake", "StockMovement", "PurchaseOrder",
        # The paperwork pinned to one branch's wall, and the licences an
        # inspector asks that branch for.
        "ComplianceDocument",
        # Work handed to somebody standing in one shop.
        "Driver", "Waybill",
    ]
    #
    # Three tables carry `branch_id` and are deliberately absent:
    #
    #   User            scoping it through the session would filter the query
    #                   that finds somebody by username, and a login that
    #                   returns nothing is a login that fails. Who may see
    #                   which staff is decided in the staff endpoints, where
    #                   the answer can be "your branch, plus yourself".
    #   UserBranch      the same, and it is the table this file reads to work
    #                   out the scope: filtering it by the scope it produces
    #                   would be circular.
    #   UserPermission  its `branch_id` means something else entirely — "this
    #                   grant applies at that shop" — so the same column name
    #                   would be filtered on the wrong meaning.
    #
    # Rows hanging off a scoped parent (a stock take's lines, a sale's items)
    # are reached through it and need no rule of their own.
    found = []
    for name in wanted:
        model = getattr(m, name, None)
        if model is not None and hasattr(model, "branch_id"):
            found.append(model)
    return found


def install(session_class: type[Session]) -> None:
    """Make every ORM query on this session class filter by branch.

    Enrolment is done here, at install time, rather than by editing fifteen
    class lines: `branch_scoped_models` is the single list, and a model that
    should be scoped and is not appears in one place rather than being absent
    from a class declaration nobody re-reads.
    """
    scoped = branch_scoped_models()
    if not scoped:
        return

    @event.listens_for(session_class, "do_orm_execute")
    def _scope(state) -> None:
        if not state.is_select or state.is_column_load or state.is_relationship_load:
            return
        if is_unscoped():
            return
        ids = visible_branch_ids()
        if ids is None:
            return
        allowed = set(ids)
        for model in scoped:
            state.statement = state.statement.options(
                with_loader_criteria(
                    model,
                    # A row with no branch is kept. Rows written before
                    # branches existed carry NULL, and hiding them would make
                    # a branch user's history start on the day this shipped.
                    lambda cls: (cls.branch_id.in_(allowed))
                    | (cls.branch_id.is_(None)),
                    include_aliases=True))


def stamp(session: Session) -> None:
    """Give a new row the branch it was created in.

    The filter above governs reading. Writing needs the other half, and it
    needs it more here than tenancy does: a sale saved without a branch is a
    sale that appears in every branch's takings, which is how a group ends up
    with four reports that each add up to the same wrong number.

    Only stamped where the caller has not set one, and only where the person
    has exactly one branch. Somebody covering three shops must say which, and
    the screen that takes the sale is what knows.
    """

    scoped = tuple(branch_scoped_models())
    if not scoped:
        return

    @event.listens_for(session, "before_flush")
    def _fill(sess, flush_context, instances) -> None:
        ids = visible_branch_ids()
        if ids is None or len(ids) != 1:
            return
        only = next(iter(ids))
        for obj in sess.new:
            if isinstance(obj, scoped) and getattr(obj, "branch_id", None) is None:
                obj.branch_id = only
