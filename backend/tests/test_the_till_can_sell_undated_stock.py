"""A till that cannot sell anything is not a till.

An opening count says how many boxes are on the shelf. It does not say what is
printed on them, because nobody reads four thousand expiry dates into a
spreadsheet before they open. So every batch it creates is undated, and undated
stock cannot be drawn: First-Expiry-First-Out has nowhere to put a batch with no
expiry, and selling one would be selling a box nobody has looked at.

The dispensary learned to ask the person holding the pack. The till did not, and
the two doors quietly diverged: at a pharmacy whose entire shelf had arrived that
way, a pharmacist could dispense a script and a cashier could not sell a tube of
cream. Every product in the shop answered "not enough stock at this branch",
about a shelf the cashier could see was full.

Against a snapshot of the local database:

  - the till says which lines need the date read off the box, in packs
  - it refuses to sell undated stock without one, and says why
  - given the date, the sale goes through and the stock comes off this branch
  - the date is kept on the batch, so the next customer is not asked again
  - the front shop's over-the-counter sale can ask the same question

  python tests/test_the_till_can_sell_undated_stock.py
"""
import sys
from datetime import date, timedelta

from snapshot_app import client, execute, sql

LATER = (date.today() + timedelta(days=500)).isoformat()


def a_shelf_with_no_dates(c):
    """Undate one product's stock at the till's branch, the way a count does."""
    me = c.get("/api/auth/me").json()
    branch = me.get("branch_id") or sql(
        "select id from branches where is_default = 1")[0][0]
    row = sql("""select b.product_id, sum(b.quantity_remaining)
                   from stock_batches b join products p on p.id = b.product_id
                  where b.branch_id = ? and b.quantity_remaining > 0
                    and p.active = 1 and coalesce(p.category,'') != 'airtime'
                  group by b.product_id having sum(b.quantity_remaining) >= 40
                  order by b.product_id limit 1""", (branch,))
    assert row, "the snapshot has no stocked product to work with"
    product_id, held = int(row[0][0]), int(row[0][1])
    execute("update stock_batches set expiry_date = null where product_id = ? and branch_id = ?",
            (product_id, branch))
    return product_id, branch, held


def run():
    c = client()
    product_id, branch, held = a_shelf_with_no_dates(c)
    name = sql("select name from products where id = ?", (product_id,))[0][0]
    print(f"      {name} — {held} units at branch {branch}, every one undated")

    asked = c.post("/api/pos/expiry-needed",
                   json={"lines": [{"product_id": product_id, "quantity": 1}]})
    assert asked.status_code == 200, asked.text
    lines = asked.json()
    assert lines and lines[0]["product_id"] == product_id, lines
    assert lines[0]["undated_units"] > 0 and lines[0]["dated_units"] == 0, lines[0]
    print("ok    the till says which line needs the date off the box")

    # The till counts in packs; the shelf counts in units. If this asked in units
    # it would let through a sale of one pack of sixty, and the cashier would be
    # refused at Complete Sale for the only reason this exists to prevent.
    per_pack = max(1, int(sql("select units_per_pack from products where id = ?",
                              (product_id,))[0][0] or 1))
    assert lines[0]["needed_units"] == per_pack, (lines[0]["needed_units"], per_pack)
    print(f"ok    …and asks in packs, not units (1 pack is {per_pack})")

    blind = c.post("/api/pos/sales", json={
        "items": [{"product_id": product_id, "quantity": 1}],
        "payment_method": "cash", "amount_tendered": 10000})
    assert blind.status_code >= 400, "undated stock was sold with no date at all"
    assert "expiry" in blind.text.lower(), blind.text[:200]
    print("ok    it will not sell undated stock, and says what is missing")

    sold = c.post("/api/pos/sales", json={
        "items": [{"product_id": product_id, "quantity": 1}],
        "payment_method": "cash", "amount_tendered": 10000,
        "pack_expiries": {str(product_id): LATER}})
    assert sold.status_code == 200, sold.text
    print(f"ok    given the date off the box, the sale goes through ({sold.json()['sale_number']})")

    left = sql("""select coalesce(sum(quantity_remaining), 0) from stock_batches
                   where product_id = ? and branch_id = ?""", (product_id, branch))[0][0]
    assert int(left) == held - per_pack, (left, held, per_pack)
    print(f"ok    and the stock came off this branch's shelf ({held} to {int(left)})")

    still_undated = sql("""select count(*) from stock_batches
                            where product_id = ? and branch_id = ? and expiry_date is null
                              and quantity_remaining > 0""", (product_id, branch))[0][0]
    assert int(still_undated) == 0, f"{still_undated} batch(es) were left undated"
    again = c.post("/api/pos/expiry-needed",
                   json={"lines": [{"product_id": product_id, "quantity": 1}]})
    assert again.json() == [], again.text
    print("ok    the date is kept on the stock, so nobody is asked for it twice")

    # The front shop asks the same question of the same service.
    otc = sql("""select p.id from products p
                   join stock_batches b on b.product_id = p.id
                  where b.branch_id = ? and b.quantity_remaining > 20 and p.active = 1
                    and coalesce(p.schedule, 0) in (0, 1, 2) and p.id != ?
                  limit 1""", (branch, product_id))
    if otc:
        otc_id = int(otc[0][0])
        execute("update stock_batches set expiry_date = null where product_id = ? and branch_id = ?",
                (otc_id, branch))
        counter = c.post("/api/dispensing/otc", json={
            "product_id": otc_id, "quantity": 1, "payment_method": "cash",
            "amount_tendered": 10000, "counselling_given": True,
            "pack_expiry": LATER})
        assert counter.status_code == 200, counter.text
        print("ok    the front shop can ask for it too")


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
