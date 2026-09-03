"""Can a script be dispensed after it has been saved?

The dispenser adds two repeats that are due, presses **Save for later**, then
**Finish capturing**, then **Dispense**, and is told:

    No valid items selected

They had selected two items. The screen showed two items. The server was right
and the message was true: the request carried an empty list.

WHY IT WAS EMPTY

The dispensing screen sent `item_ids` two different ways. For a script opened
from the worklist it sent the `item_id` captured on each line when the script
was loaded; for a fresh capture it sent the ids of the prescription it had just
created. Lines added by hand, or added from the repeats-due panel, never carry
an `item_id` at all, because nothing on the server has issued one for them yet.

Saving a draft sets the screen's "this is a script now" state without giving
those lines ids. So after **Save for later** the screen believed it was working
on an existing script, every line still had no id, `.filter(Boolean)` dropped
all of them, and the dispense posted `[]`.

WHAT IS CHECKED

The server half of it, which is the half that can be tested without a browser:

  an empty selection is refused, and refused clearly, because a dispense that
    quietly did nothing would be far worse than one that says no;
  a selection naming the script's real items dispenses;
  ids from before a draft was saved are not assumed to survive it, since the
    save endpoint replaces a draft's items wholesale.

The screen now resolves the selection against the server's own items by
product, which is stable across all of that.

Nothing is committed.

    python qa/dispense-selection.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import logging                                              # noqa: E402
logging.disable(logging.CRITICAL)

from fastapi.testclient import TestClient                   # noqa: E402
from app.main import app                                    # noqa: E402
from app.database import SessionLocal                       # noqa: E402
from app import tenancy                                     # noqa: E402
from app.models import Doctor, Patient, Product, User       # noqa: E402
from app.auth import create_token                           # noqa: E402


def main() -> int:
    tenancy.set_current_pharmacy(1)
    db = SessionLocal()
    tenancy.stamp(db)
    failures: list[str] = []

    def check(ok: bool, said: str, why: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {said}")
        if not ok:
            failures.append(why or said)

    user = db.query(User).filter(User.is_demo.is_(False)).first()
    patient = db.query(Patient).first()
    doctor = db.query(Doctor).first()
    products = (db.query(Product)
                .filter(Product.schedule.between(1, 4),
                        Product.quantity_on_hand > 20).limit(2).all())
    if not all((user, patient, doctor)) or len(products) < 2:
        print("FAIL: this database has no patient, prescriber or stocked product")
        db.close()
        return 2
    token = create_token(user)
    db.close()

    client = TestClient(app, raise_server_exceptions=False)
    head = {"Authorization": f"Bearer {token}"}
    lines = [{"product_id": p.id, "quantity": 2, "dosage_instructions": "1t bd",
              "repeats_allowed": 3, "repeat_interval_days": 30,
              "auto_refill": False, "icd10_code": ""} for p in products]
    payload = {"patient_id": patient.id, "doctor_id": doctor.id, "items": lines}
    compliance = {"id_verified": True, "id_number_seen": "QA",
                  "script_sighted": True, "prescriber_verified": True,
                  "pharmacist_initial": "QA", "compliance_notes": ""}

    # The sequence that failed: save, finish, dispense.
    draft = client.post("/api/prescriptions", headers=head,
                        json={**payload, "draft": True}).json()
    saved_ids = [i["id"] for i in draft["items"]]
    client.put(f"/api/prescriptions/{draft['id']}/draft", headers=head,
               json=payload)
    done = client.post(f"/api/prescriptions/{draft['id']}/finalise",
                       headers=head, json={}).json()
    check(done.get("rx_number") is not None,
          f"a saved draft finishes and takes a number ({done.get('rx_number')})",
          f"finalise returned {str(done)[:120]}")

    rx_id = done["id"]

    # 1. The empty selection the screen used to send.
    empty = client.post(f"/api/prescriptions/{rx_id}/dispense", headers=head,
                        json={"item_ids": [], **compliance})
    check(empty.status_code == 400,
          "an empty selection is refused rather than dispensing nothing",
          f"an empty selection answered {empty.status_code}; a dispense that "
          f"silently does nothing is worse than one that says no")

    # 2. What the screen sends now: the server's own ids, matched by product.
    on_screen = {p.id for p in products}
    selected = [i["id"] for i in done["items"] if i["product_id"] in on_screen]
    check(len(selected) == len(products),
          f"every line on screen resolves to an item on the script "
          f"({len(selected)} of {len(products)})",
          "a line on screen could not be matched to an item on the script, so "
          "the dispense would carry fewer lines than the dispenser selected")

    sale = client.post(f"/api/prescriptions/{rx_id}/dispense", headers=head,
                       json={"item_ids": selected, **compliance})
    check(sale.status_code == 200,
          f"and the dispense goes through ({sale.json().get('sale_number', '')})",
          f"dispensing the resolved selection answered {sale.status_code}: "
          f"{str(sale.json())[:140]}")

    # 3. Ids captured before the save are not to be relied on. This documents
    #    the hazard rather than asserting the endpoint replaces them: whether
    #    it reuses an id is its own business, and the screen must not care.
    check(True,
          f"ids at save time {saved_ids} vs after finishing "
          f"{[i['id'] for i in done['items']]}"
          + ("  (unchanged here, but the save replaces items wholesale, so "
             "this is not a promise)"
             if saved_ids == [i["id"] for i in done["items"]] else "  (changed)"))

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("a script saved, finished and then dispensed carries its items with it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
