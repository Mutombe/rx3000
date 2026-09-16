"""The medicine search puts what this branch can hand over first.

A pharmacy's catalogue is not its shelf. CareXpress carries sixteen thousand
lines and stocks about two thousand, at three shops, and the dispensary search
was ordering by name and then cutting to the page size. A dispenser typing
"amox" got the first forty matches in the alphabet; the one box actually behind
them could be on a page two that does not exist.

It reads as the search being wrong about the stock, which is worse than it
sounds: the dispenser picks a line the branch does not hold, gets as far as
Finish, and is refused there.

So the list is ordered by this branch's shelf first and the name second. Nothing
is hidden — the rest of the catalogue is still there, underneath, for the special
order and the item being brought in.

Against a snapshot of the local database:

  - a medicine this branch holds outranks one it does not, whatever their names
  - it is still ordered by name within each group, so the list does not jump about
  - a product the branch does not stock is still findable, not filtered away
  - the shelf figures beside each row are this branch's, not the group's

  python tests/test_the_search_offers_what_is_on_the_shelf.py
"""
import sys

from snapshot_app import client, execute, sql

#: Named so that ordering by name alone would put the out-of-stock one first.
#: If the sort were still alphabetical this test could not tell the difference.
EMPTY = "AAAA REHEARSAL NOTHING ON THE SHELF"
STOCKED = "ZZZZ REHEARSAL PLENTY ON THE SHELF"


def a_pair(c) -> tuple[int, int, int]:
    """Two medicines: one this branch stocks, one it does not."""
    me = c.get("/api/auth/me").json()
    branch = me.get("branch_id") or sql("select id from branches where is_default = 1")[0][0]
    # Cloned off a product the search already offers, so every filter this
    # endpoint applies — schedule, department, active — is satisfied by both.
    model = c.get("/api/dispensing/products?route=prescription&limit=1").json()
    assert model, "the snapshot offers no prescription medicines at all"
    # Copied column for column rather than built field by field: this endpoint
    # returns the whole ProductOut, and a row assembled by hand fails validation
    # on whichever column somebody adds next. Only the name, the code and the
    # count on hand differ.
    columns = [c for c in
               (r[0] for r in sql("select name from pragma_table_info('products')"))
               if c != "id"]
    listed = ", ".join(columns)
    taken = ", ".join(
        "?" if c in ("name", "stock_code", "quantity_on_hand") else c for c in columns)
    made = []
    for index, name in enumerate((EMPTY, STOCKED)):
        values = [{"name": name, "stock_code": f"REH{index}",
                   "quantity_on_hand": 0}[c]
                  for c in columns if c in ("name", "stock_code", "quantity_on_hand")]
        execute(f"insert into products ({listed}) select {taken} from products where id = ?",
                (*values, model[0]["id"]))
        made.append(sql("select id from products where name = ?", (name,))[0][0])
    row = sql("select pharmacy_id from products where id = ?", (made[0],))[0]
    execute("""insert into stock_batches
                 (product_id, batch_number, quantity_received, quantity_remaining,
                  expiry_date, branch_id, unit_cost, pharmacy_id)
               values (?, 'REHEARSAL', 500, 500, date('now', '+2 years'), ?, 1.0, ?)""",
            (made[1], branch, row[0]))
    return made[0], made[1], branch


def run():
    c = client()
    empty_id, stocked_id, branch = a_pair(c)
    print(f"      two medicines at branch {branch}: one with 500 on the shelf, one with none")

    found = c.get("/api/dispensing/products?route=prescription&q=REHEARSAL&limit=20").json()
    names = [p["name"] for p in found]
    assert len(names) >= 2, names
    assert names.index(STOCKED) < names.index(EMPTY), names
    print("ok    the one on the shelf comes first, though its name sorts last")

    stocked = next(p for p in found if p["id"] == stocked_id)
    empty = next(p for p in found if p["id"] == empty_id)
    assert stocked["here"] == 500, stocked["here"]
    assert empty["here"] == 0 and empty["here_undated"] == 0, empty
    print("ok    the figures beside each row are this branch's shelf")

    # Nothing is hidden: what the branch does not stock is still reachable, which
    # is what a special order and a transfer both start from.
    assert EMPTY in names, "a medicine the branch does not stock was filtered away"
    print("ok    and what the branch does not hold is still findable, not hidden")

    # Within a group the order is still the name, so the list does not reshuffle
    # under the dispenser's finger between keystrokes.
    page = c.get("/api/dispensing/products?route=prescription&limit=60").json()
    held = [p["name"] for p in page if (p.get("here") or 0) > 0 or (p.get("here_undated") or 0) > 0]
    rest = [p["name"] for p in page if p["name"] not in held]
    assert held == sorted(held), "the stocked rows are not in name order"
    assert rest == sorted(rest), "the rest are not in name order"
    print(f"ok    each group is still ordered by name ({len(held)} on the shelf, "
          f"{len(rest)} behind them)")


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
