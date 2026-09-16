"""Refreshing the catalogue from the pharmacy's own stock export.

Against a snapshot of the local database, with a small export written here so
the arithmetic is known:

  - matched on the stock code, not the name, because the name is the thing
    being corrected
  - the price, cost, SEP, pack size, barcode, AHFoZ code and shelf location are
    taken from the file
  - a line the pharmacy no longer sells is retired; one it sells again comes back
  - a department the file names is created, and the dispensary searches the
    dispensary and the OTC shelves but not cosmetics
  - a name that differs only in spacing is corrected quietly
  - a name that differs substantively is reported and NOT taken: stock codes get
    reused, and a rename carries the old product's history onto the new name
  - a preview writes nothing

  python tests/test_stock_totals_refresh.py
"""
import pathlib
import sys
import tempfile

from snapshot_app import client, sql

COLUMNS = ["STOCKCD", "DESCR", "PACKSIZE", "DEPCD", "DEPDESCR", "BINLOCATION", "RETAIL",
           "COST", "BARCODE", "NAPCD", "SEP", "SCHEDULENO", "ISACTIV", "ISDISCONT"]


def export(rows) -> str:
    """The pharmacy's export, headers three rows down as theirs has them."""
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "StockTotals"
    sheet.append(["CARE XPRESS PHARMACY"])
    sheet.append(["Report Date: today"])
    sheet.append([])
    sheet.append(COLUMNS)
    for row in rows:
        sheet.append([row.get(c, "") for c in COLUMNS])
    path = pathlib.Path(tempfile.mkdtemp()) / "stock.xlsx"
    book.save(path)
    return str(path)


def run():
    c = client()
    from app.importers import carexpress_stock_totals as refresh
    from app.database import SessionLocal
    from app import tenancy

    made = c.post("/api/products", json={"name": "Refresh Cough Syrup 100ml", "unit_price": 1.0,
                                         "cost_price": 0.5, "units_per_pack": 1}).json()
    stale = c.post("/api/products", json={"name": "Refresh Discontinued Balm", "unit_price": 4.0,
                                          "cost_price": 2.0}).json()
    reused = c.post("/api/products", json={"name": "Refresh Eye Shadow Silver", "unit_price": 9.0,
                                           "cost_price": 4.0}).json()
    for product, code in ((made, "RF-001"), (stale, "RF-002"), (reused, "RF-003")):
        sql("select 1")
        from snapshot_app import execute
        execute("update products set stock_code = ? where id = ?", (code, product["id"]))

    path = export([
        {"STOCKCD": "RF-001", "DESCR": "Refresh Cough  Syrup 100ml", "PACKSIZE": 12,
         "DEPDESCR": "DISPENSARY", "BINLOCATION": "A4-02", "RETAIL": 18.5, "COST": 9.25,
         "BARCODE": "6001234567890", "NAPCD": "AH-7781", "SEP": 20.0,
         "SCHEDULENO": "3", "ISACTIV": "Y", "ISDISCONT": "N"},
        {"STOCKCD": "RF-002", "DESCR": "Refresh Discontinued Balm", "PACKSIZE": 1,
         "DEPDESCR": "COSMETICS", "RETAIL": 4.0, "COST": 2.0,
         "ISACTIV": "N", "ISDISCONT": "Y"},
        {"STOCKCD": "RF-003", "DESCR": "Refresh Tea Tree Oil 20ml", "PACKSIZE": 1,
         "DEPDESCR": "OTC VATABLE", "RETAIL": 6.0, "COST": 3.0,
         "ISACTIV": "Y", "ISDISCONT": "N"},
        {"STOCKCD": "RF-NOT-HERE", "DESCR": "Something we never had", "RETAIL": 1.0},
    ])

    db = SessionLocal()
    tenancy.stamp(db)
    token = tenancy.set_current_pharmacy(1)
    try:
        rows = refresh.read(path)
        assert len(rows) == 4, rows
        summary, edits = refresh.plan(db, rows, rename=False)
        assert summary.matched == 3 and summary.unmatched == ["RF-NOT-HERE"], summary
        before = sql("select unit_price from products where id = ?", (made["id"],))[0][0]
        assert before == 1.0, before
        print(f"ok    a preview matches {summary.matched} of {summary.rows} on the stock code and writes nothing")

        assert len(summary.renames) == 1 and summary.renames[0][0] == "RF-003", summary.renames
        print(f"ok    the reused code is reported, not taken: "
              f"{summary.renames[0][1]!r} -> {summary.renames[0][2]!r}")

        refresh.apply(db, edits)
    finally:
        tenancy.reset_current_pharmacy(token)
        db.close()

    got = sql("""select name, unit_price, cost_price, sep_price, units_per_pack, barcode,
                        nappi_code, bin_location, active
                 from products where id = ?""", (made["id"],))[0]
    assert got[0] == "Refresh Cough Syrup 100ml", got[0]          # spacing corrected quietly
    assert (got[1], got[2], got[3]) == (18.5, 9.25, 20.0), got
    assert got[4] == 12 and got[5] == "6001234567890" and got[6] == "AH-7781", got
    assert got[7] == "A4-02" and got[8] == 1, got
    print("ok    price, cost, SEP, pack size, barcode, AHFoZ code and shelf location are taken from the file")

    assert sql("select active from products where id = ?", (stale["id"],))[0][0] == 0
    print("ok    a line the pharmacy no longer sells is retired")

    kept = sql("select name from products where id = ?", (reused["id"],))[0][0]
    assert kept == "Refresh Eye Shadow Silver", kept
    print("ok    …and the reused code keeps the name its history belongs to")

    departments = dict(sql("select name, dispensable from stock_categories"))
    assert departments.get("OTC VATABLE") == 1, departments
    assert sql("""select sc.name from products p join stock_categories sc on sc.id = p.category_id
                  where p.id = ?""", (reused["id"],))[0][0] == "OTC VATABLE"
    print("ok    a department the file names is created, and the OTC shelf is dispensed from")

    # Schedules are never taken from the file: its own column says 3 for this
    # cough syrup, and that column has a room spray in it elsewhere.
    assert sql("select schedule from products where id = ?", (made["id"],))[0][0] == 0
    print("ok    the file's SCHEDULENO is ignored — schedules are classified by name, not imported")


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
