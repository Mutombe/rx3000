"""Items that arrived with no price take the one they last sold for.

Against a snapshot of the local database (10,000 products imported from
invoice history with no price on them):

  - a preview writes nothing, and says what it would price
  - the figure offered is the most recent sale, converted to a pack price
  - an item that has never been sold is left alone, because there is nothing
    to read
  - applying prices them, and a second run finds nothing left to do
  - an item somebody has priced by hand in between is not overwritten

  python tests/test_price_from_history.py
"""
import sys

from snapshot_app import client, execute, sql


def sell(c, product, unit_price, units=1):
    """A sale at a known price, the way the till makes one."""
    r = c.post("/api/pos/sales", json={
        "items": [{"product_id": product["id"], "quantity": units, "unit_price": unit_price}],
        "payment_method": "cash", "amount_tendered": 100000.0})
    assert r.status_code == 200, r.text
    return r.json()


def run():
    c = client()

    # This pharmacy's own history, built here: the imported products in the
    # snapshot belong to another pharmacy and are correctly invisible.
    made = []
    for n, (price, per_pack) in enumerate(((7.5, 1), (2.25, 30), (4.0, 1))):
        p = c.post("/api/products", json={"name": f"History priced {n}", "unit_price": price * per_pack,
                                          "cost_price": 1.0, "units_per_pack": per_pack,
                                          "vat_rate": 0.0}).json()
        c.post("/api/stock/adjust", json={"product_id": p["id"], "quantity_delta": 500,
                                          "movement_type": "receive", "batch_number": f"PH{n}"})
        sell(c, p, price)
        if n == 0:
            sell(c, p, price)                     # sold twice, so it sorts first
        execute("update products set unit_price = 0 where id = ?", (p["id"],))
        made.append((p, price, per_pack))

    unpriced_before = sql("select count(*) from products where coalesce(unit_price, 0) <= 0")[0][0]

    preview = c.post("/api/admin/price-from-history", json={"apply": False})
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["applied"] is False and plan["priced"] == 0
    assert plan["would_price"] > 0, plan
    assert sql("select count(*) from products where coalesce(unit_price, 0) <= 0")[0][0] == unpriced_before
    print(f"ok    a preview writes nothing and offers {plan['would_price']} prices "
          f"(oldest sale {plan['oldest_days']} days back)")

    mine = {l["product_id"]: l for l in plan["lines"]}
    for product, price, per_pack in made:
        got = mine.get(product["id"])
        assert got, f"{product['name']} was not offered a price"
        # Sold over the counter, so the line price is already a pack price.
        assert abs(got["new_price"] - round(price * per_pack, 2)) < 0.005, (got, price, per_pack)
        assert got["sold_by"] == "till", got
    print("ok    an item's pack price is its last unit price times the pack")

    line = mine[made[0][0]["id"]]
    expected = round(line["last_price"], 2)
    assert line["new_price"] == expected, line
    sold = sql("""select si.unit_price from sale_items si join sales s on s.id = si.sale_id
                  where si.product_id = ? and si.unit_price > 0
                  order by si.id desc limit 1""", (line["product_id"],))
    assert sold and abs(sold[0][0] - line["last_price"]) < 0.005, (sold, line)
    print(f"ok    the figure is the last sale: {line['name'][:30]} at {line['new_price']} a pack")

    never = c.post("/api/products", json={"name": "Never sold, never priced", "unit_price": 0.0,
                                          "cost_price": 0.0, "units_per_pack": 1}).json()
    assert not any(l["product_id"] == never["id"] for l in plan["lines"])
    print("ok    an item with no sale to read is left alone")

    # Priced by hand between the preview and the button.
    by_hand = mine[made[1][0]["id"]]
    execute("update products set unit_price = 99.5 where id = ?", (by_hand["product_id"],))

    done = c.post("/api/admin/price-from-history", json={"apply": True})
    assert done.status_code == 200, done.text
    result = done.json()
    assert result["applied"] and result["priced"] > 0, result
    after = sql("select unit_price from products where id = ?", (line["product_id"],))[0][0]
    assert abs(after - expected) < 0.005, (after, expected)
    kept = sql("select unit_price from products where id = ?", (by_hand["product_id"],))[0][0]
    assert abs(kept - 99.5) < 0.005, kept
    print(f"ok    applying priced {result['priced']} items, and a hand-typed price was kept")

    again = c.post("/api/admin/price-from-history", json={"apply": True}).json()
    assert again["priced"] == 0 and again["would_price"] == 0, again
    assert sql("select unit_price from products where id = ?", (never["id"],))[0][0] == 0
    print("ok    a second run finds nothing left to do")


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
