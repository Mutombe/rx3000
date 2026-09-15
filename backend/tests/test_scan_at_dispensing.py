"""The pack picked off the shelf is checked against the prescription line.

CareXpress To-Be blueprint §5 (Barcode Verification at Dispensing) and §8.
Against a snapshot of the local database:

  - scanning a pack that is on the script finds its line
  - scanning one that is not says so
  - a GS1 pack past its expiry is flagged, whatever else it is
  - dispensing with a scan claimed for the wrong pack is refused, and makes no
    sale — the server resolves the code itself
  - the right pack dispenses, and the dispensing records the code as verified
  - with the setting on, an unscanned line is refused

  python tests/test_scan_at_dispensing.py
"""
import sys
from datetime import datetime

from snapshot_app import client, execute, sql

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def set_scan_rule(on: bool):
    execute("delete from settings where key = 'dispensing.require_scan_check'")
    execute("insert into settings (key, value, updated_at) values (?, ?, ?)",
            ("dispensing.require_scan_check", "true" if on else "false",
             datetime.utcnow().isoformat(" ")))


def two_barcoded(c):
    products = [p for p in c.get("/api/dispensing/products?route=prescription&limit=200").json()
                if (p.get("quantity_on_hand") or 0) >= 5]
    barcoded = []
    for p in products:
        code = sql("select barcode from products where id = ?", (p["id"],))[0][0]
        if code and code.isdigit() and len(code) in (8, 12, 13, 14):
            barcoded.append((p, code))
        if len(barcoded) == 2:
            return barcoded
    raise AssertionError("the snapshot needs two stocked prescription medicines with barcodes")


def a_script(c, product):
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    patients = c.get("/api/patients?q=i&limit=40").json()
    return c.post("/api/prescriptions", json={
        "patient_id": patients[0]["id"], "doctor_id": doctor["id"], "notes": "scan test",
        "items": [{**LINE, "product_id": product["id"], "quantity": 1}]}).json(), patients


def dispense(c, rx, **extra):
    return c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
        "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
        "pharmacist_initial": "TM", **extra})


def run():
    c = client()
    set_scan_rule(False)
    (right, right_code), (wrong, wrong_code) = two_barcoded(c)

    rx, patients = a_script(c, right)
    item_id = rx["items"][0]["id"]

    r = c.post("/api/scan", json={"code": right_code, "context": "dispense",
                                  "prescription_id": rx["id"]}).json()
    assert r["found"] and r["script_line"] and r["script_line"]["item_id"] == item_id, r
    print("ok    scanning a pack that is on the script finds its line")

    r = c.post("/api/scan", json={"code": wrong_code, "context": "dispense",
                                  "prescription_id": rx["id"]}).json()
    assert r["found"] and r["script_line"] is None, r
    assert any("not on this script" in w for w in r["warnings"]), r["warnings"]
    print("ok    scanning a pack that is not on the script says so")

    if len(right_code) == 13:
        gs1 = f"(01)0{right_code}(17)200101(10)OLD-LOT"
        r = c.post("/api/scan", json={"code": gs1, "context": "dispense",
                                      "prescription_id": rx["id"]}).json()
        assert r.get("expired") and any("expired" in w for w in r["warnings"]), r
        print("ok    a GS1 pack past its expiry is flagged")
    else:
        print("--    barcode is not EAN-13; the GS1 expiry check was not exercised")

    # Find a patient this script can actually go to, then make the checks.
    reached = None
    for patient in patients:
        rx = c.post("/api/prescriptions", json={
            "patient_id": patient["id"], "doctor_id": rx["doctor_id"] if "doctor_id" in rx else None,
            "notes": "scan test", "items": [{**LINE, "product_id": right["id"], "quantity": 1}]}).json()
        if "items" not in rx:
            continue
        item_id = rx["items"][0]["id"]
        before = sql("select count(*) from sales")[0][0]
        r = dispense(c, rx, scanned_codes={str(item_id): wrong_code})
        if r.status_code == 409:
            continue
        after = sql("select count(*) from sales")[0][0]
        assert r.status_code == 400 and "pack scanned" in r.json()["detail"], (
            f"a scan claimed for the wrong pack was accepted: {r.status_code} {r.text}")
        assert after == before, f"a refused dispensing made a sale ({before} -> {after})"
        reached = (rx, item_id)
        break
    assert reached, "no patient in the snapshot reached the scan check"
    rx, item_id = reached
    print("ok    a scan claimed for the wrong pack is refused, and makes no sale")

    r = dispense(c, rx, scanned_codes={str(item_id): right_code})
    assert r.status_code == 200, f"the right pack was refused: {r.text}"
    did = sql("select id, scan_verified, scan_code from dispensings where prescription_item_id = ? "
              "order by id desc limit 1", (item_id,))[0]
    assert did[1] and did[2] == right_code, did
    detail = c.get(f"/api/dispensings/{did[0]}").json()
    assert detail["scan_verified"] and detail["scan_code"] == right_code, detail
    print("ok    the right pack dispenses, recorded as scanned and verified")

    set_scan_rule(True)
    for patient in patients:
        rx = c.post("/api/prescriptions", json={
            "patient_id": patient["id"], "doctor_id": detail.get("prescription", {}).get("doctor_id"),
            "notes": "scan required", "items": [{**LINE, "product_id": right["id"], "quantity": 1}]}).json()
        if "items" not in rx:
            continue
        r = dispense(c, rx)
        if r.status_code == 409:
            continue
        assert r.status_code == 400 and "not yet scanned" in r.json()["detail"], (
            f"with the setting on, an unscanned line went out: {r.status_code} {r.text}")
        r = dispense(c, rx, scanned_codes={str(rx["items"][0]["id"]): right_code})
        assert r.status_code == 200, f"with the setting on, a scanned line was refused: {r.text}"
        print("ok    with the setting on, an unscanned line is refused and a scanned one goes out")
        break
    set_scan_rule(False)


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"FAIL  {exc}")
        sys.exit(1)
