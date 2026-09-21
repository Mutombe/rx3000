"""Does the sample-data generator write only into the pharmacy being seeded?

WHY THIS GUARD EXISTS

Tenancy is enforced by a `do_orm_execute` hook that adds loader criteria to
ORM queries. Raw SQL is not an ORM query, so the hook never sees it and a
`db.execute(text("SELECT ... FROM sales"))` reads every pharmacy on the
database. Nothing warns you. It is invisible in development, where there is
one pharmacy, and stays invisible in production until a second tenant seeds.

What it nearly cost: the seeder's ledger stage summed `FROM sales` with no
tenant predicate and posted the result as daily takings. On a fresh tenant
nothing is in `posted_takings`, so seeding the demonstration pharmacy would
have posted a paying customer's daily revenue into a ledger any prospect can
open. It had not fired only because that stage was never reached from the demo
path, and the fix for THAT would have fired this.

WHAT IS CHECKED

Both halves, because either alone gives false comfort:

  1. By reading. Every raw statement in the seeder that touches a table
     carrying `pharmacy_id` has to name a pharmacy, so a new one written
     without a predicate fails here rather than in a customer's books.

  2. By running. A pharmacy is created on a database that already holds
     another pharmacy's trade, given a few sales of its own, put through the
     ledger stage, and its books are compared against its own takings. This
     is the one that would actually have caught the original.
"""
from __future__ import annotations

import ast
import logging
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

logging.basicConfig(level=logging.ERROR)

from sqlalchemy import text                          # noqa: E402

from app.database import SessionLocal                # noqa: E402
from app import branch_scope, realseed, tenancy      # noqa: E402
from app import models                               # noqa: E402

passed = 0
failed = 0


def check(condition: bool, message: str, extra: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {message}")
    else:
        failed += 1
        print(f"  FAIL {message}{('   ' + extra) if extra else ''}")


# ---------------------------------------------------------------- by reading

print("\n  every raw statement names a pharmacy\n")

source = (BACKEND / "app" / "realseed.py").read_text(encoding="utf-8")

# The tables that carry a pharmacy. Read off the models rather than listed
# here, so a new tenant-scoped table is covered the day it is added.
tenant_tables = {
    m.class_.__tablename__ for m in models.Base.registry.mappers
    if issubclass(m.class_, models.TenantMixin)
}
check(len(tenant_tables) > 20,
      f"{len(tenant_tables)} tables carry a pharmacy_id")

# Parsed, not matched. A regex over the text finds `db.execute(text(...))`
# inside this file's own prose about `db.execute(text(...))`, and it cannot
# see that a predicate was concatenated on after the literal. The syntax tree
# knows the difference between a call and a sentence describing one.
tree = ast.parse(source)
statements = []
for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "execute"
            and isinstance(func.value, ast.Name) and func.value.id == "db"):
        continue
    written = ast.get_source_segment(source, node) or ""
    sql = " ".join(s.value for s in ast.walk(node)
                   if isinstance(s, ast.Constant) and isinstance(s.value, str))
    statements.append((node.lineno, sql, written))

check(len(statements) > 5, f"{len(statements)} raw statements to check")

# A statement is in the clear if it names no tenant table, or if the call as
# written carries a pharmacy predicate. `_only_here()` returns one to append,
# so a call that concatenates it counts as scoped.
offenders = []
for line, sql, written in statements:
    flat = " ".join(sql.split())
    if not flat:
        continue
    named = {t for t in tenant_tables
             if re.search(rf"\b(?:FROM|INTO|UPDATE|JOIN)\s+{t}\b", flat, re.I)}
    if not named:
        continue
    if "pharmacy_id" in written or "only_here" in written or "scope" in written:
        continue
    offenders.append((line, sorted(named), flat[:70]))

check(not offenders,
      "no raw statement reads or writes a tenant table unscoped",
      "" if not offenders else
      "; ".join(f"line {l} touches {', '.join(t)}: {s}" for l, t, s in offenders[:3]))

# The wipe is the deliberate exception, and it should stay deliberate.
check("--wipe-all" in source and "wipe_all" in source,
      "the unscoped wipe is still behind a flag somebody types")

# ---------------------------------------------------------------- by running

print("\n  and a second pharmacy keeps its books to itself\n")

db = SessionLocal()
tenancy.stamp(db)
tag = uuid.uuid4().hex[:6].upper()

with tenancy.unscoped():
    elsewhere = db.execute(text(
        "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM sales")).one()

if not elsewhere[0]:
    print("  ..   this database has no other pharmacy's trade to leak")
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

print(f"        the database already holds {elsewhere[0]:,} sales "
      f"worth {elsewhere[1]:,.2f}")

with tenancy.unscoped():
    ph = models.Pharmacy(name=f"Scope Guard {tag}",
                         registration_no=f"SCOPEGUARD{tag}")
    db.add(ph)
    db.commit()
    mine = ph.id

own_total = 390.0
token = tenancy.set_current_pharmacy(mine)
try:
    with branch_scope.every_branch():
        day = datetime.now() - timedelta(days=3)
        for i, amount in enumerate((100.0, 250.0, 40.0)):
            db.add(models.Sale(sale_number=f"SG{tag}{i}", total=amount,
                               payment_method="cash",
                               created_at=day + timedelta(days=i)))
        db.commit()
        made = realseed._ledger(db)
finally:
    tenancy.reset_current_pharmacy(token)

check(made.get("days posted", 0) == 3,
      "its three trading days posted", str(dict(made))[:70])

with tenancy.unscoped():
    posted = db.execute(text(
        "SELECT COALESCE(SUM(jl.debit), 0) FROM journal_lines jl "
        "  JOIN journal_entries je ON je.id = jl.entry_id "
        " WHERE je.pharmacy_id = :p AND je.source = 'daily_takings' "
        "   AND jl.account_code IN ('1000', '1110')"), {"p": mine}).scalar()
    strays = db.execute(text(
        "SELECT COUNT(*) FROM journal_entries WHERE pharmacy_id IS NULL")).scalar()

check(abs(float(posted) - own_total) < 0.5,
      f"and its ledger holds its own {own_total:,.2f} and nothing else",
      f"holds {float(posted):,.2f}, which is {float(posted) - own_total:,.2f} "
      f"of somebody else's money")
check(strays == 0,
      "no journal entry was written without a pharmacy on it",
      f"{strays} entries belong to nobody and are visible to nobody")

# The probe pharmacy and everything it wrote. A guard that leaves a pharmacy
# behind is a guard that changes the thing it measures.
with tenancy.unscoped():
    db.execute(text("DELETE FROM journal_lines WHERE entry_id IN "
                    "(SELECT id FROM journal_entries WHERE pharmacy_id = :p)"),
               {"p": mine})
    for table in ("journal_entries", "sales", "accounts", "settings"):
        try:
            db.execute(text(f"DELETE FROM {table} WHERE pharmacy_id = :p"),
                       {"p": mine})
        except Exception:                            # noqa: BLE001
            db.rollback()
    db.execute(text("DELETE FROM pharmacies WHERE id = :p"), {"p": mine})
    db.commit()

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\nraw SQL is not scoped by the tenancy hook. A seeder that forgets "
          "puts one pharmacy's money in another pharmacy's books.")
sys.exit(1 if failed else 0)
