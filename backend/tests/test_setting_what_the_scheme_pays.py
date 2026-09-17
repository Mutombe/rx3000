"""What the scheme is asked for can be set by hand, and the patient covers it.

The cover rule works off the medicine's category and a percentage. A dispenser
often knows better: this funder pays a fixed amount for this medicine, an
authorisation came back for less, half of it is being claimed and half is cash.
Where the rule is wrong, the line was going to the funder wrong.

THE RULE THAT MAKES IT SAFE is that it moves one number. The line still costs
what it costs; the scheme is asked for less and the patient covers the
difference, so the script totals the same and the shortfall moves — which is
what a shortfall is. A field that quietly reduced the price would be a discount
nobody approved, wearing a claim's name.

THE FAILURE WORTH GUARDING is the screen and the funder disagreeing. The figure
shown at the counter and the figure adjudicated onto the claim come from two
different code paths, and if they part company the pharmacy quotes one number
and bills another. So this checks both, on the same script.

Against a snapshot of the local database:

  - the totals footer shows the hand-set claim, and the shortfall absorbs it
  - the line total does not move
  - a claim authorisation cannot be spent as a price, or the other way round
  - a scheme cannot be asked for more than the line is worth
  - and the claim actually raised carries the hand-set figure

  python tests/test_setting_what_the_scheme_pays.py
"""
import sys

from snapshot_app import client, sql

LINE = {"dosage_instructions": "One twice a day", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def run():
    c = client()
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    aid = c.get("/api/medical-aids").json()[0]
    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=40").json()
               if (p.get("here") or p.get("quantity_on_hand") or 0) >= 30]
    assert stocked, "the snapshot holds no stocked medicine"
    medicine = stocked[0]

    who = c.post("/api/patients", json={
        "first_name": "Chipo", "last_name": "Claimset", "date_of_birth": "1990-06-06",
        "gender": "F", "phone": "0775555555", "medical_aid_id": aid["id"],
        "medical_aid_number": "CLM-0001", "confirmed_distinct": True}).json()

    # What the rule says, before anybody touches it.
    rule = c.post("/api/script-totals", json={
        "items": [{"product_id": medicine["id"], "quantity": 10}],
        "medical_aid_id": aid["id"]}).json()
    was = rule["lines"][0]
    print(f"      the rule: gross {was['gross']}, scheme {was['claim']}, "
          f"levy {was['levy']}")
    assert was["claim"] > 1, "the rule claims nothing, so there is nothing to override"

    # Set it to half, and the patient picks up the rest.
    asked = round(was["claim"] / 2, 2)
    hand = c.post("/api/script-totals", json={
        "items": [{"product_id": medicine["id"], "quantity": 10, "claim": asked}],
        "medical_aid_id": aid["id"]}).json()
    now = hand["lines"][0]
    assert abs(now["claim"] - asked) < 0.02, (now["claim"], asked)
    print(f"ok    the footer shows the hand-set claim: {now['claim']}")

    assert abs(now["gross"] - was["gross"]) < 0.005, (now["gross"], was["gross"])
    print(f"ok    the line still costs the same: {now['gross']}")

    moved = round(now["levy"] - was["levy"], 2)
    assert abs(moved - (was["claim"] - asked)) < 0.02, (moved, was["claim"] - asked)
    print(f"ok    and the shortfall absorbs the difference: levy {was['levy']} "
          f"to {now['levy']}")

    # ---- the authorisation is the claim's, and only the claim's -------------
    # It costs a code, like the price beside it: this changes what a funder is
    # billed and what the patient is asked for, so somebody signs for it.
    refused = c.post("/api/claim-override", json={
        "product_id": medicine["id"], "now": asked, "quantity": 10})
    assert refused.status_code == 428, refused.status_code
    print("ok    setting it without a code is refused, and asks for one")

    signed = c.post("/api/step-up", json={"action": "script.claim_set",
                                          "approver": "admin",
                                          "password": "admin123",
                                          "context": "test"})
    assert signed.status_code == 200, signed.text
    code = {"X-Step-Up": signed.json()["token"]}

    made = c.post("/api/claim-override", json={
        "product_id": medicine["id"], "now": asked, "quantity": 10,
        "reason": "The scheme authorised less"}, headers=code)
    assert made.status_code == 200, made.text
    override = made.json()
    print(f"ok    an authorisation is recorded: #{override['id']} for {override['now']}")

    kind = sql("select kind from price_overrides where id = ?", (override["id"],))[0][0]
    assert kind == "claim", kind
    print("ok    it is filed as a claim, not as a price")

    # Spending it as a price must be refused, or a claim authorisation becomes a
    # discount and the patient is charged what the scheme was going to be asked.
    rx = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": medicine["id"], "quantity": 10,
                   "price_override_id": override["id"]}]})
    assert rx.status_code >= 400 and "claim amount" in rx.text, rx.text[:200]
    print("ok    a claim authorisation cannot be spent as a price")

    # Nor more than the line is worth: overclaiming is fraud, however accidental.
    spare = c.post("/api/step-up", json={"action": "script.claim_set",
                                         "approver": "admin", "password": "admin123",
                                         "context": "test"}).json()
    too_much = c.post("/api/claim-override", json={
        "product_id": medicine["id"], "now": 999999, "quantity": 1,
        "reason": "typo"}, headers={"X-Step-Up": spare["token"]})
    assert too_much.status_code >= 400 and "worth" in too_much.text, too_much.text[:200]
    print("ok    a scheme cannot be asked for more than the line is worth")

    # ---- and it reaches the claim ------------------------------------------
    rx = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": doctor["id"],
        "items": [{**LINE, "product_id": medicine["id"], "quantity": 10,
                   "claim_override_id": override["id"]}]}).json()
    stored = sql("select claim_override from prescription_items where id = ?",
                 (rx["items"][0]["id"],))[0][0]
    assert stored is not None and abs(stored - asked) < 0.02, (stored, asked)
    print(f"ok    the line carries it onto the script: {stored}")

    out = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
        "item_ids": [i["id"] for i in rx["items"]], "payment_method": "medical_aid",
        "pharmacist_initial": "CC"})
    assert out.status_code == 200, out.text
    sale = out.json()

    claim = sql("""select amount_approved, patient_liable from claims
                    where sale_id = ? order by id desc limit 1""", (sale["id"],))
    assert claim, "no claim was raised for a medical aid dispensing"
    approved, liable = claim[0]
    # The scheme is never approved for more than it was asked for.
    assert approved <= asked + 0.02, (
        f"the scheme was approved {approved} when it was only asked for {asked}. "
        "The screen and the claim have parted company.")
    print(f"ok    the claim honours it: approved {approved}, patient owes {liable}")

    assert abs((approved + liable) - sale["total"]) < 0.02, (approved, liable, sale["total"])
    print(f"ok    and the two still add up to the sale: {sale['total']}")


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
