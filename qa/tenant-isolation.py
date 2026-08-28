"""One pharmacy cannot read another's records.

This is the check the whole tenancy exists for, and it is written to fail the
way the real thing would fail: not by raising, but by quietly returning
somebody else's patient.

The scoping is applied by the session rather than by a `WHERE` in each query,
because there are eighty-six tables and several hundred queries and a missed one
looks exactly like a correct one. So the assertions below deliberately use plain,
unsuspecting queries — `db.query(Patient).all()`, a relationship traversal, a
`get` by primary key — the kind somebody writes without having read a word about
tenancy. If those leak, the design has failed regardless of what any individual
router does.
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"tenant-isolation.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base, engine, SessionLocal        # noqa: E402
from app import models, tenancy                            # noqa: E402

Base.metadata.create_all(engine)
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


# Two pharmacies on one deployment, which is the whole point.
with tenancy.unscoped():
    db = SessionLocal()
    acme = models.Pharmacy(name="Acme Pharmacy")
    beta = models.Pharmacy(name="Beta Chemists")
    db.add_all([acme, beta])
    db.commit()
    acme_id, beta_id = acme.id, beta.id

    db.add_all([
        models.Patient(first_name="Acme", last_name="Patient", pharmacy_id=acme_id),
        models.Patient(first_name="Beta", last_name="Patient", pharmacy_id=beta_id),
        models.Product(name="Acme Product", pharmacy_id=acme_id),
        models.Product(name="Beta Product", pharmacy_id=beta_id),
    ])
    db.commit()
    acme_patient = db.query(models.Patient).filter_by(first_name="Acme").one().id
    beta_patient = db.query(models.Patient).filter_by(first_name="Beta").one().id
    db.close()

print("signed in as Acme")
token = tenancy.set_current_pharmacy(acme_id)
db = SessionLocal()
names = [f"{p.first_name} {p.last_name}" for p in db.query(models.Patient).all()]
check(names == ["Acme Patient"], f"a plain patient list shows only Acme's: {names}")
products = [p.name for p in db.query(models.Product).all()]
check(products == ["Acme Product"], f"and only Acme's products: {products}")

# The one that a hand-written `WHERE` would miss: fetching by id.
check(db.get(models.Patient, beta_patient) is None,
      "fetching Beta's patient by primary key returns nothing")
check(db.get(models.Patient, acme_patient) is not None,
      "while Acme's own is still reachable")

# And counting, which is what dashboards do.
check(db.query(models.Patient).count() == 1, "a count sees one patient, not two")
db.close()
tenancy.reset_current_pharmacy(token)

print("\nsigned in as Beta")
token = tenancy.set_current_pharmacy(beta_id)
db = SessionLocal()
names = [f"{p.first_name} {p.last_name}" for p in db.query(models.Patient).all()]
check(names == ["Beta Patient"], f"the same query now shows only Beta's: {names}")
check(db.get(models.Patient, acme_patient) is None,
      "Acme's patient is not reachable by id either")
db.close()
tenancy.reset_current_pharmacy(token)

print("\nsigned in as nobody")
db = SessionLocal()
# The important default. An unauthenticated or mis-wired request must not see
# everything — it must see nothing, because an empty screen gets reported by
# lunchtime and a screen full of another pharmacy's patients might never be.
check(db.query(models.Patient).count() == 0,
      "no pharmacy in force returns nothing, not everything")
db.close()

print("\nnew rows are stamped without being told")
token = tenancy.set_current_pharmacy(beta_id)
db = SessionLocal()
tenancy.stamp(db)
db.add(models.Patient(first_name="Written", last_name="Blind"))
db.commit()
written = db.query(models.Patient).filter_by(first_name="Written").one()
check(written.pharmacy_id == beta_id,
      "a row saved with no pharmacy set gets the one in force")
db.close()
tenancy.reset_current_pharmacy(token)

token = tenancy.set_current_pharmacy(acme_id)
db = SessionLocal()
check(db.query(models.Patient).filter_by(first_name="Written").count() == 0,
      "and Acme cannot see it")
db.close()
tenancy.reset_current_pharmacy(token)

print("\nshared reference data stays shared")
with tenancy.unscoped():
    db = SessionLocal()
    db.add(models.DiagnosisCode(code="E11.9", description="Type 2 diabetes"))
    db.commit()
    db.close()
token = tenancy.set_current_pharmacy(acme_id)
db = SessionLocal()
check(db.query(models.DiagnosisCode).count() == 1,
      "Acme sees the ICD-10 book")
db.close()
tenancy.reset_current_pharmacy(token)
token = tenancy.set_current_pharmacy(beta_id)
db = SessionLocal()
check(db.query(models.DiagnosisCode).count() == 1,
      "and so does Beta — one book, not one per tenant")
db.close()
tenancy.reset_current_pharmacy(token)

print(f"\n{len(failures)} failing" if failures else "\nall checks passed")
sys.exit(1 if failures else 0)
