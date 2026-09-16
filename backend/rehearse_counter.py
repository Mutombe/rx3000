"""A shift at each counter, through the real API, against the real database.

    python rehearse_counter.py --pharmacy 5

`rehearse_remote.py` proves the stock functions behave on this data. This goes
the whole way: it starts the application in this process, signs in as a real
member of staff at each branch, and works a script from search to label to
payment through the same HTTP endpoints the browser calls. Nothing is mocked and
no fixture is invented — the patient, the prescriber, the medicine and the shelf
are CareXpress's own.

Every request runs inside one database transaction that is rolled back at the
end, so the pharmacy is exactly as it was: no sale, no claim, no stock movement,
no invoice number spent. The application still commits normally; its commits
land on a savepoint inside that transaction and go when it does.

The lifespan is deliberately not run, because that is what applies migrations
and this must not alter a live schema.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
from datetime import date, timedelta


def _target() -> str:
    env = pathlib.Path(__file__).with_name(".env")
    if not env.exists():
        sys.exit("backend/.env not found; nothing to read the target from.")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SEED_TARGET_URL="):
            url = line.split("=", 1)[1].strip()
            if url:
                return url
    sys.exit("SEED_TARGET_URL is not set in backend/.env.")


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--pharmacy", type=int, default=5)
parser.add_argument("--branch", type=int, default=None)
args = parser.parse_args()

os.environ["DATABASE_URL"] = _target()
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import logging                                                   # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)

from fastapi.testclient import TestClient                        # noqa: E402
from sqlalchemy import func                                      # noqa: E402
from sqlalchemy.orm import sessionmaker                          # noqa: E402

from app import branch_scope, models as m, tenancy               # noqa: E402
from app.auth import create_token                                # noqa: E402
from app.database import engine, get_db                          # noqa: E402
from app.main import app                                         # noqa: E402

# One transaction for the whole run, rolled back at the end. The application's
# own commits become savepoint releases inside it (join_transaction_mode), so
# every endpoint behaves exactly as it does in production and nothing survives.
connection = engine.connect()
outer = connection.begin()
Rehearsal = sessionmaker(bind=connection, autocommit=False, autoflush=False,
                         join_transaction_mode="create_savepoint")
tenancy.install(Rehearsal)
branch_scope.install(Rehearsal)


def _rehearsal_db():
    db = Rehearsal()
    tenancy.stamp(db)
    branch_scope.stamp(db)
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _rehearsal_db
http = TestClient(app, raise_server_exceptions=False)

fails: list[str] = []
notes: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))
    if not ok:
        fails.append(label)
    return ok


def as_user(user: m.User, db) -> None:
    http.headers["Authorization"] = "Bearer " + create_token(user, db)


print(f"target: {os.environ['DATABASE_URL'].split('@')[-1].split('/')[0]}")

book = Rehearsal()
tenancy.stamp(book)
try:
    with tenancy.unscoped():
        pharmacy = book.get(m.Pharmacy, args.pharmacy)
        print(f"pharmacy: {pharmacy.name if pharmacy else args.pharmacy}")
        shops = (book.query(m.Branch).filter(m.Branch.pharmacy_id == args.pharmacy)
                 .order_by(m.Branch.id).all())
        if args.branch:
            shops = [b for b in shops if b.id == args.branch]

        for branch in shops:
            print(f"\n=== {branch.name} (branch {branch.id}) ===")
            # The person who would actually do this: a pharmacist at this shop,
            # or whoever is posted here.
            staff = (book.query(m.User)
                     .filter(m.User.pharmacy_id == args.pharmacy,
                             m.User.branch_id == branch.id, m.User.active.is_(True))
                     .order_by(m.User.role != "pharmacist", m.User.id).all())
            if not staff:
                check("somebody is posted here to dispense", False, "nobody is")
                continue
            who = staff[0]
            as_user(who, book)
            print(f"  signed in as {who.username} ({who.role})")

            # --- the dispensary's own search --------------------------------
            found = http.get("/api/dispensing/products?route=prescription&limit=60")
            if not check("the dispensary search answers", found.status_code == 200,
                         found.text[:120]):
                continue
            rows = found.json()
            held = [p for p in rows if (p.get("here") or 0) > 0
                    or (p.get("here_undated") or 0) > 0]
            check("the search says what THIS branch holds, not the group's total",
                  all("here" in p for p in rows),
                  f"{len(held)} of {len(rows)} on the page are on this shelf")
            if not held:
                notes.append(f"{branch.name}: the first page of the dispensary search "
                             "holds nothing this branch stocks")
                # Fall back to something this branch definitely has.
                sits = (book.query(m.Product).join(
                    m.StockBatch, m.StockBatch.product_id == m.Product.id)
                    .filter(m.Product.pharmacy_id == args.pharmacy,
                            m.Product.active.is_(True),
                            m.StockBatch.branch_id == branch.id,
                            m.StockBatch.quantity_remaining >= 30).first())
                if sits is None:
                    check("this branch has something to dispense", False, "the shelf is empty")
                    continue
                line = http.get(f"/api/dispensing/products?search={sits.stock_code}&limit=5")
                held = [p for p in line.json() if p["id"] == sits.id] if line.ok else []
                if not held:
                    check("a medicine this branch holds can be found by code", False,
                          sits.stock_code or str(sits.id))
                    continue
            medicine = max(held, key=lambda p: (p.get("here") or 0) + (p.get("here_undated") or 0))
            print(f"  dispensing: {medicine['name'][:44]}  "
                  f"(here {medicine.get('here')}, undated {medicine.get('here_undated')})")

            # --- a patient, created at the counter ---------------------------
            made = http.post("/api/patients", json={
                "first_name": "Rehearsal", "last_name": f"DoNotKeep{branch.id}",
                "date_of_birth": "1990-01-01", "gender": "F", "phone": "0770000000",
                "confirmed_distinct": True})
            if not check("a patient can be created at the counter",
                         made.status_code in (200, 201), made.text[:140]):
                continue
            patient = made.json()

            prescribers = http.get("/api/doctors?limit=5")
            people = prescribers.json()
            people = people["items"] if isinstance(people, dict) else people
            if not check("there is a prescriber to capture against",
                         bool(people), prescribers.text[:100]):
                continue
            doctor = people[0]

            # --- the script --------------------------------------------------
            # Never more than the shelf holds: this is here to test the counter,
            # not to prove that a shortage is reported.
            want = max(1, min(10, (medicine.get("here") or 0)
                              + (medicine.get("here_undated") or 0)))
            rx = http.post("/api/prescriptions", json={
                "patient_id": patient["id"], "doctor_id": doctor["id"],
                "items": [{"product_id": medicine["id"], "quantity": want,
                           "dosage_instructions": "One twice a day",
                           "repeats_allowed": 0, "repeat_interval_days": 30,
                           "auto_refill": False}]})
            if not check("a script can be captured", rx.status_code in (200, 201),
                         rx.text[:200]):
                continue
            script = rx.json()
            item_ids = [i["id"] for i in script["items"]]
            print(f"  script {script.get('prescription_number', script['id'])}")

            # --- what the counter is warned about before Finish --------------
            warned = http.post("/api/dispensing/expiry-needed", json={
                "lines": [{"product_id": medicine["id"], "quantity": want}]})
            check("the counter is asked for the pack date BEFORE it finishes",
                  warned.status_code == 200, warned.text[:120])
            asked = warned.json() if warned.status_code == 200 else []
            needs_date = bool(asked)
            if needs_date:
                print(f"    it wants the expiry off the pack "
                      f"({asked[0]['undated_units']} undated, {asked[0]['dated_units']} dated)")

            def dispense(body: dict):
                return http.post(f"/api/prescriptions/{script['id']}/dispense", json=body)

            # Finishing without the date must be refused, not guessed at.
            if needs_date:
                blind = dispense({"item_ids": item_ids, "payment_method": "cash",
                                  "pharmacist_initial": "RH"})
                check("finishing without the pack date is refused, with the reason",
                      blind.status_code >= 400 and "expiry" in blind.text.lower(),
                      f"{blind.status_code} {blind.text[:110]}")

            # --- the dispensing itself ---------------------------------------
            before = (book.query(func.coalesce(func.sum(m.StockBatch.quantity_remaining), 0))
                      .filter(m.StockBatch.product_id == medicine["id"],
                              m.StockBatch.branch_id == branch.id).scalar() or 0)
            elsewhere_before = (book.query(func.coalesce(
                func.sum(m.StockBatch.quantity_remaining), 0))
                .filter(m.StockBatch.product_id == medicine["id"],
                        m.StockBatch.branch_id != branch.id).scalar() or 0)

            body = {"item_ids": item_ids, "payment_method": "cash",
                    "pharmacist_initial": "RH", "receipt_private": True}
            if needs_date:
                body["pack_expiries"] = {
                    str(medicine["id"]): (date.today() + timedelta(days=400)).isoformat()}
            out = dispense(body)
            if not check("the dispensing goes through", out.status_code == 200,
                         out.text[:220]):
                continue
            sale = out.json()
            print(f"  sale {sale.get('sale_number')}  total {sale.get('total')}")

            check("it is billed at a real price", (sale.get("total") or 0) > 0,
                  str(sale.get("total")))
            check("the privacy choice is kept on the sale",
                  sale.get("receipt_private") is True, str(sale.get("receipt_private")))

            book.expire_all()
            after = (book.query(func.coalesce(func.sum(m.StockBatch.quantity_remaining), 0))
                     .filter(m.StockBatch.product_id == medicine["id"],
                             m.StockBatch.branch_id == branch.id).scalar() or 0)
            elsewhere_after = (book.query(func.coalesce(
                func.sum(m.StockBatch.quantity_remaining), 0))
                .filter(m.StockBatch.product_id == medicine["id"],
                        m.StockBatch.branch_id != branch.id).scalar() or 0)
            check("it came off THIS branch's shelf", int(before) - int(after) == want,
                  f"{int(before):,} to {int(after):,}")
            check("and no other branch's shelf moved",
                  int(elsewhere_before) == int(elsewhere_after),
                  f"{int(elsewhere_before):,} unchanged")

            # --- the label the box goes out with ------------------------------
            labels = http.get(f"/api/prescriptions/{script['id']}/labels")
            if check("a label can be printed", labels.status_code == 200, labels.text[:120]):
                first = (labels.json() or [{}])[0]
                check("the label names the medicine in full",
                      medicine["name"].split()[0].lower() in
                      (first.get("product_name") or "").lower(),
                      (first.get("product_name") or "")[:52])
                for field, what in (("patient_name", "the patient's name"),
                                    ("dosage_instructions", "the directions"),
                                    ("rx_number", "the script number"),
                                    ("pharmacy_name", "the pharmacy"),
                                    ("dispensed_by", "who dispensed it"),
                                    ("expiry_date", "the expiry"),
                                    ("batch_number", "the batch")):
                    check(f"the label carries {what}", bool(first.get(field)),
                          str(first.get(field))[:46])
                check("the label says which box of how many",
                      first.get("item_count", 0) >= 1,
                      f"{first.get('item_number')} of {first.get('item_count')}")

            # --- the till settles it ------------------------------------------
            read_back = http.get(f"/api/pos/sales/{sale['id']}")
            if check("the till can read the dispensing back",
                     read_back.status_code == 200, read_back.text[:120]):
                check("…and the privacy choice reached the till unaided",
                      read_back.json().get("receipt_private") is True,
                      str(read_back.json().get("receipt_private")))
            paid = http.post(f"/api/pos/sales/{sale['id']}/pay", json={
                "payment_method": "cash", "amount_tendered": float(sale["total"]) + 20})
            check("the till takes the payment", paid.status_code == 200, paid.text[:160])

            # --- a walk-in sale at the same till -------------------------------
            # Something else off this shelf, in date: the script above may have
            # taken the last of the first medicine, and a till that refuses to
            # sell what is not there is the till working.
            book.expire_all()
            over_counter = (book.query(m.Product).join(
                m.StockBatch, m.StockBatch.product_id == m.Product.id)
                .filter(m.Product.pharmacy_id == args.pharmacy,
                        m.Product.active.is_(True), m.Product.id != medicine["id"],
                        m.StockBatch.branch_id == branch.id,
                        m.StockBatch.quantity_remaining >= 20,
                        m.StockBatch.expiry_date >= date.today()).first())
            if over_counter is None:
                # Which is the ordinary case on an opening count: the shelf is
                # real and not one box on it has a date recorded yet. The till
                # has to be able to ask, exactly as the dispensary does.
                over_counter = (book.query(m.Product).join(
                    m.StockBatch, m.StockBatch.product_id == m.Product.id)
                    .filter(m.Product.pharmacy_id == args.pharmacy,
                            m.Product.active.is_(True), m.Product.id != medicine["id"],
                            m.StockBatch.branch_id == branch.id,
                            m.StockBatch.quantity_remaining >= 20,
                            m.StockBatch.expiry_date.is_(None)).first())
            if over_counter is None:
                check("the till has something on this shelf to sell", False, "nothing")
            else:
                asks = http.post("/api/pos/expiry-needed", json={
                    "lines": [{"product_id": over_counter.id, "quantity": 1}]})
                check("the till asks for the pack date while the box is in hand",
                      asks.status_code == 200, f"{asks.status_code} {asks.text[:90]}")
                till_body = {"items": [{"product_id": over_counter.id, "quantity": 1}],
                             "payment_method": "cash", "amount_tendered": 500}
                if asks.status_code == 200 and asks.json():
                    print(f"    the till wants a date for "
                          f"{asks.json()[0]['name'][:38]}")
                    blind = http.post("/api/pos/sales", json=till_body)
                    check("…and will not sell undated stock without it",
                          blind.status_code >= 400,
                          f"{blind.status_code} {blind.text[:90]}")
                    till_body["pack_expiries"] = {
                        str(over_counter.id): (date.today() + timedelta(days=400)).isoformat()}
                counter = http.post("/api/pos/sales", json=till_body)
                check("a walk-in sale rings up at this till",
                      counter.status_code in (200, 201), counter.text[:200])

            # --- the queues the shop works from --------------------------------
            for path, what in (("/api/prescriptions/table?limit=5", "the scripts page loads"),
                               ("/api/dispensing/will-call", "the to-follow queue loads"),
                               ("/api/dispensary/worklist", "the worklist loads"),
                               ("/api/dispensing/history?limit=5", "the history loads")):
                r = http.get(path)
                check(what, r.status_code == 200, f"{r.status_code} {r.text[:80]}")

            # --- what a scheme would be billed ----------------------------------
            aid = book.query(m.MedicalAid).order_by(m.MedicalAid.id).first()
            if aid:
                codes = http.post("/api/scheme-codes", json={
                    "medical_aid_id": aid.id, "product_ids": [medicine["id"]]})
                if check(f"{aid.name} codes can be read", codes.status_code == 200,
                         codes.text[:120]):
                    got = (codes.json().get("codes") or [{}])[0]
                    print(f"    {aid.name} code: {got.get('code') or 'none'} "
                          f"({got.get('origin')})")
                est = http.post("/api/claim-estimate", json={
                    "medical_aid_id": aid.id,
                    "items": [{"product_id": medicine["id"], "quantity": want}]})
                check("a claim can be estimated before it is sent",
                      est.status_code == 200, est.text[:140])
finally:
    http.headers.pop("Authorization", None)
    book.close()
    outer.rollback()
    connection.close()

print("\n" + ("=" * 62))
if notes:
    print("\nworth knowing:")
    for n in notes:
        print(f"  - {n}")
print(f"\n{len(fails)} check(s) failed" if fails else "\nevery check passed")
for f in fails:
    print(f"    {f}")
print("nothing was committed: the whole rehearsal was rolled back.")
sys.exit(1 if fails else 0)
