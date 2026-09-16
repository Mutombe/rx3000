"""Stock comes off the shelf the dispenser is standing at.

Every path that consumes stock took a `branch_id` and fell back to the DEFAULT
branch when nobody passed one — and no caller ever passed one. So a dispenser at
CareXpress Chinamano, with 1,936 products on the shelf in front of them, drew
against Central's shelf and was told "not enough stock at this branch". The
message was true. The branch was the wrong one.

Against a snapshot of the local database:

  - a dispenser at a branch draws that branch's stock, not the default's
  - …and the count that moves is that branch's, not the default's
  - stock they cannot reach at another branch is not counted for them
  - the refusal names the shelf they are standing at
  - a user with no branch on record still gets the default, which is what a
    one-shop pharmacy has and never thinks about
  - receiving puts goods on the receiver's own shelf

  python tests/test_the_shelf_you_are_standing_at.py
"""
import sys
from datetime import date, timedelta

from snapshot_app import client, execute, sql

GOOD = (date.today() + timedelta(days=400)).isoformat()


def run():
    c = client()
    from app.auth import hash_password
    from app.database import SessionLocal
    from app.services import branches as branch_svc
    from app.tenancy import reset_current_pharmacy, set_current_pharmacy

    pharmacy_id = sql("select pharmacy_id from products where pharmacy_id is not null limit 1")[0][0]
    for code, name in (("TSA", "Shelf A"), ("TSB", "Shelf B")):
        if not sql("select id from branches where code = ?", (code,)):
            execute("insert into branches (code, name, is_default, active, pharmacy_id) "
                    "values (?, ?, 0, 1, ?)", (code, name, pharmacy_id))
    a = sql("select id from branches where code = 'TSA'")[0][0]
    b = sql("select id from branches where code = 'TSB'")[0][0]

    if not sql("select id from users where username = 'shelf_tendai'"):
        execute("insert into users (username, password_hash, full_name, role, active, "
                "pharmacy_id, branch_id) values (?, ?, ?, 'pharmacist', 1, ?, ?)",
                ("shelf_tendai", hash_password("Counter-pass-1"), "Tendai at Shelf B",
                 pharmacy_id, b))
    execute("update users set branch_id = ? where username = 'shelf_tendai'", (b,))

    # An existing dispensable medicine rather than a new one: the snapshot the
    # API reads is built when `client()` is called, so a product inserted after
    # that is visible to `sql` and invisible to the server — which is a fine way
    # to spend an hour proving the wrong thing.
    stocked = c.get("/api/dispensing/products?route=prescription&limit=40").json()
    assert stocked, "no dispensable medicines in this snapshot"
    product_id = stocked[0]["id"]
    execute("delete from stock_batches where product_id = ?", (product_id,))

    # 40 on Shelf A (which is NOT where Tendai stands), 12 on Shelf B.
    for branch_id, qty, batch in ((a, 40, "SHELF-A"), (b, 12, "SHELF-B")):
        execute("insert into stock_batches (product_id, branch_id, batch_number, expiry_date, "
                "quantity_received, quantity_remaining, unit_cost, pharmacy_id) "
                "values (?, ?, ?, ?, ?, ?, 2.0, ?)",
                (product_id, branch_id, batch, GOOD, qty, qty, pharmacy_id))
    execute("update products set quantity_on_hand = 52 where id = ?", (product_id,))

    r = c.post("/api/auth/login", json={"username": "shelf_tendai", "password": "Counter-pass-1"},
               headers={"Authorization": ""})
    assert r.status_code == 200, r.text
    them = {"Authorization": "Bearer " + r.json()["access_token"]}

    # The search says what THIS shelf holds, not the group's 52.
    found = c.get("/api/dispensing/products?route=prescription&limit=60",
                  headers=them).json()
    mine = [p for p in found if p["id"] == product_id]
    assert mine, f"the medicine under test is not in the search ({len(found)} returned)"
    assert mine[0]["quantity_on_hand"] == 52, mine[0]["quantity_on_hand"]
    assert mine[0]["here"] == 12, mine[0]["here"]
    print("ok    the search says 12 here, not the pharmacy's 52")

    # Dispensing draws Shelf B.
    from app import helpers
    from app.models import Product, StockBatch
    token = set_current_pharmacy(pharmacy_id)
    db = SessionLocal()
    try:
        user_id = sql("select id from users where username = 'shelf_tendai'")[0][0]
        product = db.get(Product, product_id)
        helpers.consume_stock_fefo(db, product, 5, "sale", user_id, reference="SHELFTEST")
        db.commit()
        db.expire_all()

        left_a = sql("select quantity_remaining from stock_batches where product_id = ? "
                     "and branch_id = ?", (product_id, a))[0][0]
        left_b = sql("select quantity_remaining from stock_batches where product_id = ? "
                     "and branch_id = ?", (product_id, b))[0][0]
        assert left_a == 40, f"it drew from the wrong shelf: A has {left_a}"
        assert left_b == 7, f"B should have 7, has {left_b}"
        print(f"ok    five came off Shelf B ({left_b} left); Shelf A is untouched ({left_a})")

        # More than this shelf holds is refused, however much the group has.
        try:
            helpers.consume_stock_fefo(db, product, 20, "sale", user_id, reference="SHELFTEST")
            raise AssertionError("it drew 20 from a shelf holding 7")
        except Exception as exc:                          # noqa: BLE001
            said = str(getattr(exc, "detail", exc))
            assert "branch" in said.lower(), said
            assert "7" in said, said
            print(f"ok    twenty is refused, naming the shelf they are at: {said[:64]}…")
        db.rollback()

        # Somebody with no branch on record still gets the default, which is
        # what a one-shop pharmacy has and never thinks about.
        assert branch_svc.branch_of(db, None) is None
        nobody = sql("select id from users where branch_id is null limit 1")
        if nobody:
            assert branch_svc.branch_of(db, nobody[0][0]) is None
        print("ok    a user with no branch on record still falls back to the default")

        # Receiving puts goods on the receiver's own shelf.
        helpers.receive_stock_batch(db, product, 9, user_id, batch_number="NEW-B",
                                    expiry_date=date.today() + timedelta(days=500))
        db.commit()
        landed = sql("select branch_id from stock_batches where product_id = ? "
                     "and batch_number = 'NEW-B'", (product_id,))[0][0]
        assert landed == b, f"received onto branch {landed}, not the receiver's {b}"
        print("ok    what they receive lands on their own shelf")
    finally:
        db.close()
        reset_current_pharmacy(token)

    execute("delete from batch_allocations where batch_id in "
            "(select id from stock_batches where product_id = ?)", (product_id,))
    execute("delete from stock_movements where product_id = ?", (product_id,))
    execute("delete from stock_batches where product_id = ?", (product_id,))
    execute("delete from branches where code in ('TSA', 'TSB')")


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
