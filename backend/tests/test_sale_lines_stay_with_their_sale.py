"""A sale's lines belong to the pharmacy the sale does.

The invoice importer set the pharmacy on each sale and left it off the lines,
so the lines took whichever pharmacy the importing session was in. On the
CareXpress import that was another tenant for 70,305 of 80,116 lines: the
pharmacy could see its invoices and not what was on them, and the other tenant
could see both.

Against a snapshot of the local database:

  - a line written for another pharmacy's sale takes that sale's pharmacy,
    whatever pharmacy the session is working as
  - lines already filed under the wrong pharmacy are moved to their sale's by
    the migration, and nothing else moves
  - the sale's own pharmacy can then read its lines back

  python tests/test_sale_lines_stay_with_their_sale.py
"""
import sys

from snapshot_app import client, execute, sql


def run():
    c = client()                       # runs the migrations, signed in as admin

    left = sql("""select count(*) from sale_items si join sales s on s.id = si.sale_id
                  where coalesce(si.pharmacy_id, -1) <> coalesce(s.pharmacy_id, -1)""")[0][0]
    assert left == 0, f"{left} line(s) are still filed under the wrong pharmacy"
    moved = sql("""select count(*) from sale_items si join sales s on s.id = si.sale_id
                   where si.pharmacy_id = s.pharmacy_id and s.pharmacy_id <> 1""")[0][0]
    print(f"ok    the migration moved the imported lines home ({moved} under their own pharmacy)")

    # A sale belonging to another pharmacy, written while working as this one.
    from app.database import SessionLocal
    from app.models import Product, Sale, SaleItem
    from app import tenancy

    product_id = sql("select id from products where pharmacy_id = 1 limit 1")[0][0]
    other = sql("select id from pharmacies where id <> 1 limit 1")
    other_id = other[0][0] if other else 999
    db = SessionLocal()
    tenancy.stamp(db)
    token = tenancy.set_current_pharmacy(1)          # working as pharmacy 1 …
    try:
        sale = Sale(sale_number="TEST-TENANCY-1", status="paid", total=1.0,
                    pharmacy_id=other_id)            # … writing another's sale
        sale.items = [SaleItem(product_id=product_id, description="x", quantity=1,
                               unit_price=1.0, line_total=1.0)]
        db.add(sale)
        db.commit()
        sale_id = sale.id
    finally:
        tenancy.reset_current_pharmacy(token)
        db.close()

    got = sql("select pharmacy_id from sale_items where sale_id = ?", (sale_id,))
    assert got and all(row[0] == other_id for row in got), (got, other_id)
    print(f"ok    a line written for another pharmacy's sale is filed under that pharmacy ({other_id})")

    execute("update sale_items set pharmacy_id = 1 where sale_id = ?", (sale_id,))
    from app.database import engine
    from app.migrate import run_migrations
    run_migrations(engine)
    got = sql("select pharmacy_id from sale_items where sale_id = ?", (sale_id,))
    assert all(row[0] == other_id for row in got), got
    print("ok    a line put under the wrong pharmacy is moved back by the migration")

    execute("delete from sale_items where sale_id = ?", (sale_id,))
    execute("delete from sales where id = ?", (sale_id,))


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
