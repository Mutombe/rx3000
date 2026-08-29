"""A scheme's list of what it will pay for.

Full CRUD on the server since the day it was written, and no screen anywhere,
which meant the coverage check on the dispensing page had been answering from
formularies nobody could see, let alone maintain. The model's own warning is
the reason this is worth getting right: `default_rule` decides the fate of
every product nobody has listed, and getting it backwards is the difference
between over-claiming and rejecting everything.

So what is asserted here is the pair of behaviours a screen has to be honest
about — an open formulary pays for what is not listed, a closed one refuses it
— and that listing a product twice corrects the entry rather than creating a
second one. A formulary that could hold two contradictory rules for one product
would answer differently depending on which row was read first.
"""
import os
import pathlib
import sys

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"formulary.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient              # noqa: E402
from app.database import Base, engine, SessionLocal, get_db   # noqa: E402
from app import models                                 # noqa: E402
from app.main import app                               # noqa: E402
from app.auth import get_current_user                  # noqa: E402

Base.metadata.create_all(engine)
db = SessionLocal()
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


user = models.User(username="a", full_name="A", role="admin", password_hash="x")
statin = models.Product(name="Atorvastatin", strength="20mg", unit_price=12.0)
brand = models.Product(name="Lipitor", strength="20mg", unit_price=41.0)
db.add_all([user, statin, brand])
db.commit()

app.dependency_overrides[get_current_user] = lambda: user
app.dependency_overrides[get_db] = lambda: db
client = TestClient(app)

print("an open formulary and a closed one")
op = client.post("/api/claiming/formularies", json={
    "code": "cim-open", "name": "CIMAS Private Hospital", "default_rule": "covered"})
cl = client.post("/api/claiming/formularies", json={
    "code": "psmas-closed", "name": "PSMAS Standard", "default_rule": "excluded"})
check(op.status_code == 200 and cl.status_code == 200, "both created")
check(op.json()["code"] == "CIM-OPEN",
      f"the code is upper-cased, so it matches however it was typed "
      f"({op.json()['code']})")

print("\na code used twice")
again = client.post("/api/claiming/formularies", json={
    "code": "CIM-OPEN", "name": "Another", "default_rule": "covered"})
check(again.status_code == 400, f"refused ({again.status_code})")

print("\na rule that is neither open nor closed")
bad = client.post("/api/claiming/formularies", json={
    "code": "X1", "name": "X", "default_rule": "sometimes"})
check(bad.status_code == 400,
      f"refused ({bad.status_code}) — there is no third answer, and a bad one "
      f"here decides every unlisted product")

print("\nlisting the brand as reference-priced against the generic")
open_id = op.json()["id"]
entry = client.post(f"/api/claiming/formularies/{open_id}/entries", json={
    "product_id": brand.id, "status": "reference", "reference_price": 12.0,
    "note": "paid at the generic price"})
check(entry.status_code == 200, f"filed ({entry.status_code})")
check(entry.json()["reference_price"] == 12.0,
      "at 12.00 — the patient carries the 29.00 difference to the brand")

print("\nlisting it again with a different rule")
changed = client.post(f"/api/claiming/formularies/{open_id}/entries", json={
    "product_id": brand.id, "status": "excluded", "note": "off formulary from August"})
check(changed.status_code == 200, "accepted")
rows = client.get(f"/api/claiming/formularies/{open_id}/entries").json()
check(len(rows) == 1,
      f"there is still one entry for that product ({len(rows)}) — two rows "
      f"would answer differently depending on which was read first")
check(rows[0]["status"] == "excluded", "and it is the newer rule that stands")

print("\nwhat the screen shows for each entry")
check(rows[0].get("product", {}).get("name") == "Lipitor",
      "the product comes back with the entry, so a formulary is a list of "
      "medicines rather than a list of numbers to look up")

print("\nfiltering to one standing")
client.post(f"/api/claiming/formularies/{open_id}/entries", json={
    "product_id": statin.id, "status": "covered"})
excluded = client.get(
    f"/api/claiming/formularies/{open_id}/entries?status_filter=excluded").json()
check(len(excluded) == 1 and excluded[0]["product_id"] == brand.id,
      "only the excluded line comes back")

print("\na product that does not exist")
ghost = client.post(f"/api/claiming/formularies/{open_id}/entries", json={
    "product_id": 99999, "status": "covered"})
check(ghost.status_code == 404, f"refused ({ghost.status_code})")

print("\na standing that is not one of the four")
weird = client.post(f"/api/claiming/formularies/{open_id}/entries", json={
    "product_id": statin.id, "status": "maybe"})
check(weird.status_code == 400, f"refused ({weird.status_code})")

print()
if failures:
    print(f"{len(failures)} failed")
    sys.exit(1)
print("a formulary says one thing per product, and says which way it defaults")
