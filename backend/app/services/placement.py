"""Which shop somebody works in, and what happens when they move.

`branch_scope` decides what a person can see once they have a branch. This is
how they get one, and it is the half that makes the other half reachable: a
scoping rule with no way to assign a branch is a scoping rule that never
narrows anybody, which is indistinguishable from not having written it.

A MOVE IS AN EVENT, NOT AN EDIT

Setting `user.branch_id = 3` answers "where is she now" and destroys "where was
she in March". Those are different questions and the second is the one an
inspector asks. The controlled register is signed by people, and "who was
working at Avondale on the fourteenth" cannot be answered from a column that
has been overwritten four times since.

So every placement writes a `StaffTransfer` as well: from, to, when, who moved
them, and why. The column is the current answer and the rows are the history,
and neither is derivable from the other.

COVER IS NOT A TRANSFER

The relief pharmacist who does Avondale on Mondays and Borrowdale on Thursdays
has not moved. Modelling that as a transfer means moving her twice a week and
losing the meaning of the word; modelling it as "all branches" hands her the
whole group. It is a `UserBranch` row, with an end date where the cover has
one, because a locum's reach should end with the locum rather than when
somebody remembers to tidy up.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import branch_scope
from ..models import Branch, StaffTransfer, User, UserBranch


class PlacementError(Exception):
    """Something about the move does not make sense. Carries the sentence."""


def _branch(db: Session, branch_id: int) -> Branch:
    with branch_scope.every_branch():
        branch = db.get(Branch, branch_id)
    if branch is None:
        raise PlacementError("That branch does not exist.")
    return branch


def place(db: Session, user: User, branch_id: int | None, *, actor: User,
          reason: str = "", on: date | None = None) -> StaffTransfer:
    """Put somebody in a shop, or move them to another one.

    `branch_id=None` takes them out of a branch and back to seeing everything,
    which is what head office and a group bookkeeper need. It is written to the
    history like any other move, because "she stopped being a branch person in
    June" is exactly as much of a fact as the move that put her there.
    """
    if user.user_type != "staff":
        raise PlacementError(
            f"{user.full_name} is not a member of staff, so there is no shop "
            f"to put them in. Patients and prescribers reach their own records "
            f"and never the application.")

    from_id = user.branch_id
    if from_id == branch_id:
        where = _branch(db, branch_id).name if branch_id else "no branch"
        raise PlacementError(f"{user.full_name} is already at {where}.")

    to_branch = _branch(db, branch_id) if branch_id is not None else None

    # A cover row for the shop they are moving to is now redundant, and worse
    # than redundant: it would outlive the transfer and quietly extend their
    # reach back to a shop they had left.
    if branch_id is not None:
        stale = (db.query(UserBranch)
                 .filter(UserBranch.user_id == user.id,
                         UserBranch.branch_id == branch_id).all())
        for row in stale:
            db.delete(row)

    user.branch_id = branch_id
    move = StaffTransfer(
        user_id=user.id, from_branch_id=from_id, to_branch_id=branch_id,
        moved_on=on or date.today(), reason=reason.strip()[:300],
        moved_by_id=actor.id,
    )
    db.add(move)
    db.commit()
    db.refresh(move)
    return move


def set_reach(db: Session, user: User, all_branches: bool, *,
              actor: User) -> None:
    """Let somebody see the whole group, or stop them.

    Separate from `place` because it is a different decision: a bookkeeper who
    reconciles four branches needs to see all of them and does not work in any
    of them, while a branch manager works in one and should see one. Rolling
    both into a single "level" field would force those two into the same slot.

    Having a home branch and seeing the group at once is allowed rather than
    refused. A group pharmacist based at Avondale is an ordinary arrangement,
    and the two fields then say different true things: where she works, and
    what she may read.
    """
    user.all_branches = bool(all_branches)
    db.add(StaffTransfer(
        user_id=user.id, from_branch_id=user.branch_id,
        to_branch_id=user.branch_id, moved_on=date.today(),
        reason=("Given sight of every branch" if all_branches
                else "Sight of other branches removed"),
        moved_by_id=actor.id,
    ))
    db.commit()


def add_cover(db: Session, user: User, branch_id: int, *, actor: User,
              until: date | None = None, reason: str = "") -> UserBranch:
    """A shop somebody covers besides their own."""
    branch = _branch(db, branch_id)
    if user.branch_id == branch_id:
        raise PlacementError(
            f"{branch.name} is already {user.full_name}'s own branch.")
    existing = (db.query(UserBranch)
                .filter(UserBranch.user_id == user.id,
                        UserBranch.branch_id == branch_id).first())
    if existing is not None:
        # Extending an existing cover rather than refusing. Somebody adding
        # the same shop again means "and also next month", not "I made a
        # mistake", and a refusal there is answered by deleting and re-adding.
        existing.until = until
        if reason:
            existing.reason = reason.strip()[:200]
        db.commit()
        db.refresh(existing)
        return existing

    row = UserBranch(user_id=user.id, branch_id=branch_id, until=until,
                     reason=reason.strip()[:200], added_by_id=actor.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def drop_cover(db: Session, user: User, branch_id: int) -> None:
    rows = (db.query(UserBranch)
            .filter(UserBranch.user_id == user.id,
                    UserBranch.branch_id == branch_id).all())
    if not rows:
        raise PlacementError("They do not cover that branch.")
    for row in rows:
        db.delete(row)
    db.commit()


def describe(db: Session, user: User) -> dict:
    """Where somebody works, what else they cover, and every move they made."""
    today = date.today()
    with branch_scope.every_branch():
        home = db.get(Branch, user.branch_id) if user.branch_id else None
        cover = (db.query(UserBranch)
                 .filter(UserBranch.user_id == user.id)
                 .order_by(UserBranch.added_at.desc()).all())
        moves = (db.query(StaffTransfer)
                 .filter(StaffTransfer.user_id == user.id)
                 .order_by(StaffTransfer.moved_on.desc(),
                           StaffTransfer.id.desc()).all())
        branches = {b.id: b for b in db.query(Branch).all()}
        visible = branch_scope.for_user(db, user)

    return {
        "branch": ({"id": home.id, "name": home.name, "code": home.code}
                   if home else None),
        "all_branches": bool(user.all_branches),
        # What they can see right now, which is the thing the scoping actually
        # uses. Sent so an administrator can confirm the effect rather than
        # infer it from three fields.
        "sees": ("every branch" if visible is None
                 else ", ".join(sorted(branches[b].name for b in visible
                                       if b in branches))),
        "cover": [{
            "branch_id": row.branch_id,
            "branch": branches[row.branch_id].name
            if row.branch_id in branches else "—",
            "until": row.until.isoformat() if row.until else None,
            "expired": bool(row.until and row.until < today),
            "reason": row.reason or "",
            "added_by": row.added_by.full_name if row.added_by else "",
        } for row in cover],
        "moves": [{
            "id": row.id,
            "from": (branches[row.from_branch_id].name
                     if row.from_branch_id in branches else None),
            "to": (branches[row.to_branch_id].name
                   if row.to_branch_id in branches else None),
            "on": row.moved_on.isoformat() if row.moved_on else None,
            "reason": row.reason or "",
            "by": row.moved_by.full_name if row.moved_by else "",
        } for row in moves],
    }
