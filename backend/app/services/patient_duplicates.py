"""Is this person already on file?

CareXpress To-Be blueprint §6 and §7: duplicate patients are detected at
registration and prompt a review, so one person's history does not split
across two records — two sets of allergies, two repeat counts, claims against
two members that are one.

RX5000 saved every registration without looking. With 14,000 patients and a
counter that is busy, the second record is not a hypothetical: it is what
happens when a surname is typed "Moyo" once and "Moyo " the next time, or when
the patient is found by a phone number that was changed.

The rules, strongest first:

  same ID number                         the identity document says so
  same date of birth and surname         a namesake is unlikely to share both
  same phone number and surname          a family shares a phone; a surname narrows it
  same full name, nothing else to go on  a weak signal, only when the new record
                                         carries neither ID nor date of birth

Normalised before comparing — case, spaces, hyphens, and the last nine digits
of a phone — because the variations are exactly where a duplicate comes from.
Read through the ORM inside a request, so a pharmacy is only ever told about
its own patients.
"""
import re

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import Patient

LIMIT = 5


def _id(value: str | None) -> str:
    return re.sub(r"[\s\-/]", "", (value or "")).upper()


def _name(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip().lower()


def _phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-9:] if len(digits) >= 7 else ""


def find(db: Session, *, first_name: str = "", last_name: str = "",
         id_number: str = "", date_of_birth=None, phone: str = "",
         exclude_id: int | None = None) -> list[dict]:
    """Patients on file who may be this person, strongest match first."""
    wanted_id = _id(id_number)
    wanted_last = _name(last_name)
    wanted_full = f"{_name(first_name)} {wanted_last}".strip()
    wanted_phone = _phone(phone)

    clauses = []
    if wanted_id:
        # Normalised in SQL the same way as in Python: hyphens and spaces out,
        # upper case. REPLACE and UPPER are the same on SQLite and Postgres.
        normalised = func.upper(func.replace(func.replace(Patient.id_number, "-", ""), " ", ""))
        clauses.append(normalised == wanted_id)
    if wanted_last:
        clauses.append(func.lower(func.trim(Patient.last_name)) == wanted_last)
    if date_of_birth:
        clauses.append(Patient.date_of_birth == date_of_birth)
    if not clauses:
        return []

    query = db.query(Patient).filter(or_(*clauses))
    if exclude_id:
        query = query.filter(Patient.id != exclude_id)

    found = []
    for p in query.limit(300):
        same_last = wanted_last and _name(p.last_name) == wanted_last
        reasons, rank = [], 9
        if wanted_id and _id(p.id_number) == wanted_id:
            reasons.append("Same ID number")
            rank = min(rank, 0)
        if date_of_birth and p.date_of_birth == date_of_birth and same_last:
            reasons.append("Same date of birth and surname")
            rank = min(rank, 1)
        if wanted_phone and _phone(p.phone) == wanted_phone and same_last:
            reasons.append("Same phone number and surname")
            rank = min(rank, 2)
        if (not wanted_id and not date_of_birth and wanted_full
                and f"{_name(p.first_name)} {_name(p.last_name)}" == wanted_full):
            reasons.append("Same full name")
            rank = min(rank, 3)
        if not reasons:
            continue
        found.append({
            "id": p.id,
            "profile_number": p.profile_number,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "id_number": p.id_number or "",
            "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
            "phone": p.phone or "",
            "reasons": reasons,
            "strength": "strong" if rank == 0 else "likely",
            "_rank": rank,
        })

    found.sort(key=lambda m: (m["_rank"], m["last_name"], m["first_name"]))
    for m in found:
        m.pop("_rank")
    return found[:LIMIT]
