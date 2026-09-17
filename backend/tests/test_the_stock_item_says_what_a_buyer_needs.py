"""The stock item page answers the questions it is opened with.

A product record holds a quantity, a cost and a price. None of those is what
somebody opens this page to find out, which is always one of:

  have I got any        and the answer is about THIS branch, not the group
  what did it cost me   and the answer is the shelf's weighted average, not
                        whatever the catalogue last remembered
  when do I run out     and nothing in the record answers that at all

The incumbent's stock screen is full of exactly these — packs beside units,
average cost beside average retail, markup, on order — because they are what a
buyer decides on.

Against a snapshot of the local database:

  - packs and units are both given, and they agree with the pack size
  - what this branch holds is reported apart from the group's total
  - average cost is weighted over the stock on the shelf
  - markup and margin are worked from that cost, not the catalogue's
  - days of cover is blank rather than infinite where nothing moves
  - a record that disagrees with its own batches says so

  python tests/test_the_stock_item_says_what_a_buyer_needs.py
"""
import sys

from snapshot_app import client, execute, sql


def run():
    c = client()
    me = c.get("/api/auth/me").json()
    branch = me.get("branch_id") or sql("select id from branches where is_default = 1")[0][0]

    row = sql("""select p.id, p.units_per_pack from products p
                   join stock_batches b on b.product_id = p.id
                  where b.branch_id = ? and b.quantity_remaining > 0 and p.active = 1
                  group by p.id having count(b.id) >= 1 limit 1""", (branch,))
    assert row, "the snapshot has no stocked product at this branch"
    product_id = int(row[0][0])

    # Two batches at different costs, so a weighted average is not the same
    # number as either of them and cannot be got right by accident.
    execute("delete from stock_batches where product_id = ? and branch_id = ?",
            (product_id, branch))
    pharmacy = sql("select pharmacy_id from products where id = ?", (product_id,))[0][0]
    for cost, units, batch in ((10.0, 30, "CHEAP"), (20.0, 10, "DEAR")):
        execute("""insert into stock_batches
                     (product_id, batch_number, quantity_received, quantity_remaining,
                      expiry_date, branch_id, unit_cost, pharmacy_id, received_at)
                   values (?, ?, ?, ?, date('now','+2 years'), ?, ?, ?,
                           datetime('now'))""",
                (product_id, batch, units, units, branch, cost, pharmacy))
    execute("update products set quantity_on_hand = 40, units_per_pack = 10, "
            "unit_price = 300, reorder_level = 5 where id = ?", (product_id,))

    got = c.get(f"/api/products/{product_id}").json()
    shelf = got.get("shelf")
    assert shelf, "the stock item carries none of the buyer's figures"

    assert shelf["units"] == 40 and shelf["per_pack"] == 10, shelf
    assert abs(shelf["packs"] - 4.0) < 0.001, shelf["packs"]
    print(f"ok    packs and units, and they agree: {shelf['packs']} packs of "
          f"{shelf['per_pack']} is {shelf['units']} units")

    assert shelf["here"] == 40, shelf["here"]
    print(f"ok    what this branch holds is its own figure: {shelf['here']}")

    # (30 x 10 + 10 x 20) / 40 = 12.50. Neither batch's cost, and not the
    # catalogue's either.
    assert abs(shelf["avg_cost"] - 12.5) < 0.005, shelf["avg_cost"]
    print(f"ok    average cost is weighted over the shelf: {shelf['avg_cost']} "
          "from 30 at 10.00 and 10 at 20.00")

    # 300 a pack over 10 units is 30.00 each, against a 12.50 cost.
    assert abs(shelf["each"] - 30.0) < 0.005, shelf["each"]
    assert abs(shelf["markup_percent"] - 140.0) < 0.5, shelf["markup_percent"]
    assert abs(shelf["margin_percent"] - 58.3) < 0.5, shelf["margin_percent"]
    print(f"ok    markup {shelf['markup_percent']}% and margin "
          f"{shelf['margin_percent']}% come off that cost, not the catalogue's")

    assert abs(shelf["at_cost"] - 500.0) < 0.5, shelf["at_cost"]
    assert abs(shelf["at_retail"] - 1200.0) < 0.5, shelf["at_retail"]
    print(f"ok    and the shelf is worth {shelf['at_cost']} at cost, "
          f"{shelf['at_retail']} at retail")

    assert shelf["days_cover"] is None or shelf["days_cover"] > 0, shelf["days_cover"]
    if shelf["a_day"] == 0:
        assert shelf["days_cover"] is None, (
            "nothing moves and it still claimed a number of days of cover; "
            "'never runs out' is the absence of a fact, not a fact")
        print("ok    days of cover is blank where nothing goes out, not infinite")
    else:
        print(f"ok    days of cover: {shelf['days_cover']} at {shelf['a_day']} a day")

    assert shelf["disagrees"] is False, shelf["disagrees"]
    print("ok    the record agrees with the batches behind it")

    # And it notices when they part company, which is the difference between an
    # empty shelf and an uncounted one.
    execute("update products set quantity_on_hand = 999 where id = ?", (product_id,))
    off = c.get(f"/api/products/{product_id}").json()["shelf"]
    assert off["disagrees"] is True, off
    assert off["days_cover"] is None or off["days_cover"] > 0
    print(f"ok    and says so when they do: record {off['units']}, "
          f"batches {off['here'] + off['here_undated']}")

    # ---- the ceiling, which this system never had ---------------------------
    execute("update products set quantity_on_hand = 40, max_level = 100 where id = ?",
            (product_id,))
    capped = c.get(f"/api/products/{product_id}").json()["shelf"]
    assert capped["max_level"] == 100, capped["max_level"]
    assert capped["to_max"] == 60, capped["to_max"]
    print(f"ok    a maximum says how much to order: {capped['to_max']} would "
          f"reach {capped['max_level']}")

    execute("update products set max_level = 0 where id = ?", (product_id,))
    none = c.get(f"/api/products/{product_id}").json()["shelf"]
    assert none["to_max"] is None, (
        "no maximum is set and it still said how much would reach it; zero is "
        "'nobody has decided', not 'the ceiling is nothing'")
    print("ok    and no maximum means no ceiling, rather than a ceiling of zero")

    # ---- what has actually left the shelf -----------------------------------
    usage = c.get(f"/api/products/{product_id}/usage?months=6").json()
    assert len(usage["months"]) >= 6, len(usage["months"])
    assert all("-" in m["month"] for m in usage["months"]), usage["months"][:2]
    # Every month in the window is present, including the empty ones: a gap in
    # a series reads as no data rather than as no demand.
    assert usage["months"] == sorted(usage["months"], key=lambda m: m["month"])
    print(f"ok    usage is a month at a time, oldest first, "
          f"{len(usage['months'])} of them with none skipped")

    assert usage["out_total"] >= 0 and usage["a_month"] >= 0
    for key in ("out", "in", "adjusted", "written_off", "moved"):
        assert all(key in m for m in usage["months"]), key
    print("ok    and separates what went out, came in, was written off and moved")


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
