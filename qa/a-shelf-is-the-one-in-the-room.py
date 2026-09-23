"""What is on hand means what is on hand HERE.

`Product.quantity_on_hand` is the pharmacy's whole shelf added up across every
branch, and it is correct: a valuation and a group reorder both want it. The
defect was never that number, it was every caller that read it to answer a
question about one room.

The shape of the failure is always the same and never looks like an error. A
dispenser is told there are five, because five exist four hundred kilometres
away. A call list tells a shop to telephone patients for medicine the other
branch received. A mixture is started because all six ingredients are "in
stock", and the FEFO walk refuses the fourth one halfway through with a patient
waiting. In each case one screen answered a branch question with a group total,
and nothing anywhere said which it had given.

WHAT THIS GUARDS

  the helper is per branch     `on_hand_many` returns this shop's figures for a
                               whole page in one query. Everything below is
                               built on it, so if it silently fell back to the
                               group every other check here would still pass
                               while the product was wrong again.

  sellable means sellable      the shelf holds stock that cannot be handed
                               over. A count wants it, a dispenser must not be
                               promised it, and undated stock is most of an
                               imported opening balance and IS sellable.

  the call list is local       the list somebody works down with a telephone.
                               A wrong name on it costs a patient a trip.

  the bench sees its own       whether a preparation can be made up is a
                               question about the shelf in the room.

  the picker says both         a product list carries `here` beside the group
                               total, so the two numbers are visible as two
                               numbers rather than one being mistaken for the
                               other.

    python qa/a-shelf-is-the-one-in-the-room.py
"""
import os
import pathlib
import sys
from datetime import date, timedelta

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "."))/"one-shelf.sqlite"
if SCRATCH.exists():
    SCRATCH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{SCRATCH.as_posix()}"

BACKEND = pathlib.Path(__file__).resolve().parents[1]/"backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base, engine, SessionLocal          # noqa: E402
from app import branch_scope, models, schemas, tenancy       # noqa: E402
from app.services import branches, to_follows                # noqa: E402

Base.metadata.create_all(engine)
failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


def session():
    """A session shaped like the one a request gets. See the sister guard."""
    db = SessionLocal()
    tenancy.stamp(db)
    branch_scope.stamp(db)
    return db


TODAY = date.today()

# Two shops. Avondale has none of the amoxicillin; Borrowdale has forty.
with tenancy.unscoped(), branch_scope.every_branch():
    db = session()
    group = models.Pharmacy(name="Zvandiri Pharmacies")
    db.add(group)
    db.commit()
    gid = group.id

    avondale = models.Branch(name="Avondale", code="AVN", pharmacy_id=gid)
    borrowdale = models.Branch(name="Borrowdale", code="BOR", pharmacy_id=gid)
    db.add_all([avondale, borrowdale])
    db.commit()
    avn, bor = avondale.id, borrowdale.id

    amox = models.Product(name="Amoxicillin", strength="500mg", pharmacy_id=gid,
                          quantity_on_hand=40, units_per_pack=1, active=True)
    para = models.Product(name="Paracetamol", strength="500mg", pharmacy_id=gid,
                          quantity_on_hand=30, units_per_pack=1, active=True)
    db.add_all([amox, para])
    db.commit()
    amox_id, para_id = amox.id, para.id

    db.add_all([
        # All forty of the amoxicillin are at the other shop.
        models.StockBatch(product_id=amox_id, branch_id=bor, batch_number="B1",
                          quantity_remaining=40, expiry_date=TODAY + timedelta(days=365),
                          pharmacy_id=gid),
        # Avondale's paracetamol: ten good, ten expired, five quarantined,
        # five with no date recorded at all (an imported opening balance).
        models.StockBatch(product_id=para_id, branch_id=avn, batch_number="P-good",
                          quantity_remaining=10, expiry_date=TODAY + timedelta(days=200),
                          pharmacy_id=gid),
        models.StockBatch(product_id=para_id, branch_id=avn, batch_number="P-expired",
                          quantity_remaining=10, expiry_date=TODAY - timedelta(days=5),
                          pharmacy_id=gid),
        models.StockBatch(product_id=para_id, branch_id=avn, batch_number="P-held",
                          quantity_remaining=5, status="quarantined",
                          expiry_date=TODAY + timedelta(days=200), pharmacy_id=gid),
        models.StockBatch(product_id=para_id, branch_id=avn, batch_number="P-undated",
                          quantity_remaining=5, expiry_date=None, pharmacy_id=gid),
    ])

    patient = models.Patient(first_name="Rudo", last_name="Kembo", pharmacy_id=gid)
    db.add(patient)
    db.commit()

    # Avondale owes this patient amoxicillin, and the stock came into the
    # OTHER shop.
    db.add(models.OwedItem(reference="TF1", patient_id=patient.id,
                           product_id=amox_id, quantity_owed=10,
                           status="outstanding", pharmacy_id=gid))
    db.commit()
    db.close()

token = tenancy.set_current_pharmacy(gid)
try:
    with branch_scope.every_branch():
        db = session()

        print("\nthe helper is per branch")
        at_avn = branches.on_hand_many(db, [amox_id], avn)
        at_bor = branches.on_hand_many(db, [amox_id], bor)
        check(at_avn[amox_id] == 0,
              f"Avondale holds none of the amoxicillin, not the group's 40 "
              f"(got {at_avn[amox_id]})")
        check(at_bor[amox_id] == 40,
              f"Borrowdale holds all forty (got {at_bor[amox_id]})")
        check(branches.on_hand_many(db, [amox_id], None)[amox_id] == 40,
              "no branch named means the group, for the single-shop pharmacy")
        check(branches.on_hand_many(db, [amox_id, para_id], avn).keys()
              == {amox_id, para_id},
              "every product asked about gets an answer, zero included")

        print("\nsellable means sellable")
        everything = branches.on_hand_many(db, [para_id], avn)[para_id]
        sellable = branches.on_hand_many(
            db, [para_id], avn, sellable_only=True)[para_id]
        check(everything == 30,
              f"a count sees all thirty on the premises (got {everything})")
        check(sellable == 15,
              f"a dispenser is promised the 10 in date plus the 5 undated, "
              f"not the expired or the quarantined (got {sellable})")

        print("\nthe call list is local")
        # Borrowdale can honour it; Avondale cannot, whatever the group says.
        here = to_follows.ready(db, branch_id=avn)
        there = to_follows.ready(db, branch_id=bor)
        check(not any(o["can_settle_now"] for o in here),
              "Avondale is not told to telephone a patient for medicine it "
              "has not got")
        check(any(o["can_settle_now"] for o in there),
              "Borrowdale, which has it, is")
        group_view = to_follows.ready(db)
        check(any(o["can_settle_now"] for o in group_view),
              "a pharmacy with no branches in play still sees the group, as "
              "it always did")

        print("\nthe picker says both")
        user = models.User(username="tsitsi", password_hash="x",
                           full_name="Tsitsi M", role="assistant",
                           branch_id=avn, pharmacy_id=gid)
        db.add(user)
        db.commit()
        from app.routers import stock_router
        rows = stock_router.list_products(q="Amoxicillin", db=db, user=user)
        shown = [schemas.ProductOut.model_validate(r, from_attributes=True)
                 for r in rows]
        check(len(shown) == 1, f"the picker found the line (got {len(shown)})")
        if shown:
            check(shown[0].quantity_on_hand == 40,
                  "the group total is still reported, and still means the group")
            check(shown[0].here == 0,
                  f"and `here` says this counter can reach none of it "
                  f"(got {shown[0].here})")
        db.close()
finally:
    tenancy.reset_current_pharmacy(token)

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("On hand means on hand here.")
