"""A medicine label names its batch and expiry, or it does not print.

The CareXpress To-Be blueprint (§5 Label Mandatory Fields, §7 Label Printing)
requires batch and expiry on every medication label and blocks the label
without them. RX5000 used to print regardless, leaving those lines off, so a
box could leave the counter carrying nothing a recall could be traced by.

Checked against real dispensings in a snapshot of the local database:

  - a line that went out, from a batch with an expiry, prints
  - a line on the same script that has not been dispensed is refused
  - once that batch has no expiry on file, the label is refused and names it

  python tests/test_label_batch_expiry.py
"""
import sys

from snapshot_app import client, execute

LINE = {"dosage_instructions": "One daily", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "I10"}


def _dispense_one_of_two(c):
    """A two-line script with only the first line dispensed."""
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=40").json()
               if (p.get("quantity_on_hand") or 0) >= 5]
    first, second = stocked[0], stocked[1]
    for patient in c.get("/api/patients?q=a&limit=25").json():
        rx = c.post("/api/prescriptions", json={
            "patient_id": patient["id"], "doctor_id": doctor["id"], "notes": "label test",
            "items": [{**LINE, "product_id": first["id"], "quantity": 2},
                      {**LINE, "product_id": second["id"], "quantity": 2}],
        }).json()
        dispensed = next(i for i in rx["items"] if i["product_id"] == first["id"])
        r = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
            "item_ids": [dispensed["id"]], "payment_method": "cash", "pharmacist_initial": "TM"})
        if r.status_code == 409:
            continue
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        return rx, first, second
    raise AssertionError("no patient in the snapshot could be dispensed to")


def _label_for(labels, product):
    return next(l for l in labels if l["product_name"] == product["name"])


def run():
    c = client()
    rx, first, second = _dispense_one_of_two(c)
    labels = c.get(f"/api/prescriptions/{rx['id']}/labels").json()

    went_out = _label_for(labels, first)
    assert went_out["batch_number"] and went_out["expiry_date"], went_out
    assert went_out["printable"] is True, f"a dispensed line with a batch and expiry was refused: {went_out}"
    assert went_out["blocked_reason"] == "", went_out
    print("ok    a line that went out, from a batch with an expiry, prints")

    waiting = _label_for(labels, second)
    assert waiting["printable"] is False, f"a line not yet dispensed would print: {waiting}"
    assert "Not dispensed yet" in waiting["blocked_reason"], waiting["blocked_reason"]
    print("ok    a line that has not been dispensed is refused, and says so")

    # Take the expiry off the batch that line came from, as an imported or
    # hand-entered batch might arrive, and ask again.
    execute("update stock_batches set expiry_date = null where batch_number = ?",
            (went_out["batch_number"],))
    relabel = _label_for(c.get(f"/api/prescriptions/{rx['id']}/labels").json(), first)
    assert relabel["printable"] is False, f"a label with no expiry on file would print: {relabel}"
    assert went_out["batch_number"] in relabel["blocked_reason"], relabel["blocked_reason"]
    assert "no expiry" in relabel["blocked_reason"], relabel["blocked_reason"]
    print("ok    a batch with no expiry on file is refused, naming the batch")


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"FAIL  {exc}")
        sys.exit(1)
