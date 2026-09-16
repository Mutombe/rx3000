"""Practice numbers for the prescribers, from the pharmacy's own script report.

    python -m app.importers.carexpress_prescribers --file "DOCTORS Patient S.xlsx" --pharmacy 13
    python -m app.importers.carexpress_prescribers --file … --pharmacy 13 --apply

WHY THIS EXISTS

The prescriber list came across with names and nothing else: 689 prescribers,
not one of them with a practice number. A funder adjudicates on that number, so
every claim for a script written by any of them carries a prescriber the funder
cannot identify.

The pharmacy's own "DOCTORS: Patient Scripts" report has the number against
every script it lists — 185 prescribers, 175 of whom are already on file here.

WHICH NUMBER IS WHICH

The practice number a Zimbabwean funder adjudicates on IS the AHFoZ number, so
`Prac No` fills both: the practice number a prescriber prints on their own
stationery, and the number the claim is paid against. `Group No`, where the
report has one, is the group practice they bill under — recorded beside it
rather than confused with it.

MATCHED ON THE NAME, WHICH IS ALL EITHER SIDE HAS

Squashed to letters, so " MUNGWADZI" and "Mungwadzi Dr" are the same prescriber
and a stray space or title cannot hide one. Anything that does not match is
listed rather than guessed at: a practice number written against the wrong
prescriber is worse than a blank one, because a blank is visibly missing and a
wrong one is quietly rejected by the funder months later.

WHERE THE REPORT DISAGREES WITH ITSELF

Nine prescribers appear under two practice numbers — a locum writing under two
practices, a doctor who has moved, or a keying slip. The one on the most scripts
is taken, and where that is a tie the one on the most recent script wins:
the number somebody is writing under this month is the one a funder will
recognise. Both are reported either way, because picking silently is how the
rarer number disappears from view for ever.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict

from ..database import SessionLocal
from ..models import Doctor
from ..tenancy import reset_current_pharmacy, set_current_pharmacy, unscoped

HEADER = ("Doctor", "Prac No")


def _squash(name: str) -> str:
    """A name with its spacing, case and titles taken out."""
    text = re.sub(r"\b(DR|DOCTOR|MISS|MRS|MR|PROF|SR)\b", " ", (name or "").upper())
    return re.sub(r"[^A-Z]", "", text)


def read(path: str) -> list[dict]:
    """Every script line in the report: who wrote it, and under what number."""
    import openpyxl

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = book[book.sheetnames[0]]
    columns: list[str] | None = None
    rows: list[dict] = []
    for raw in sheet.iter_rows(values_only=True):
        values = ["" if v is None else str(v).strip() for v in raw]
        if columns is None:
            if all(h in values for h in HEADER):
                columns = values
            continue
        if not any(values):
            continue
        row = dict(zip(columns, values))
        if row.get("Doctor"):
            rows.append(row)
    if columns is None:
        raise SystemExit(f"{path} has no Doctor/Prac No header — is it the doctors report?")
    return rows


def plan(db, rows: list[dict]) -> dict:
    """Which prescriber gets which number, and what cannot be decided here."""
    seen: dict[str, Counter] = defaultdict(Counter)
    groups: dict[str, Counter] = defaultdict(Counter)
    names: dict[str, str] = {}
    latest: dict[tuple[str, str], str] = {}
    for row in rows:
        key = _squash(row["Doctor"])
        if not key:
            continue
        names.setdefault(key, " ".join(row["Doctor"].split()))
        number = (row.get("Prac No") or "").strip()
        if number:
            seen[key][number] += 1
            when = (row.get("Script Date") or "").strip()
            if when > latest.get((key, number), ""):
                latest[(key, number)] = when
        group = (row.get("Group No") or "").strip()
        if group:
            groups[key][group] += 1

    ours = {}
    for doctor in db.query(Doctor).all():
        ours.setdefault(_squash(doctor.name), doctor)

    edits, conflicts, unmatched, already, missing = [], [], [], [], []

    def best(key: str, counts: Counter) -> str:
        """Most scripts wins; a tie goes to whoever wrote most recently."""
        return max(counts, key=lambda n: (counts[n], latest.get((key, n), "")))
    for key, counts in seen.items():
        doctor = ours.get(key)
        if doctor is None:
            number = best(key, counts)
            unmatched.append((names[key], number))
            missing.append((names[key], number,
                            groups[key].most_common(1)[0][0] if groups.get(key) else ""))
            continue
        number = best(key, counts)
        if len(counts) > 1:
            conflicts.append((doctor.name, dict(counts)))
        group = groups[key].most_common(1)[0][0] if groups.get(key) else ""
        current = (doctor.practice_number or "").strip()
        if current == number and (doctor.ahfoz_number or "").strip() == number:
            already.append(doctor.name)
            continue
        edits.append((doctor, number, group, current))
    return {"edits": edits, "conflicts": conflicts, "unmatched": unmatched,
            "already": already, "missing": missing, "prescribers": len(seen)}


def create_missing(db, missing: list[tuple], pharmacy_id: int | None) -> int:
    """Write down prescribers the report names that the list has never had.

    They have written scripts this pharmacy dispensed. Not having them on file
    is why somebody types the name again on the next one.
    """
    for name, number, group in missing:
        db.add(Doctor(name=" ".join(name.title().split())[:120],
                      practice_number=number[:30],
                      # The same number: it is what the funder pays on.
                      ahfoz_number=number[:40],
                      active=True, pharmacy_id=pharmacy_id))
    db.commit()
    return len(missing)


def apply(db, edits: list[tuple]) -> int:
    for doctor, number, group, _current in edits:
        doctor.practice_number = number[:30]
        # The number the claim is paid against is the same number. Left alone
        # where the pharmacy has already typed one of its own.
        if not (doctor.ahfoz_number or "").strip():
            doctor.ahfoz_number = number[:40]

    db.commit()
    return len(edits)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True)
    parser.add_argument("--pharmacy", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--create-missing", action="store_true",
                        help="also write down prescribers the report names that are not on file")
    args = parser.parse_args(argv)

    rows = read(args.file)
    token = set_current_pharmacy(args.pharmacy)
    db = SessionLocal()
    try:
        found = plan(db, rows)
        print(f"\n{len(rows):,} script line(s) naming {found['prescribers']} prescriber(s)")
        print(f"{len(found['edits']):,} prescriber(s) would take a practice number"
              + ("" if args.apply else " — nothing written, this is a preview"))
        print(f"{len(found['already']):,} already have the one the report gives")
        for doctor, number, group, current in found["edits"][:12]:
            was = f" (was {current})" if current else ""
            print(f"    {doctor.name[:34]:<36} {number}{was}"
                  + (f"   group {group}" if group else ""))
        if len(found["edits"]) > 12:
            print(f"    … and {len(found['edits']) - 12:,} more")
        if found["conflicts"]:
            print(f"\n  {len(found['conflicts'])} prescriber(s) appear under more than one "
                  "number; the commonest is taken, a tie going to the most recent:")
            for name, counts in found["conflicts"]:
                spread = ", ".join(f"{n} on {c} script(s)" for n, c in counts.items())
                print(f"    {name[:30]:<32} {spread}")
        if found["unmatched"]:
            print(f"\n  {len(found['unmatched'])} name(s) in the report are not prescribers here:")
            for name, number in found["unmatched"][:10]:
                print(f"    {name[:34]:<36} {number}")
        if args.apply:
            print(f"\n  {apply(db, found['edits']):,} prescriber(s) updated.")
            if args.create_missing:
                from .. import tenancy
                made = create_missing(db, found["missing"], tenancy.current_pharmacy_id())
                print(f"  {made:,} prescriber(s) written down for the first time.")
        return 0
    finally:
        db.close()
        reset_current_pharmacy(token)


if __name__ == "__main__":
    with unscoped():
        sys.exit(main())
