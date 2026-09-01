"""CareXpress's dispensing history, out of the same Patient Item Detail export.

That file was already read once, for the people in it — patients, their
schemes, their prescribers. What was left on the floor is the reason the file
exists: **26,543 scripts made of 53,206 dispensed lines**, each with the
medicine, the quantity, what it was sold at, who prescribed it and who handed
it over.

Until this ran, the CareXpress tenant had 45,728 sales and not one
prescription. Every clinical screen in the software — the dispensing history, a
patient's own record, the controlled register, repeats, chronics, churn — was
empty for a pharmacy with sixteen months of trading behind it.

WHAT A SCRIPT IS HERE

`Sctno` groups the lines. One script number, one date, one patient, one
prescriber, one or more medicines. That grouping is the whole value of the
file: a sale tells you money changed hands, a script tells you what a person
was being treated for and what they are due next.

THREE THINGS THIS DELIBERATELY DOES NOT DO

  **It does not invent a diagnosis.** 53,141 of the 53,206 lines carry
  `Z76.9`: the incumbent's placeholder for "no reason recorded". Loading that
  would give every script in the pharmacy a diagnosis code, and every claim
  screen would then believe one had been recorded. The 65 real ones are kept
  and the placeholder is dropped.

  **It does not move stock.** These medicines left the shelf in another system,
  months ago, and the stock on hand was imported as counted. Replaying the
  movements would take the shelf down twice.

  **It does not set a repeat due date.** Nothing in the export says a script was
  repeatable, and guessing would put twenty-six thousand invented reminders on
  the call sheet. What is loaded is what happened; what is due next is a
  decision for the pharmacist.

Idempotent: keyed on the script number within the tenant, so a second run
changes nothing. Every write is scoped to CareXpress.

    python -m app.importers.carexpress_scripts "C:/path/patient detail.xlsx"
"""
from __future__ import annotations

import sys
from datetime import datetime

import openpyxl

from ..database import SessionLocal
from ..models import (Dispensing, Doctor, Patient, Pharmacy, Prescription,
                      PrescriptionItem, Product, User)
from ..tenancy import unscoped

TENANT = "CareXpress Pharmacy"
HEADER_ROW = 8

#: The incumbent's "no reason recorded". Kept out rather than loaded: a
#: diagnosis on every script that means nothing is worse than none at all,
#: because every claim screen would believe one had been recorded.
PLACEHOLDER_ICD = "Z76.9"

#: Written in batches so an interrupted run resumes rather than losing
#: everything, and so 26,000 scripts do not sit in one transaction.
BATCH = 400


def _clean(value) -> str:
    return str(value).strip() if value is not None else ""


def _when(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _clean(value)
    if not text:
        return None
    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, shape)
        except ValueError:
            continue
    return None


def _qty(value) -> int:
    """A quantity, rounded up to something dispensable.

    The export carries fractions — 6.533333 of a 28-pack, 0.021 of a tin —
    because the incumbent divided a pack. A prescription line is a count of
    units handed to a person, so anything above nothing becomes at least one.
    """
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 1
    if n <= 0:
        return 1
    return max(1, int(round(n)))


def load(path: str, *, limit: int = 0) -> dict:
    db = SessionLocal()
    counts = {
        "rows": 0, "scripts": 0, "items": 0, "dispensings": 0,
        "skipped_existing": 0, "no_patient": 0, "no_product": 0,
        "real_diagnoses": 0,
    }
    try:
        with unscoped():
            pharmacy = db.query(Pharmacy).filter(Pharmacy.name == TENANT).first()
            if pharmacy is None:
                raise SystemExit(f"No pharmacy called {TENANT!r}. Load the "
                                 f"catalogue and the patients first.")

            # Everything this needs to resolve a row, read once. 53,206 rows
            # against a lookup per row would be a quarter of a million queries.
            products = {
                _clean(code).upper(): pid
                for pid, code in db.query(Product.id, Product.stock_code)
                .filter(Product.pharmacy_id == pharmacy.id).all() if code
            }
            people = {
                f"{_clean(f).upper()} {_clean(l).upper()}".strip(): pid
                for pid, f, l in db.query(Patient.id, Patient.first_name,
                                          Patient.last_name)
                .filter(Patient.pharmacy_id == pharmacy.id).all()
            }
            doctors = {
                _clean(name).upper(): did
                for did, name in db.query(Doctor.id, Doctor.name)
                .filter(Doctor.pharmacy_id == pharmacy.id).all() if name
            }
            # Whoever this pharmacy's records are written against. The export
            # names 39 dispensers who are not users of this system; the
            # dispensing record keeps their name in the initials field rather
            # than inventing 39 logins that nobody can sign in to.
            actor = (db.query(User).filter(User.pharmacy_id == pharmacy.id)
                     .order_by(User.id).first())
            already = {
                n for (n,) in db.query(Prescription.rx_number)
                .filter(Prescription.pharmacy_id == pharmacy.id).all() if n
            }

        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = book.worksheets[0]

        current: dict | None = None
        pending: list[dict] = []

        def flush() -> None:
            """Write the scripts gathered so far, three round trips a batch.

            Not one flush per script and another per line. That is 133,000
            inserts for this file, and against the hosted database — where a
            round trip is about ninety milliseconds — flushing per row is the
            difference between four minutes and the better part of three hours,
            on a connection that drops. So each batch is added whole and
            flushed once per layer, which is the fewest trips that still lets
            the layer below read the ids the layer above just took.
            """
            if not pending:
                return

            scripts = [
                Prescription(
                    rx_number=script["number"],
                    patient_id=script["patient_id"],
                    doctor_id=script["doctor_id"],
                    date_prescribed=script["at"].date(),
                    status="active",
                    finalised_at=script["at"],
                    created_at=script["at"],
                    # The diagnosis is a property of the line, not the script:
                    # `Prescription` has no icd10_code and `PrescriptionItem`
                    # does, which is the right way round — one script can treat
                    # two things.
                    notes="Imported from CareXpress",
                    pharmacy_id=pharmacy.id,
                )
                for script in pending
            ]
            db.add_all(scripts)
            db.flush()

            items, owners = [], []
            for script, rx in zip(pending, scripts):
                for line in script["lines"]:
                    items.append(PrescriptionItem(
                        prescription_id=rx.id,
                        product_id=line["product_id"],
                        quantity=line["quantity"],
                        # The export carries no directions. Left empty rather
                        # than filled with the product's own description.
                        dosage_instructions="",
                        icd10_code=script["icd"],
                        # Nothing in the export says a script was repeatable.
                        repeats_allowed=0,
                        repeats_used=0,
                        pharmacy_id=pharmacy.id,
                    ))
                    owners.append((script, line))
            db.add_all(items)
            db.flush()

            db.add_all([
                Dispensing(
                    prescription_item_id=item.id,
                    quantity=item.quantity,
                    dispensed_at=script["at"],
                    dispensed_by_id=actor.id if actor else None,
                    # The person who actually handed it over, as the incumbent
                    # recorded them. They are not users here.
                    #
                    # Eight characters, because that is what the column is.
                    # This sliced at ten and SQLite accepted it without a word
                    #, it does not enforce a VARCHAR length, so it loaded
                    # cleanly here and failed on the first batch against
                    # Postgres with "value too long for type character
                    # varying(8)". The dialect that accepts more is always the
                    # one you develop against.
                    pharmacist_initial=line["dispenser"][:8].upper(),
                    is_repeat=False,
                    script_sighted=True,
                    compliance_notes="Imported from CareXpress",
                    pharmacy_id=pharmacy.id,
                )
                for item, (script, line) in zip(items, owners)
            ])
            db.commit()

            counts["scripts"] += len(scripts)
            counts["items"] += len(items)
            counts["dispensings"] += len(items)
            print(f"  {counts['scripts']:,} scripts … {counts['items']:,} lines",
                  flush=True)
            pending.clear()

        for n, row in enumerate(sheet.iter_rows(values_only=True)):
            if n < HEADER_ROW or not row:
                continue
            number = _clean(row[0])
            if not number or number.lower() == "sctno":
                continue
            counts["rows"] += 1
            if limit and counts["scripts"] >= limit:
                break

            at = _when(row[1]) or datetime.utcnow()
            name = f"{_clean(row[11]).upper()} {_clean(row[12]).upper()}".strip()
            patient_id = people.get(name)
            doctor_id = doctors.get(_clean(row[22]).upper()) if len(row) > 22 else None
            icd_raw = _clean(row[31]) if len(row) > 31 else ""
            icd = "" if icd_raw.upper() == PLACEHOLDER_ICD else icd_raw

            key = f"CX{number}"

            # The script number changing is what ends one script and begins the
            # next; the file is grouped, not keyed. Everything that decides
            # whether to start a new one, already loaded, no patient, belongs
            # HERE and only here. Testing `already` on every row instead meant
            # the second line of a script found its own number already taken by
            # its first line, and every script came out with exactly one item.
            if current is None or current["number"] != key:
                if current is not None and current["lines"]:
                    pending.append(current)
                    if len(pending) >= BATCH:
                        flush()
                current = None

                if key in already:
                    counts["skipped_existing"] += 1
                    continue
                if patient_id is None:
                    counts["no_patient"] += 1
                    continue
                if icd:
                    counts["real_diagnoses"] += 1
                current = {"number": key, "at": at, "patient_id": patient_id,
                           "doctor_id": doctor_id, "icd": icd, "lines": []}
                already.add(key)

            if current is None:
                continue

            code = _clean(row[5]).upper()
            product_id = products.get(code)
            if not product_id:
                # A stock code this catalogue does not hold. Counted rather
                # than guessed at: pinning it to an invented product would put
                # a medicine on a patient's record that they were never given.
                counts["no_product"] += 1
                continue
            current["lines"].append({
                "product_id": product_id,
                "quantity": _qty(row[7]),
                # The export carries no directions — only the product's own
                # description, which is not how to take it. Putting that in the
                # directions field would print "BETADINE ANTISEP SLTN 5L" on a
                # label where "apply twice daily" belongs, and a patient record
                # would then show directions for every historical script that
                # were never given.
                "dispenser": _clean(row[24]) if len(row) > 24 else "",
            })

        if current is not None and current["lines"]:
            pending.append(current)
        flush()
        return counts
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    counts = load(sys.argv[1], limit=limit)
    print(f"  {counts['rows']:>7,} rows read")
    print(f"  {counts['scripts']:>7,} scripts written")
    print(f"  {counts['items']:>7,} lines on them")
    print(f"  {counts['dispensings']:>7,} dispensing records")
    print(f"  {counts['real_diagnoses']:>7,} carried a real diagnosis "
          f"(the rest were the incumbent's placeholder)")
    if counts["skipped_existing"]:
        print(f"  {counts['skipped_existing']:>7,} rows already loaded, left alone")
    if counts["no_patient"]:
        print(f"  {counts['no_patient']:>7,} scripts skipped — no patient of that name")
    if counts["no_product"]:
        print(f"  {counts['no_product']:>7,} lines skipped — stock code not in the catalogue")


if __name__ == "__main__":
    main()
