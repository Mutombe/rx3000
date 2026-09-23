"""One shop's trading is its own, in the ledger as well as on the shelf.

The accounts were the last pharmacy-wide thing in a system that is otherwise
per branch. Stock sits on one shelf, a sale is rung up at one till, and the
journal that recorded both knew only the group — so an owner with four shops
could see which one sold the most and never which one MADE anything, because
gross profit lives in the ledger and the ledger had no branches in it.

WHAT THIS GUARDS, AND WHY EACH ONE IS HERE

  the entry is stamped        posting a sale writes the till's branch onto the
                              journal entry. From the SALE, not the session, so
                              a queue cleared at head office days later still
                              files the sale where it was rung up.

  the statement narrows       `income_statement(branch_id=...)` returns that
                              shop's revenue and nobody else's. This is the one
                              worth writing a test for: the filter reaches the
                              figures through a JOIN onto a column select, and
                              a join criterion that silently fails to apply
                              produces a statement that looks perfectly normal
                              and is the group's.

  the branches sum            each branch's gross profit, added up, equals the
                              group's. If the unallocated entries leaked into
                              the branch statements the sum would exceed the
                              group, which is the failure that makes an owner
                              stop believing the report.

  the group is not a branch   a bank charge has no shop and must not acquire
                              one. Guessing a branch for group costs is how
                              four statements stop reconciling to one.

  the old entries stay        every entry posted before the column existed
                              carries NULL. They must remain visible to a
                              branch user, or their history begins on the
                              morning this shipped.

    python qa/a-branch-earns-its-own-profit.py
"""
import os
import pathlib
import sys
from datetime import date

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"branch-profit.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base, engine, SessionLocal          # noqa: E402
from app import branch_scope, models, tenancy                # noqa: E402
from app.services import ledger, statements                  # noqa: E402


def session():
    """A session shaped like the one a request gets.

    `SessionLocal()` on its own does not stamp new rows with the pharmacy in
    force, because `get_db` registers that per session rather than on the
    class. A guard that skips it writes rows with a null tenant, which the
    scoping filter then hides from the guard's own assertions, so the test
    fails for a reason that has nothing to do with what it is testing.
    """
    db = SessionLocal()
    tenancy.stamp(db)
    branch_scope.stamp(db)
    return db

Base.metadata.create_all(engine)
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


TODAY = date.today()
YEAR_START = date(TODAY.year, 1, 1)

# A pharmacy group with two shops, the accounts a pharmacy actually posts to,
# and an open period to post into.
with tenancy.unscoped(), branch_scope.every_branch():
    db = session()
    group = models.Pharmacy(name="Zvandiri Pharmacies")
    db.add(group)
    db.commit()

    avondale = models.Branch(name="Avondale", code="AVN", pharmacy_id=group.id)
    borrowdale = models.Branch(name="Borrowdale", code="BOR", pharmacy_id=group.id)
    db.add_all([avondale, borrowdale])
    db.commit()
    avn, bor = avondale.id, borrowdale.id

    for code, name, kind in [
        ("1010", "Bank", "asset"), ("1200", "Stock", "asset"),
        ("4000", "Sales", "income"), ("5000", "Cost of sales", "expense"),
        ("6200", "Bank charges", "expense"),
    ]:
        db.add(models.Account(code=code, name=name, type=kind, active=True,
                              pharmacy_id=group.id))
    db.add(models.TradingPeriod(
        code=f"{TODAY.year}-{TODAY.month:02d}", status="open",
        start_date=date(TODAY.year, TODAY.month, 1), end_date=TODAY,
        pharmacy_id=group.id))
    db.commit()
    group_id = group.id
    db.close()


def money_lines(revenue, cost):
    return [
        ledger.Line(account_code="1010", debit=revenue, description="Takings"),
        ledger.Line(account_code="4000", credit=revenue, description="Sales"),
        ledger.Line(account_code="5000", debit=cost, description="Cost of sales"),
        ledger.Line(account_code="1200", credit=cost, description="Stock issued"),
    ]


token = tenancy.set_current_pharmacy(group_id)
try:
    with branch_scope.every_branch():
        db = session()

        # Avondale sells 1,000 at a cost of 600. Borrowdale sells 400 at 250.
        avn_entry = ledger.post(
            db, entry_date=TODAY, description="Avondale takings",
            lines=money_lines(1000.0, 600.0), source="sale", source_id=1,
            branch_id=avn)
        ledger.post(
            db, entry_date=TODAY, description="Borrowdale takings",
            lines=money_lines(400.0, 250.0), source="sale", source_id=2,
            branch_id=bor)
        # A group cost that belongs to no shop.
        ledger.post(
            db, entry_date=TODAY, description="Bank charges",
            lines=[ledger.Line(account_code="6200", debit=30.0,
                               description="Monthly charges"),
                   ledger.Line(account_code="1010", credit=30.0,
                               description="Bank")],
            source="bank_charge")

        print("\nthe entry is stamped")
        check(avn_entry.branch_id == avn,
              "a sale entry carries the branch it was rung up at")
        charges = (db.query(models.JournalEntry)
                   .filter(models.JournalEntry.source == "bank_charge").one())
        check(charges.branch_id is None,
              "a bank charge belongs to the group, not to a shop")

        print("\nthe statement narrows")
        whole = statements.income_statement(db, start=YEAR_START, upto=TODAY)
        one = statements.income_statement(db, start=YEAR_START, upto=TODAY,
                                          branch_id=avn)
        other = statements.income_statement(db, start=YEAR_START, upto=TODAY,
                                            branch_id=bor)
        check(whole["revenue"] == 1400.0,
              f"the group sold 1400 (got {whole['revenue']})")
        check(one["revenue"] == 1000.0,
              f"Avondale sold 1000 and not the group's 1400 "
              f"(got {one['revenue']})")
        check(other["revenue"] == 400.0,
              f"Borrowdale sold 400 (got {other['revenue']})")
        check(one["branch_id"] == avn,
              "the statement says which shop it is for")

        print("\nthe branches sum")
        check(round(one["gross_profit"] + other["gross_profit"], 2)
              == whole["gross_profit"],
              f"the shops' gross profit adds up to the group's "
              f"({one['gross_profit']} + {other['gross_profit']} vs "
              f"{whole['gross_profit']})")

        print("\nthe group is not a branch")
        # 30 of bank charges sits in the group statement and in neither shop's.
        check(whole["operating_expenses"] == 30.0,
              f"the group carries the bank charges "
              f"(got {whole['operating_expenses']})")
        check(one["operating_expenses"] == 0.0
              and other["operating_expenses"] == 0.0,
              "neither shop is charged for a cost that was never theirs")

        db.close()

    print("\nthe old entries stay")
    # An entry from before the column existed, and a branch user looking at it.
    with branch_scope.every_branch():
        db = session()
        old = ledger.post(
            db, entry_date=TODAY, description="Before branches existed",
            lines=money_lines(50.0, 20.0), source="sale", source_id=3)
        check(old.branch_id is None, "an unstamped entry carries no branch")
        db.close()

    btoken = branch_scope.set_visible_branches(frozenset({avn}))
    try:
        db = session()
        seen = {e.description for e in db.query(models.JournalEntry).all()}
        check("Avondale takings" in seen,
              "a branch user sees their own shop's entries")
        check("Borrowdale takings" not in seen,
              "a branch user does not see the other shop's takings")
        check("Before branches existed" in seen,
              "a branch user keeps the history that predates the column")
        check("Bank charges" in seen,
              "a branch user still sees the group costs carried above them")

        # THE ONE THAT WOULD FAIL SILENTLY.
        #
        # Above, the scope is proved against `db.query(JournalEntry)`, where
        # the entry is the thing being selected. The statement is not shaped
        # like that: it selects COLUMNS off journal_lines and reaches the entry
        # through a join, and `with_loader_criteria` applying to a joined
        # entity rather than a selected one is the kind of thing that either
        # works or quietly does not. If it does not, a branch manager opens
        # their income statement and reads the group's takings as their own,
        # with nothing anywhere to say so.
        mine = statements.income_statement(db, start=YEAR_START, upto=TODAY)
        check(mine["revenue"] == 1050.0,
              f"a branch user's own statement is their shop (1000) plus the "
              f"unbranched history (50), not the group's 1450 "
              f"(got {mine['revenue']})")
        db.close()
    finally:
        branch_scope.reset_visible_branches(btoken)
finally:
    tenancy.reset_current_pharmacy(token)

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The ledger knows which shop earned it.")
