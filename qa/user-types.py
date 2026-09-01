"""Can a patient's login reach the pharmacy's application?

Three kinds of person sign in here and they are not variations of one another.
Staff arrive with a username and password and reach the application. A patient
arrives with a signed link and a four-digit code and reaches their own record.
A prescriber arrives with an account tied to a practice number and reaches the
prescribing portal.

The danger is what happens when that distinction is not made. `role` defaults
to `assistant`, so a patient login that reached `get_current_user` would be
treated as a member of staff with an assistant's permissions — over somebody
else's pharmacy, holding somebody else's patients' records. Not because anybody
granted it, but because the default was never meant to be reached by that kind
of user.

So the check is a positive one: **is this staff**, rather than *is this not a
patient*. A user type nobody has thought of yet must be refused the application
rather than admitted by falling through a list of exclusions, and the test
below is written against a type that does not exist yet, for that reason.

Nothing is committed.

    python qa/user-types.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal              # noqa: E402
from app import tenancy                            # noqa: E402
from app.models import User                        # noqa: E402
from app.services import user_types                # noqa: E402


def main() -> int:
    tenancy.set_current_pharmacy(1)
    db = SessionLocal()
    tenancy.stamp(db)
    failures: list[str] = []

    def check(ok: bool, said: str, why: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {said}")
        if not ok:
            failures.append(why or said)

    try:
        staff = db.query(User).filter(User.is_demo.is_(False)).first()
        if staff is None:
            print("FAIL: no user on this database")
            return 2

        check(user_types.may_use_application(staff),
              f"a member of staff ({staff.role}) reaches the application")

        for kind, reaches in (("patient", False), ("prescriber", False),
                              # A type nobody has invented yet. It must be
                              # refused, not admitted by default.
                              ("kiosk", False), ("", True)):
            staff.user_type = kind
            allowed = user_types.may_use_application(staff)
            label = kind or "(blank, an older record)"
            check(allowed == reaches,
                  f"a {label} login "
                  + ("reaches" if reaches else "is refused")
                  + " the application",
                  f"a {label} login is "
                  + ("refused" if reaches else "admitted")
                  + ", and a login admitted by default holds an assistant's "
                    "permissions over somebody else's patients")
        staff.user_type = "staff"

        # And the inference, for records written before the column existed.
        staff.user_type = ""
        staff.patient_id = 1
        check(user_types.of(staff) == "patient",
              "a login with a patient attached reads as a patient even where "
              "the column was never set",
              "an older patient login reads as staff, which is the one wrong "
              "answer that matters")
        staff.patient_id = None
        staff.user_type = "staff"

        # The PIN report: the finding, not the mechanism.
        report = user_types.pin_report(db)
        print()
        print(f"  {report['says']}")
        signs = [u for u in report["without_pin"] if u["signs_controlled"]]
        if signs:
            print(f"       including: "
                  + ", ".join(u["full_name"] for u in signs[:4]))
        check(isinstance(report["with_pin"], int),
              f"{report['with_pin']} of {report['staff']} staff can sign in "
              f"their own name")
    finally:
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("only staff reach the application, and an unknown kind of login is "
          "refused rather than admitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
