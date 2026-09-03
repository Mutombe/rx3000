"""A dispenser at one shop does not see another shop's trade.

Written the way the real failure would arrive: not as an exception, but as a
stock figure that quietly includes Borrowdale's boxes, so the Avondale
assistant orders nothing and runs out on Friday.

WHY THE ASSERTIONS LOOK NAIVE

They are meant to. The scoping is applied by the session, not by a `WHERE` in
each query, because there are hundreds of queries and a missed one looks
exactly like a correct one. So the queries below are the plain, unsuspecting
kind somebody writes without having read a word about branches:
`db.query(Sale).all()`, a `get` by primary key, a sum. If those leak, the
design has failed whatever any individual router does.

THE ONE THAT MATTERS MOST

Not "does the filter exist" — it plainly does, it is forty lines away — but
**does assigning somebody a branch actually change what they see**. The default
for an unassigned user is deliberately "everything", so that shipping this does
not blank the product for every customer who already has staff. A default that
permissive is only safe if the assignment bites, and the fifth check below is
the one that would catch a filter that had been quietly disabled.

    python qa/branch-scope.py
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"branch-scope.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base, engine, SessionLocal          # noqa: E402
from app import branch_scope, models, tenancy                # noqa: E402

Base.metadata.create_all(engine)
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


# One pharmacy group, two shops, and a sale rung up in each.
with tenancy.unscoped(), branch_scope.every_branch():
    db = SessionLocal()
    group = models.Pharmacy(name="Zvandiri Pharmacies")
    db.add(group)
    db.commit()

    avondale = models.Branch(name="Avondale", code="AVN", pharmacy_id=group.id)
    borrowdale = models.Branch(name="Borrowdale", code="BOR", pharmacy_id=group.id)
    db.add_all([avondale, borrowdale])
    db.commit()
    avn, bor = avondale.id, borrowdale.id

    db.add_all([
        models.Sale(sale_number="S-AVN", total=100.0, branch_id=avn,
                    pharmacy_id=group.id),
        models.Sale(sale_number="S-BOR", total=250.0, branch_id=bor,
                    pharmacy_id=group.id),
        # Written before branches existed. Must stay visible to everybody, or a
        # branch user's history starts on the day this shipped.
        models.Sale(sale_number="S-OLD", total=7.0, branch_id=None,
                    pharmacy_id=group.id),
    ])

    counter = models.User(username="tsitsi", password_hash="x",
                          full_name="Tsitsi M", role="assistant",
                          branch_id=avn, pharmacy_id=group.id)
    relief = models.User(username="rudo", password_hash="x",
                         full_name="Rudo K", role="pharmacist",
                         branch_id=avn, pharmacy_id=group.id)
    owner = models.User(username="owner", password_hash="x",
                        full_name="The Owner", role="admin",
                        all_branches=True, pharmacy_id=group.id)
    unplaced = models.User(username="old", password_hash="x",
                           full_name="Predates This", role="assistant",
                           pharmacy_id=group.id)
    db.add_all([counter, relief, owner, unplaced])
    db.commit()

    # Rudo covers Borrowdale on Thursdays, and a cover that has run out.
    db.add_all([
        models.UserBranch(user_id=relief.id, branch_id=bor,
                          reason="Thursday cover", pharmacy_id=group.id),
    ])
    db.commit()
    counter_id, relief_id, owner_id, unplaced_id = (
        counter.id, relief.id, owner.id, unplaced.id)
    db.close()


def as_user(user_id):
    """A session seeing exactly what that person's token would let them see."""
    with tenancy.unscoped(), branch_scope.every_branch():
        db = SessionLocal()
        user = db.get(models.User, user_id)
        visible = branch_scope.for_user(db, user)
        db.close()
    return visible


def totals(visible):
    token = tenancy.set_current_pharmacy(1)
    btoken = branch_scope.set_visible_branches(visible)
    try:
        db = SessionLocal()
        sales = db.query(models.Sale).all()
        out = sorted(round(s.total, 2) for s in sales)
        db.close()
        return out
    finally:
        branch_scope.reset_visible_branches(btoken)
        tenancy.reset_current_pharmacy(token)


print("\n  who sees which takings\n")

counter_sees = totals(as_user(counter_id))
check(250.0 not in counter_sees,
      "the Avondale assistant does not see the Borrowdale sale")
check(100.0 in counter_sees,
      "she does see her own branch's sale")
check(7.0 in counter_sees,
      "and the sale written before branches existed, which is her history")

relief_sees = totals(as_user(relief_id))
check(100.0 in relief_sees and 250.0 in relief_sees,
      "the relief pharmacist covering both shops sees both")

owner_sees = totals(as_user(owner_id))
check(100.0 in owner_sees and 250.0 in owner_sees,
      "the owner sees the group")

unplaced_sees = totals(as_user(unplaced_id))
check(100.0 in unplaced_sees and 250.0 in unplaced_sees,
      "somebody nobody has placed in a branch still sees everything, so "
      "shipping this does not blank an existing customer's product")

# The check that would catch a filter quietly turned off: the assignment has
# to make a difference, not merely exist.
check(counter_sees != unplaced_sees,
      "ASSIGNING A BRANCH CHANGES WHAT SOMEBODY SEES — the permissive default "
      "for an unassigned user is only safe because of this line")

print("\n  a naive query, the kind written without reading branch_scope\n")

token = tenancy.set_current_pharmacy(1)
btoken = branch_scope.set_visible_branches(as_user(counter_id))
try:
    db = SessionLocal()
    # `get` by primary key, straight past any WHERE somebody might have added.
    leaked = [s for s in db.query(models.Sale).all() if s.branch_id == bor]
    check(not leaked,
          "db.query(Sale).all() does not return the other branch's row")

    from sqlalchemy import func
    total = db.query(func.coalesce(func.sum(models.Sale.total), 0.0)).scalar()
    check(round(total, 2) == 107.0,
          f"a sum over the same query is scoped too ({total}, expected 107.0)")
    db.close()
finally:
    branch_scope.reset_visible_branches(btoken)
    tenancy.reset_current_pharmacy(token)

print("\n  the escape hatch still crosses branches on purpose\n")

token = tenancy.set_current_pharmacy(1)
btoken = branch_scope.set_visible_branches(as_user(counter_id))
try:
    with branch_scope.every_branch():
        db = SessionLocal()
        everything = db.query(models.Sale).count()
        db.close()
    check(everything == 3,
          "every_branch() sees the group, for the transfer and the scorecard")
finally:
    branch_scope.reset_visible_branches(btoken)
    tenancy.reset_current_pharmacy(token)

print("\n  placing and moving somebody, which is what makes any of it "
      "reachable\n")

from app.services import placement                            # noqa: E402

with tenancy.unscoped(), branch_scope.every_branch():
    db = SessionLocal()
    boss = db.get(models.User, owner_id)
    newbie = models.User(username="tendai", password_hash="x",
                         full_name="Tendai N", role="assistant",
                         pharmacy_id=1)
    db.add(newbie)
    db.commit()

    before = branch_scope.for_user(db, newbie)
    placement.place(db, newbie, avn, actor=boss, reason="Started at Avondale")
    after = branch_scope.for_user(db, newbie)
    check(before is None and after == frozenset({avn}),
          "placing somebody narrows them from the whole group to one shop")

    placement.place(db, newbie, bor, actor=boss, reason="Moved to cover")
    moved = branch_scope.for_user(db, newbie)
    check(moved == frozenset({bor}),
          "moving them again follows the transfer, not the first placement")

    told = placement.describe(db, newbie)
    check(len(told["moves"]) == 2,
          f"both moves are kept ({len(told['moves'])}), because a branch that "
          f"cannot say who worked there in March cannot investigate anything")
    check(any(m["reason"] == "Started at Avondale" for m in told["moves"]),
          "with the reason somebody typed at the time")
    check(told["moves"][0]["from"] == "Avondale"
          and told["moves"][0]["to"] == "Borrowdale",
          "and the move says where from as well as where to")

    # Cover, and a cover that has run out.
    placement.add_cover(db, newbie, avn, actor=boss, reason="Thursdays")
    both = branch_scope.for_user(db, newbie)
    check(both == frozenset({avn, bor}),
          "cover widens the reach without moving them")

    from datetime import date, timedelta
    placement.drop_cover(db, newbie, avn)
    placement.add_cover(db, newbie, avn, actor=boss,
                        until=date.today() - timedelta(days=1))
    lapsed = branch_scope.for_user(db, newbie)
    check(lapsed == frozenset({bor}),
          "a cover that has run out is not a cover, so a locum's reach ends "
          "with the locum rather than when somebody tidies up")

    # Moving somebody to a shop they were covering must not leave the cover
    # row behind, or their reach would silently extend back to the shop they
    # left.
    placement.add_cover(db, newbie, avn, actor=boss, reason="Cover again")
    placement.place(db, newbie, avn, actor=boss, reason="Transferred there")
    check(branch_scope.for_user(db, newbie) == frozenset({avn}),
          "transferring somebody to a shop they covered drops the stale cover, "
          "which would otherwise keep their old branch in reach")

    refused = None
    try:
        placement.place(db, newbie, avn, actor=boss)
    except placement.PlacementError as exc:
        refused = str(exc)
    check(refused is not None and "already" in refused,
          f"and moving them where they already are says so: {refused!r}")
    db.close()

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  {f}")
    raise SystemExit(1)
print("a shop's trade stays in the shop, and the group still adds up")
