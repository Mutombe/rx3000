"""Retiring a prescriber takes them out of the picker, and out of nothing else.

The ask was to remove every prescriber with no practice number. Deleting them is
the one thing that cannot be done: all 539 of them here — and 689 in production
— are named on scripts this pharmacy has dispensed, and a dispensing record is a
legal record of who prescribed what to whom. A delete either fails on the key or
blanks the prescriber on thousands of them, turning a bad prescriber list into a
bad dispensing history.

`Doctor.active` has said "Retired, never deleted" since the model was written,
and `DELETE /doctors/{id}` has always set it. What was missing is that the picker
read the whole table regardless — so retiring somebody changed nothing anybody
could see, which is why the list never got any shorter.

Against a snapshot of the local database:

  - a retired prescriber is gone from the list a script is captured against
  - …and still there for the screens that maintain the list
  - …and still named on every script they ever wrote
  - a script can still be read, and its prescriber is still theirs
  - the job that does this in bulk takes only the unnumbered ones
  - …leaves alone anyone who has written recently, whose number is just untyped
  - …and can be undone

  python tests/test_retiring_a_prescriber.py
"""
import sys

from snapshot_app import client, execute, sql


def run():
    c = client()

    doctors = c.get("/api/doctors").json()
    doctors = doctors["items"] if isinstance(doctors, dict) else doctors
    assert len(doctors) >= 2, "need a couple of prescribers"

    # One with a number, who has written something, and one without.
    numbered = c.post("/api/doctors", json={"name": "Dr Numbered Chikomo",
                                            "practice_number": "0910234"}).json()
    blank = c.post("/api/doctors", json={"name": "Dr Nameless Nobody",
                                         "practice_number": ""}).json()

    who = c.post("/api/patients", json={"first_name": "Rutendo", "last_name": "Keeps",
                                        "date_of_birth": "1988-08-08", "gender": "F",
                                        "phone": "0779333222", "confirmed_distinct": True}).json()
    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=30").json()
               if (p.get("quantity_on_hand") or 0) >= 5]
    rx = c.post("/api/prescriptions", json={
        "patient_id": who["id"], "doctor_id": blank["id"],
        "items": [{"product_id": stocked[0]["id"], "quantity": 1,
                   "dosage_instructions": "One daily", "repeats_allowed": 0,
                   "repeat_interval_days": 30, "auto_refill": False,
                   "icd10_code": "I10"}]}).json()
    assert rx.get("id"), rx

    gone = c.delete(f"/api/doctors/{blank['id']}")
    assert gone.status_code == 200, gone.text

    picker = c.get("/api/doctors").json()
    picker = picker["items"] if isinstance(picker, dict) else picker
    names = [d["name"] for d in picker]
    assert "Dr Nameless Nobody" not in names, "a retired prescriber is still in the picker"
    assert "Dr Numbered Chikomo" in names, "the wrong prescriber went"
    print(f"ok    retired, and out of the picker ({len(picker)} left, was {len(picker) + 1})")

    everyone = c.get("/api/doctors?include_retired=true").json()
    everyone = everyone["items"] if isinstance(everyone, dict) else everyone
    assert "Dr Nameless Nobody" in [d["name"] for d in everyone], \
        "the maintenance list cannot see them either, so they cannot be brought back"
    print("ok    …and still there for the screens that maintain the list")

    still = sql("select doctor_id from prescriptions where id = ?", (rx["id"],))
    assert still and still[0][0] == blank["id"], still
    again = c.get(f"/api/prescriptions/{rx['id']}")
    assert again.status_code == 200, again.text
    assert again.json()["doctor"]["name"] == "Dr Nameless Nobody", again.json()["doctor"]
    print("ok    …and the script they wrote still names them, and still reads")

    # The bulk job, on the same database.
    from app.database import SessionLocal
    from app.importers import retire_unnumbered_prescribers as job
    from app.models import Doctor

    from app.tenancy import reset_current_pharmacy, set_current_pharmacy
    mine = sql("select pharmacy_id from doctors where id = ?", (blank["id"],))[0][0]
    token = set_current_pharmacy(mine)
    db = SessionLocal()
    try:
        # Back on the shelf, so the job has something to do.
        c.put(f"/api/doctors/{blank['id']}", json={"active": True})
        db.expire_all()
        found = job.plan(db, keep_days=0)
        going = {d.name for d in found["retire"]}
        assert "Dr Nameless Nobody" in going, sorted(going)[:8]
        assert "Dr Numbered Chikomo" not in going, "it is taking numbered prescribers too"
        print(f"ok    the bulk job takes the {len(found['retire'])} unnumbered, and no others")

        # A prescriber who wrote this week is a number nobody has typed, not a
        # dead record.
        recent = job.plan(db, keep_days=90)
        kept = {d.name for d in recent["keep"]}
        assert "Dr Nameless Nobody" in kept, \
            "somebody who wrote a script today was put away anyway"
        print(f"ok    …and leaves alone the {len(recent['keep'])} who have written recently")

        job.apply(db, found["retire"])
        db.expire_all()
        assert db.get(Doctor, blank["id"]).active is False
        brought_back = job.restore(db)
        db.expire_all()
        assert db.get(Doctor, blank["id"]).active is True, "restore did not bring them back"
        print(f"ok    …and can be undone ({brought_back} brought back)")
    finally:
        db.close()
        reset_current_pharmacy(token)

    # Tidy up after ourselves: this runs against a working database.
    execute("delete from prescription_items where prescription_id = ?", (rx["id"],))
    execute("delete from prescriptions where id = ?", (rx["id"],))
    execute("delete from doctors where id in (?, ?)", (blank["id"], numbered["id"]))


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
