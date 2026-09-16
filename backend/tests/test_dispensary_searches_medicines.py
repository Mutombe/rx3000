"""The medicine search offers medicines, not the whole shop.

Every CareXpress line came across as schedule 0 — one pharmacy's entire
catalogue, sixteen thousand of them — so a dispenser searching for a medicine
while a patient waited was offered fizzy drinks, hair food and phone credit,
and a chocolate bar could be put on a prescription.

The pharmacy's own departments already know which is which. Against a snapshot
of the local database:

  - a department is judged on what is filed in it: mostly medicine dispenses,
    mostly shop does not
  - the dispensary search skips a department that is marked shop-only
  - a scheduled medicine is found wherever it is filed
  - the pharmacy can switch a department back on, and its lines return
  - an unclassified catalogue still works: schedule 0 medicines are searchable
    on a script, while controlled substances never are
  - nothing changes on the stock screens: the lines are still catalogued,
    counted and valued

  python tests/test_dispensary_searches_medicines.py
"""
import sys

from snapshot_app import client, sql


def run():
    c = client()

    def search(route, q, limit=200):
        r = c.get(f"/api/dispensing/products?route={route}&q={q}&limit={limit}")
        assert r.status_code == 200, r.text
        return {p["name"] for p in r.json()}

    shop = c.post("/api/stock-categories", json={"name": "Test Drinks & Snacks"}).json()
    dispensary = c.post("/api/stock-categories", json={"name": "Test Dispensary"}).json()

    fizzy = c.post("/api/products", json={"name": "Test Fizzy Orange 400ml", "category": "front_shop",
                                          "unit_price": 1.0, "category_id": shop["id"]}).json()
    tablet = c.post("/api/products", json={"name": "Test Paracetamol 500mg tablets", "category": "medicine",
                                           "unit_price": 3.0, "category_id": dispensary["id"]}).json()
    # Filed with the drinks, but scheduled: a medicine is a medicine wherever
    # somebody put it.
    misfiled = c.post("/api/products", json={"name": "Test Amoxicillin 250mg caps", "category": "front_shop",
                                             "schedule": 4, "unit_price": 8.0,
                                             "category_id": shop["id"]}).json()
    assert all("id" in p for p in (fizzy, tablet, misfiled))

    c.put(f"/api/stock-categories/{shop['id']}", json={"dispensable": False})
    listed = c.get("/api/stock-categories").json()["items"]
    assert any(x["id"] == shop["id"] and x["dispensable"] is False for x in listed), listed[:3]
    print("ok    a department can be marked shop-only, and says so on the departments screen")

    found = search("otc", "Test%20")
    assert fizzy["name"] not in found, "the drink is still in the medicine search"
    assert tablet["name"] in found, found
    print("ok    the medicine search skips a shop-only department, and keeps the medicines")

    found = search("prescription", "Test%20")
    assert misfiled["name"] in found, "a scheduled medicine filed with the drinks was not found"
    assert fizzy["name"] not in found
    assert tablet["name"] in found, "an unscheduled medicine is not searchable on a script"
    print("ok    a scheduled medicine is found wherever it is filed; an unclassified one is searchable on a script")

    controlled = sql("select name from products where schedule >= 5 and pharmacy_id = 1 limit 1")
    if controlled:
        on_script = search("prescription", controlled[0][0].split()[0])
        assert controlled[0][0] not in on_script, "a controlled substance is offered on the ordinary tab"
        print("ok    a controlled substance is never offered on the prescription tab")

    back = c.put(f"/api/stock-categories/{shop['id']}", json={"dispensable": True})
    assert back.status_code == 200, back.text
    assert back.json()["dispensable"] is True, back.json()
    again = search("otc", "Test%20")
    assert fizzy["name"] in again, f"switching it back on did not return its lines: {sorted(again)}"
    print("ok    switched back on, the department's lines return")
    c.put(f"/api/stock-categories/{shop['id']}", json={"dispensable": False})

    cats = {x["id"]: x for x in c.get("/api/stock-categories").json()["items"]}
    assert cats[shop["id"]]["products"] >= 2, cats[shop["id"]]
    catalogue = c.get(f"/api/products?q=Test%20Fizzy&limit=5").json()
    rows = catalogue["items"] if isinstance(catalogue, dict) else catalogue
    assert any(p["name"] == fizzy["name"] for p in rows), "the drink left the catalogue as well"
    print("ok    the lines are still catalogued, counted and valued — only the medicine search changed")


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
