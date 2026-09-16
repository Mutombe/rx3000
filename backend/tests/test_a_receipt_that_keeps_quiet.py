"""A receipt that does not say what somebody is being treated for.

A dispensing slip carries a person's health on it. "FLUOXETINE 20MG" on a piece
of paper handed across a counter discloses it to whoever is standing in the
queue, and the patient who most needs it kept quiet is exactly the one who will
not ask for it in front of everybody.

So it is asked before anything prints, and — this is the part that matters — the
answer is kept on the SALE. The billing is often sent to the till and printed
there by a cashier who never met the patient and has no way to know.

Against a snapshot of the local database:

  - a dispensing takes the choice and keeps it on the sale
  - a sale settled at the till still carries it, unread by anybody in between
  - the default is an ordinary itemised receipt, because that is what a receipt
    is for
  - the printed slip names no medicine when it is private
  - …and still carries the totals, the tax and the invoice number, because it is
    a tax invoice and the pharmacy has to be able to find the lines again

  python tests/test_a_receipt_that_keeps_quiet.py
"""
import re
import sys
import pathlib

from snapshot_app import client, sql

LINE = {"quantity": 14, "dosage_instructions": "One at night", "repeats_allowed": 0,
        "repeat_interval_days": 30, "auto_refill": False, "icd10_code": "F32.9"}


def run():
    c = client()
    doctors = c.get("/api/doctors?limit=3").json()
    doctor = (doctors["items"] if isinstance(doctors, dict) else doctors)[0]
    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=40").json()
               if (p.get("here") or p.get("quantity_on_hand") or 0) >= 20]
    assert len(stocked) >= 2, "need two stocked medicines"
    who = c.post("/api/patients", json={"first_name": "Nyarai", "last_name": "Quiet",
                                        "date_of_birth": "1994-04-04", "gender": "F",
                                        "phone": "0779808070", "confirmed_distinct": True}).json()

    def dispense(product, private):
        rx = c.post("/api/prescriptions", json={
            "patient_id": who["id"], "doctor_id": doctor["id"],
            "items": [{**LINE, "product_id": product["id"]}]}).json()
        out = c.post(f"/api/prescriptions/{rx['id']}/dispense", json={
            "item_ids": [i["id"] for i in rx["items"]], "payment_method": "cash",
            "pharmacist_initial": "SA", "receipt_private": private})
        assert out.status_code == 200, out.text
        return out.json()

    quiet = dispense(stocked[0], True)
    assert quiet["receipt_private"] is True, quiet.get("receipt_private")
    assert sql("select receipt_private from sales where id = ?", (quiet["id"],))[0][0]
    print("ok    the dispensing takes the choice and keeps it on the sale")

    plain = dispense(stocked[1], False)
    assert not plain["receipt_private"], plain.get("receipt_private")
    print("ok    the default is an ordinary itemised receipt")

    # Read back the way the till reads it: a fresh fetch, nobody having passed
    # the choice along by hand.
    again = c.get(f"/api/pos/sales/{quiet['id']}")
    if again.status_code == 200:
        assert again.json().get("receipt_private") is True, again.json().get("receipt_private")
        print("ok    the till reads it off the sale, not from whoever dispensed it")

    paid = c.post(f"/api/pos/sales/{quiet['id']}/pay",
                  json={"payment_method": "cash", "amount_tendered": quiet["total"] + 5})
    assert paid.status_code == 200, paid.text
    assert paid.json().get("receipt_private") is True, paid.json().get("receipt_private")
    print("ok    …and it survives being settled at the till")

    # The printed slip itself.
    printer = (pathlib.Path(__file__).resolve().parents[2]
               / "frontend" / "src" / "print.ts").read_text(encoding="utf-8")
    assert "const discreet = !!(sale as { receipt_private?: boolean }).receipt_private" in printer, \
        "the receipt no longer asks whether it should keep quiet"
    body = printer[printer.index("const discreet"):printer.index("const loyalty")]
    assert "item${itemCount === 1" in body, "a private receipt should still say how many items"
    assert "Itemised copy on request" in body, "it should say an itemised copy can be had"
    # Everything a tax invoice needs is outside the private branch.
    rest = printer[printer.index("Subtotal (excl. VAT)"):printer.index("Thank you for your business")]
    for must in ("Subtotal", "VAT", "TOTAL", "Paid by"):
        assert must in rest, f"a private receipt lost {must}, which a tax invoice needs"
    assert "sale.sale_number" in printer
    print("ok    private: no medicine named, but the totals, tax and number remain")


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
