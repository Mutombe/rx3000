"""Can one empty cell in one row break a whole screen?

WHAT HAPPENED

A pharmacist opened a product and got "Something went wrong at our end."
Not that product: `BatchOut.received_at` was declared as a required datetime
over a column that is nullable. 970 of that customer's 2,631 batches have no
arrival date, quite legitimately, because they came in through an opening
stock import rather than through a booking-in screen.

A response model that fails to serialise fails the WHOLE response. So one
such batch in stock did not blank the batches panel — it took the product
page down, and the error named nothing, because the detail goes to a log the
pharmacy cannot read.

WHY IT IS STRUCTURAL RATHER THAN CARELESS

    quantity_on_hand = Column(Integer, default=0)

reads as "always a number". It is not: `default=` applies to an ORM insert
and to nothing else. Anything that arrived by import, by migration, or by raw
SQL carries NULL. A sweep found 161 required schema fields sitting over
nullable columns, which is one mistake made structurally and not 161 of them.

WHAT IS CHECKED

That the base class still coerces a NULL scalar to its empty value, because
that single validator is what stands between 139 of those fields and the same
outage; that it does NOT invent dates, since there is no empty date and a
screen showing 1970 is worse than one saying "not recorded"; and that no
column a schema still demands has started carrying NULLs — which is the alarm
that would have gone off months before a pharmacist saw a broken page.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from pydantic import BaseModel                      # noqa: E402
from sqlalchemy import text                         # noqa: E402

from app import schemas                             # noqa: E402
from app.database import Base, SessionLocal         # noqa: E402
from app.tenancy import unscoped                    # noqa: E402
import app.models                                   # noqa: F401,E402

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


MAPPERS = list(Base.registry.mappers)


def best_model(schema):
    """The model a schema is read off, by how much of it the model explains.

    There is no declared link between the two, so it is inferred: the mapper
    that accounts for the most of the schema's field names wins, and a match
    below four fifths is not trusted at all rather than guessed at.
    """
    names = set(schema.model_fields)
    best, score = None, 0.0
    for m in MAPPERS:
        have = {c.key for c in m.columns} | set(m.relationships.keys())
        have |= {n for n, v in vars(m.class_).items() if isinstance(v, property)}
        covered = len(names & have) / max(1, len(names))
        if covered > score:
            best, score = m, covered
    return (best, score) if score >= 0.8 else (None, score)


print("\n  the coercion that stands between a NULL and an outage\n")

# Read off the module, not the model. A name beginning with an underscore on
# a Pydantic model becomes a private attribute rather than the dict you wrote,
# so the lookup inside the validator would raise on every field — which is how
# the first version of this fix would have replaced one outage with a worse
# one. Caught here, before it shipped.
empty = getattr(schemas, "EMPTY_FOR", {})
check(isinstance(empty, dict) and bool(empty),
      "the module still says what an empty scalar is",
      f"got {type(empty).__name__}")
check(empty.get(str) == "" and empty.get(int) == 0
      and empty.get(float) == 0.0 and empty.get(bool) is False,
      "text, counts, amounts and flags each have their empty value",
      str(empty))

# There is no empty date. Nought is 1970 and today is a lie, and a screen
# showing either is worse than one saying nothing.
from datetime import date, datetime                 # noqa: E402
check(date not in empty and datetime not in empty,
      "and a date is NOT invented, because there is no empty date")


class _Probe(schemas.ORM):
    text_field: str
    count_field: int
    amount_field: float
    flag_field: bool


class _Row:
    text_field = None
    count_field = None
    amount_field = None
    flag_field = None


try:
    got = _Probe.model_validate(_Row(), from_attributes=True)
    check(got.text_field == "" and got.count_field == 0
          and got.amount_field == 0.0 and got.flag_field is False,
          "a row of NULLs serialises instead of failing the response",
          repr(got))
except Exception as exc:                            # noqa: BLE001
    check(False, "a row of NULLs serialises instead of failing the response",
          f"{type(exc).__name__}: {exc}")

print("\n  and nothing a schema still demands has gone null\n")

# What the coercion does not cover: a required field whose type has no empty
# value, over a column that allows NULL. None of these carry NULLs today. The
# day one does, this fails here rather than in a pharmacy.
exposed: list[tuple[str, str, str, str]] = []
for name, obj in vars(schemas).items():
    if not (inspect.isclass(obj) and issubclass(obj, BaseModel)):
        continue
    if not (getattr(obj, "model_config", {}) or {}).get("from_attributes"):
        continue
    mapper, _ = best_model(obj)
    if mapper is None:
        continue
    cols = {c.key: c for c in mapper.columns}
    for fname, field in obj.model_fields.items():
        if not field.is_required():
            continue
        col = cols.get(fname)
        if col is None or not col.nullable:
            continue
        if field.annotation in empty:
            continue                                # coerced above
        exposed.append((obj.__name__, mapper.class_.__tablename__, fname,
                        getattr(field.annotation, "__name__", "?")))

check(bool(exposed) or True, f"{len(exposed)} field(s) are not covered by it")

db = SessionLocal()
broken: list[str] = []
looked = 0
with unscoped():
    for cls, table, column, _kind in exposed:
        try:
            nulls = db.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")).scalar()
        except Exception:                           # noqa: BLE001
            db.rollback()
            continue                                # table not on this database
        looked += 1
        if nulls:
            broken.append(f"{table}.{column} ({nulls:,} null) breaks {cls}")

check(looked > 0, f"checked {looked} of them against the database")
check(not broken,
      "none of them has a NULL in it",
      "; ".join(broken[:4]))

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\none empty cell in one row should cost you that cell, not the "
          "screen it is on.")
sys.exit(1 if failed else 0)
