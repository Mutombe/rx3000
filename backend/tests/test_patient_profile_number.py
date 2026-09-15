"""Every patient has a profile number, however they came to be on file.

CareXpress To-Be blueprint §3 step 1: a patient is registered and a profile
number auto-generated. Checked against a snapshot of the local database, after
the application has started and migrated it:

  - every patient already on file has been numbered, and no pharmacy holds
    the same number twice (the unique index is in place)
  - registering at the counter issues one, and the next is the next
  - a patient written straight to the database — the importer's door — is
    numbered too
  - the number finds the patient in a search
  - migrating again renumbers nobody

  python tests/test_patient_profile_number.py
"""
import re
import sys

from snapshot_app import SNAPSHOT, client, sql

NUMBER = re.compile(r"PT\d{4}\d{5}")


def check_existing_patients_are_numbered():
    client()                                            # starts, so migrates
    total = sql("select count(*) from patients")[0][0]
    blank = sql("select count(*) from patients where profile_number is null "
                "or trim(profile_number) = ''")[0][0]
    assert total > 0, "the snapshot has no patients"
    assert blank == 0, f"{blank} of {total} existing patients were left without a number"
    malformed = [n for (n,) in sql("select profile_number from patients")
                 if not NUMBER.fullmatch(n or "")]
    assert not malformed, f"badly formed numbers: {malformed[:5]}"
    dupes = sql("select pharmacy_id, profile_number, count(*) from patients "
                "group by pharmacy_id, profile_number having count(*) > 1")
    assert not dupes, f"a pharmacy holds the same number twice: {dupes[:5]}"
    index = sql("select name from sqlite_master where type = 'index' "
                "and name = 'uq_patients_tenant_profile_number'")
    assert index, "the per-pharmacy unique index was not created"
    return total


def check_counter_registration_issues_the_next_number():
    c = client()
    a = c.post("/api/patients", json={"first_name": "Tariro", "last_name": "Profiletest"})
    b = c.post("/api/patients", json={"first_name": "Rufaro", "last_name": "Profiletest"})
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    na, nb = a.json()["profile_number"], b.json()["profile_number"]
    assert NUMBER.fullmatch(na or "") and NUMBER.fullmatch(nb or ""), (na, nb)
    assert na[:6] == nb[:6] and int(nb[6:]) == int(na[6:]) + 1, (
        f"two registrations in a row were not consecutive: {na}, {nb}")
    # A client cannot choose its own number.
    forced = c.post("/api/patients", json={"first_name": "Chosen", "last_name": "Profiletest",
                                           "profile_number": "PT000000001"})
    assert forced.status_code == 200, forced.text
    assert forced.json()["profile_number"] != "PT000000001", "a client chose its own number"
    return a.json()


def check_a_patient_written_directly_is_numbered():
    """The importer's door: an ORM session, no endpoint, no request."""
    from app.database import SessionLocal
    from app.models import Patient

    pharmacy = sql("select pharmacy_id from patients where pharmacy_id is not null limit 1")
    db = SessionLocal()
    try:
        p = Patient(first_name="Imported", last_name="Profiletest",
                    pharmacy_id=pharmacy[0][0] if pharmacy else None)
        db.add(p)
        db.commit()
        pid = p.id
    finally:
        db.close()
    stored = sql("select profile_number from patients where id = ?", (pid,))[0][0]
    assert NUMBER.fullmatch(stored or ""), f"an imported patient was not numbered: {stored!r}"


def check_the_number_finds_the_patient(patient):
    hits = client().get(f"/api/patients?q={patient['profile_number']}&limit=5").json()
    assert any(h["id"] == patient["id"] for h in hits), (
        f"searching {patient['profile_number']} did not find the patient")


def check_migrating_again_renumbers_nobody():
    from sqlalchemy import create_engine

    from app.migrate import run_migrations

    before = dict(sql("select id, profile_number from patients"))
    run_migrations(create_engine(f"sqlite:///{SNAPSHOT.as_posix()}"))
    after = dict(sql("select id, profile_number from patients"))
    changed = [pid for pid in before if before[pid] != after.get(pid)]
    assert not changed, f"a second migration renumbered {len(changed)} patient(s)"


if __name__ == "__main__":
    failed = 0
    try:
        total = check_existing_patients_are_numbered()
        print(f"ok    all {total} patients already on file are numbered, uniquely per pharmacy")
        registered = check_counter_registration_issues_the_next_number()
        print("ok    registering at the counter issues the next number, and cannot be chosen")
        check_a_patient_written_directly_is_numbered()
        print("ok    a patient written straight to the database is numbered too")
        check_the_number_finds_the_patient(registered)
        print("ok    the number finds the patient in a search")
        check_migrating_again_renumbers_nobody()
        print("ok    migrating again renumbers nobody")
    except AssertionError as exc:
        failed = 1
        print(f"FAIL  {exc}")
    sys.exit(failed)
