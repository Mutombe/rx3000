"""The three kinds of person who sign in here, and what each may reach.

`role` says what a member of staff may do. It cannot say what somebody *is* —
and the three kinds are not variations of one another. They arrive by different
doors, prove themselves differently, and reach different halves of the system.

    staff       username and password, then a PIN at the till.
                Reaches the application; `role` and the capability grants
                decide how much of it.

    patient     a signed link and a four-digit code.
                Reaches their own record and nothing else, ever. No role, no
                capabilities, no PIN — there is no till for them to stand at.

    prescriber  their own account, tied to a practice number.
                Reads dispensing status and writes prescriptions in, which is
                why it cannot be a link: a link that can prescribe is a
                prescription pad held by everybody it was ever forwarded to.

WHY THE PIN IS ONLY FOR STAFF, AND WHY IT IS NOT OPTIONAL FOR THEM

The password says *this session belongs to a person*. The PIN says *this person
is standing here now*, and on a till that stays signed in from eight until six
those are not the same claim. The second is the one the controlled register
needs, and it is the one a shared session cannot make.

Which is why a member of staff without a PIN is a gap rather than a preference:
every dispensing they check is recorded against whoever signed the till in that
morning. The report below names them, because a pharmacy cannot fix what it
cannot list.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Doctor, Patient, User

#: (type, what it is, how they prove it, what they reach, does a PIN apply)
TYPES: list[tuple[str, str, str, str, bool]] = [
    ("staff", "Somebody who works here",
     "Username and password, then a PIN for anything that has to be signed",
     "The application, as far as their role and grants allow",
     True),
    ("patient", "Somebody the pharmacy dispenses to",
     "A signed link the pharmacy sends, and a four-digit code",
     "Their own record only — never the application",
     False),
    ("prescriber", "A doctor who prescribes into this pharmacy",
     "Their own account, tied to a practice number",
     "Dispensing status for their own patients, and submitting scripts",
     False),
]

BY_KEY = {t[0]: t for t in TYPES}


def describe(kind: str) -> dict:
    entry = BY_KEY.get(kind) or BY_KEY["staff"]
    key, what, how, reaches, pin = entry
    return {"user_type": key, "what": what, "signs_in_with": how,
            "reaches": reaches, "needs_pin": pin}


def of(user: User) -> str:
    """What kind this user is, tolerating a record written before the column.

    Read from the column where it is set, and inferred once where it is not —
    an older database has every login as staff by default, and a patient login
    created before this existed would otherwise be treated as a member of
    staff, which is the one wrong answer that matters.
    """
    kind = (getattr(user, "user_type", "") or "").strip()
    if kind in BY_KEY:
        return kind

    # A value that IS set but is not one of the three is not a staff account.
    # The first version fell through to "staff" here, which meant a type
    # nobody had implemented yet — a kiosk, a courier, anything a later release
    # adds — would be admitted to the application with an assistant's
    # permissions until somebody noticed. Returned as-is so the caller can
    # refuse it and the screen can name it.
    if kind:
        return kind

    # Blank is the migration default and genuinely means staff: every record
    # that predates this column belongs to somebody who works here. The two
    # inferences below only correct the ones that do not.
    if getattr(user, "patient_id", None):
        return "patient"
    if getattr(user, "doctor_id", None):
        return "prescriber"
    return "staff"


def may_use_application(user: User) -> bool:
    """Only staff reach the application.

    Checked as a positive — "is this staff" — rather than as "is this not a
    patient". A user type nobody has thought of yet must be refused the
    application rather than admitted to it by falling through a list of
    exclusions.
    """
    return of(user) == "staff"


def pin_report(db: Session) -> dict:
    """Which staff can sign for what they do, and which cannot.

    A member of staff with no PIN is not a preference somebody has expressed.
    It means every dispensing they check is recorded against whoever signed the
    till in that morning — so the controlled register names the wrong person,
    quietly, on every line they touched.
    """
    staff = [u for u in db.query(User).filter(User.is_demo.is_(False)).all()
             if of(u) == "staff" and u.active]
    without = [u for u in staff if not u.pin_hash]
    locked = [u for u in staff if u.pin_locked_until]

    # The ones it matters most for: a PIN is what lets somebody sign a
    # controlled handover in their own name.
    critical = [u for u in without if u.role in ("pharmacist", "admin", "manager")]

    return {
        "staff": len(staff),
        "with_pin": len(staff) - len(without),
        "without_pin": [{"id": u.id, "full_name": u.full_name,
                         "username": u.username, "role": u.role,
                         "signs_controlled": u.role in ("pharmacist", "admin")}
                        for u in without],
        "locked_out": [{"id": u.id, "full_name": u.full_name,
                        "until": u.pin_locked_until} for u in locked],
        "says": (
            f"{len(without)} of {len(staff)} staff have no PIN"
            + (f", including {len(critical)} who sign for controlled medicines"
               if critical else "")
            + ". Everything they do is recorded against whoever opened the "
              "till that morning."
            if without else
            f"All {len(staff)} staff can sign in their own name."),
    }


def directory(db: Session) -> dict:
    """Everybody who can sign in, by kind. The list nobody had.

    Staff were listable and the other two were not, so "who can reach this
    pharmacy's data" had no answer that included the patient with a live portal
    link or the prescriber submitting scripts.
    """
    users = db.query(User).filter(User.is_demo.is_(False)).all()

    buckets: dict[str, list] = {k: [] for k in BY_KEY}
    for user in users:
        buckets.setdefault(of(user), []).append({
            "id": user.id, "full_name": user.full_name,
            "username": user.username, "role": user.role,
            "active": bool(user.active),
            "has_pin": bool(user.pin_hash),
            "patient_id": getattr(user, "patient_id", None),
            "doctor_id": getattr(user, "doctor_id", None),
        })

    # Patients with a portal code are people who can reach their own record
    # whether or not they have a `users` row — the link is the credential. They
    # belong in a directory of who can see what.
    with_portal = (db.query(func.count(Patient.id))
                   .filter(Patient.portal_code != "",
                           Patient.portal_code.isnot(None)).scalar() or 0)

    return {
        "types": [describe(k) for k in BY_KEY],
        "users": buckets,
        "counts": {k: len(v) for k, v in buckets.items()},
        "patients_with_portal_access": int(with_portal),
        "note": (
            f"{int(with_portal):,} patient(s) can open their own record with a "
            f"link and a code. They hold no login here and reach nothing but "
            f"their own record."),
    }
