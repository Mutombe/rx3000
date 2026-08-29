"""CareXpress's patient register, out of the incumbent's Patient Item Detail.

53,206 dispensed lines covering 14,455 people, their schemes, their
prescribers and their contact details. What is loaded and why:

  **Patients**, keyed on the identity number where there is one and on the name
  otherwise. Only 151 of the 53,206 lines carry an ID, which is a fact about
  the old system rather than about the people, so name-keying is the rule and
  not the fallback. Two different people with the same name will merge; that is
  a known cost, and the alternative — 53,206 patient records, one per
  dispensing — is worse in every direction.

  **Medical aids**, with the currency read off the name. The incumbent encoded
  it there — "CIMAS USD MANUAL", "CELLMED ZWL MANUAL" — so the same funder
  appears twice, once per currency it settles in. They are kept separate,
  because they are separate: a claim paid in ZiG against a USD sale is a
  different debt from one paid in USD, and merging them would hide exactly the
  exposure the reconciliation screen was built to show.

  **Prescribers**, 689 of them, as written. No attempt is made to normalise
  "MUNGWADZI DR" against "DR MUNGWADZI" — a name this pharmacy has been using
  for two years is the name their staff will search for.

Idempotent: run it twice and the second run changes nothing. Every write is
scoped to the CareXpress tenant.

    python -m app.importers.carexpress_patients "C:/path/patient detail.xlsx"
"""
from __future__ import annotations

import re
import sys
from datetime import datetime

from ..database import SessionLocal
from ..models import Doctor, MedicalAid, Patient, Pharmacy
from ..tenancy import unscoped

HEADER_ROW = 8
TENANT = "CareXpress Pharmacy"

#: The currency the incumbent wrote into the scheme's name.
CURRENCY = re.compile(r"\b(USD|ZWL|ZWG|ZIG)\b", re.I)


def _clean(value) -> str:
    return str(value).strip() if value is not None else ""


def _phone(value) -> str:
    """A number the pharmacy could actually ring.

    The export writes 0 for "none", and a register full of patients whose
    telephone number is zero is worse than one with the field empty: the repeat
    call sheet would work through them one by one.
    """
    text = _clean(value)
    if text in ("", "0", "0.0", "None"):
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text[:30]


def _currency_of(name: str) -> str:
    found = CURRENCY.search(name or "")
    if not found:
        return ""
    code = found.group(1).upper()
    return "ZWG" if code in ("ZWL", "ZIG") else code


def run(path: str) -> dict:
    import openpyxl

    db = SessionLocal()
    counts = {"patients": 0, "updated": 0, "aids": 0, "doctors": 0, "rows": 0}

    with unscoped():
        pharmacy = db.query(Pharmacy).filter(Pharmacy.name == TENANT).first()
        if pharmacy is None:
            raise SystemExit(f"No tenant named {TENANT!r}. Nothing was written.")

        # Read what is already there once, rather than a lookup per row: 53,206
        # rows against a database round trip each is the difference between a
        # minute and an afternoon.
        # Medical aids are not tenant-scoped in this schema — they are shared
        # reference data across every pharmacy. Worth knowing, because the
        # commercial terms hang off the same row (levy, scheme discount, fee
        # model), so two pharmacies currently share a negotiated discount. Not
        # changed here: that is a migration, not an import.
        aids = {a.name.upper(): a for a in db.query(MedicalAid).all()}
        doctors = {d.name.upper(): d for d in db.query(Doctor)
                   .filter(Doctor.pharmacy_id == pharmacy.id).all()}
        existing = {}
        for p in db.query(Patient).filter(Patient.pharmacy_id == pharmacy.id).all():
            existing[_key(p.id_number, p.first_name, p.last_name)] = p

        book = openpyxl.load_workbook(path, read_only=True)
        sheet = book.worksheets[0]
        rows = sheet.iter_rows(min_row=HEADER_ROW, values_only=True)
        header = [_clean(c) for c in next(rows)]
        at = {name: i for i, name in enumerate(header)}

        def cell(row, name):
            i = at.get(name)
            return row[i] if i is not None and i < len(row) else None

        seen: set[str] = set()
        for row in rows:
            if not row:
                continue
            first = _clean(cell(row, "Firstname")).title()
            last = _clean(cell(row, "Surname")).title()
            if not first and not last:
                continue
            counts["rows"] += 1

            # ---- the scheme -------------------------------------------------
            aid = None
            aid_name = _clean(cell(row, "Medical Aid"))
            if aid_name and aid_name.upper() != "PRIVATE":
                key = aid_name.upper()
                aid = aids.get(key)
                if aid is None:
                    aid = MedicalAid(
                        name=aid_name.title(),
                        scheme_code=_clean(cell(row, "Medical Aid CD"))[:20] or aid_name[:20],
                        currency_code=_currency_of(aid_name),
                    )
                    db.add(aid)
                    # Flushed, not committed, and only because the patient rows
                    # below need its id. Doctors do not, so they are not.
                    db.flush()
                    aids[key] = aid
                    counts["aids"] += 1

            # ---- the prescriber ---------------------------------------------
            doctor_name = _clean(cell(row, "Doctor"))
            if doctor_name and doctor_name.upper() not in doctors:
                doctor = Doctor(name=doctor_name.title(), pharmacy_id=pharmacy.id)
                db.add(doctor)
                # No flush. Nothing here needs the prescriber's id, and a round
                # trip per new name is 689 of them before a single patient is
                # written — invisible on SQLite, a minute of waiting against a
                # hosted database.
                doctors[doctor_name.upper()] = doctor
                counts["doctors"] += 1

            # ---- the person -------------------------------------------------
            id_number = _clean(cell(row, "ID No"))
            key = _key(id_number, first, last)
            if key in seen:
                continue
            seen.add(key)

            address = ", ".join(
                part for part in (
                    _clean(cell(row, "Addr Line1")), _clean(cell(row, "Addr Line2")),
                    _clean(cell(row, "Addr Line3")), _clean(cell(row, "Addr Line4")),
                ) if part and part != "0")

            patient = existing.get(key)
            if patient is None:
                patient = Patient(
                    first_name=first or "Unknown",
                    last_name=last or "Unknown",
                    id_number=id_number[:40],
                    pharmacy_id=pharmacy.id,
                )
                db.add(patient)
                existing[key] = patient
                counts["patients"] += 1
            else:
                counts["updated"] += 1

            # Filled rather than overwritten: a later row with a blank telephone
            # number must not erase one an earlier row supplied.
            patient.address = patient.address or address[:200]
            patient.phone = patient.phone or _phone(cell(row, "Cell No")) \
                or _phone(cell(row, "Home Nr")) or _phone(cell(row, "Work Nr"))
            email = _clean(cell(row, "Email"))
            if email and "@" in email and not patient.email:
                patient.email = email[:120]
            if aid is not None and not patient.medical_aid_id:
                patient.medical_aid_id = aid.id
                patient.medical_aid_number = _clean(cell(row, "Member No"))[:40]

            if counts["rows"] % 4000 == 0:
                # Committed, not merely flushed. Against the hosted database
                # one transaction spanning 53,206 rows is a transaction that
                # loses everything when the connection drops — and seed_remote
                # says plainly that it does. Committing in batches makes an
                # interrupted run resumable, which is what the idempotency is
                # for.
                db.commit()
                print(f"  {counts['rows']:,} rows … {counts['patients']:,} people",
                      flush=True)

        book.close()
        db.commit()

    db.close()
    return counts


def _key(id_number, first, last) -> str:
    """One person, however the old system spelled them.

    The identity number wins where there is one. There almost never is — 151
    lines out of 53,206 — so the name is what actually does the work.
    """
    ident = _clean(id_number)
    if ident:
        return f"id:{ident.upper()}"
    return f"nm:{_clean(first).upper()}|{_clean(last).upper()}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Give me the path to 'patient detail.xlsx'.")
    started = datetime.now()
    result = run(sys.argv[1])
    print(f"\n{result['rows']:,} rows read in {(datetime.now() - started).seconds}s")
    print(f"  {result['patients']:,} patients created")
    print(f"  {result['aids']} medical aids")
    print(f"  {result['doctors']} prescribers")
