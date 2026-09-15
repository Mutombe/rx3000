"""Paid by medical aid, chosen at Finish.

Against a snapshot of the local database:

  - the estimate is made against a scheme and number from the card, for a
    patient with no scheme on file, without changing the patient
  - dispensing on that claim refuses a missing scheme, member number, or (held)
    reason — and nothing is dispensed
  - claim now: one claim, adjudicated, and the patient's record takes the card
  - hold: one claim, not sent, carrying the reason
  - a patient with a scheme already on file, dispensed on the choice, gets one
    claim, not two
  - the shortfall is settled against the sale with the ordinary pay endpoint

  python tests/test_dispense_medical_aid_choice.py
"""
import sys

from snapshot_app import client, execute, sql

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def run():
    c = client()
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=60").json()
               if (p.get("quantity_on_hand") or 0) >= 20 and (p.get("unit_price") or 0) > 0]
    schemes = c.get("/api/medical-aids").json()
    assert schemes, "no medical aid schemes in the database"
    scheme = schemes[0]

    fresh = c.post("/api/patients", json={
        "first_name": "Tariro", "last_name": "Claimtest", "date_of_birth": "1980-02-02",
        "gender": "F", "phone": "0771000999", "confirmed_distinct": True}).json()
    assert "id" in fresh, fresh
    execute("UPDATE patients SET medical_aid_id = NULL, medical_aid_number = '' WHERE id = ?", (fresh["id"],))

    items = [{"product_id": stocked[0]["id"], "quantity": 2}]
    none = c.post("/api/claim-estimate", json={"patient_id": fresh["id"], "items": items}).json()
    assert none["scheme_pays"] == 0, none
    est = c.post("/api/claim-estimate", json={"patient_id": fresh["id"], "items": items,
                                              "medical_aid_id": scheme["id"],
                                              "member_number": "CARD-001"}).json()
    assert est["scheme_pays"] > 0 and est["scheme"] == scheme["name"], est
    row = sql("SELECT medical_aid_id FROM patients WHERE id = ?", (fresh["id"],))[0]
    assert row[0] is None, row
    print(f"ok    estimate against the card: scheme pays {est['scheme_pays']}, patient {est['patient_pays']}; record untouched")

    def script(patient_id, product):
        return c.post("/api/prescriptions", json={
            "patient_id": patient_id, "doctor_id": doctor["id"], "notes": "aid choice",
            "items": [{**LINE, "product_id": product["id"], "quantity": 2}]}).json()

    def dispense(rx, claim):
        return c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
            "item_ids": [i["id"] for i in rx["items"]], "payment_method": "medical_aid",
            "pharmacist_initial": "TM", "claim": claim})

    rx = script(fresh["id"], stocked[0])
    for claim, said in ((dict(medical_aid_id=999999, member_number="X"), "Choose the medical aid"),
                        (dict(medical_aid_id=scheme["id"], member_number="  "), "member number"),
                        (dict(medical_aid_id=scheme["id"], member_number="C1", hold=True, hold_reason=""), "held")):
        r = dispense(rx, claim)
        assert r.status_code == 400 and said in r.json()["detail"], r.text
    assert not sql("SELECT d.id FROM dispensings d JOIN prescription_items pi ON pi.id = d.prescription_item_id WHERE pi.prescription_id = ?", (rx["id"],)), "refused, yet a sale exists"
    print("ok    missing scheme, member number or hold reason is refused; nothing dispensed")

    r = dispense(rx, dict(medical_aid_id=scheme["id"], member_number="CARD-001", dependent_code="01"))
    assert r.status_code == 200, r.text
    sale = r.json()
    claims = sql("SELECT status, amount_claimed, submitted_at FROM claims WHERE sale_id = ?", (sale["id"],))
    assert len(claims) == 1 and claims[0][2] is not None, claims
    rec = sql("SELECT medical_aid_id, medical_aid_number, dependent_code FROM patients WHERE id = ?", (fresh["id"],))[0]
    assert tuple(rec) == (scheme["id"], "CARD-001", "01"), rec
    print(f"ok    claim now: one claim ({claims[0][0]}); patient record takes the card")

    paid = c.post(f"/api/pos/sales/{sale['id']}/pay", json={
        "payment_method": "split",
        "tenders": [{"method": "medical_aid", "currency_code": "USD",
                     "amount": round(sale["total"] - sale["claim"]["patient_liable"], 2)},
                    {"method": "cash", "currency_code": "USD",
                     "amount": round(sale["claim"]["patient_liable"], 2)}]})
    assert paid.status_code == 200 and paid.json()["status"] == "paid", paid.text
    n = sql("SELECT COUNT(*) FROM claims WHERE sale_id = ?", (sale["id"],))[0][0]
    assert n == 1, f"settling raised a second claim: {n}"
    assert paid.status_code == 200, paid.text
    print(f"ok    shortfall settled at the counter: {paid.json().get('status')}")

    rx2 = script(fresh["id"], stocked[1])
    r = dispense(rx2, dict(medical_aid_id=scheme["id"], member_number="CARD-001",
                           hold=True, hold_reason="Scheme offline"))
    assert r.status_code == 200, r.text
    claims = sql("SELECT status, submitted_at, deferred_reason FROM claims WHERE sale_id = ?", (r.json()["id"],))
    assert len(claims) == 1 and claims[0][1] is None, claims
    print(f"ok    hold: one claim, not sent ({claims[0][0]}: {claims[0][2]})")

    rx3 = script(fresh["id"], stocked[2])      # now on file: must not claim twice
    r = dispense(rx3, dict(medical_aid_id=scheme["id"], member_number="CARD-001"))
    assert r.status_code == 200, r.text
    n = sql("SELECT COUNT(*) FROM claims WHERE sale_id = ?", (r.json()["id"],))[0][0]
    assert n == 1, n
    print("ok    scheme already on file: one claim, not two")


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print("FAIL", exc)
        sys.exit(1)
    print("\nall passed")
