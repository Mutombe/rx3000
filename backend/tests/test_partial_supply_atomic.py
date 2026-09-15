"""A dispensing that fails leaves nothing behind — including a short supply.

The dispense endpoint builds a sale, deducts stock and records what is owed,
line by line, and means to commit once at the end so that a refusal on any
line undoes all of it. Recording an owed balance committed on its own, inside
that loop. So a script whose first line was partly supplied and whose second
line was then refused for want of stock left behind:

  - the first line's stock, already deducted,
  - an owed balance for a supply that never happened,
  - a half-built sale,

all committed, none of it undone by the refusal the dispenser was shown.

Runs in-process against a snapshot of the local database (tests/snapshot_app.py),
so it needs no server and cannot touch real data:

  python tests/test_partial_supply_atomic.py
"""
import sys

from snapshot_app import client, sql

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def _facts(product_id: int, prescription_item_id: int) -> tuple[float, int, int]:
    """Stock, sales and owed balances, as stored."""
    stock = sql("select quantity_on_hand from products where id = ?", (product_id,))
    assert stock, f"product {product_id} is not in the snapshot"
    sales = sql("select count(*) from sales")[0][0]
    owed = sql("select count(*) from owed_items where prescription_item_id = ?",
               (prescription_item_id,))[0][0]
    return stock[0][0], sales, owed


def _setup(c, patient_query: str):
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=40").json()
               if (p.get("quantity_on_hand") or 0) >= 5]
    assert len(stocked) >= 2, "the snapshot needs two prescription medicines in stock"
    return c.get(f"/api/patients?q={patient_query}&limit=25").json(), doctor, stocked


def test_a_refused_dispensing_with_a_short_supply_leaves_nothing_behind():
    c = client()
    patients, doctor, stocked = _setup(c, "a")
    first, second = stocked[0], stocked[1]

    # A patient whose script reaches the stock check. Some carry a blocking
    # warning that refuses the dispensing earlier, for a different reason,
    # which would prove nothing about this one.
    for patient in patients:
        rx = c.post("/api/prescriptions", json={
            "patient_id": patient["id"], "doctor_id": doctor["id"], "notes": "atomicity test",
            "items": [{**LINE, "product_id": first["id"], "quantity": 5},
                      {**LINE, "product_id": second["id"], "quantity": 9_999_999}],
        })
        assert rx.status_code == 200, rx.text
        rx = rx.json()
        item_first = next(i for i in rx["items"] if i["product_id"] == first["id"])
        stock_before, sales_before, owed_before = _facts(first["id"], item_first["id"])

        r = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
            "item_ids": [i["id"] for i in rx["items"]],
            "payment_method": "cash", "pharmacist_initial": "TM",
            # One of five handed over on the first line; four owed.
            "supply": {str(item_first["id"]): 1},
        })
        if r.status_code == 409:
            continue
        assert r.status_code == 400, f"the second line should be refused for stock: {r.status_code} {r.text}"
        stock_after, sales_after, owed_after = _facts(first["id"], item_first["id"])
        assert owed_after == owed_before, (
            f"an owed balance was left behind by a refused dispensing ({owed_before} -> {owed_after})")
        assert stock_after == stock_before, (
            f"the first line's stock stayed deducted after the refusal ({stock_before} -> {stock_after})")
        assert sales_after == sales_before, (
            f"a half-built sale was left behind ({sales_before} -> {sales_after})")
        return
    raise AssertionError("no patient in the snapshot reached the stock check")


def test_a_successful_short_supply_still_keeps_its_balance():
    """Taking the commit out of `record` must not lose the balance when the
    dispensing goes through; the endpoint's own commit now carries it."""
    c = client()
    patients, doctor, stocked = _setup(c, "e")
    product = stocked[-1]
    for patient in patients:
        rx = c.post("/api/prescriptions", json={
            "patient_id": patient["id"], "doctor_id": doctor["id"], "notes": "short supply kept",
            "items": [{**LINE, "product_id": product["id"], "quantity": 5}],
        }).json()
        item = rx["items"][0]
        stock_before, _, owed_before = _facts(product["id"], item["id"])
        r = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
            "item_ids": [item["id"]], "payment_method": "cash",
            "pharmacist_initial": "TM", "supply": {str(item["id"]): 2},
        })
        if r.status_code == 409:
            continue
        assert r.status_code == 200, f"a short supply should dispense: {r.status_code} {r.text}"
        stock_after, _, owed_after = _facts(product["id"], item["id"])
        assert owed_after == owed_before + 1, (
            f"the owed balance was lost on a dispensing that succeeded ({owed_before} -> {owed_after})")
        assert round(stock_before - stock_after, 6) == 2, (
            f"only the two handed over should leave the shelf ({stock_before} -> {stock_after})")
        return
    raise AssertionError("no patient in the snapshot reached a successful dispensing")


def test_a_promise_recorded_on_its_own_is_saved():
    """The standalone endpoint lost the commit `record` used to do for it, and
    has to do its own. Read back through a fresh connection, so a row that was
    only flushed and then discarded would not be counted."""
    c = client()
    product = c.get("/api/dispensing/products?route=prescription&limit=5").json()[0]
    before = sql("select count(*) from owed_items where product_id = ?", (product["id"],))[0][0]
    r = c.post("/api/to-follows", json={"product_id": product["id"], "quantity": 3,
                                        "notes": "in on Friday"})
    assert r.status_code == 200, r.text
    after = sql("select count(*) from owed_items where product_id = ?", (product["id"],))[0][0]
    assert after == before + 1, f"a promise recorded on its own was not saved ({before} -> {after})"


if __name__ == "__main__":
    failed = 0
    for label, fn in [
        ("a refused dispensing with a short supply leaves nothing behind",
         test_a_refused_dispensing_with_a_short_supply_leaves_nothing_behind),
        ("a successful short supply still keeps its balance",
         test_a_successful_short_supply_still_keeps_its_balance),
        ("a promise recorded on its own is saved",
         test_a_promise_recorded_on_its_own_is_saved),
    ]:
        try:
            fn()
            print(f"ok    {label}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {label}: {exc}")
    sys.exit(1 if failed else 0)
