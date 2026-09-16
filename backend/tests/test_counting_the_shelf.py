"""The pharmacy's own count, read onto the right shelf without doubling it.

The stock export is the file a pharmacy actually works from, and four things
about it will quietly ruin a catalogue if they are got wrong:

  - `StockOH` counts PACKS and is fractional. ACRIPTEGA 30s at 0.667 is twenty
    tablets. Read as units it is nought, and 368 of 1,936 lines are fractional.
  - it is a COUNT, not a delivery. Run twice, an import that adds doubles the
    whole shop.
  - it speaks for ONE branch. This pharmacy has three, and 235 products stand in
    two of them; a total that forgets the others contradicts its own batches.
  - one line reads $3,145,500,000.00. Loading it puts it on a label.

Against a snapshot of the local database, with a made-up export:

  - packs become units, multiplied by the pack size
  - a second run changes nothing: the shelf is set, never added to
  - a lower count takes stock off, and records the difference as an adjustment
  - stock standing in another branch is added back, not lost
  - a dated batch is left alone; only the opening one is counted up or down
  - the opening batch carries no expiry, so the counter asks for it off the pack
  - a price the file cannot mean is refused, and the old price stands
  - a count below zero becomes nothing
  - everything written belongs to the pharmacy, which unscoped jobs must do by hand

  python tests/test_counting_the_shelf.py
"""
import sys
from datetime import date, timedelta

from snapshot_app import client, execute, sql


def make_export(path, rows, heading):
    import openpyxl
    book = openpyxl.Workbook()
    sheet = book.active
    for line in heading:
        sheet.append([line])
    sheet.append(["StockCd", "Descr", "Pack Size", "StockOH", "TP0Retail", "TP0Cost"])
    for row in rows:
        sheet.append(row)
    book.save(path)


def run():
    c = client()
    import os
    import tempfile

    from app.database import SessionLocal
    from app.importers import carexpress_stock_on_hand as job
    from app.models import Branch, Product, StockBatch, StockMovement
    from app.tenancy import reset_current_pharmacy, set_current_pharmacy

    # A branch of our own, named so the file can point at it.
    pharmacy_id = sql("select pharmacy_id from products where pharmacy_id is not null limit 1")[0][0]
    if not sql("select id from branches where code = 'TCNT'"):
        execute("insert into branches (code, name, address, is_default, active, pharmacy_id) "
                "values ('TCNT', 'Counting Test Branch', '9 Ledger Road, Harare', 0, 1, ?)",
                (pharmacy_id,))
    branch_id = sql("select id from branches where code = 'TCNT'")[0][0]
    other_id = sql("select id from branches where pharmacy_id = ? and id != ? limit 1",
                   (pharmacy_id, branch_id))[0][0]

    made = []
    for n, (name, pack, price) in enumerate([
            ("Counting Tabs 100s", 100, 20.00),     # fractional packs
            ("Counting Syrup", 1, 8.00),            # also stands in another branch
            ("Counting Caps 30s", 30, 15.00),       # has a dated batch too
            ("Counting Cream", 1, 5.00),            # the absurd price
            ("Counting Drops", 1, 3.00)]):          # counts below zero
        code = f"TCNT{n}"
        if not sql("select id from products where stock_code = ?", (code,)):
            execute("insert into products (stock_code, name, units_per_pack, unit_price, "
                    "cost_price, quantity_on_hand, vat_rate, pharmacy_id) "
                    "values (?, ?, ?, ?, ?, 0, 0, ?)",
                    (code, name, pack, price, price / 2, pharmacy_id))
        made.append((code, sql("select id from products where stock_code = ?", (code,))[0][0]))

    ids = {code: pid for code, pid in made}
    execute("delete from stock_batches where product_id in "
            "(select id from products where stock_code like 'TCNT%')")
    execute("update products set quantity_on_hand = 0 where stock_code like 'TCNT%'")

    # Counting Syrup already stands in the other branch: 7 on that shelf.
    execute("insert into stock_batches (product_id, branch_id, batch_number, expiry_date, "
            "quantity_received, quantity_remaining, unit_cost, pharmacy_id) "
            "values (?, ?, 'OTHERSHELF', ?, 7, 7, 1.0, ?)",
            (ids["TCNT1"], other_id, (date.today() + timedelta(days=400)).isoformat(),
             pharmacy_id))
    execute("update products set quantity_on_hand = 7 where id = ?", (ids["TCNT1"],))
    # Counting Caps has 30 in a real, dated batch on the branch being counted.
    execute("insert into stock_batches (product_id, branch_id, batch_number, expiry_date, "
            "quantity_received, quantity_remaining, unit_cost, pharmacy_id) "
            "values (?, ?, 'REAL-1', ?, 30, 30, 0.4, ?)",
            (ids["TCNT2"], branch_id, (date.today() + timedelta(days=300)).isoformat(),
             pharmacy_id))
    execute("update products set quantity_on_hand = 30 where id = ?", (ids["TCNT2"],))

    heading = ["COUNTING TEST PHARMACY", "9 Ledger Road, Harare", "Stock Usage & History"]
    rows = [
        ["TCNT0", "Counting Tabs 100s", 100, 4.62, 20.00, 10.00],
        ["TCNT1", "Counting Syrup", 1, 5, 8.00, 4.00],
        ["TCNT2", "Counting Caps 30s", 30, 2, 15.00, 7.50],
        ["TCNT3", "Counting Cream", 1, 3, 3145500000.00, 14.60],
        ["TCNT4", "Counting Drops", 1, -2, 3.00, 1.50],
    ]
    path = os.path.join(tempfile.gettempdir(), "counting-test.xlsx")
    make_export(path, rows, heading)

    token = set_current_pharmacy(pharmacy_id)
    db = SessionLocal()
    try:
        read_heading, read_rows = job.read(path)
        shelf = job.whose_shelf(db, read_heading, pharmacy_id)
        assert shelf is not None and shelf.id == branch_id, shelf
        print(f"ok    the file says which shelf it counted: {shelf.name}")

        found = job.plan(db, read_rows)
        job.apply(db, found, branch_id, pharmacy_id)
        db.expire_all()

        def on_hand(code):
            return db.get(Product, ids[code]).quantity_on_hand or 0

        # 4.62 packs of 100 is 462 tablets, not four.
        assert on_hand("TCNT0") == 462, on_hand("TCNT0")
        print(f"ok    4.62 packs of 100 is {on_hand('TCNT0')} tablets, not 4")

        # 5 on this shelf, and the 7 standing in the other branch are still there.
        assert on_hand("TCNT1") == 12, on_hand("TCNT1")
        print("ok    5 counted here plus 7 in the other branch is 12, not 5")

        # The dated batch of 30 is real; the count of 2 packs (60) tops it up by 30.
        assert on_hand("TCNT2") == 60, on_hand("TCNT2")
        real = db.query(StockBatch).filter(StockBatch.product_id == ids["TCNT2"],
                                           StockBatch.batch_number == "REAL-1").first()
        assert real.quantity_remaining == 30, real.quantity_remaining
        print("ok    a dated batch is left alone; only the opening one moves")

        opening = db.query(StockBatch).filter(StockBatch.product_id == ids["TCNT0"],
                                              StockBatch.branch_id == branch_id).first()
        assert opening.expiry_date is None, opening.expiry_date
        assert opening.batch_number == "OPENING", opening.batch_number
        print("ok    the opening batch carries no expiry, so the counter asks for it")

        # The price the file cannot mean never reached the catalogue.
        cream = db.get(Product, ids["TCNT3"])
        assert abs(cream.unit_price - 5.00) < 0.001, cream.unit_price
        assert found.absurd and found.absurd[0][0] == "TCNT3", found.absurd
        print(f"ok    $3,145,500,000.00 refused; the price is still {cream.unit_price}")

        assert on_hand("TCNT4") == 0, on_hand("TCNT4")
        assert found.negative and found.negative[0][0] == "TCNT4", found.negative
        print("ok    a count of minus two becomes nothing, and is listed")

        # A count, not a delivery: run it again and nothing moves.
        before = {code: on_hand(code) for code, _ in made}
        again = job.plan(db, read_rows)
        job.apply(db, again, branch_id, pharmacy_id)
        db.expire_all()
        after = {code: on_hand(code) for code, _ in made}
        assert before == after, (before, after)
        print(f"ok    run twice, the shelf is unchanged ({after['TCNT0']} tablets, not 924)")

        # Counted down, and the difference recorded as an adjustment.
        fewer = [r if r[0] != "TCNT0" else ["TCNT0", "Counting Tabs 100s", 100, 2, 20.00, 10.00]
                 for r in rows]
        make_export(path, fewer, heading)
        _h, less_rows = job.read(path)
        job.apply(db, job.plan(db, less_rows), branch_id, pharmacy_id)
        db.expire_all()
        assert on_hand("TCNT0") == 200, on_hand("TCNT0")
        moves = (db.query(StockMovement)
                 .filter(StockMovement.product_id == ids["TCNT0"],
                         StockMovement.reference == "stock count")
                 .order_by(StockMovement.id.desc()).first())
        assert moves.quantity_delta == -262, moves.quantity_delta
        assert moves.movement_type == "adjustment", moves.movement_type
        print(f"ok    counted down to 200, and the ledger says {moves.quantity_delta}")

        # Unscoped jobs stamp by hand or the rows belong to nobody.
        orphans = [b for b in db.query(StockBatch)
                   .filter(StockBatch.reference == "counted from the pharmacy's export").all()
                   if b.pharmacy_id is None]
        assert not orphans, f"{len(orphans)} batch(es) belong to no pharmacy"
        strays = [m for m in db.query(StockMovement)
                  .filter(StockMovement.reference == "stock count").all()
                  if m.pharmacy_id is None]
        assert not strays, f"{len(strays)} movement(s) belong to no pharmacy"
        print("ok    every row written names the pharmacy it belongs to")

        # And the batch ledger agrees with the figure the counter reads.
        for code, pid in made:
            held = sum(b.quantity_remaining or 0 for b in
                       db.query(StockBatch).filter(StockBatch.product_id == pid).all())
            assert held == on_hand(code), (code, held, on_hand(code))
        print("ok    on-hand agrees with the batches behind it, on every line")
    finally:
        db.close()
        reset_current_pharmacy(token)

    execute("delete from stock_movements where product_id in "
            "(select id from products where stock_code like 'TCNT%')")
    execute("delete from stock_batches where product_id in "
            "(select id from products where stock_code like 'TCNT%')")
    execute("delete from products where stock_code like 'TCNT%'")
    execute("delete from branches where code = 'TCNT'")


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
