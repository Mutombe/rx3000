"""Stock that moves between shops arrives carrying what it left with.

A transfer used to create one batch at the receiving branch: no expiry, no batch
number, just a quantity. Everything the sending branch knew about those boxes
was thrown away in the van.

Two things break when that happens, and the second is the one that matters.
Stock that had been properly dated at one shop arrives at the next as undated,
so it cannot be dispensed until somebody reads every pack again — which is the
whole job the receiving pharmacist thought had already been done. And a pack
with three weeks left on it arrives indistinguishable from a pack with three
years, so First-Expiry-First-Out has nothing to order by and the short-dated box
sits at the back until it is a write-off.

It is not a hypothetical for CareXpress. Every unit they hold is at one branch;
moving it to the other two is the next thing they will do.

Against a snapshot of the local database:

  - a transfer records which batches actually left
  - the receiving branch gets one batch per batch that left, with its own expiry
  - the batch number survives the journey, so a recall still finds the boxes
  - the shortest-dated stock is drawn first, and still is on the far side
  - a transfer raised before any of this was recorded can still be received

  python tests/test_a_transfer_carries_its_dates.py
"""
import sys
from datetime import date, timedelta

from snapshot_app import client, execute, sql

SOON = date.today() + timedelta(days=40)
LATER = date.today() + timedelta(days=900)


def two_shops(c):
    """A product sitting at one branch in two batches, and somewhere to send it."""
    here = sql("select id from branches where is_default = 1")[0][0]
    there = sql("select id from branches where id != ? and active = 1 limit 1", (here,))
    if not there:
        execute("""insert into branches (name, code, active, is_default, pharmacy_id)
                   select 'Rehearsal Branch', 'REH', 1, 0, pharmacy_id
                     from branches where id = ?""", (here,))
        there = sql("select id from branches where code = 'REH'")
    there = there[0][0]

    product = c.get("/api/dispensing/products?route=prescription&limit=1").json()[0]["id"]
    pharmacy = sql("select pharmacy_id from products where id = ?", (product,))[0][0]
    execute("delete from stock_batches where product_id = ? and branch_id in (?, ?)",
            (product, here, there))
    for number, expiry, units in (("SHORT-1", SOON, 30), ("LONG-1", LATER, 70)):
        execute("""insert into stock_batches
                     (product_id, batch_number, quantity_received, quantity_remaining,
                      expiry_date, branch_id, unit_cost, pharmacy_id)
                   values (?, ?, ?, ?, ?, ?, 1.5, ?)""",
                (product, number, units, units, expiry.isoformat(), here, pharmacy))
    return product, here, there


def run():
    c = client()
    product, here, there = two_shops(c)
    print(f"      30 units expiring {SOON:%b %Y} and 70 expiring {LATER:%b %Y}, "
          f"at branch {here}")

    # Enough to empty the short-dated batch and bite into the long-dated one, so
    # the test can tell a preserved date from a copied one.
    sent = c.post("/api/branches/transfers", json={
        "from_branch_id": here, "to_branch_id": there,
        "product_id": product, "quantity": 50, "notes": "Rehearsal"})
    assert sent.status_code == 200, sent.text
    transfer = sent.json()
    print(f"ok    50 units despatched ({transfer['reference']})")

    row = sql("select drawn_json from branch_transfers where id = ?", (transfer["id"],))[0][0]
    assert row and "SHORT-1" in row and "LONG-1" in row, row
    print("ok    the transfer records which batches actually left")

    left = sql("""select batch_number, quantity_remaining from stock_batches
                   where product_id = ? and branch_id = ? order by expiry_date""",
               (product, here))
    assert dict(left) == {"SHORT-1": 0, "LONG-1": 50}, left
    print("ok    the shortest-dated stock went first, not the easiest to reach")

    got = c.post(f"/api/branches/transfers/{transfer['id']}/receive")
    assert got.status_code == 200, got.text

    arrived = sql("""select batch_number, expiry_date, quantity_remaining
                       from stock_batches where product_id = ? and branch_id = ?
                      order by expiry_date""", (product, there))
    assert len(arrived) == 2, arrived
    assert all(a[1] for a in arrived), f"a batch arrived with no expiry: {arrived}"
    print(f"ok    it arrived as two batches, both dated: {arrived}")

    by_number = {a[0]: a for a in arrived}
    assert any("SHORT-1" in n for n in by_number), by_number
    short = next(a for n, a in by_number.items() if "SHORT-1" in n)
    assert str(short[1]).startswith(SOON.isoformat()), (short, SOON)
    assert short[2] == 30, short
    print("ok    the short-dated 30 are still short-dated on the far side")

    long_one = next(a for n, a in by_number.items() if "LONG-1" in n)
    assert str(long_one[1]).startswith(LATER.isoformat()), (long_one, LATER)
    assert long_one[2] == 20, long_one
    print("ok    …and the batch numbers survived, so a recall still finds them")

    # A transfer raised before any of this existed has nothing recorded. It must
    # still be receivable: the stock is physically standing in the shop.
    old = c.post("/api/branches/transfers", json={
        "from_branch_id": here, "to_branch_id": there,
        "product_id": product, "quantity": 5}).json()
    execute("update branch_transfers set drawn_json = '' where id = ?", (old["id"],))
    again = c.post(f"/api/branches/transfers/{old['id']}/receive")
    assert again.status_code == 200, again.text
    print("ok    an older transfer, with nothing recorded, can still be booked in")


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
