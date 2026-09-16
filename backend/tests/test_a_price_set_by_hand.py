"""A price changed at the counter costs a code, and leaves a record.

Catalogue prices arrive from a supplier file and are wrong often enough that a
dispenser has to be able to change one — a margin loaded wrong on import, a
figure that wants rounding to something a person can hand over notes for.
Refusing outright does not stop it happening; it moves it onto a calculator and
a handwritten slip, where nothing is recorded at all.

So it is allowed, it costs somebody's code, and this is what has to be true of
it. Against a snapshot of the local database:

  - setting a price without an authorisation is refused with 428, not 403
  - a cashier is not on the list of people who may set one at all
  - the pharmacist dispensing signs for it with their own code, which is the
    point: sending them to find a second pharmacist to round $8.97 to $9.00
    produces a calculator and a handwritten slip, not a second signature
  - authorised, the record says what it was, what it became, and who signed
  - the record is written when the code is accepted, even if no script follows
  - a script quoting that authorisation is billed at the hand-set price
  - the sale line, and the label, carry the same figure
  - the authorisation is then spent: a second line cannot help itself to it
  - and it cannot be pointed at a different medicine, or used by anybody else
  - the overrides report names the medicine, both figures and both people

  python tests/test_a_price_set_by_hand.py
"""
import sys

from snapshot_app import client, execute, sql

LINE = {"quantity": 30, "dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def run():
    c = client()
    from app.auth import hash_password

    # The pharmacist who dispenses and signs for it, and a cashier who may do
    # neither. `script.price_set` is self-approving on purpose — see the module
    # note — but the list of who may approve it at all does not include a till.
    if not sql("select id from users where username = 'disp_tendai'"):
        execute("insert into users (username, password_hash, full_name, role, active, "
                "pharmacy_id, branch_id) values (?, ?, ?, 'pharmacist', 1, 1, 1)",
                ("disp_tendai", hash_password("Counter-pass-1"), "Tendai dispensing"))
    execute("update users set role = 'pharmacist' where username = 'disp_tendai'")
    if not sql("select id from users where username = 'till_only'"):
        execute("insert into users (username, password_hash, full_name, role, active, "
                "pharmacy_id, branch_id) values (?, ?, ?, 'cashier', 1, 1, 1)",
                ("till_only", hash_password("Counter-pass-1"), "A cashier"))
    if not sql("select id from users where username = 'pharm_rudo'"):
        execute("insert into users (username, password_hash, full_name, role, active, "
                "pharmacy_id, branch_id) values (?, ?, ?, 'pharmacist', 1, 1, 1)",
                ("pharm_rudo", hash_password("Signs-for-it-1"), "Rudo the pharmacist"))

    r = c.post("/api/auth/login", json={"username": "disp_tendai", "password": "Counter-pass-1"},
               headers={"Authorization": ""})
    assert r.status_code == 200, r.text
    them = {"Authorization": "Bearer " + r.json()["access_token"]}

    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=60").json()
               if (p.get("quantity_on_hand") or 0) >= 60 and (p.get("unit_price") or 0) > 0]
    assert len(stocked) >= 2, "need two stocked, priced medicines"
    product, other = stocked[0], stocked[1]
    pack = max(1, int(product.get("units_per_pack") or 1))
    shelf = round((product["unit_price"] or 0) / pack, 4)
    # Rounded off the way a counter rounds: the line, not the price each.
    wanted_line = round(shelf * 30 * 0.9, 2)
    each = round(wanted_line / 30, 4)

    body = {"product_id": product["id"], "now": each, "was": shelf,
            "quantity": 30, "reason": "Rounded at the counter"}

    bare = c.post("/api/price-override", json=body, headers=them)
    assert bare.status_code == 428, f"{bare.status_code}: {bare.text}"
    print("ok    without an authorisation it asks for one (428), it does not just refuse")

    # A cashier is not on the list at all.
    till = c.post("/api/auth/login", json={"username": "till_only",
                                           "password": "Counter-pass-1"},
                  headers={"Authorization": ""}).json()
    refused = c.post("/api/step-up", json={"action": "script.price_set",
                                           "password": "Counter-pass-1"},
                     headers={"Authorization": "Bearer " + till["access_token"]})
    assert refused.status_code >= 400 and "not permitted to approve" in refused.text, refused.text
    print("ok    a cashier is not permitted to set a price at all")

    signed = c.post("/api/step-up", json={"action": "script.price_set",
                                          "approver": "pharm_rudo",
                                          "password": "Signs-for-it-1",
                                          "context": "test"}, headers=them)
    assert signed.status_code == 200, signed.text
    token = signed.json()["token"]

    made = c.post("/api/price-override", json=body,
                  headers={**them, "X-Step-Up": token})
    assert made.status_code == 200, made.text
    override = made.json()
    assert abs(override["now"] - each) < 0.0001, override
    assert abs(override["was"] - shelf) < 0.0001, override
    assert "Rudo" in (override["approved_by"] or ""), override
    print(f"ok    authorised: {override['was']} -> {override['now']} each, "
          f"signed by {override['approved_by']}")

    # Written now, not when a sale happens. An override somebody got a password
    # for and then walked away from is the interesting one.
    row = sql("select requested_by_id, approved_by_id, sale_item_id, prescription_item_id "
              "from price_overrides where id = ?", (override["id"],))
    assert row and row[0][2] is None and row[0][3] is None, row
    print("ok    the record exists before any script does")

    # An abandoned one, to prove the same.
    spare = c.post("/api/step-up", json={"action": "script.price_set",
                                         "approver": "pharm_rudo",
                                         "password": "Signs-for-it-1"}, headers=them).json()
    abandoned = c.post("/api/price-override",
                       json={**body, "now": round(shelf / 2, 4)},
                       headers={**them, "X-Step-Up": spare["token"]})
    assert abandoned.status_code == 200, abandoned.text

    # On a script, and billed at what was authorised.
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    who = c.post("/api/patients", json={"first_name": "Tapiwa", "last_name": "Rounded",
                                        "date_of_birth": "1991-01-01", "gender": "M",
                                        "phone": "0779222111", "confirmed_distinct": True},
                 headers=them).json()
    rx = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": product["id"],
                   "price_override_id": override["id"]}]}, headers=them)
    assert rx.status_code == 200, rx.text
    rx = rx.json()
    held = sql("select unit_price_override from prescription_items where id = ?",
               (rx["items"][0]["id"],))
    assert held and abs((held[0][0] or 0) - each) < 0.0001, held
    print("ok    the line carries the hand-set price, read off the record and not the request")

    out = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
        "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
        "pharmacist_initial": "RM"}, headers=them)
    assert out.status_code == 200, out.text
    sale = out.json()
    line = [i for i in sale["items"] if i["product_id"] == product["id"]][0]
    assert abs(line["unit_price"] - each) < 0.0001, line
    assert abs(line["line_total"] - wanted_line) < 0.02, (line, wanted_line)
    shelf_total = round(shelf * 30, 2)
    print(f"ok    the sale charges {line['line_total']} and not the shelf's {shelf_total}")

    followed = sql("select sale_item_id from price_overrides where id = ?", (override["id"],))
    assert followed and followed[0][0], "the authorisation did not follow the money"
    print("ok    the authorisation is attached to the sale line it paid for")

    labels = c.get(f"/api/prescriptions/{rx['id']}/labels", headers=them)
    if labels.status_code == 200:
        rows = labels.json()
        mine_ = [l for l in (rows if isinstance(rows, list) else rows.get("labels", []))
                 if l.get("product_name") == product["name"]]
        if mine_:
            assert abs((mine_[0].get("unit_price") or 0) - round(each, 2)) < 0.02, mine_[0]
            print("ok    the label quotes the same figure the patient is charged")

    # A script already waiting on the worklist is dispensed as itself, so a
    # price set on one of its lines has to reach the line that already exists.
    # Dropped, it was quoted on screen and charged at the shelf price.
    queued = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": other["id"]}]}, headers=them).json()
    pack2 = max(1, int(other.get("units_per_pack") or 1))
    shelf2 = round((other["unit_price"] or 0) / pack2, 4)
    signed2 = c.post("/api/step-up", json={"action": "script.price_set",
                                           "approver": "pharm_rudo",
                                           "password": "Signs-for-it-1"}, headers=them).json()
    ok2 = c.post("/api/price-override",
                 json={"product_id": other["id"], "now": round(shelf2 * 0.8, 4),
                       "was": shelf2, "quantity": 30, "reason": "Agreed with the patient"},
                 headers={**them, "X-Step-Up": signed2["token"]}).json()
    onto = c.post(f"/api/prescriptions/{queued['id']}/items/{queued['items'][0]['id']}/price",
                  json={"price_override_id": ok2["id"]}, headers=them)
    assert onto.status_code == 200, onto.text
    sold = c.post(f"/api/prescriptions/{queued['id']}/dispense", json={
        "item_ids": [i["id"] for i in queued["items"]], "payment_method": "cash",
        "pharmacist_initial": "RM"}, headers=them)
    assert sold.status_code == 200, sold.text
    got = [i for i in sold.json()["items"] if i["product_id"] == other["id"]][0]
    assert abs(got["unit_price"] - ok2["now"]) < 0.0001, (got, ok2)
    print("ok    a price set on a script already on the worklist reaches the till")

    # Spent. A second line cannot help itself to one approval.
    again = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": product["id"],
                   "price_override_id": override["id"]}]}, headers=them)
    assert again.status_code == 409, f"{again.status_code}: {again.text}"
    print("ok    the same authorisation cannot price a second script")

    # Nor a different medicine.
    wrong = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": other["id"],
                   "price_override_id": abandoned.json()["id"]}]}, headers=them)
    assert wrong.status_code == 400, f"{wrong.status_code}: {wrong.text}"
    print("ok    an authorisation for one medicine cannot price another")

    # Nor somebody else's.
    admin = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": product["id"],
                   "price_override_id": abandoned.json()["id"]}]})
    assert admin.status_code == 403, f"{admin.status_code}: {admin.text}"
    print("ok    one person's authorisation is not another person's to spend")

    # A decimal point in the wrong place is a typo, not a decision.
    silly = c.post("/api/step-up", json={"action": "script.price_set",
                                         "approver": "pharm_rudo",
                                         "password": "Signs-for-it-1"}, headers=them).json()
    fat = c.post("/api/price-override",
                 json={**body, "now": round(shelf * 1000, 2)},
                 headers={**them, "X-Step-Up": silly["token"]})
    assert fat.status_code == 400 and "decimal point" in fat.text, fat.text
    print("ok    a thousand times the shelf price is caught as a slipped decimal point")

    # The report reads it back, with both figures and both people.
    from datetime import date
    today = date.today().isoformat()
    report = c.get(f"/api/reports/run/price_overrides?date_from={today}&date_to={today}"
                   "&per_page=500")
    assert report.status_code == 200, f"{report.status_code}: {report.text[:200]}"
    if report.status_code == 200:
        rows = report.json().get("rows") or []
        mine_ = [r for r in rows if r.get("product") == product["name"]]
        assert mine_, [r.get("product") for r in rows][:8]
        assert any("Rudo" in str(r.get("approved_by")) for r in mine_), mine_[:2]
        assert any(r.get("sale_number") == "not sold" for r in rows), \
            "an abandoned override is missing from the report"
        print(f"ok    the report names it: {mine_[0]['shelf_price']} -> {mine_[0]['sold_at']}, "
              f"approved by {mine_[0]['approved_by']}")

    # And the till's own lines are not all called discounts. A dispensary line
    # is priced per unit against a per-pack catalogue price, and comparing the
    # two used to report every multi-pack medicine as sold at 97% off.
    if True:
        rows = report.json().get("rows") or []
        nonsense = [r for r in rows
                    if r.get("approved_by") == "-" and abs(r.get("percent") or 0) > 90]
        assert not nonsense, nonsense[:3]
        print("ok    per-unit dispensary lines are not reported as 90%-off discounts")


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
