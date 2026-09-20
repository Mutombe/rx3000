"""The last link: the number on the label opens the script it was printed from.

Two guards already stand either side of this one.

`qa/barcode-reads.mjs` proves the ENCODER: it draws the symbol from
`code128.ts` and reads it back. `qa/label-barcode-reads.mjs` proves the
PRINTED ARTEFACT: it builds the real dispensing label as a PDF, rasterises it
the way a driver would, and scans the bars out of the picture.

Both of them end at a string. Neither asks what happens when somebody scans
that string at a counter, and for a long time the answer was

    Nothing is stocked under that code.

The product printed a barcode on every label it could not itself read, because
every path through the scanner resolved to a product and a script number is
not a product. The symbol was correct, the print was correct, and the feature
did not exist.

WHAT THIS CHECKS

That a script number handed to the scanner comes back as the prescription it
names, with the things a dispenser needs in the second after the beep; that a
script which must not be dispensed says so instead of opening; that the scan
is written onto the script's own trail; and that a script belonging to another
pharmacy is not found, which is the one failure that would matter most.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient          # noqa: E402

from app.main import app                           # noqa: E402
from app.database import SessionLocal              # noqa: E402
from app.tenancy import unscoped, set_current_pharmacy   # noqa: E402
from app import auth, branch_scope, models         # noqa: E402

passed = 0
failed = 0


def check(condition: bool, message: str, extra: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {message}")
    else:
        failed += 1
        print(f"  FAIL {message}{('   ' + extra) if extra else ''}")


client = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:5].upper()

with unscoped():
    me = (db.query(models.User)
          .filter(models.User.is_demo.is_(False), models.User.active,
                  models.User.pharmacy_id.isnot(None))
          .first())
    if me is None:
        print("  ..   no account on this database to sign in as")
        sys.exit(0)
    headers = {"Authorization": f"Bearer {auth.create_token(me, db)}"}
    mine = me.pharmacy_id

set_current_pharmacy(mine)
made: list[int] = []

with branch_scope.every_branch():
    patient = db.query(models.Patient).first()
    product = db.query(models.Product).filter(models.Product.active).first()
    if patient is None or product is None:
        print("  ..   no patient or product on this database")
        sys.exit(0)

    def script(status: str, pharmacy_id: int,
               suffix: str = "") -> models.Prescription:
        # The suffix matters. Both the live script and the other pharmacy's
        # were once named from the status alone, so two "active" scripts got
        # the SAME number differing only by pharmacy — and the cross-tenant
        # check was then scanning a string that also matched our own script,
        # finding ours, and reporting a leak that was not happening. A test
        # that cries wolf about tenancy is worse than no test.
        rx = models.Prescription(
            rx_number=f"QA{tag}{status[:3].upper()}{suffix}",
            patient_id=patient.id, status=status, pharmacy_id=pharmacy_id)
        db.add(rx)
        db.flush()
        db.add(models.PrescriptionItem(
            prescription_id=rx.id, product_id=product.id, quantity=30,
            dosage_instructions="One three times a day", pharmacy_id=pharmacy_id))
        db.flush()
        made.append(rx.id)
        return rx

    live = script("active", mine)
    cancelled = script("cancelled", mine)
    # The same shape, belonging to somebody else. This is the row that must
    # NOT come back.
    other = (db.query(models.Pharmacy)
             .filter(models.Pharmacy.id != mine).first())
    theirs = script("active", other.id, suffix="X") if other else None
    db.commit()
    live_number, cancelled_number = live.rx_number, cancelled.rx_number
    theirs_number = theirs.rx_number if theirs else ""


def scan(code: str) -> dict:
    return client.post("/api/scan", headers=headers,
                       json={"code": code, "context": "dispense"}).json()


print("\n  a printed label, scanned at the counter\n")

got = scan(live_number)
check(got.get("found") is True, "a script number is recognised at all",
      str(got.get("message"))[:60])
check(got.get("kind") == "prescription",
      "and is reported as a prescription rather than a product",
      f"kind={got.get('kind')}")
rx = got.get("prescription") or {}
check(rx.get("rx_number") == live_number,
      "the script that comes back is the one on the label")
check(bool(rx.get("patient")), "it names the patient at the counter",
      f"patient={rx.get('patient')!r}")
check(len(rx.get("lines") or []) == 1,
      "and the medicines on it", f"{len(rx.get('lines') or [])} line(s)")
check(rx.get("may_dispense") is True, "a live script may be dispensed")
line = (rx.get("lines") or [{}])[0]
check("dispensed" in line and "outstanding" in line,
      "each line says what has gone out and what is still owed")

print("\n  and one that must not go out\n")

stopped = scan(cancelled_number)
srx = stopped.get("prescription") or {}
check(srx.get("may_dispense") is False, "a cancelled script refuses")
check("cancelled" in (srx.get("refuse") or "").lower(),
      "and says why, in words somebody can act on",
      (srx.get("refuse") or "")[:60])

print("\n  another pharmacy's script\n")

if theirs_number:
    away = scan(theirs_number)
    check(away.get("kind") != "prescription" and not away.get("prescription"),
          "is not found, because the lookup is tenant scoped",
          f"kind={away.get('kind')}")
else:
    print("  ..   only one pharmacy on this database, so nothing to cross")

print("\n  the trail it leaves\n")

with branch_scope.every_branch():
    trail = (db.query(models.ScriptChange)
             .filter(models.ScriptChange.prescription_id == live.id,
                     models.ScriptChange.field == "scanned").all())
check(len(trail) >= 1, "the scan is written onto the script's own history",
      f"{len(trail)} row(s)")
check(all(r.changed_by_id == me.id for r in trail),
      "against the person who scanned it")

# Left cancelled rather than deleted: other rows point at a prescription, and
# a script is not a thing this system deletes.
with branch_scope.every_branch(), unscoped():
    for rx_id in made:
        row = db.get(models.Prescription, rx_id)
        if row is not None:
            row.status = "cancelled"
            row.rx_number = f"{row.rx_number}-QA"
    db.commit()

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\na barcode the product prints and cannot read is decoration.")
sys.exit(1 if failed else 0)
