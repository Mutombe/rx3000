"""Every way a script can go out, or be stopped, at the dispensary.

Against a snapshot of the local database, with medicines and batches made for
the purpose so the arithmetic is known exactly:

  supply     full, spanning two batches earliest-expiry first; short supply (a
             to-follow for the balance); nothing handed over; over-supply refused
  stock      not enough refused and nothing written; a failing second line leaves
             the first untouched; expired-only and undated stock named for what
             they are; undated stock dated from the pack; a pack already expired
  repeats    original then each repeat, the count and next date kept, one more
             refused; a no-repeat line dispensed twice refused
  schedule   controlled without its compliance record refused; a cashier
             refused; a pharmacist with the record dispensed; a controlled
             line with no repeats refused a second time; a prohibited schedule
  state      draft, cancelled and held scripts refused
  checks     wrong pack scanned; initials and counselling when required
  money      a private patient raises no claim; a member is claimed once; the
             medical aid choice held; paid now in cash; paid now by a member
             with the scheme's share; a waybill for delivery
  after      labels print for what went out; the script leaves the worklist

  python tests/test_dispensing_scenarios.py
"""
import sys
from datetime import date, datetime, timedelta

from snapshot_app import client, execute, sql

TODAY = date.today()
LINE = {"dosage_instructions": "One three times a day", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}
passed = []


def ok(label):
    passed.append(label)
    print("ok   ", label)


def setting(key, value):
    execute("delete from settings where key = ?", (key,))
    if value is not None:
        execute("insert into settings (key, value, updated_at) values (?, ?, ?)",
                (key, value, datetime.utcnow().isoformat(" ")))


def run():
    c = client()
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    scheme = c.get("/api/medical-aids").json()[0]
    seq = [0]

    def product(name, schedule=0, batches=(), units=10, price=20.0):
        """A medicine at $2 a unit (pack of 10 at $20), with the batches given as
        (quantity, expiry or None)."""
        seq[0] += 1
        p = c.post("/api/products", json={
            "name": f"Scenario {name} {seq[0]}", "schedule": schedule, "units_per_pack": units,
            "unit_price": price, "cost_price": price / 2, "vat_rate": 0.0,
            "category": "medicine", "dosage_form": "tablet"}).json()
        assert "id" in p, p
        for i, (qty, expiry) in enumerate(batches):
            r = c.post("/api/stock/adjust", json={
                "product_id": p["id"], "quantity_delta": qty, "movement_type": "receive",
                "batch_number": f"B{seq[0]}-{i}", "expiry_date": expiry.isoformat() if expiry else None})
            assert r.status_code == 200, r.text
        return p

    def patient(first, aid=False):
        seq[0] += 1
        p = c.post("/api/patients", json={
            "first_name": first, "last_name": f"Scenario{seq[0]}", "date_of_birth": "1985-05-05",
            "gender": "M", "phone": f"07730{seq[0]:05d}", "confirmed_distinct": True}).json()
        assert "id" in p, p
        if aid:
            execute("update patients set medical_aid_id = ?, medical_aid_number = ? where id = ?",
                    (scheme["id"], f"M{seq[0]}", p["id"]))
        else:
            execute("update patients set medical_aid_id = NULL, medical_aid_number = '' where id = ?",
                    (p["id"],))
        return p

    def script(who, lines, **extra):
        r = c.post("/api/prescriptions", json={
            "patient_id": who["id"], "doctor_id": doctor["id"], "notes": "scenario", **extra,
            "items": [{**LINE, **line} for line in lines]})
        assert r.status_code == 200, r.text
        return r.json()

    def dispense(rx, headers=None, items=None, **extra):
        body = {"item_ids": items or [i["id"] for i in rx["items"]], "payment_method": "cash",
                "pharmacist_initial": "TM", **extra}
        return c.post(f"/api/prescriptions/{rx['id']}/dispense", json=body, headers=headers or {})

    def on_hand(p):
        return sql("select quantity_on_hand from products where id = ?", (p["id"],))[0][0]

    def batches(p):
        return sql("select batch_number, quantity_remaining from stock_batches where product_id = ? "
                   "order by id", (p["id"],))

    def sales_of(rx):
        return sql("""select distinct d.sale_id from dispensings d
                      join prescription_items pi on pi.id = d.prescription_item_id
                      where pi.prescription_id = ?""", (rx["id"],))

    def refused(r, status, words):
        detail = r.json().get("detail")
        text = detail if isinstance(detail, str) else str(detail)
        assert r.status_code == status and words.lower() in text.lower(), f"{r.status_code} {r.text}"

    anna = patient("Anna")

    # ---- supply ------------------------------------------------------------------
    p = product("FEFO", batches=[(30, TODAY + timedelta(days=400)), (8, TODAY + timedelta(days=60))])
    rx = script(anna, [{"product_id": p["id"], "quantity": 12}])
    r = dispense(rx)
    assert r.status_code == 200, r.text
    assert [q for _, q in batches(p)] == [26, 0], batches(p)
    assert on_hand(p) == 26 and r.json()["total"] == 24.0, (on_hand(p), r.json()["total"])
    moves = sql("select count(*) from stock_movements where product_id = ? and movement_type = 'sale'", (p["id"],))
    assert moves[0][0] == 2, moves
    ok("full supply draws the earlier expiry first, across two batches, priced per unit")

    p = product("Short", batches=[(50, TODAY + timedelta(days=300))])
    rx = script(anna, [{"product_id": p["id"], "quantity": 10}])
    r = dispense(rx, supply={str(rx["items"][0]["id"]): 3})
    assert r.status_code == 200, r.text
    owed = sql("select quantity_owed from owed_items where prescription_item_id = ?", (rx["items"][0]["id"],))
    assert on_hand(p) == 47 and owed and owed[0][0] == 7, (on_hand(p), owed)
    ok("short supply hands over 3, draws 3, and records 7 to follow")

    rx = script(anna, [{"product_id": p["id"], "quantity": 5}])
    r = dispense(rx, supply={str(rx["items"][0]["id"]): 0})
    assert r.status_code == 200 and on_hand(p) == 47, r.text
    ok("nothing handed over draws nothing and owes the whole line")

    rx = script(anna, [{"product_id": p["id"], "quantity": 5}])
    refused(dispense(rx, supply={str(rx["items"][0]["id"]): 6}), 400, "cannot supply 6 of 5")
    ok("over-supply is refused")

    # ---- stock -------------------------------------------------------------------
    scarce = product("Scarce", batches=[(4, TODAY + timedelta(days=200))])
    plenty = product("Plenty", batches=[(40, TODAY + timedelta(days=200))])
    sales_before = sql("select count(*) from sales")[0][0]
    rx = script(anna, [{"product_id": plenty["id"], "quantity": 5}, {"product_id": scarce["id"], "quantity": 9}])
    refused(dispense(rx), 400, "not enough stock")
    assert on_hand(plenty) == 40 and on_hand(scarce) == 4, (on_hand(plenty), on_hand(scarce))
    assert sql("select count(*) from sales")[0][0] == sales_before
    ok("a second line short of stock refuses the whole script; the first line's stock is untouched, no sale")

    stale = product("Expired", batches=[(20, TODAY - timedelta(days=5))])
    rx = script(anna, [{"product_id": stale["id"], "quantity": 2}])
    refused(dispense(rx), 400, "past their expiry")
    ok("stock past its expiry is refused and called that")

    undated = product("Undated", batches=[(20, None)])
    # Received with no expiry the store assumes one; opening stock imported from
    # another system has none at all, which is the case here.
    execute("update stock_batches set expiry_date = NULL where product_id = ?", (undated["id"],))
    rx = script(anna, [{"product_id": undated["id"], "quantity": 2}])
    refused(dispense(rx), 400, "no expiry date recorded")
    refused(dispense(rx, pack_expiries={str(undated["id"]): (TODAY - timedelta(days=1)).isoformat()}),
            400, "expired on")
    r = dispense(rx, pack_expiries={str(undated["id"]): (TODAY + timedelta(days=500)).isoformat()})
    assert r.status_code == 200 and on_hand(undated) == 18, r.text
    ok("undated stock is named, a pack already expired is refused, the date off the pack dispenses it")

    # ---- repeats -----------------------------------------------------------------
    rep = product("Repeat", batches=[(100, TODAY + timedelta(days=300))])
    rx = script(anna, [{"product_id": rep["id"], "quantity": 10, "repeats_allowed": 2}])
    item_id = rx["items"][0]["id"]
    for n in range(3):
        r = dispense(rx)
        assert r.status_code == 200, f"dispensing {n + 1}: {r.text}"
    used, nxt = sql("select repeats_used, next_repeat_date from prescription_items where id = ?", (item_id,))[0]
    assert used == 2 and nxt is None, (used, nxt)
    refused(dispense(rx), 400, "no repeats remaining")
    assert on_hand(rep) == 70
    ok("original and two repeats go out, the count reaches 2 of 2, a fourth is refused")

    once = script(anna, [{"product_id": rep["id"], "quantity": 1}])
    assert dispense(once).status_code == 200
    refused(dispense(once), 400, "no repeats remaining")
    ok("a line with no repeats cannot be dispensed twice")

    # ---- schedule ----------------------------------------------------------------
    s5 = product("Controlled", schedule=5, batches=[(30, TODAY + timedelta(days=300))])
    rx = script(anna, [{"product_id": s5["id"], "quantity": 2}])
    refused(dispense(rx), 400, "requires")
    from app.auth import hash_password
    for name, role in (("scen_cashier", "cashier"), ("scen_pharm", "pharmacist")):
        if not sql("select id from users where username = ?", (name,)):
            execute("insert into users (username, password_hash, full_name, role, active, pharmacy_id, branch_id) "
                    "values (?, ?, ?, ?, 1, 1, 1)",
                    (name, hash_password("Scenario-pass-1"), f"Scenario {role.title()}", role))
    tokens = {}
    for name in ("scen_cashier", "scen_pharm"):
        r = c.post("/api/auth/login", json={"username": name, "password": "Scenario-pass-1"},
                   headers={"Authorization": ""})
        assert r.status_code == 200, r.text
        tokens[name] = {"Authorization": "Bearer " + r.json()["access_token"]}
    compliance = dict(id_verified=True, id_number_seen="63-123456-A-12", script_sighted=True,
                      prescriber_verified=True)
    r = dispense(rx, headers=tokens["scen_cashier"], **compliance)
    assert r.status_code == 403, r.text
    r = dispense(rx, headers=tokens["scen_pharm"], **compliance)
    assert r.status_code == 200 and on_hand(s5) == 28, r.text
    reg = sql("select count(*) from register_entries where product_id = ?", (s5["id"],))
    assert reg[0][0] >= 2, reg        # the receipt and the dispensing
    refused(dispense(rx, headers=tokens["scen_pharm"], **compliance), 400, "repeat")
    ok("controlled: refused without the record, refused to a cashier, dispensed by a pharmacist with it, once")

    s7 = product("Prohibited", schedule=7, batches=[(5, TODAY + timedelta(days=300))])
    r = c.post("/api/prescriptions", json={
        "patient_id": anna["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": s7["id"], "quantity": 1}]})
    refused(r, 400, "cannot be prescribed")
    ok("a prohibited schedule is stopped at capture, before it can reach dispensing")

    # ---- script state --------------------------------------------------------------
    rx = script(anna, [{"product_id": plenty["id"], "quantity": 1}])
    assert c.post(f"/api/prescriptions/{rx['id']}/holds", json={"reason_code": "patient_request"}).status_code == 200
    refused(dispense(rx), 409, "on hold")
    rx2 = script(anna, [{"product_id": plenty["id"], "quantity": 1}])
    assert c.post(f"/api/prescriptions/{rx2['id']}/cancel", json={"reason": "Captured twice"}).status_code == 200
    refused(dispense(rx2), 400, "cancelled")
    draft = c.post("/api/prescriptions", json={
        "patient_id": anna["id"], "doctor_id": doctor["id"], "draft": True,
        "items": [{**LINE, "product_id": plenty["id"], "quantity": 1}]}).json()
    refused(dispense(draft), 400, "Finish capturing")
    assert on_hand(plenty) == 40
    ok("held, cancelled and draft scripts are refused and draw nothing")

    # ---- checks ------------------------------------------------------------------
    rx = script(anna, [{"product_id": plenty["id"], "quantity": 1}])
    refused(dispense(rx, scanned_codes={str(rx["items"][0]["id"]): "0000000000000"}), 400, "pack scanned")
    setting("dispensing.require_pharmacist_initial", "true")
    refused(dispense(rx, pharmacist_initial=""), 400, "initials")
    setting("dispensing.require_counselling", "always")
    refused(dispense(rx), 400, "counselling")
    r = dispense(rx, counselling_points=["dose"])
    setting("dispensing.require_counselling", None)
    assert r.status_code == 200, r.text
    ok("a wrong pack, missing initials and missing counselling are each refused; recorded, it goes")

    # ---- money -------------------------------------------------------------------
    rx = script(anna, [{"product_id": plenty["id"], "quantity": 2}])
    r = dispense(rx)
    assert r.status_code == 200 and not sql("select id from claims where sale_id = ?", (r.json()["id"],))
    paid = c.post(f"/api/pos/sales/{r.json()['id']}/pay", json={
        "payment_method": "split", "tenders": [{"method": "cash", "currency_code": "USD", "amount": 4.0}]})
    assert paid.status_code == 200 and paid.json()["status"] == "paid", paid.text
    ok("a private patient raises no claim, and pays in cash at the counter")

    member = patient("Brian", aid=True)
    rx = script(member, [{"product_id": plenty["id"], "quantity": 5}])
    r = dispense(rx)
    assert r.status_code == 200, r.text
    sale = r.json()
    claims = sql("select count(*) from claims where sale_id = ?", (sale["id"],))[0][0]
    assert claims == 1 and sale["claim"], sale.get("claim")
    liable = sale["claim"]["patient_liable"]
    paid = c.post(f"/api/pos/sales/{sale['id']}/pay", json={"payment_method": "split", "tenders": [
        {"method": "medical_aid", "currency_code": "USD", "amount": round(sale["total"] - liable, 2)},
        {"method": "cash", "currency_code": "USD", "amount": liable}]})
    assert paid.status_code == 200 and paid.json()["status"] == "paid", paid.text
    assert sql("select count(*) from claims where sale_id = ?", (sale["id"],))[0][0] == 1
    ok("a member is claimed once on dispensing, and settles the shortfall with the scheme's share")

    rx = script(member, [{"product_id": plenty["id"], "quantity": 1}])
    r = dispense(rx, claim={"medical_aid_id": scheme["id"], "member_number": "M-card",
                            "hold": True, "hold_reason": "Switch down"})
    assert r.status_code == 200, r.text
    held = sql("select submitted_at, deferred_reason from claims where sale_id = ?", (r.json()["id"],))
    assert len(held) == 1 and held[0][0] is None, held
    ok("the medical aid choice held raises one claim, unsent, with its reason")

    rx = script(anna, [{"product_id": plenty["id"], "quantity": 1}])
    r = dispense(rx)
    drivers = c.get("/api/drivers").json()
    if not drivers:
        drivers = [c.post("/api/drivers", json={"full_name": "Scenario Driver", "phone": "0771234567"}).json()]
    wb = c.post("/api/waybills", json={"sale_id": r.json()["id"], "patient_id": anna["id"],
                                       "address": "12 Samora Machel Ave", "delivery_fee": 2.0,
                                       "driver_profile_id": drivers[0]["id"]})
    assert wb.status_code == 200 and wb.json().get("waybill_number"), wb.text
    ok("out for delivery raises a waybill against the sale")

    # ---- after -------------------------------------------------------------------
    rx = script(anna, [{"product_id": plenty["id"], "quantity": 3}, {"product_id": rep["id"], "quantity": 3}])
    r = dispense(rx)
    assert r.status_code == 200, r.text
    labels = c.get(f"/api/prescriptions/{rx['id']}/labels").json()
    assert len(labels) == 2 and all(l["printable"] for l in labels), labels
    queue = c.get("/api/dispensary/worklist").json()["queue"]
    assert not any(q["prescription_id"] == rx["id"] for q in queue)
    ok("labels print for both lines, and the script leaves the worklist")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:                  # noqa: BLE001
        import os
        import traceback
        traceback.print_exc()
        print("FAIL", exc)
        sys.stdout.flush()
        os._exit(1)          # the scheduler's threads would keep a failed run alive
    print(f"\nall {len(passed)} scenarios passed")
