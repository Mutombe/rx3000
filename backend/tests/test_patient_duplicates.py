"""The same person is not registered twice without somebody saying so.

CareXpress To-Be blueprint §6 and §7: duplicate patients are detected at
registration and prompt a review; a duplicate is flagged for merge.

Taken from a real patient in a snapshot of the local database, and typed back
the way a busy counter types — different case, stray spaces, the ID without
its hyphens, the phone with the country code — because those variations are
exactly how a second record gets made.

  python tests/test_patient_duplicates.py
"""
import sys

from snapshot_app import client, sql


def _someone_with_everything(c):
    for p in c.get("/api/patients?q=a&limit=200").json():
        digits = "".join(ch for ch in (p.get("phone") or "") if ch.isdigit())
        if p.get("id_number") and p.get("date_of_birth") and len(digits) >= 9 and "-" in p["id_number"]:
            return p
    raise AssertionError("no patient in the snapshot has an ID number, date of birth and phone")


def run():
    c = client()
    p = _someone_with_everything(c)
    name = f"{p['first_name']} {p['last_name']} ({p['profile_number']})"

    # --- the ID number, typed without its hyphens and in lower case
    retyped_id = p["id_number"].replace("-", "").lower()
    m = c.post("/api/patients/duplicates", json={
        "first_name": "Somebody", "last_name": "Else", "id_number": retyped_id}).json()
    hit = next((x for x in m if x["id"] == p["id"]), None)
    assert hit and "Same ID number" in hit["reasons"] and hit["strength"] == "strong", (
        f"{name} was not found by their ID number typed as {retyped_id!r}: {m}")
    print("ok    the same ID number, typed differently, is a strong match")

    # --- date of birth and surname, surname with stray spaces and capitals
    m = c.post("/api/patients/duplicates", json={
        "first_name": "Another", "last_name": f"  {p['last_name'].upper()} ",
        "date_of_birth": p["date_of_birth"]}).json()
    hit = next((x for x in m if x["id"] == p["id"]), None)
    assert hit and "Same date of birth and surname" in hit["reasons"], (
        f"{name} was not found by date of birth and surname: {m}")
    print("ok    the same date of birth and surname is a likely match")

    # --- the phone, written with the country code
    digits = "".join(ch for ch in p["phone"] if ch.isdigit())
    m = c.post("/api/patients/duplicates", json={
        "first_name": "Third", "last_name": p["last_name"], "phone": "+263 " + digits[-9:]}).json()
    hit = next((x for x in m if x["id"] == p["id"]), None)
    assert hit and "Same phone number and surname" in hit["reasons"], (
        f"{name} was not found by phone and surname: {m}")
    print("ok    the same phone and surname, written with the country code, is a likely match")

    # --- registering the match without saying so is refused, and nothing is saved
    before = sql("select count(*) from patients")[0][0]
    r = c.post("/api/patients", json={
        "first_name": p["first_name"], "last_name": p["last_name"], "id_number": retyped_id})
    after = sql("select count(*) from patients")[0][0]
    assert r.status_code == 409, f"a duplicate was registered without review: {r.status_code} {r.text}"
    assert p["profile_number"] in r.json()["detail"], r.json()["detail"]
    assert after == before, f"a refused registration still saved a patient ({before} -> {after})"
    print("ok    registering a match without confirming is refused, names the record, saves nothing")

    # --- confirmed as a different person: registered, and flagged
    r = c.post("/api/patients", json={
        "first_name": p["first_name"], "last_name": p["last_name"],
        "date_of_birth": p["date_of_birth"],
        "confirmed_distinct": True, "possible_duplicate_of_id": p["id"]})
    assert r.status_code == 200, r.text
    flagged = r.json()
    assert flagged["possible_duplicate_of_id"] == p["id"], flagged
    print("ok    confirmed as a different person, they are registered and flagged for review")

    # --- correcting the flagged record does not wipe the flag
    edit = {k: flagged[k] for k in ("first_name", "last_name", "id_number", "date_of_birth",
                                    "email", "address", "allergies", "chronic_conditions",
                                    "medical_aid_id", "medical_aid_number", "dependent_code")}
    edit["phone"] = "0772000111"
    r = c.put(f"/api/patients/{flagged['id']}", json=edit)
    assert r.status_code == 200, r.text
    assert r.json()["possible_duplicate_of_id"] == p["id"], "editing the patient wiped their duplicate flag"
    print("ok    editing a flagged patient keeps the flag")

    # --- somebody new is registered without any prompt
    m = c.post("/api/patients/duplicates", json={
        "first_name": "Zvikomborero", "last_name": "Unmatchedsurname-7731"}).json()
    assert m == [], f"a new person was matched to somebody: {m}"
    r = c.post("/api/patients", json={"first_name": "Zvikomborero",
                                      "last_name": "Unmatchedsurname-7731"})
    assert r.status_code == 200, r.text
    print("ok    somebody genuinely new is registered with no prompt")


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"FAIL  {exc}")
        sys.exit(1)
