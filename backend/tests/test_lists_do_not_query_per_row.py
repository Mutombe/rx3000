"""A list costs the same number of queries whether it shows ten rows or three hundred.

This is the fault that does not show up on a laptop. Against a database in the
same building an extra query costs a fraction of a millisecond, so a list that
fetches each row's medicine separately is merely inelegant. Against a hosted one
each query costs a round trip — about three hundred milliseconds on the
CareXpress deployment — so three hundred rows fetching three things each is
nine hundred round trips, and the screen takes over a minute.

That is not a hypothetical either. It is what the controlled-drugs register was
doing: 0.2ms of SQL and 74 seconds of waiting, on the statutory record an
inspector asks to see.

A count is the right thing to assert rather than a duration. Time depends on the
machine, the network and what else is running, so a timing test either passes
everywhere or fails everywhere for reasons that have nothing to do with the
code. The query count is the same number on a laptop and in production, and it
is the number that causes the duration.

Each list below is measured at two sizes. What matters is not the absolute
count, it is that the count does not follow the number of rows.

  python tests/test_lists_do_not_query_per_row.py
"""
import sys

from sqlalchemy import event

from snapshot_app import client

#: A fixed allowance, for lists too short in the snapshot to measure a slope on.
#:
#: Not zero: paging can cost a count, and a longer page can reach a relationship
#: the short one happened not to.
SLACK = 10

#: And the real rule: a list may not spend more than this many extra statements
#: per extra row.
#:
#: A query per row scores 1.0, and the register was scoring 3.0 — the medicine,
#: the patient and the prescriber, each fetched separately for every line. A
#: fixed set of eager loads scores 0.0 however long the list runs. A quarter is
#: far above anything correct and far below anything broken, so this fails on
#: the fault and not on the ordinary variation around it.
PER_ROW = 0.25

#: The lists, and the parameter that sets how many rows come back.
LISTS = [
    ("the controlled-drugs register", "/api/register?limit={n}"),
    ("the register, paged", "/api/register/paged?per_page={n}"),
    ("the pharmacy-medicine register", "/api/dispensing/otc?limit={n}"),
    ("the same, paged", "/api/dispensing/otc/paged?per_page={n}"),
    ("stock movement history", "/api/stock/movements/paged?per_page={n}"),
    ("the journal", "/api/ledger/entries?limit={n}"),
    ("the journal, paged", "/api/ledger/entries/paged?per_page={n}"),
]


def run():
    c = client()
    from app.database import engine

    count = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _tick(*_args):
        count["n"] += 1

    def statements(path: str) -> tuple[int, int]:
        count["n"] = 0
        said = c.get(path)
        assert said.status_code == 200, f"{path}: {said.status_code} {said.text[:120]}"
        body = said.json()
        rows = body if isinstance(body, list) else (body.get("items") or [])
        return count["n"], len(rows)

    worst = 0.0
    for what, shape in LISTS:
        few, few_rows = statements(shape.format(n=5))
        many, many_rows = statements(shape.format(n=200))
        grew = many - few
        # A list that cannot be made longer here has nothing to prove: the
        # snapshot simply does not hold enough rows. Say so rather than pass
        # quietly, because a green line nobody can interpret is worse than none.
        if many_rows <= few_rows:
            print(f"ok    {what}: only {many_rows} row(s) in the snapshot, "
                  f"{many} statement(s), nothing to grow")
            continue
        extra_rows = many_rows - few_rows
        allowed = max(SLACK, int(extra_rows * PER_ROW))
        slope = grew / extra_rows
        assert grew <= allowed, (
            f"{what}: {few} statement(s) for {few_rows} rows became {many} for "
            f"{many_rows}. That is {grew} more for {extra_rows} more rows, "
            f"{slope:.2f} a row, which is a query per row in all but name. On "
            "the hosted database each one is a round trip: three hundred rows "
            "at three queries each is how the register came to take 74 seconds.")
        print(f"ok    {what}: {few_rows} rows cost {few}, {many_rows} rows cost "
              f"{many} — {slope:.3f} statements a row")
        worst = max(worst, slope)

    print(f"\nthe steepest list costs {worst:.3f} statements a row; "
          f"a query per row would be 1.000")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:                  # noqa: BLE001
        import os
        import traceback
        traceback.print_exc()
        print("FAIL", exc)
        sys.stdout.flush()
        os._exit(1)
    print("\nall passed")
