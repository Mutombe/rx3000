"""Who rang the sale up, and who actually took the money, are two people.

A dispensary sale is created by the dispenser when the medicine leaves the
shelf, and paid at the front by whoever is on the till. Every cash-up and shift
report attributed it by `cashier_id` — the dispenser — so the cashier's own
drawer was short of money they had counted, and the dispenser's figures carried
money they never touched. On a short drawer each is then asked to answer for the
other's total.

Against a snapshot of the local database:

  - a dispensary sale is rung up by the dispenser and settled by nobody yet
  - settling it at the till records who took it, and when, by name
  - the cash-up counts it for the person who took it, not the one who rang it up
  - the cashier performance report says the same
  - a sale settled by the dispenser themselves records them, so working alone
    is traceable too
  - sales from before this was recorded still count by who rang them up

  python tests/test_who_took_the_money.py
"""
import sys
from datetime import datetime

from snapshot_app import client, execute, sql

LINE = {"quantity": 1, "dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def run():
    c = client()
    from app.auth import hash_password

    # A cashier at the front, who is not the dispenser.
    if not sql("select id from users where username = 'till_kudzai'"):
        execute("insert into users (username, password_hash, full_name, role, active, "
                "pharmacy_id, branch_id) values (?, ?, ?, 'cashier', 1, 1, 1)",
                ("till_kudzai", hash_password("Counter-pass-1"), "Kudzai at the till"))
    cashier_id = sql("select id from users where username = 'till_kudzai'")[0][0]
    r = c.post("/api/auth/login", json={"username": "till_kudzai", "password": "Counter-pass-1"},
               headers={"Authorization": ""})
    assert r.status_code == 200, r.text
    till = {"Authorization": "Bearer " + r.json()["access_token"]}

    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=40").json()
               if (p.get("quantity_on_hand") or 0) >= 5]
    who = c.post("/api/patients", json={"first_name": "Nyasha", "last_name": "Drawer",
                                        "date_of_birth": "1993-03-03", "gender": "F",
                                        "phone": "0779444555", "confirmed_distinct": True}).json()

    def dispense(product):
        rx = c.post("/api/prescriptions", json={
            "patient_id": who["id"], "doctor_id": doctor["id"],
            "items": [{**LINE, "product_id": product["id"]}]}).json()
        out = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
            "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
            "pharmacist_initial": "SA"})
        assert out.status_code == 200, out.text
        return out.json()

    sale = dispense(stocked[0])
    admin_id = sql("select id from users where username = 'admin'")[0][0]
    row = sql("select cashier_id, settled_by_id from sales where id = ?", (sale["id"],))[0]
    assert row[0] == admin_id and row[1] is None, row
    print("ok    rung up by the dispenser, settled by nobody yet")

    paid = c.post(f"/api/pos/sales/{sale['id']}/pay",
                  json={"payment_method": "cash", "amount_tendered": sale["total"] + 5},
                  headers=till)
    assert paid.status_code == 200, paid.text
    settled = paid.json()
    assert settled["settled_by_id"] == cashier_id, settled["settled_by_id"]
    assert settled["settled_by_name"] == "Kudzai at the till", settled["settled_by_name"]
    assert settled["cashier_name"] and settled["settled_at"], settled
    print(f"ok    settled at the till by {settled['settled_by_name']}, "
          f"rung up by {settled['cashier_name']}")

    # The cash-up counts what a person actually took.
    def counted_for(user_id):
        rows = sql("""select count(*) from sales
                      where coalesce(settled_by_id, cashier_id) = ? and id = ?""",
                   (user_id, sale["id"]))
        return rows[0][0]

    assert counted_for(cashier_id) == 1, "the till's own sale is not in their drawer"
    assert counted_for(admin_id) == 0, "the dispenser is still carrying money they never took"
    print("ok    the cash-up counts it for the till, not for the dispenser")

    report = c.get("/api/reports/run?key=cashier_performance&days=1")
    if report.status_code == 200:
        names = [r.get("cashier") for r in (report.json().get("rows") or [])]
        assert any("Kudzai" in str(n) for n in names), names[:6]
        print(f"ok    the cashier report credits them by name ({[n for n in names if 'Kudzai' in str(n)]})")

    # Working alone: the dispenser takes it themselves, and that is recorded.
    alone = dispense(stocked[1])
    mine = c.post(f"/api/pos/sales/{alone['id']}/pay",
                  json={"payment_method": "cash", "amount_tendered": alone["total"] + 5})
    assert mine.status_code == 200, mine.text
    assert mine.json()["settled_by_id"] == admin_id, mine.json()["settled_by_id"]
    print("ok    taken by the dispenser working alone, it records them")

    # A sale from before any of this was recorded still counts by who rang it up.
    execute("update sales set settled_by_id = NULL, settled_at = NULL where id = ?", (alone["id"],))
    assert sql("""select count(*) from sales
                  where coalesce(settled_by_id, cashier_id) = ? and id = ?""",
               (admin_id, alone["id"]))[0][0] == 1
    print("ok    older sales, with nothing recorded, still count by who rang them up")


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
