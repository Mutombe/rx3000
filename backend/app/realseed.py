"""Replace the placeholder data with a working Zimbabwean pharmacy.

What was there before was scaffolding that outlived its purpose: 545 products
called "AMOX Probe 3BB7B2", 150 patients called Test Sweep, 7,000 messages whose
body was "Sweep test message", and four South African medical aid schemes in a
product sold in Harare. It demonstrated that the screens render. It could not be
shown to anybody.

This builds the alternative from `zimdata`, whose distributions come from two
months of real trading. Run it with:

    python -m app.realseed              # replace the placeholder rows
    python -m app.realseed --wipe-all   # start the transactional history over

It is **idempotent on the reference data** — schemes, catalogue, prescribers,
suppliers are matched by name and updated rather than duplicated — and it will
not run twice over the transactional history unless asked, because two months of
sales seeded twice is a takings chart that has quietly doubled.
"""
from __future__ import annotations

import argparse
import calendar
import collections
import random
import re
import sys
from datetime import date, datetime, timedelta

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from . import auth, zimdata
from .config import settings
from .database import SessionLocal
from .models import (
    Campaign, Claim, Deal, Dispensing, Doctor, JournalEntry, LayBy, LayByItem,
    LayByPayment,
    Lead, MedicalAid, Message, OwedItem, Patient, Prescription,
    PrescriptionItem,
    Product, PurchaseOrder, PurchaseOrderItem, RegisterEntry, Remittance,
    Sale, SaleItem,
    Shift, StockBatch, Supplier, SupplierInvoice, SupplierInvoiceItem,
    SupplierPayment, SupplierPaymentAllocation, User,
)

# A fixed seed, so two people running this get the same pharmacy and can talk
# about "the Chirenje script" and mean the same one.
RNG = random.Random(57)

#: Rows the earlier scaffolding left behind, matched by the shape of their names.
#:
#: Every one of these is a fixture named after the behaviour it was written to
#: exercise: 99 copies of "FEFO Expired Only" for the first-expiry-first-out
#: draw, 99 of "FEFO Test Syrup", a hundred "CLAIMLATER Cream 0B3406" for the
#: deferred-claim path, and 215 "AMOX Probe 3BB7B2" for the catalogue. Useful
#: while they were being written; indistinguishable from stock once they are on
#: the inventory screen.
PLACEHOLDER_PRODUCTS = [
    "%Probe%", "FEFO %", "CLAIMLATER%", "%Sweep%", "Test %", "%Fixture%",
    "LEDGER %", "Unnamed product%",
    # South African airtime in a Zimbabwean pharmacy, priced in rand. Replaced
    # by Econet and NetOne vouchers in the catalogue.
    "Vodacom Airtime%", "MTN Airtime%", "Telkom Airtime%",
]
#: Test patients, by the shape of the names the fixtures gave them: "Allergy
#: Probe 66B5C7", "Crud Updated 634712", "Test Sweep". Matched on both halves of
#: the name, because a first name of "Allergy" is as much a fixture as a surname
#: ending in six hex digits.
PLACEHOLDER_PATIENTS = [
    ("last_name", "Sweep"),
    ("last_name", "Updated%"),
    ("first_name", "Crud"),
    ("first_name", "Allergy"),
    ("first_name", "Test"),
    ("last_name", "Probe%"),
]
PLACEHOLDER_PATIENT = "Sweep"

#: Schemes from the wrong country. Discovery, Bonitas, GEMS and Momentum are
#: South African, and a Zimbabwean pharmacist reading that list decides in about
#: two seconds that this product was not built for them.
FOREIGN_SCHEMES = ["Discovery Health", "Bonitas", "GEMS", "Momentum Health"]


def _delete_where_in(db: Session, table: str, column: str, ids: list[int]) -> int:
    """Delete rows pointing at any of `ids`, tolerating a table this build lacks.

    Raw SQL rather than the ORM because several of these tables have no mapped
    class in this module and importing nine more models to delete from them would
    couple a data script to the whole schema. Chunked at 400 because SQLite caps
    the number of bound parameters in one statement, and a wipe that works on a
    small database and fails on a full one is worse than one that never worked.
    """
    if not ids:
        return 0
    removed = 0
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        marks = ",".join(":p%d" % j for j in range(len(chunk)))
        params = {("p%d" % j): v for j, v in enumerate(chunk)}
        try:
            removed += db.execute(
                text(f"DELETE FROM {table} WHERE {column} IN ({marks})"), params
            ).rowcount
            db.commit()
        except Exception:  # noqa: BLE001 - the table or column is not in this build
            db.rollback()
            return removed
    return removed


def _clear_placeholders(db: Session) -> dict[str, int]:
    """Remove the scaffolding, and everything hanging off it.

    Order matters: a sale item points at a product and a sale, and SQLite will
    not enforce that for us here. Children first, or the catalogue is left with
    orphan lines that render as a blank description and a real price.
    """
    counts: dict[str, int] = {}

    probe_ids: list[int] = []
    for pattern in PLACEHOLDER_PRODUCTS:
        probe_ids.extend(p.id for p in db.query(Product)
                                         .filter(Product.name.like(pattern)).all())
    # A catalogue entry and an older bare row of the same name are the same
    # medicine listed twice; the one with no strength or pack is the older.
    catalogue_names = {name for name, *_ in zimdata.CATALOGUE}
    probe_ids.extend(
        p.id for p in db.query(Product).filter(Product.name.in_(catalogue_names)).all()
        if not (p.strength or "").strip() and not (p.pack_size or "").strip()
    )
    # A hex suffix on a real medicine name is a fixture too: three copies of
    # "Warfarin Sodium BC8A73" exist so an interaction test had something
    # unambiguous to point at, and on the inventory screen they read as stock.
    #
    # Matched with a regex rather than a LIKE. `% ______` was tried first and
    # would also have taken Aspirin Cardio, Glucometer Strips and Surgical
    # Spirit — three real products whose names happen to end in six characters
    # after a space. A pattern loose enough to catch the fixtures was loose
    # enough to delete the catalogue.
    hex_suffix = re.compile(r"\s[0-9A-F]{6}$")
    probe_ids.extend(
        p.id for p in db.query(Product).all()
        if p.name and hex_suffix.search(p.name)
    )
    probe_ids = sorted(set(probe_ids))
    sweep_ids: list[int] = []
    for field, pattern in PLACEHOLDER_PATIENTS:
        column = getattr(Patient, field)
        query = (db.query(Patient).filter(column.like(pattern))
                 if "%" in pattern else
                 db.query(Patient).filter(column == pattern))
        sweep_ids.extend(p.id for p in query.all())
    sweep_ids = sorted(set(sweep_ids))

    if sweep_ids:
        counts["messages"] = (db.query(Message)
                                .filter(Message.patient_id.in_(sweep_ids))
                                .delete(synchronize_session=False))
        rx_ids = [r.id for r in db.query(Prescription)
                                  .filter(Prescription.patient_id.in_(sweep_ids)).all()]
        if rx_ids:
            item_ids = [i[0] for i in db.query(PrescriptionItem.id)
                                        .filter(PrescriptionItem.prescription_id.in_(rx_ids)).all()]
            # Four tables point at a prescription item, and each of them is a
            # record of something that happened: a dispensing, a register entry,
            # an amendment, a to-follow. They go first.
            for table, column in [("dispensings", "prescription_item_id"),
                                  ("register_entries", "prescription_item_id"),
                                  ("owed_items", "prescription_item_id"),
                                  ("script_changes", "prescription_item_id")]:
                _delete_where_in(db, table, column, item_ids)
            for table, column in [("script_changes", "prescription_id"),
                                  ("reprints", "prescription_id"),
                                  ("waybills", "prescription_id"),
                                  ("message_acknowledgements", "prescription_id")]:
                _delete_where_in(db, table, column, rx_ids)
            db.query(PrescriptionItem).filter(
                PrescriptionItem.prescription_id.in_(rx_ids)
            ).delete(synchronize_session=False)
            counts["prescriptions"] = db.query(Prescription).filter(
                Prescription.id.in_(rx_ids)
            ).delete(synchronize_session=False)
        sale_ids = [s.id for s in db.query(Sale)
                                    .filter(Sale.patient_id.in_(sweep_ids)).all()]
        if sale_ids:
            item_ids = [i[0] for i in db.query(SaleItem.id)
                                        .filter(SaleItem.sale_id.in_(sale_ids)).all()]
            _delete_where_in(db, "batch_allocations", "sale_item_id", item_ids)
            for table in ["claims", "dispensings", "fiscal_receipts", "laybys",
                          "otc_sales", "owed_items", "reprints", "waybills",
                          "sale_tenders"]:
                _delete_where_in(db, table, "sale_id", sale_ids)
            db.query(SaleItem).filter(SaleItem.sale_id.in_(sale_ids)).delete(synchronize_session=False)
            counts["sales"] = db.query(Sale).filter(Sale.id.in_(sale_ids)).delete(synchronize_session=False)
        # Twelve tables point at a patient, and each is a record of something
        # that happened to them. They go first, or the delete fails on a
        # constraint and takes the whole clear with it.
        # A lay-by has payments and items of its own, so it is not a leaf: its
        # children go before it does, or the delete fails on a constraint and
        # takes the whole clear with it. One lay-by belonging to one fixture
        # patient blocked all thirty-five.
        layby_ids = [r[0] for r in db.query(LayBy.id)
                                     .filter(LayBy.patient_id.in_(sweep_ids)).all()]
        _delete_where_in(db, "layby_payments", "layby_id", layby_ids)
        _delete_where_in(db, "layby_items", "layby_id", layby_ids)
        _delete_where_in(db, "laybys", "id", layby_ids)

        for table in ["activities", "authorisations", "claims", "contacts",
                      "messages", "otc_sales", "owed_items",
                      "register_entries", "tickets", "waybills",
                      "message_acknowledgements", "dispensings"]:
            _delete_where_in(db, table, "patient_id", sweep_ids)
        counts["patients"] = db.query(Patient).filter(
            Patient.id.in_(sweep_ids)
        ).delete(synchronize_session=False)

    if probe_ids:
        # Sixteen tables point at a product. Each one is a fact about that
        # product — a batch received, a movement, a barcode, a formulary listing,
        # a line on somebody's order — and all of them have to go before the
        # product itself can. The list came out of the schema rather than out of
        # memory; the first version of this remembered two of the sixteen.
        line_ids = [i[0] for i in db.query(SaleItem.id)
                                    .filter(SaleItem.product_id.in_(probe_ids)).all()]
        _delete_where_in(db, "batch_allocations", "sale_item_id", line_ids)
        db.query(SaleItem).filter(SaleItem.product_id.in_(probe_ids)).delete(synchronize_session=False)

        rx_line_ids = [i[0] for i in db.query(PrescriptionItem.id)
                                       .filter(PrescriptionItem.product_id.in_(probe_ids)).all()]
        for table, column in [("dispensings", "prescription_item_id"),
                              ("register_entries", "prescription_item_id"),
                              ("owed_items", "prescription_item_id"),
                              ("script_changes", "prescription_item_id")]:
            _delete_where_in(db, table, column, rx_line_ids)
        db.query(PrescriptionItem).filter(
            PrescriptionItem.product_id.in_(probe_ids)
        ).delete(synchronize_session=False)

        batch_ids = [r[0] for r in db.execute(text(
            "SELECT id FROM stock_batches WHERE product_id IN ("
            + ",".join(str(int(i)) for i in probe_ids) + ")")).fetchall()] if probe_ids else []
        _delete_where_in(db, "batch_allocations", "batch_id", batch_ids)

        for table in ["authorisations", "branch_transfers", "deal_items",
                      "formulary_entries", "layby_items", "mixture_ingredients",
                      "otc_sales", "product_barcodes", "purchase_order_items",
                      "register_entries", "stock_batches", "stock_movements",
                      "stock_take_lines", "owed_items"]:
            _delete_where_in(db, table, "product_id", probe_ids)

        counts["products"] = db.query(Product).filter(
            Product.id.in_(probe_ids)
        ).delete(synchronize_session=False)

    # The wrong country's schemes, and any patient still pointing at one.
    foreign = db.query(MedicalAid).filter(MedicalAid.name.in_(FOREIGN_SCHEMES)).all()
    if foreign:
        ids = [m.id for m in foreign]
        db.query(Patient).filter(Patient.medical_aid_id.in_(ids)).update(
            {Patient.medical_aid_id: None, Patient.medical_aid_number: None},
            synchronize_session=False)
        for table in ["claims", "authorisations", "formulary_entries",
                      "scheme_products", "scheme_rules"]:
            _delete_where_in(db, table, "medical_aid_id", ids)
        counts["foreign schemes"] = db.query(MedicalAid).filter(
            MedicalAid.id.in_(ids)
        ).delete(synchronize_session=False)

    # Any message still carrying the test copy, whoever it belongs to.
    counts["test messages"] = (db.query(Message)
                                 .filter(Message.body.like("%Sweep test%"))
                                 .delete(synchronize_session=False))

    # Branches, last, and only the ones nothing points at.
    #
    # Products and patients have been cleaned of their fixtures from the
    # beginning; branches never were. Two called "Crud Branch 634712" and "Crud
    # Branch 2971BC" sat there until they turned up on the owner's own
    # dashboard, in the table comparing how each shop is trading. A branch
    # reaches more screens than either of the others — every scorecard, every
    # transfer, every cash-up.
    #
    # A branch that has taken a sale or held a batch is real however it was
    # named, so only orphans go.
    from .models import Branch
    branch_ids: list[int] = []
    for pattern in PLACEHOLDER_BRANCHES:
        branch_ids.extend(b.id for b in db.query(Branch)
                          .filter(Branch.name.like(pattern)).all())
    orphans = []
    for bid in sorted(set(branch_ids)):
        used = False
        for table in ("sales", "stock_batches", "shifts", "branch_transfers"):
            try:
                if db.execute(text(
                        f"SELECT 1 FROM {table} WHERE branch_id = :b LIMIT 1"),
                        {"b": bid}).first():
                    used = True
                    break
            except Exception:                      # noqa: BLE001 - table absent
                continue
        if not used:
            orphans.append(bid)
    if orphans:
        counts["test branches"] = _delete_where_in(db, "branches", "id", orphans)

    db.commit()
    return {k: v for k, v in counts.items() if v}


#: (claims in by, funder settles on) — day of the month, as the memoranda are
#: written. Spread deliberately: a pharmacy with six funders on the same date
#: has one impossible week a month, and the real ones are not aligned.
AGREEMENTS = {
    "CIMAS": (25, 15),
    "FMH": (20, 10),
    "FMHZWA": (20, 10),
    "ALLIANCE": (15, 28),
    "BONVIE": (25, 20),
    "FBC": (30, 21),
    "FLIMAS": (15, 5),
    "FMGU": (25, 12),
    "PSMAS": (10, 30),
    "NYAR": (20, 18),
    "AHSSZWA": (28, 14),
}


def _schemes(db: Session) -> list[MedicalAid]:
    """The schemes that turn up on a Harare counter, matched by name."""
    out = []
    for name, code, currency, levy, _note in zimdata.SCHEMES:
        row = db.query(MedicalAid).filter(MedicalAid.name == name).first()
        if not row:
            row = MedicalAid(name=name)
            db.add(row)
        row.scheme_code = code
        row.currency_code = currency
        row.levy_percent = levy
        row.active = True
        # CIMAS wants a fingerprint at the counter. Saying so in the data is the
        # difference between a demo that surprises a pharmacist and one that
        # makes them nod.
        row.biometric_required = code in {"CIMAS", "FMH"}

        # The claiming agreement, which every pharmacy has and none of them
        # keeps anywhere a system can read. The dates below are the ordinary
        # shape of one: claims in by the middle or the end of the month, money
        # back two to six weeks later. A realtime scheme settles continuously
        # and has no cut-off at all, which is exactly why it is worth showing
        # the difference on a screen rather than assuming every funder is the
        # same.
        if not row.claim_cutoff_day and not row.settlement_days:
            if row.realtime:
                row.settlement_days = 7
            else:
                agreed = AGREEMENTS.get(code)
                if agreed:
                    row.claim_cutoff_day, row.settlement_day = agreed
                    row.agreement_reference = f"MOU-{code}-2026"
        out.append(row)
    db.commit()
    return out


def _catalogue(db: Session) -> list[Product]:
    """The medicines, matched on name plus strength so two Amlodipine rows of
    different strengths stay two rows."""
    out = []
    for name, form, strength, pack, schedule, price, cost, category in zimdata.CATALOGUE:
        row = (db.query(Product)
                 .filter(Product.name == name, Product.strength == strength)
                 .first())
        if not row:
            row = Product(name=name, strength=strength)
            db.add(row)
        row.dosage_form = form
        row.pack_size = pack
        row.schedule = schedule
        row.unit_price = price
        row.cost_price = cost
        row.category = category
        # What is actually in the box. The interaction checker falls back to the
        # product name, which carries a generic and misses every brand, so the
        # ingredient is stated wherever the name does not already say it.
        row.active_ingredient = zimdata.ACTIVE_INGREDIENTS.get(name, name.lower())
        # A fraction, not a percentage.
        #
        # The till computes `line_total / (1 + product.vat_rate)`, so 15% is
        # 0.15 here. Written as 15.0 it divides by sixteen, and every VAT figure
        # in the system is wrong by two orders of magnitude — silently, because
        # nothing validates a tax rate against a plausible range.
        row.vat_rate = 0.0 if schedule >= 3 else 0.15  # prescription medicine is zero rated
        if not row.quantity_on_hand:
            # Deep enough to sell from, shallow enough that the reorder screen
            # has something real on it.
            row.quantity_on_hand = RNG.randint(0, 240)
        if not row.reorder_level:
            row.reorder_level = RNG.choice([20, 30, 40, 50])
        out.append(row)
    db.commit()
    return out


def _people(db: Session, schemes: list[MedicalAid], target: int) -> list[Patient]:
    """Patients, recombined from the name pool. No real person is reproduced."""
    have = db.query(Patient).count()
    need = max(0, target - have)
    made = []
    used: set[tuple[str, str]] = set()
    for _ in range(need * 3):
        if len(made) >= need:
            break
        first = RNG.choice(zimdata.GIVEN_NAMES)
        last = RNG.choice(zimdata.SURNAMES)
        if (first, last) in used:
            continue
        used.add((first, last))

        born = date(RNG.randint(1945, 2022), RNG.randint(1, 12), RNG.randint(1, 28))
        # Roughly a third of the counter is on a scheme; the claim summary put
        # 396 of 434 scripts on private cash, and the walk-in trade is larger
        # still. A demo where everybody has medical aid hides the whole problem.
        scheme = RNG.choice(schemes) if RNG.random() < 0.30 else None

        p = Patient(
            first_name=first,
            last_name=last,
            date_of_birth=born,
            # Zimbabwean national ID: 63-123456-K-42.
            id_number=f"{RNG.randint(1, 86):02d}-{RNG.randint(100000, 999999)}"
                      f"-{RNG.choice('ABCDEFGHJKLMNPQRSTVWXY')}-{RNG.randint(0, 89):02d}",
            phone=f"07{RNG.choice('1378')}{RNG.randint(1000000, 9999999)}",
            address=f"{RNG.randint(1, 240)} {RNG.choice(['Samora Machel Ave', 'Second Street', 'Josiah Chinamano Ave', 'Nelson Mandela Ave', 'Rekayi Tangwena Ave', 'Chiremba Road', 'Seke Road'])}, "
                    f"{RNG.choice(['Harare', 'Chitungwiza', 'Norton', 'Ruwa', 'Epworth'])}",
            medical_aid_id=scheme.id if scheme else None,
            # Generated. The real member numbers stay where they are.
            medical_aid_number=(f"{RNG.randint(10000000, 99999999)}" if scheme else None),
            dependent_code=(str(RNG.randint(0, 4)) if scheme else None),
            loyalty_points=RNG.choice([0, 0, 0, 5, 12, 40, 92, 150]),
        )
        age = (date.today() - born).days // 365
        if age > 38 and RNG.random() < 0.42:
            p.chronic_conditions = ", ".join(
                RNG.sample(zimdata.CHRONIC_CONDITIONS, RNG.choice([1, 1, 2])))
        if RNG.random() < 0.12:
            p.allergies = RNG.choice(zimdata.ALLERGIES)
        db.add(p)
        made.append(p)
    db.commit()
    return made


def _staff(db: Session) -> list[User]:
    """The people on the invoices, with the roles they rang up under.

    Two of them took 3,906 of 5,056 invoices between them, which is what a real
    roster looks like: two people carry the counter and everybody else covers
    around them. A demo where six identically-busy staff share the day evenly is
    a demo nobody recognises.

    Everybody gets the same starter password, said out loud on the sign-in
    screen. This is seed data for a demonstration, not an account anybody keeps.
    """
    out = []
    for username, full_name, role in zimdata.STAFF:
        row = db.query(User).filter(User.username == username).first()
        if not row:
            row = User(username=username, password_hash=auth.hash_password("rx5000staff"))
            db.add(row)
        row.full_name = full_name
        row.role = role
        row.active = True
        row.is_demo = False
        out.append(row)
    db.commit()
    return out


def _retire_expired_demos(db: Session) -> int:
    """Deactivate demo accounts whose four hours are up.

    Deactivated rather than deleted: what somebody entered during a demo is kept,
    and their name is on the sales and scripts they made. Deleting the user would
    orphan those rows or, worse, silently reassign them.
    """
    now = datetime.now()
    rows = (db.query(User)
              .filter(User.is_demo.is_(True), User.active.is_(True),
                      User.demo_expires_at.isnot(None),
                      User.demo_expires_at <= now)
              .all())
    for row in rows:
        row.active = False
    db.commit()
    return len(rows)


def _prescribers(db: Session) -> list[Doctor]:
    out = []
    for name, practice, phone in zimdata.DOCTORS:
        row = db.query(Doctor).filter(Doctor.name == name).first()
        if not row:
            row = Doctor(name=name)
            db.add(row)
        row.practice_number = practice
        row.phone = phone
        out.append(row)
    db.commit()
    return out


def _branch(db: Session) -> None:
    """Give the shop an address and a telephone number.

    `default_branch` creates a placeholder called "Main branch" with neither,
    because it exists to satisfy a foreign key rather than to describe a
    pharmacy. That placeholder is what the dispensing label prints at the foot,
    so every sticker went out with a name and two blank lines where the address
    and the number should be — which on a real label is the part a patient uses
    to ring back about their medicine.
    """
    from .services import branches

    branch = branches.default_branch(db)
    changed = False
    # "Main branch" is the placeholder `default_branch` invents to satisfy a
    # foreign key. It is not a pharmacy's name, and it is what the label footer
    # prints, so the demo replaces it — a real one that has been named is left
    # alone by the blank check below.
    if (branch.name or "").strip() in ("", "Main branch"):
        branch.name = zimdata.PHARMACY["trading_name"]
        changed = True
    for field, value in (
        ("name", zimdata.PHARMACY["trading_name"]),
        ("address", zimdata.PHARMACY["address"]),
        ("phone", zimdata.PHARMACY["phone"]),
        ("registration_no", zimdata.PHARMACY["licence"]),
        ("city", "Harare"),
    ):
        if not (getattr(branch, field, "") or "").strip():
            setattr(branch, field, value)
            changed = True
    if changed:
        db.commit()


def _suppliers(db: Session) -> None:
    for name, contact, phone, email in zimdata.SUPPLIERS:
        row = db.query(Supplier).filter(Supplier.name == name).first()
        if not row:
            row = Supplier(name=name)
            db.add(row)
        row.contact_person = contact
        row.phone = phone
        row.email = email
    db.commit()


def _basket_value() -> float:
    """A basket, sampled from the shape the real ones have.

    Log-normal around a $5.00 median, which reproduces the measured mean of
    $7.84 and ninetieth percentile of $18 — a long thin tail of large baskets
    over a floor of one- and two-dollar sales. A uniform range between two
    numbers gives a takings chart a flat top that no counter has ever produced.
    """
    v = RNG.lognormvariate(0, zimdata.BASKET_SIGMA) * zimdata.BASKET_MEDIAN
    return round(min(max(v, 0.50), 299.00), 2)


def _hour() -> int:
    """An hour of the day, weighted the way the counter actually trades."""
    hours = [h for h, _ in zimdata.HOURLY_SHARE]
    weights = [w for _, w in zimdata.HOURLY_SHARE]
    return RNG.choices(hours, weights=weights)[0]


def _trading(db: Session, days: int, products: list[Product],
             patients: list[Patient], cashiers: list[User]) -> int:
    """Fill in the last `days` days of counter trade."""
    if not products or not cashiers:
        return 0

    # Weighted so the front-shop staples move like staples. A catalogue where
    # every line sells equally makes the top-sellers report meaningless, which is
    # one of the reports a pharmacy owner opens first.
    staples = set(zimdata.STAPLES)
    weights = [
        # Named staples first, then the cheap front shop, then everything else.
        # A flat catalogue makes the top-sellers report meaningless, and that is
        # one of the two reports a pharmacy owner opens first.
        # ORS is damped rather than excluded: at fifty cents it is the only
        # line that fits a one-dollar basket, so left alone it wins every one of
        # them and finishes as the top seller by a factor of four.
        0.6 if p.name == "Oral Rehydration Salts" else
        14.0 if p.name in staples else
        4.0 if (p.schedule or 0) <= 2 and (p.unit_price or 0) < 6 else
        2.5 if (p.schedule or 0) <= 2 else
        1.5 if (p.unit_price or 0) < 8 else 1.0
        for p in products
    ]

    made = 0
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # Carry on from the highest number actually in use, whatever its prefix.
    #
    # The first version split on "-" and fell back to a constant when there was
    # no dash — and every number here is INV111696, with no dash — so a second
    # run started again at the first number and collided on the unique index
    # partway through. Reading the digits off the end works for any prefix, and
    # the max is taken rather than the last row's, because ids and numbers do not
    # have to agree.
    seq = 111696
    for (number,) in db.query(Sale.sale_number).all():
        digits = re.findall(r"(\d+)$", number or "")
        if digits:
            seq = max(seq, int(digits[0]) + 1)

    # Which days already have trade, so a run that was interrupted picks up
    # where it stopped instead of starting again or doubling what is there.
    # Against a remote database an hour-long seed will be interrupted; assuming
    # otherwise is how you end up with one day holding four hundred sales.
    done_days = {d for (d,) in db.query(func.date(Sale.created_at))
                                 .group_by(func.date(Sale.created_at)).all()}
    done_days = {str(d) for d in done_days}

    for back in range(days, -1, -1):
        day = start - timedelta(days=back)
        if day.date().isoformat() in done_days:
            continue
        if day.weekday() == 6:
            count = int(zimdata.SALES_PER_DAY * 0.55)   # Sunday is quieter, not shut
        elif day.weekday() == 5:
            count = int(zimdata.SALES_PER_DAY * 0.85)
        else:
            count = zimdata.SALES_PER_DAY + RNG.randint(-14, 14)

        pending: list[tuple[Sale, list]] = []
        for _ in range(count):
            when = day.replace(hour=_hour(), minute=RNG.randint(0, 59),
                               second=RNG.randint(0, 59))
            if when > datetime.now():
                continue

            target = _basket_value()
            lines, spent = [], 0.0
            # Lines are added until the basket is close to its target, rather
            # than a fixed one-to-four with whatever they happened to cost.
            #
            # Both earlier versions missed, in opposite directions. Picking a
            # line count first and ignoring the target pushed the median from the
            # measured $5.00 to $7.50, because a basket was always at least as
            # expensive as its priciest line. Then filtering to what was still
            # affordable but keeping the fixed count pulled it down to $4.00 and
            # flattened the tail, because a $60 basket cannot be reached in four
            # cheap lines. Filling toward the target fixes both: small baskets
            # stay one or two lines, large ones become the six-line collection
            # somebody makes once a month.
            for _ in range(9):
                remaining = target - spent
                if spent >= target * 0.85 or remaining <= 0.45:
                    break
                affordable = [i for i, pr in enumerate(products)
                              if 0 < (pr.unit_price or 0) <= remaining + 0.01]
                if not affordable:
                    break
                pool = [products[i] for i in affordable]
                pool_w = [weights[i] for i in affordable]
                product = RNG.choices(pool, weights=pool_w)[0]
                unit = product.unit_price or 0
                # Quantity stays small. A basket is filled by adding lines, the
                # way a counter fills one; twelve of the same cheap sachet is
                # what a generator does, not a customer, and it made oral
                # rehydration salts the top seller by a factor of four.
                qty = min(RNG.choice([1, 1, 1, 2, 2, 3]), max(1, int(remaining // unit)))
                line = round(unit * qty, 2)
                lines.append((product, qty, line))
                spent += line
            if not lines:
                continue

            total = round(spent, 2)
            # VAT out of a VAT-inclusive line, the way the till does it.
            # Prescription medicine is zero rated; the front shop is not.
            vat = round(sum(l - l / (1 + (p.vat_rate or 0)) for p, _, l in lines), 2)
            pending.append((Sale(
                sale_number=f"INV{seq}",
                patient_id=(RNG.choice(patients).id
                            if patients and RNG.random() < 0.34 else None),
                cashier_id=RNG.choice(cashiers).id,
                created_at=when,
                subtotal=round(total - vat, 2),
                vat_amount=vat,
                total=total,
                payment_method=RNG.choices(
                    ["cash", "ecocash", "card", "swipe"],
                    weights=[0.52, 0.28, 0.13, 0.07])[0],
                # "paid", not "completed".
                #
                # The vocabulary is pending / paid / void, and the till sets
                # "paid" when the money is taken. "completed" reads correctly to
                # a person and matches nothing in the code, so every takings
                # figure, every VAT return and the whole of Analytics reported
                # zero against four thousand real sales. A status column is only
                # as good as the set of values something actually queries.
                status="paid",
                currency_code="USD",
            ), lines))
            seq += 1
            made += 1

        # One flush for the day, not one per sale.
        #
        # A sale needs its id before its items can point at it, and the obvious
        # way to get it is `add` then `flush` — which against SQLite on the same
        # machine costs nothing and against Postgres over the internet is a
        # network round trip per sale. Eighty round trips a day across sixty days
        # is what turned a twelve-second seed into a two-hour one, and it was
        # invisible locally because the local database is a file.
        #
        # Flushing the whole day at once assigns every id in one exchange.
        for sale, _lines in pending:
            db.add(sale)
        db.flush()
        for sale, sale_lines in pending:
            for product, qty, line in sale_lines:
                db.add(SaleItem(
                    sale_id=sale.id, product_id=product.id,
                    description=f"{product.name} {product.strength}".strip(),
                    quantity=qty, unit_price=product.unit_price,
                    vat_rate=product.vat_rate or 0, line_total=line,
                    unit_cost=product.cost_price,
                ))
        db.commit()
    return made


def _settled_on(sold_at, status):
    """When a claim was paid, or None if it has not been.

    A settlement date is a fixed number of days after the sale, which for a
    script dispensed last week lands next month. A remittance dated in the
    future is the kind of detail that ends a demonstration, so a claim whose
    money has not arrived yet is simply not settled.
    """
    if status not in ("approved", "partial"):
        return None
    paid = sold_at + timedelta(days=RNG.randint(14, 45))
    return paid if paid.date() <= date.today() else None


def _dispensary(db: Session, days: int, products, patients, doctors, staff) -> dict[str, int]:
    """Scripts, what was dispensed against them, and everything that follows.

    A pharmacy screen with an empty table on it tells a prospect nothing except
    that the feature exists. So this fills the dispensary side the way the
    counter side was filled: from the same trading pattern, with the same split
    between private cash and scheme work the claim summary shows.

    Every downstream record is derived rather than invented independently. A
    claim points at the sale it came from, a register entry points at the
    dispensing that caused it, a to-follow points at the script line the
    pharmacy could not fill. Generating those separately gives a demo where two
    screens disagree about the same money, which is the first thing anybody
    evaluating a pharmacy system notices.
    """
    made = collections.Counter()
    if not (products and patients and doctors and staff):
        return dict(made)

    prescribable = [p for p in products if (p.schedule or 0) >= 3]
    pharmacists = [u for u in staff if u.role in ("pharmacist", "admin")] or staff
    schemed = [p for p in patients if p.medical_aid_id]
    if not prescribable:
        return dict(made)

    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    claim_seq, owed_seq = 9100, 400
    balances: dict[int, int] = {}

    # Which days already have scripts, so an interrupted run fills the gaps
    # rather than starting again or writing a second set on top.
    done_days = {str(d) for (d,) in
                 db.query(func.date(Prescription.created_at))
                   .group_by(func.date(Prescription.created_at)).all()}

    # Carry on from the highest number in use rather than a constant, or a
    # resumed run collides on the unique index partway through.
    rx_seq = 38100
    for (number,) in db.query(Prescription.rx_number).all():
        digits = re.findall(r"(\d+)$", number or "")
        if digits:
            rx_seq = max(rx_seq, int(digits[0]) + 1)
    for prefix, table, column, start_at in [("TF", "owed_items", "reference", 400),
                                            ("CLM", "claims", "claim_number", 9100)]:
        highest = start_at
        for (ref,) in db.execute(text(f"SELECT {column} FROM {table}")).all():
            digits = re.findall(r"(\d+)$", ref or "")
            if digits:
                highest = max(highest, int(digits[0]) + 1)
        if prefix == "TF":
            owed_seq = highest
        else:
            claim_seq = highest

    for back in range(days, -1, -1):
        day = start - timedelta(days=back)
        # 434 scripts in a fortnight at the pharmacy the figures came from, so
        # about thirty a day, and a Sunday is quieter.
        if day.date().isoformat() in done_days:
            continue
        count = 30 if day.weekday() < 5 else (18 if day.weekday() == 5 else 9)

        # Built in three passes, one flush each, instead of two flushes per line.
        #
        # A prescription item needs its script's id, and a dispensing needs the
        # item's id, so the obvious shape is add-flush-add-flush all the way
        # down. Against SQLite on the same machine a flush costs nothing; against
        # Postgres over the internet it is a network round trip, and ninety of
        # them a day across sixty days is what turned a twelve-second seed into a
        # two-hour one. It was invisible locally because the local database is a
        # file. Three exchanges a day instead of ninety.
        planned = []
        for _ in range(count):
            when = day.replace(hour=_hour(), minute=RNG.randint(0, 59))
            if when > datetime.now():
                continue
            patient = RNG.choice(patients)
            doctor = RNG.choice(doctors)
            rx = Prescription(
                rx_number=f"RX{rx_seq}",
                patient_id=patient.id,
                doctor_id=doctor.id,
                date_prescribed=when.date(),
                created_at=when,
                status="completed",
            )
            rx_seq += 1
            planned.append({"rx": rx, "when": when, "patient": patient,
                            "doctor": doctor, "icd": RNG.choice(zimdata.ICD10)[0],
                            "lines": []})
        if not planned:
            continue

        for p in planned:
            db.add(p["rx"])
        db.flush()
        made["prescriptions"] += len(planned)

        for p in planned:
            for _ in range(RNG.choice([1, 1, 2, 2, 3])):
                product = RNG.choice(prescribable)
                category = product.category or ""
                sig = RNG.choice(zimdata.DIRECTIONS.get(category, zimdata.DIRECTIONS_DEFAULT))
                # Chronic medicine is written with repeats; a course of
                # antibiotics is not. Getting that wrong fills the repeats screen
                # with finished antibiotics.
                chronic = category in ("Cardiovascular", "Antidiabetic", "Respiratory",
                                       "Antiretroviral", "Psychotropic", "Anticonvulsant")
                repeats = RNG.choice([3, 5, 5, 6]) if chronic else 0
                used = RNG.randint(0, repeats) if repeats else 0
                item = PrescriptionItem(
                    prescription_id=p["rx"].id,
                    product_id=product.id,
                    dosage_instructions=sig,
                    quantity=RNG.choice([14, 28, 30, 30, 60]),
                    repeats_allowed=repeats,
                    repeats_used=used,
                    repeat_interval_days=30 if repeats else None,
                    icd10_code=p["icd"],
                    supply_days=30 if repeats else 7,
                )
                if repeats and used < repeats:
                    item.next_repeat_date = (p["when"] + timedelta(days=30 * (used + 1))).date()
                db.add(item)
                p["lines"].append((item, product))
                made["script lines"] += 1
        db.flush()

        for p in planned:
            when, patient, doctor = p["when"], p["patient"], p["doctor"]
            for item, product in p["lines"]:
                # About one line in fourteen cannot be filled today. That is the
                # to-follow, and it is the feature a Zimbabwean pharmacy asks
                # about first, because the alternative is a note by the till.
                if RNG.random() < 0.07:
                    owed_seq += 1
                    db.add(OwedItem(
                        reference=f"TF{owed_seq}",
                        prescription_item_id=item.id,
                        patient_id=patient.id,
                        product_id=product.id,
                        quantity_owed=item.quantity,
                        quantity_settled=0,
                        status="outstanding",
                        promised_for=(when + timedelta(days=RNG.choice([1, 2, 3, 7]))).date(),
                        created_at=when,
                        created_by_id=RNG.choice(staff).id,
                    ))
                    made["to-follows"] += 1
                    continue

                pharmacist = RNG.choice(pharmacists)
                initials = "".join(w[0] for w in (pharmacist.full_name or "P").split()[:2]).upper()
                # The shelf skews recent, and heavily. An uncollected bag from six
                # weeks ago is rare not because people are prompt but because
                # somebody eventually deals with it: it goes back to stock and the
                # claim comes off. A flat 7% across sixty days produced a shelf
                # where every bag was over a month old, which is not a will-call
                # list, it is a museum.
                stays = 0.55 if back <= 2 else 0.25 if back <= 7 else 0.07 if back <= 30 else 0.01
                collected_at = None
                if RNG.random() >= stays:
                    collected_at = min(when + timedelta(hours=RNG.choice([0, 0, 1, 2, 5, 26, 50])),
                                       datetime.now())
                db.add(Dispensing(
                    prescription_item_id=item.id,
                    quantity=item.quantity,
                    dispensed_by_id=pharmacist.id,
                    dispensed_at=when,
                    is_repeat=bool(item.repeats_used),
                    schedule=product.schedule,
                    # Typed from the schedule, as the live dispensing path does.
                    # Left unset, every seeded row defaulted to "prescription"
                    # and the controlled register came out empty.
                    dispense_type=("controlled" if (product.schedule or 0) >= 5
                                   else "prescription"),
                    script_sighted=True,
                    pharmacist_initial=initials,
                    collected_at=collected_at,
                    collected_by_id=pharmacist.id if collected_at else None,
                    collected_name=("" if not collected_at else
                                    RNG.choice(["", "", "", "patient",
                                                "daughter", "husband", "driver"])),
                ))
                made["dispensings"] += 1

                # Schedule 5 and 6 go in the register, with a running balance.
                # The balance is carried rather than recomputed per row: a
                # register whose balance does not descend is the one thing an
                # inspector notices immediately.
                if (product.schedule or 0) >= 5:
                    balance = max(0, balances.get(product.id, RNG.randint(60, 200)) - item.quantity)
                    balances[product.id] = balance
                    db.add(RegisterEntry(
                        product_id=product.id,
                        schedule=product.schedule,
                        entry_type="dispensed",
                        quantity_delta=-item.quantity,
                        balance_after=balance,
                        patient_id=patient.id,
                        doctor_id=doctor.id,
                        prescription_item_id=item.id,
                        user_id=pharmacist.id,
                        reference=p["rx"].rx_number,
                        created_at=when,
                    ))
                    made["register entries"] += 1
        db.commit()

    # Claims, against sales that already exist for scheme patients.
    #
    # Built from real sales rather than invented, so the claiming screens and the
    # takings screens agree about how much money is involved.
    if schemed:
        by_id = {p.id: p for p in schemed}
        # Sales that already carry a claim, so a second run tops up rather than
        # writing a duplicate.
        #
        # This block sits outside the day-by-day skip above and ran in full every
        # time, so re-running the seeder gave every scheme sale a second claim
        # against it — 101 became 202 with the same money behind them, and the
        # claim summary quietly doubled. One sale has one claim.
        claimed_already = {sale_id for (sale_id,) in db.query(Claim.sale_id).all()}
        sales = (db.query(Sale)
                   .filter(Sale.patient_id.in_(list(by_id)))
                   .order_by(Sale.created_at.desc())
                   .limit(420).all())
        for sale in sales:
            if sale.id in claimed_already:
                continue
            patient = by_id.get(sale.patient_id)
            if not patient or not patient.medical_aid_id:
                continue
            scheme = db.get(MedicalAid, patient.medical_aid_id)
            if not scheme:
                continue
            claim_seq += 1
            gross = round(sale.total or 0, 2)
            levy = round(gross * (scheme.levy_percent or 0) / 100, 2)
            claimed = round(gross - levy, 2)
            # The states a claiming clerk actually works through, weighted the
            # way the claim summary reads: most of the money is still out.
            # The states a claiming clerk actually works through, in the
            # vocabulary the routers query: "deferred" is the one held back
            # because the switch was down, which is the screen a Zimbabwean
            # pharmacy looks at most.
            status = RNG.choices(
                ["approved", "submitted", "partial", "rejected", "deferred"],
                weights=[0.34, 0.30, 0.16, 0.10, 0.10])[0]
            db.add(Claim(
                claim_number=f"CLM{claim_seq}",
                sale_id=sale.id,
                patient_id=patient.id,
                medical_aid_id=scheme.id,
                gross=gross,
                levy=levy,
                amount_claimed=claimed,
                amount_approved=(claimed if status == "approved" else
                                 round(claimed * 0.6, 2) if status == "partial" else 0),
                patient_liable=levy,
                settled_amount=((claimed if status == "approved" else
                                 round(claimed * 0.6, 2) if status == "partial" else 0)
                                if _settled_on(sale.created_at, status) else 0.0),
                settled_at=_settled_on(sale.created_at, status),
                submitted_at=(sale.created_at + timedelta(days=1)
                              if status != "deferred" else None),
                status=status,
                icd10_code=RNG.choice(zimdata.ICD10)[0],
                authorisation=f"APWEB-{RNG.randint(10**12, 10**13 - 1)}",
                response_message=("Paid in full" if status == "approved" else
                                  "Awaiting remittance" if status == "submitted" else
                                  "Paid short against the reference price" if status == "partial" else
                                  "Member not on risk for this benefit" if status == "rejected" else
                                  "Switch was down at the time of sale"),
                deferred_reason=("Switch offline at point of sale"
                                 if status == "deferred" else None),
                deferred_at=(sale.created_at if status == "deferred" else None),
                created_at=sale.created_at,
            ))
            made["claims"] += 1
        db.commit()

    return dict(made)


def _stock_and_supply(db: Session, products, staff) -> dict[str, int]:
    """Batches with real expiry dates, and the orders that brought them in."""
    made = collections.Counter()
    suppliers = db.query(Supplier).all()
    if not suppliers or not products:
        return dict(made)

    # Each half decides for itself whether it has work.
    #
    # The caller used to gate the whole stage on the number of batches, so a
    # database that had batches but no purchase orders got neither — which is
    # exactly the state that produced no deliveries, no supplier invoices and
    # no creditors, on a system whose accounting screens all read from them.
    # Opening batches are not deliveries. `ensure_opening_batches` creates one
    # per product, numbered "OPENING", to give pre-existing stock somewhere to
    # live — and on the hosted database those 121 placeholders were enough to
    # satisfy a plain count, so this stage never ran and every batch in
    # production was an opening one. That meant every dispensing label printed
    # batch "OPENING", a recall search by batch number matched the entire
    # catalogue, picking had nothing real to order by, and nothing was ever
    # short dated so the expiry provision was permanently zero. Count the
    # batches that came from a delivery, which is what the question means.
    need_batches = (db.query(StockBatch)
                      .filter(StockBatch.batch_number != "OPENING").count()) < 50
    need_orders = db.query(PurchaseOrder).count() == 0

    today = date.today()
    for i, product in enumerate(products if need_batches else []):
        # Two or three batches a line, one of which is often short dated. A batch
        # list where nothing ever expires makes the expiry report look like a
        # feature nobody needs.
        for n in range(RNG.choice([1, 2, 2, 3])):
            if n == 0 and RNG.random() < 0.14:
                expiry = today + timedelta(days=RNG.randint(-40, 80))
            else:
                expiry = today + timedelta(days=RNG.randint(180, 900))
            qty = RNG.randint(20, 300)
            db.add(StockBatch(
                product_id=product.id,
                batch_number=f"{RNG.choice('ABCDEFGH')}{RNG.randint(10000, 99999)}",
                expiry_date=expiry,
                quantity_received=qty,
                quantity_remaining=RNG.randint(0, qty),
                unit_cost=product.cost_price or 0,
                received_at=datetime.now() - timedelta(days=RNG.randint(5, 300)),
            ))
            made["batches"] += 1
        if i % 40 == 0:
            db.commit()
    db.commit()

    # What is short comes first, and the rest of the order is made up from the
    # catalogue.
    #
    # The old version ordered only what was at or below its reorder level, which
    # after a seed is nothing at all — so it made no orders, and with no orders
    # there were no deliveries, no supplier invoices and no creditors. A
    # pharmacy orders every week whether or not anything has hit its minimum.
    if not need_orders:
        return dict(made)

    low = [p for p in products if (p.quantity_on_hand or 0) <= (p.reorder_level or 0)]
    orders_each = 3
    n = 0
    for supplier in suppliers:
        for _ in range(orders_each):
            n += 1
            want = RNG.randint(4, 9)
            lines = list(RNG.sample(low, min(len(low), want))) if low else []
            if len(lines) < want:
                spare = [p for p in products if p not in lines]
                lines += RNG.sample(spare, min(len(spare), want - len(lines)))
            if not lines:
                continue
            # Weighted to received, because a delivery that arrived is the one
            # that carries a bill behind it.
            status = RNG.choices(["draft", "sent", "received"],
                                 weights=[10, 22, 68])[0]
            placed = datetime.now() - timedelta(days=RNG.randint(3, 75))
            order = PurchaseOrder(
                order_number=f"PO2026{1000 + n}",
                supplier_id=supplier.id,
                status=status,
                created_at=placed,
                # Set, not left null: the payables screen ages a delivery from
                # the day it arrived, and every row read "not recorded".
                received_at=(placed + timedelta(days=RNG.randint(1, 6))
                             if status == "received" else None),
            )
            db.add(order)
            db.flush()
            for product in lines:
                qty = RNG.choice([20, 30, 50, 100])
                # Not every delivery is complete. A short delivery is what the
                # three-way match on the payables screen exists to catch, and
                # one that never happens leaves it with nothing to find.
                got = qty
                if status == "received" and RNG.random() < 0.12:
                    got = int(qty * RNG.uniform(0.6, 0.9))
                db.add(PurchaseOrderItem(
                    order_id=order.id, product_id=product.id,
                    quantity_ordered=qty,
                    quantity_received=got if status == "received" else 0,
                    unit_cost=product.cost_price or 0,
                ))
            made["purchase orders"] += 1
            if n % 6 == 0:
                db.commit()
    db.commit()
    return dict(made)


def _allocate_batches(db: Session) -> dict[str, int]:
    """Say which batch served which sale line.

    The till does this through `consume_stock_fefo`; the seeder wrote sales
    directly and skipped it, so every batch had a quantity and no idea where any
    of it went. That is invisible on the stock screens — the numbers all add up —
    and it makes recall tracing return nothing, which is the one time it matters.

    Allocated first-expiry-first-out, the way the counter does it, so the trace
    tells the truth about which batch a patient actually got.
    """
    made = collections.Counter()
    if db.execute(text("SELECT COUNT(*) FROM batch_allocations")).scalar() > 50:
        return dict(made)

    # Batches per product, soonest expiry first: that is the order stock leaves
    # a shelf and therefore the order it has to be allocated in.
    shelves: dict[int, list] = collections.defaultdict(list)
    for b in (db.query(StockBatch)
                .order_by(StockBatch.expiry_date.asc().nullslast(),
                          StockBatch.received_at.asc()).all()):
        shelves[b.product_id].append({"id": b.id, "left": b.quantity_received or 0})

    rows = (db.query(SaleItem.id, SaleItem.product_id, SaleItem.quantity)
              .join(Sale, Sale.id == SaleItem.sale_id)
              .order_by(Sale.created_at.asc()).all())
    for line_id, product_id, quantity in rows:
        want = quantity or 0
        for batch in shelves.get(product_id, []):
            if want <= 0:
                break
            if batch["left"] <= 0:
                continue
            take = min(batch["left"], want)
            db.execute(text(
                "INSERT INTO batch_allocations (batch_id, sale_item_id, quantity, created_at) "
                "VALUES (:b, :s, :q, :t)"),
                {"b": batch["id"], "s": line_id, "q": take, "t": datetime.now()})
            batch["left"] -= take
            want -= take
            made["batch allocations"] += 1
        if made["batch allocations"] % 500 == 0:
            db.commit()
    db.commit()
    return dict(made)


def _payables(db: Session) -> dict[str, int]:
    """Supplier invoices against the deliveries, and payment of some of them.

    Without these the supplier accounts screen has nothing to show, and the
    creditors control account carries deliveries nobody has been billed for.

    A deliberate few do not match: a price rise between order and invoice, and a
    short delivery billed in full. Those two are the whole reason the three-way
    match exists, and a demonstration in which every invoice agrees does not
    show it doing anything.
    """
    made = collections.Counter()
    already = db.query(SupplierInvoice).count()
    if already:
        return {"invoices already recorded": already}

    received = (db.query(PurchaseOrder)
                  .filter(PurchaseOrder.status == "received").all())
    if not received:
        return dict(made)

    today = date.today()
    seq = 44000
    raised: list[tuple[SupplierInvoice, float]] = []

    for order in received:
        goods = round(sum((i.unit_cost or 0.0) * (i.quantity_received or 0)
                          for i in order.items), 2)
        if goods <= 0:
            continue
        seq += 1
        billed_on = (order.received_at or datetime.now()).date()

        # Most invoices agree. About one in six does not, which is close to what
        # a pharmacy actually sees and often enough that the match earns its
        # place on the screen.
        trouble = RNG.random()
        short_billed = 0.10 <= trouble < 0.17
        lines_at: dict[int, float] = {}
        billed = goods
        if trouble < 0.10:
            bump = RNG.uniform(1.06, 1.22)
            billed = round(goods * bump, 2)
            lines_at = {i.product_id: round((i.unit_cost or 0.0) * bump, 2)
                        for i in order.items}
        elif short_billed:
            billed = round(sum((i.unit_cost or 0.0) * (i.quantity_ordered or 0)
                               for i in order.items), 2)

        invoice = SupplierInvoice(
            invoice_number=f"ZW-{seq}", supplier_id=order.supplier_id,
            order_id=order.id, invoice_date=billed_on,
            due_date=billed_on + timedelta(days=RNG.choice([30, 30, 45, 60])),
            total=billed, currency_code="USD",
            status="matched" if abs(billed - goods) < 0.005 else "unmatched",
            created_at=datetime.combine(billed_on, datetime.min.time()),
        )
        db.add(invoice)
        db.flush()
        for item in order.items:
            quantity = ((item.quantity_ordered or 0) if short_billed
                        else (item.quantity_received or 0))
            if not quantity:
                continue
            cost = lines_at.get(item.product_id, item.unit_cost or 0.0)
            db.add(SupplierInvoiceItem(
                invoice_id=invoice.id, product_id=item.product_id,
                quantity=quantity, unit_cost=round(cost, 2),
                line_total=round(cost * quantity, 2)))
        made["invoices"] += 1
        raised.append((invoice, billed))
    db.commit()

    # Pay the older ones and leave the recent ones outstanding, so the ageing
    # has something in every column rather than one lump in the first.
    for invoice, billed in raised:
        if (today - invoice.invoice_date).days < 25 or RNG.random() < 0.25:
            continue
        paid_on = invoice.invoice_date + timedelta(days=RNG.randint(20, 40))
        if paid_on > today:
            continue
        payment = SupplierPayment(
            supplier_id=invoice.supplier_id, amount=billed, paid_on=paid_on,
            method=RNG.choice(["bank", "bank", "bank", "ecocash"]),
            reference=f"FCB-TT-{RNG.randint(1000, 9999)}",
            created_at=datetime.combine(paid_on, datetime.min.time()))
        db.add(payment)
        db.flush()
        db.add(SupplierPaymentAllocation(
            payment_id=payment.id, invoice_id=invoice.id, amount=billed))
        invoice.status = "paid"
        made["payments"] += 1
    db.commit()
    return dict(made)


def _ledger(db: Session) -> dict[str, int]:
    """Put the trading history into the books.

    The ledger was empty. Not thin — empty: no chart, no entries, so the trial
    balance, the VAT return, the balance sheet and the creditors ageing all had
    nothing to read and every one of them rendered a zero as though that were
    the answer.

    Takings post as one entry a day rather than one an eighty-first of a day.
    That is not a shortcut: a pharmacy's cash book is a daily takings journal,
    and four thousand individual entries would be both slower to write and less
    like the thing being modelled.
    """
    from .services import ledger, payables, posting

    made = collections.Counter()
    ledger.ensure_chart(db)

    # A sale with a claim against it was not paid for in cash.
    #
    # Every sale was marked cash, so the day's takings all landed in the cash
    # account and medical scheme debtors stayed at nil while three hundred
    # claims sat outstanding. The books said nobody owed the pharmacy anything
    # while the claims screen said otherwise, and both were reading the same
    # database.
    marked = db.execute(text(
        "UPDATE sales SET payment_method = 'medical_aid' "
        " WHERE payment_method <> 'medical_aid' "
        "   AND id IN (SELECT sale_id FROM claims)")).rowcount
    if marked:
        db.commit()
        made["sales billed to a scheme"] = marked

    # Skip the takings that are already written, not the whole stage.
    #
    # Returning here meant the deliveries below never posted, so a database that
    # had its takings but gained purchase orders afterwards ended up with
    # supplier invoices and an empty creditors account — and the ageing screen
    # then reported a difference of everything owed, blaming the pharmacy for a
    # gap this function had left.
    posted_takings = {e.source_id for e in db.query(JournalEntry)
                      .filter(JournalEntry.source == "daily_takings").all()}
    if posted_takings:
        made["takings already posted"] = len(posted_takings)

    rate = settings.VAT_RATE or 0.0
    rows = db.execute(text(
        "SELECT DATE(created_at) AS d, "
        "       SUM(total) AS gross, "
        "       SUM(CASE WHEN payment_method = 'medical_aid' THEN total ELSE 0 END) AS aid "
        "  FROM sales GROUP BY DATE(created_at) ORDER BY d")).mappings().all()

    for row in rows:
        gross = round(float(row["gross"] or 0.0), 2)
        if gross <= 0:
            continue
        on_account = round(float(row["aid"] or 0.0), 2)
        cash = round(gross - on_account, 2)
        net = round(gross / (1 + rate), 2) if rate else gross
        vat = round(gross - net, 2)
        day = row["d"] if isinstance(row["d"], date) else date.fromisoformat(str(row["d"]))
        if int(day.strftime("%Y%m%d")) in posted_takings:
            continue

        lines = []
        if cash:
            lines.append(ledger.Line(account_code="1000", debit=cash,
                                     description="Takings banked"))
        if on_account:
            lines.append(ledger.Line(account_code="1110", debit=on_account,
                                     description="Owed by the schemes"))
        lines.append(ledger.Line(account_code="4000", credit=net,
                                 description="Dispensary and front shop"))
        if vat:
            lines.append(ledger.Line(account_code="2100", credit=vat,
                                     description="VAT on sales"))
        try:
            ledger.post(db, entry_date=day,
                        description=f"Takings for {day:%d %B %Y}", lines=lines,
                        source="daily_takings", source_id=int(day.strftime("%Y%m%d")))
            made["days posted"] += 1
        except ledger.LedgerError:
            # One day that will not balance is not worth losing the other sixty.
            made["days that would not post"] += 1

    # The purchase side, so stock does not only ever go down.
    for order in db.query(PurchaseOrder).filter(
            PurchaseOrder.status == "received").all():
        if posting.post_stock_receipt(db, order).get("posted"):
            made["deliveries posted"] += 1
    db.commit()

    # An invoice that agrees with the delivery needs no one's judgement, so it
    # is approved and posted. The ones that do not agree are deliberately left
    # for a pharmacist, which is the whole point of the match.
    for invoice in db.query(SupplierInvoice).filter(
            SupplierInvoice.posted_reference == "").all():
        if payables.match(db, invoice)["matched"]:
            if payables.post_invoice(db, invoice).get("posted"):
                made["invoices posted"] += 1
            else:
                made["invoices that agreed already"] += 1
    db.commit()

    # Cash banked, weekly.
    #
    # Without it the bank account only ever went down — supplier payments left
    # it and nothing arrived — so the balance sheet showed a pharmacy four
    # thousand dollars overdrawn while its safe held thirty. A pharmacy banks
    # its takings; the books should say so.
    banked_already = {e.source_id for e in db.query(JournalEntry)
                      .filter(JournalEntry.source == "banking").all()}
    weeks = db.execute(text(
        "SELECT MIN(DATE(created_at)) AS start, MAX(DATE(created_at)) AS finish "
        "  FROM sales")).mappings().first()
    if weeks and weeks["start"]:
        start = weeks["start"] if isinstance(weeks["start"], date) else date.fromisoformat(str(weeks["start"]))
        finish = weeks["finish"] if isinstance(weeks["finish"], date) else date.fromisoformat(str(weeks["finish"]))
        day = start + timedelta(days=(4 - start.weekday()) % 7)   # the first Friday
        while day <= finish:
            marker = int(day.strftime("%Y%m%d"))
            if marker in banked_already:
                day += timedelta(days=7)
                continue
            week = db.execute(text(
                "SELECT COALESCE(SUM(total), 0) AS t FROM sales "
                " WHERE payment_method <> 'medical_aid' "
                "   AND DATE(created_at) > :from_day AND DATE(created_at) <= :to_day"),
                {"from_day": day - timedelta(days=7), "to_day": day}).scalar()
            # A float of the week's takings, kept back to open the till on
            # Monday. Banking every last cent is not what anybody does.
            amount = round(float(week or 0.0) * RNG.uniform(0.82, 0.93), 2)
            if amount > 0:
                try:
                    ledger.post(
                        db, entry_date=day,
                        description=f"Cash banked, week to {day:%d %B}",
                        lines=[
                            ledger.Line(account_code="1010", debit=amount,
                                        description="Deposited"),
                            ledger.Line(account_code="1000", credit=amount,
                                        description="Out of the safe"),
                        ],
                        source="banking", source_id=marker)
                    made["weeks banked"] += 1
                except ledger.LedgerError:
                    made["weeks that would not bank"] += 1
            day += timedelta(days=7)
    db.commit()

    # And the money that went out.
    #
    # The payments were written as rows and never posted, so trade creditors
    # carried every delivery and none of the settlements — the account said the
    # pharmacy owed four thousand dollars it had already paid, which is the
    # same one-way creditor this whole module was written to end.
    for payment in db.query(SupplierPayment).filter(
            SupplierPayment.posted_reference == "").all():
        supplier = db.get(Supplier, payment.supplier_id)
        amount = round(payment.amount or 0.0, 2)
        if amount <= 0:
            continue
        try:
            entry = ledger.post(
                db, entry_date=payment.paid_on,
                description=f"Payment to {supplier.name if supplier else 'a supplier'}",
                lines=[
                    ledger.Line(account_code="2000", debit=amount,
                                description="Settled",
                                party_type="supplier", party_id=payment.supplier_id),
                    ledger.Line(account_code="1010", credit=amount,
                                description=payment.reference or "Payment"),
                ],
                source="supplier_payment", source_id=payment.id)
            payment.posted_reference = entry.reference
            made["payments posted"] += 1
        except ledger.LedgerError:
            made["payments that would not post"] += 1
    db.commit()
    return dict(made)


#: What a Zimbabwean dispensary actually makes on the bench. Extemporaneous
#: preparations are not a curiosity here: a paediatric dose of something only
#: made as an adult tablet, or a skin preparation nobody imports, is compounded
#: because the alternative is the patient going without.
MIXTURES = [
    ("MAGTRI", "Magnesium trisilicate mixture", "oral liquid", 200, "mL", 3.50, 14,
     "Triturate the powders with a little water to a smooth paste, then make up "
     "to volume. Shake before each dose.",
     "10mL three times a day after food."),
    ("CALAM", "Calamine lotion, fortified", "lotion", 200, "mL", 3.00, 30,
     "Levigate the calamine and zinc oxide with the glycerin, then add the "
     "solution slowly with constant stirring.",
     "Apply to the affected area twice a day."),
    ("WHIT", "Whitfield's ointment", "ointment", 100, "g", 4.00, 60,
     "Melt the base on a water bath, dissolve the acids in it and stir until "
     "cold to prevent the crystals settling out.",
     "Apply thinly to the affected area at night."),
    ("KMNO4", "Potassium permanganate solution 1:8000", "solution", 500, "mL", 2.50, 7,
     "Dissolve the crystals fully before diluting. An undissolved crystal will "
     "burn the skin, so the solution is not issued until it is clear.",
     "Dilute as directed and soak for ten minutes twice a day."),
    ("ORS", "Oral rehydration solution", "oral liquid", 1000, "mL", 1.50, 1,
     "Dissolve in one litre of cooled boiled water. Discard anything unused "
     "after twenty-four hours.",
     "Drink freely after each loose stool."),
    ("PARAPAED", "Paracetamol paediatric suspension 120mg/5mL", "oral liquid",
     100, "mL", 3.00, 14,
     "Triturate the tablets to a fine powder, wet with the vehicle and make up "
     "to volume. Label 'shake well'.",
     "5mL every six hours as needed. Not more than four doses in a day."),
]


#: The raw materials a compounding bench keeps. Not medicines a patient is
#: handed — powders and bases that go into what is made on the bench — but a
#: pharmacy stocks and counts them like anything else, and a formula naming an
#: ingredient the shop does not hold is a recipe nobody can follow.
RAW_MATERIALS = [
    ("Magnesium Trisilicate Powder", "500g", 14.00, "powder"),
    ("Light Magnesium Carbonate", "500g", 12.50, "powder"),
    ("Calamine Powder", "500g", 11.00, "powder"),
    ("Benzoic Acid Powder", "250g", 16.00, "powder"),
    ("Salicylic Acid Powder", "250g", 18.50, "powder"),
    ("Potassium Permanganate Crystals", "100g", 9.50, "crystals"),
    ("Sodium Bicarbonate Powder", "500g", 7.50, "powder"),
    ("Sodium Chloride Powder", "500g", 6.00, "powder"),
    ("Anhydrous Glucose Powder", "500g", 8.00, "powder"),
    ("Emulsifying Ointment Base", "500g", 13.00, "base"),
    ("Glycerin BP", "500mL", 10.50, "liquid"),
]


def _drop_sweep_mixtures(db: Session) -> int:
    """Remove the compounding fixtures the old scaffolding left behind.

    "Sweep Test Mixture" and "Controlled Sweep Cream" were the whole of the
    compounding bench, which is why the screen looked like a feature nobody had
    finished rather than one nobody had filled in.
    """
    from .models import Mixture, MixtureIngredient

    doomed = [m.id for m in db.query(Mixture)
              .filter(Mixture.name.ilike("%sweep%")).all()]
    if not doomed:
        return 0
    db.query(MixtureIngredient).filter(
        MixtureIngredient.mixture_id.in_(doomed)).delete(synchronize_session=False)
    db.query(Mixture).filter(Mixture.id.in_(doomed)).delete(synchronize_session=False)
    db.commit()
    return len(doomed)


def _raw_materials(db: Session) -> int:
    """Stock the bench, so a formula names things the pharmacy actually holds."""
    made = 0
    for name, pack, cost, form in RAW_MATERIALS:
        row = db.query(Product).filter(Product.name == name).first()
        if row is None:
            row = Product(name=name)
            db.add(row)
            made += 1
        row.pack_size = pack
        row.dosage_form = form
        row.category = "medicine"
        row.schedule = 0
        row.cost_price = cost
        row.unit_price = round(cost * 1.45, 2)
        row.active = True
        if not row.quantity_on_hand:
            row.quantity_on_hand = RNG.randint(2, 12)
        row.reorder_level = 2
    db.commit()
    return made


def _compounding(db: Session, products) -> dict[str, int]:
    """The formulas kept on the bench, with what goes into them.

    The compounding screen was empty, which reads as a feature nobody uses
    rather than a bench nobody wrote down. These are the preparations an
    ordinary Harare dispensary makes, with a method written the way a
    pharmacist would say it — including the parts that matter for safety, like
    a permanganate crystal that has not dissolved.
    """
    from .models import Mixture, MixtureIngredient

    made = collections.Counter()
    by_name = {p.name.lower(): p for p in products}

    def find(*words):
        for name, product in by_name.items():
            if all(w in name for w in words):
                return product
        return None

    recipes = {
        "MAGTRI": [(find("magnesium"), 10, "g"), (find("sodium"), 5, "g")],
        "CALAM": [(find("calamine"), 15, "g"), (find("zinc"), 5, "g")],
        "WHIT": [(find("benzoic"), 6, "g"), (find("salicylic"), 3, "g")],
        "KMNO4": [(find("potassium"), 1, "g")],
        "ORS": [(find("sodium"), 3, "g"), (find("glucose"), 20, "g")],
        "PARAPAED": [(find("paracetamol"), 24, "tablets")],
    }

    for code, name, form, yield_qty, unit, fee, life, method, directions in MIXTURES:
        row = db.query(Mixture).filter(Mixture.code == code).first()
        if row is None:
            row = Mixture(code=code)
            db.add(row)
            made["formulas"] += 1
        row.name = name
        row.form = form
        row.yield_quantity = yield_qty
        row.yield_unit = unit
        row.compounding_fee = fee
        row.shelf_life_days = life
        row.method = method
        row.directions = directions
        row.active = True
        db.flush()

        if db.query(MixtureIngredient).filter(
                MixtureIngredient.mixture_id == row.id).count():
            continue
        for product, quantity, ing_unit in recipes.get(code, []):
            if product is None:
                # Said nothing rather than inventing an ingredient. A formula
                # short of a line is obvious on the screen; a formula naming a
                # product the pharmacy does not stock is a wrong answer that
                # looks right.
                continue
            db.add(MixtureIngredient(mixture_id=row.id, product_id=product.id,
                                     quantity=quantity, unit=ing_unit))
            made["ingredients"] += 1
    db.commit()
    return dict(made)


def _deliveries(db: Session, staff) -> dict[str, int]:
    """Waybills for medicine that went out by driver.

    A pharmacy that delivers has a book of these and the screen was empty. The
    mix is deliberate: most arrive, a few are still out, and one or two fail —
    a delivery book where everything succeeded is not a delivery book, it is a
    list of receipts.
    """
    from .models import Waybill

    made = collections.Counter()
    if db.query(Waybill).count():
        return {"waybills already recorded": db.query(Waybill).count()}

    sales = (db.query(Sale)
               .filter(Sale.patient_id.isnot(None))
               .order_by(Sale.created_at.desc()).limit(60).all())
    drivers = [u for u in staff if u.active] or staff
    if not sales or not drivers:
        return dict(made)

    seq = 4100
    for sale in sales:
        if RNG.random() < 0.45:
            continue
        patient = db.get(Patient, sale.patient_id)
        if patient is None:
            continue
        seq += 1
        raised = sale.created_at or datetime.now()
        # Most get there. Some are still on the road. A couple do not, and the
        # reason is the useful part of the record.
        roll = RNG.random()
        if roll < 0.72:
            status, delivered = "delivered", raised + timedelta(hours=RNG.randint(2, 30))
        elif roll < 0.92:
            status, delivered = "despatched", None
        else:
            status, delivered = "failed", None

        db.add(Waybill(
            waybill_number=f"WB{seq}",
            sale_id=sale.id,
            patient_id=patient.id,
            recipient=f"{patient.first_name} {patient.last_name}".strip(),
            address=patient.address or RNG.choice(zimdata.SUBURBS)
                    if hasattr(zimdata, "SUBURBS") else (patient.address or "Harare"),
            phone=patient.phone or "",
            instructions=RNG.choice([
                "", "", "Gate is on the left, ask for the caretaker.",
                "Telephone on arrival, the dogs are loose.",
                "Leave with reception if nobody is in.",
            ]),
            status=status,
            driver_id=RNG.choice(drivers).id,
            received_by=("" if status != "delivered" else RNG.choice(
                ["the patient", "spouse", "daughter", "the caretaker", "neighbour"])),
            failure_reason=("" if status != "failed" else RNG.choice([
                "Nobody at the address after two attempts.",
                "Telephone off; could not confirm anybody was in.",
                "Address could not be found from the directions given.",
            ])),
            requires_id_check=RNG.random() < 0.18,
            created_at=raised,
            created_by_id=RNG.choice(drivers).id,
            dispatched_at=raised + timedelta(minutes=RNG.randint(20, 200)),
            delivered_at=delivered,
        ))
        made[status] += 1
        made["waybills"] += 1
    db.commit()
    return dict(made)


#: How a funder actually pays. Most lines go through; a fifth come back short
#: because the member owes a levy or the item was repriced to the scheme's
#: tariff; a tenth are refused outright. A remittance where every line paid in
#: full is not a remittance, it is a receipt, and it would leave the shortfall
#: screens empty and the reconciliation work invisible.
PAID_IN_FULL = 0.72
SHORT_PAID = 0.90          # cumulative: 0.72–0.90 short, the rest refused

REFUSALS = [
    ("NO_AUTH", "No valid pre-authorisation was held."),
    ("BENEFIT_EXHAUSTED", "The member's benefit was exhausted."),
    ("MEMBER_INVALID", "The member was not active on the service date."),
    ("NOT_COVERED", "The item is not on the member's formulary."),
    ("STALE", "Submitted outside the funder's claiming window."),
]


def _remittances(db: Session) -> dict[str, int]:
    """The money coming back from the funders, against claims already sent.

    Claiming was only half-written down. Claims went out and nothing recorded
    them being paid, so the calendar could say when CIMAS settles but never that
    it had, every claim sat "submitted" for ever, and the shortfall screens —
    the ones that decide whether a difference goes to the patient or to
    write-off — had nothing in them to work on.

    Advices are built from real claims and imported through the ordinary import
    path, so the matching, the classification and the settling of the claim all
    run as they would for a file a funder actually sent. Seeding the rows
    directly would have produced the same screens and proved none of it.

    The current month is deliberately left unpaid: a pharmacy always has money
    in the air, and a claiming screen showing nothing outstanding is the one
    state that never happens.
    """
    from .services import era

    made = collections.Counter()
    if db.query(Remittance).count():
        return {"advices already imported": db.query(Remittance).count()}

    claims = (db.query(Claim)
                .filter(Claim.status.in_(("submitted", "approved", "paid")),
                        Claim.amount_claimed > 0)
                .order_by(Claim.created_at).all())
    if not claims:
        return dict(made)

    this_month = date.today().replace(day=1)

    # One advice per funder per month, the way a statement arrives.
    months: dict[tuple[int, str], list] = collections.defaultdict(list)
    for claim in claims:
        raised = (claim.submitted_at or claim.created_at)
        if raised is None:
            continue
        period = raised.date().replace(day=1)
        if period >= this_month:
            continue                      # still in the air, and should be
        months[(claim.medical_aid_id, period.isoformat())].append(claim)

    for (aid_id, period_iso), batch in sorted(months.items(), key=lambda kv: kv[0][1]):
        aid = db.get(MedicalAid, aid_id)
        if aid is None:
            continue
        period = date.fromisoformat(period_iso)

        # They pay on the day the memorandum says, in the month after the claim.
        pay_month = (period.replace(day=28) + timedelta(days=7)).replace(day=1)
        day = aid.settlement_day or 25
        last = calendar.monthrange(pay_month.year, pay_month.month)[1]
        paid_on = pay_month.replace(day=min(day, last))
        if paid_on > date.today():
            continue                      # not due yet; nothing has arrived

        lines = []
        for n, claim in enumerate(batch, start=1):
            claimed = round(claim.amount_claimed or 0.0, 2)
            roll = RNG.random()
            if roll < PAID_IN_FULL:
                paid, code, reason = claimed, "PAID", ""
            elif roll < SHORT_PAID:
                # A shortfall with a cause. The levy is the honest common one:
                # the member owes it, so it is billed on rather than written off.
                if (aid.levy_fixed or aid.levy_percent):
                    cut = max(aid.levy_fixed or 0.0,
                              round(claimed * (aid.levy_percent or 0) / 100, 2))
                    cut = min(cut or round(claimed * 0.15, 2), round(claimed * 0.6, 2))
                    code, reason = "LEVY", ""
                else:
                    cut = round(claimed * RNG.uniform(0.08, 0.35), 2)
                    code, reason = "TARIFF", ""
                paid = round(max(claimed - max(cut, 0.5), 0.5), 2)
            else:
                paid, (code, reason) = 0.0, RNG.choice(REFUSALS)

            patient = claim.patient
            lines.append({
                "line_number": n,
                "claim_reference": claim.claim_number,
                "policy_number": getattr(patient, "medical_aid_number", "") or "",
                "member_name": (f"{patient.first_name} {patient.last_name}".strip()
                                if patient else ""),
                "service_date": (claim.submitted_at or claim.created_at).date(),
                "amount_claimed": claimed,
                "amount_allowed": paid,
                "amount_paid": paid,
                "reason_code": code,
                "reason": reason,
            })
            made[{"PAID": "paid in full"}.get(code,
                 "short paid" if paid > 0 else "refused")] += 1

        # Funders do pay for things the pharmacy cannot find — a line keyed to
        # somebody else's claim number, or one already written off here. The
        # unmatched state is a real part of this work, so leave one in.
        if len(lines) > 12 and RNG.random() < 0.35:
            stray = round(RNG.uniform(4, 40), 2)
            lines.append({
                "line_number": len(lines) + 1,
                "claim_reference": f"CLM{RNG.randint(900000, 999999)}",
                "policy_number": "", "member_name": "",
                "service_date": period,
                "amount_claimed": stray, "amount_allowed": stray,
                "amount_paid": stray, "reason_code": "PAID", "reason": "",
            })
            made["unmatched"] += 1

        code = aid.scheme_code or f"AID{aid.id}"
        try:
            era.import_advice(
                db,
                funder_id=code,
                remittance_number=f"ERA-{code}-{period:%Y%m}",
                payment_reference=f"TT{RNG.randint(10**7, 10**8 - 1)}",
                payment_date=paid_on,
                currency_code=aid.currency_code or "USD",
                lines=lines,
                source="switch",
                notes=f"{aid.name} statement for {period:%B %Y}.",
            )
        except era.RemittanceError:
            # Already imported. Said nothing rather than counting it twice.
            continue
        made["advices"] += 1
    return dict(made)


#: Why somebody walks in and asks for something by name.
#:
#: Keyed on the product's category rather than words in its name. Name matching
#: was tried first and quietly failed: "Ferrous Sulphate" contains neither
#: "iron" nor "supplement", so four sales in five fell through to a limp
#: "asked for by name" — a record that looks complete and says nothing, which is
#: the exact failure the indication field exists to prevent.
OTC_INDICATIONS = {
    "analgesic": ["headache", "period pain", "backache", "toothache until the dentist",
                  "fever in a child", "muscular pain after work"],
    "respiratory": ["a dry night cough", "a chesty cough for three days",
                    "cough after a cold", "a blocked chest"],
    "antihistamine": ["hay fever", "an allergic rash", "itching at night",
                      "reaction to something eaten"],
    "antiseptic": ["a grazed knee", "cleaning a small wound", "a cut that keeps opening"],
    "first aid": ["dressing a graze", "a small burn", "a blister"],
    "dermatological": ["an itchy rash", "insect bites", "heat rash on a baby",
                       "dry cracked skin"],
    "gastrointestinal": ["stomach cramps", "heartburn after eating", "indigestion",
                         "loose stools since yesterday"],
    "anthelmintic": ["deworming the household", "routine deworming for a child"],
    "supplement": ["a supplement the patient asked for", "tiredness",
                   "pregnancy supplement", "advised to take iron"],
    "cardiovascular": ["on the doctor's advice, low dose", "continuing what the clinic started"],
}

#: Sold at the counter but not pharmacy medicines: airtime, wipes, a
#: thermometer. They belong on the till, not in a register that records a
#: pharmacist's clinical decision — a counselled sale of five dollars of airtime
#: is not a wrong row, it is a nonsense one.
NOT_MEDICINE = ("airtime", "front shop", "front_shop")

#: When the right answer is "see a doctor". A counter that never refers is a
#: counter that sells to everybody, which is the thing the record exists to
#: catch.
REFERRAL_NOTES = [
    "Pain for more than ten days; referred rather than sold again.",
    "Child under two with a fever; sent to the clinic.",
    "Cough with blood; referred the same morning.",
    "Asked for a third course in a month; referred.",
    "Blood pressure taken at the counter was high; referred.",
]


def _otc(db: Session, products, staff, days: int) -> dict[str, int]:
    """Counter sales of pharmacy medicines, the trade that needs no script.

    A Zimbabwean dispensary does a great deal of this — paracetamol, cough
    linctus, an antacid, deworming tablets — and the screen was empty, which
    reads as a feature nobody uses rather than a day nobody wrote down.

    It is not a till receipt. Selling a schedule 1 or 2 without a prescription
    is allowed because a pharmacist stands behind it, so the record carries who
    that was, what the customer said was wrong, and whether they were counselled
    or sent to a doctor. Seeding it without those would produce a screen that
    looks right and records nothing worth keeping.
    """
    from .models import OTCSale

    made = collections.Counter()
    if db.query(OTCSale).count():
        return {"counter sales already recorded": db.query(OTCSale).count()}

    sellable = [
        p for p in products
        if (p.schedule or 0) <= 2
        and (p.category or "").strip().lower() not in NOT_MEDICINE
        and (p.category or "").strip().lower() in OTC_INDICATIONS
    ]
    pharmacists = [u for u in staff if (u.role or "") in ("pharmacist", "admin")] or staff
    if not sellable or not pharmacists:
        return dict(made)

    now = datetime.now()
    for day in range(days):
        when = now - timedelta(days=day)
        if when.weekday() == 6:
            continue                       # Sunday; the counter is quiet
        for _ in range(RNG.randint(3, 11)):
            product = RNG.choice(sellable)
            reasons = OTC_INDICATIONS[(product.category or "").strip().lower()]
            referred = RNG.random() < 0.06
            db.add(OTCSale(
                product_id=product.id,
                quantity=RNG.choice([1, 1, 1, 2, 2, 3]),
                schedule=product.schedule or 0,
                customer_name="",           # most counter trade is anonymous
                pharmacist_id=RNG.choice(pharmacists).id,
                indication=RNG.choice(reasons),
                # A schedule 2 sold without counselling is the audit finding, so
                # it is not always true — but it is nearly always true.
                counselling_given=RNG.random() < 0.93,
                referred_to_doctor=referred,
                notes=RNG.choice(REFERRAL_NOTES) if referred else "",
                created_at=when.replace(hour=RNG.randint(8, 17),
                                        minute=RNG.randint(0, 59)),
            ))
            made["counter sales"] += 1
            if referred:
                made["referred to a doctor"] += 1
        if day % 10 == 0:
            db.commit()
    db.commit()
    return dict(made)


def _outreach(db: Session, patients, products, staff) -> dict[str, int]:
    """Reminders and campaigns, written the way a pharmacy writes them."""
    made = collections.Counter()
    if not patients or not products:
        return dict(made)

    for subject, body in zimdata.CAMPAIGN_TEMPLATES:
        campaign = Campaign(
            name=subject, channel="sms", segment="all",
            subject=subject, body=body, status="sent",
            audience_size=len(patients),
            sent_count=int(len(patients) * RNG.uniform(0.86, 0.98)),
            created_by_id=staff[0].id if staff else None,
            created_at=datetime.now() - timedelta(days=RNG.randint(3, 40)),
        )
        campaign.failed_count = campaign.audience_size - campaign.sent_count
        campaign.sent_at = campaign.created_at
        db.add(campaign)
        db.flush()
        for patient in RNG.sample(patients, min(len(patients), 45)):
            db.add(Message(
                patient_id=patient.id, channel="sms", message_type="campaign",
                subject=subject,
                body=body.format(name=patient.first_name),
                status=RNG.choices(["sent", "failed"], weights=[0.94, 0.06])[0],
                campaign_id=campaign.id,
                sent_at=campaign.created_at,
            ))
            made["campaign messages"] += 1
        made["campaigns"] += 1
    db.commit()

    # Birthdays, from the dates of birth already on file. A small feature, and
    # the one a patient actually remembers the pharmacy for.
    today = date.today()
    for patient in patients:
        if not patient.date_of_birth or patient.date_of_birth.month != today.month:
            continue
        db.add(Message(
            patient_id=patient.id, channel="sms", message_type="birthday",
            subject="Birthday",
            body=f"Happy birthday {patient.first_name}, from all of us at RX5000 "
                 f"Pharmacy. Come in this month for 10% off any front shop item.",
            status=RNG.choices(["sent", "queued"], weights=[0.9, 0.1])[0],
            sent_at=datetime.now() - timedelta(days=RNG.randint(0, 25)),
        ))
        made["birthday messages"] += 1
        if made["birthday messages"] >= 25:
            break

    # A handful typed by hand at the counter, which is what "free-type" means.
    HAND_WRITTEN = [
        "Good day {name}, the Coartem you asked about is now in stock.",
        "Hello {name}, your medical aid rejected the claim. Please call the scheme on the number on your card, then come back to us.",
        "{name}, we still have your change from Saturday. Ask for Kundai at the counter.",
        "Good day {name}, the doctor has phoned through a change to your script. Please come in before Friday.",
        "Hello {name}, we could not reach you on the number we have. Please confirm your phone number next time you are in.",
    ]
    for patient in RNG.sample(patients, min(len(patients), 18)):
        db.add(Message(
            patient_id=patient.id,
            channel=RNG.choices(["sms", "whatsapp"], weights=[0.6, 0.4])[0],
            message_type="custom",
            subject="",
            body=RNG.choice(HAND_WRITTEN).format(name=patient.first_name),
            status=RNG.choices(["sent", "failed"], weights=[0.92, 0.08])[0],
            sent_at=datetime.now() - timedelta(days=RNG.randint(0, 30)),
        ))
        made["counter messages"] += 1

    # Repeat reminders, against script lines that are genuinely due. Written
    # against real lines so the reminder screen and the repeats screen cannot
    # disagree about who is owed what.
    due = (db.query(PrescriptionItem)
             .filter(PrescriptionItem.next_repeat_date.isnot(None))
             .limit(160).all())
    for item in due:
        rx = db.get(Prescription, item.prescription_id)
        product = db.get(Product, item.product_id)
        if not rx or not product:
            continue
        patient = db.get(Patient, rx.patient_id)
        if not patient:
            continue
        template = RNG.choice(zimdata.REMINDER_TEMPLATES)
        db.add(Message(
            patient_id=patient.id,
            channel=RNG.choices(["sms", "whatsapp"], weights=[0.7, 0.3])[0],
            # "repeat", not "reminder".
            #
            # The Patient Adherence tabs filter on repeat / birthday / custom.
            # "reminder" reads correctly to a person and matches none of them, so
            # three of the four tabs were empty while 160 repeat reminders sat in
            # the table. The same mistake as the sale status: a value nothing
            # queries is a value that does not exist.
            message_type="repeat",
            subject="Repeat due",
            body=template.format(
                name=patient.first_name,
                product=f"{product.name} {product.strength or ''}".strip(),
                due=item.next_repeat_date.strftime("%d %b")),
            status=RNG.choices(["sent", "queued", "failed"], weights=[0.82, 0.12, 0.06])[0],
            scheduled_for=datetime.combine(item.next_repeat_date, datetime.min.time()),
            sent_at=datetime.now() - timedelta(days=RNG.randint(0, 20)),
        ))
        made["reminders"] += 1
    db.commit()
    return dict(made)


def _laybys(db: Session, patients, products, staff) -> dict[str, int]:
    """Lay-bys, which is how a $45 blood pressure monitor gets bought here.

    Not a fringe feature. A monitor is more than a week's grocery money, so it is
    paid off over a month and collected when it is clear. A pharmacy evaluating
    this looks for it early, and an empty lay-by screen reads as "not supported"
    rather than "none open today".
    """
    made = collections.Counter()
    dear = [p for p in products if (p.unit_price or 0) >= 6]
    if not (patients and dear and staff):
        return dict(made)

    for n in range(14):
        patient = RNG.choice(patients)
        lines = RNG.sample(dear, RNG.choice([1, 1, 2]))
        total = round(sum((p.unit_price or 0) * 1 for p in lines), 2)
        opened = datetime.now() - timedelta(days=RNG.randint(3, 70))
        status = RNG.choices(["open", "completed", "cancelled"],
                             weights=[0.55, 0.35, 0.10])[0]
        layby = LayBy(
            layby_number=f"LB{4200 + n}",
            patient_id=patient.id,
            status=status,
            total=total,
            minimum_deposit=round(total * 0.25, 2),
            due_date=(opened + timedelta(days=60)).date(),
            created_at=opened,
            created_by_id=RNG.choice(staff).id,
            completed_at=opened + timedelta(days=RNG.randint(20, 55)) if status == "completed" else None,
            cancelled_at=opened + timedelta(days=RNG.randint(30, 80)) if status == "cancelled" else None,
            cancellation_fee=round(total * 0.10, 2) if status == "cancelled" else 0,
        )
        db.add(layby)
        db.flush()
        for product in lines:
            db.add(LayByItem(layby_id=layby.id, product_id=product.id,
                             quantity=1, unit_price=product.unit_price))
        # Payments in the amounts people actually pay: a deposit, then whatever
        # is spare that week. Round figures, because that is what cash is.
        paid, when = 0.0, opened
        target = total if status == "completed" else round(total * RNG.uniform(0.25, 0.8), 2)
        while paid < target - 0.01:
            when = when + timedelta(days=RNG.randint(3, 14))
            if when > datetime.now():
                break
            amount = min(round(RNG.choice([5, 5, 10, 10, 20])), round(target - paid, 2))
            if amount <= 0:
                break
            db.add(LayByPayment(layby_id=layby.id, amount=amount, created_at=when,
                                method=RNG.choice(["cash", "ecocash"]),
                                currency_code="USD",
                                user_id=RNG.choice(staff).id))
            paid += amount
            made["layby payments"] += 1
        made["lay-bys"] += 1
    db.commit()
    return dict(made)


def _shifts(db: Session, staff, days: int) -> dict[str, int]:
    """A cash-up a day, with the variances a real drawer has.

    Every shift balancing to the cent is the tell that a demo was generated. A
    counter is out by a dollar or two most days: a note miscounted, change given
    from a pocket, a sale rung up in the wrong currency. The point of the screen
    is explaining a variance, not celebrating its absence.
    """
    made = collections.Counter()
    if not staff:
        return dict(made)

    for back in range(min(days, 45), 0, -1):
        day = (datetime.now() - timedelta(days=back)).replace(hour=8, minute=0, second=0, microsecond=0)
        rows = db.query(Sale).filter(
            Sale.created_at >= day,
            Sale.created_at < day + timedelta(days=1)).all()
        if not rows:
            continue
        cash = sum(s.total or 0 for s in rows if s.payment_method == "cash")
        card = sum(s.total or 0 for s in rows if s.payment_method in ("card", "swipe"))
        opening = 50.0
        expected = round(opening + cash, 2)
        # Out by a couple of dollars most days, exact about a third of the time.
        drift = RNG.choice([0, 0, 0, -2, -1, -0.5, 0.5, 1, 2, -5])
        db.add(Shift(
            user_id=RNG.choice(staff).id,
            opened_at=day,
            closed_at=day.replace(hour=22),
            opening_float=opening,
            expected_cash=expected,
            counted_cash=round(expected + drift, 2),
            variance=round(drift, 2),
            card_total=round(card, 2),
            sales_count=len(rows),
            status="closed",
            till_no="4",
            run_number=4067 + back,
            notes=("Short, note miscounted at hand over" if drift < -1 else
                   "Over, change given from float" if drift > 1 else ""),
            counted_by_id=RNG.choice(staff).id,
            counted_at=day.replace(hour=22, minute=20),
        ))
        made["cash-ups"] += 1
    db.commit()
    return dict(made)


def _crm(db: Session, staff) -> dict[str, int]:
    """Zimbabwean accounts, in place of the South African fixtures.

    The CRM side sells to clinics, mines, schools and corporates: the wholesale
    and occupational-health work that sits alongside the retail counter. What was
    there was Highveld Logistics and Piet van Zyl, which is a different country's
    demo.
    """
    made = collections.Counter()
    if not staff:
        return dict(made)

    # Children before parents. A deal has line items, activities, quotes and a
    # timeline hanging off it, and a lead can point at the deal it converted
    # into; deleting the parents first is a constraint failure, and the tables
    # involved are read out of the schema rather than remembered.
    deal_ids = [d.id for d in db.query(Deal).all()]
    lead_ids = [l.id for l in db.query(Lead).all()]
    for table, column in [("deal_items", "deal_id"), ("quotes", "deal_id"),
                          ("quote_lines", "deal_id"), ("activities", "deal_id"),
                          ("timeline_entries", "deal_id"), ("tasks", "deal_id"),
                          ("leads", "converted_deal_id")]:
        _delete_where_in(db, table, column, deal_ids)
    for table, column in [("activities", "lead_id"), ("timeline_entries", "lead_id"),
                          ("tasks", "lead_id")]:
        _delete_where_in(db, table, column, lead_ids)
    # `leads.converted_deal_id` is nulled rather than the lead deleted: the
    # delete above would take the lead with the deal, and a converted lead is a
    # record of how the deal was won.
    db.query(Lead).update({Lead.converted_deal_id: None}, synchronize_session=False)
    db.commit()
    _delete_where_in(db, "deals", "id", deal_ids)
    _delete_where_in(db, "leads", "id", lead_ids)
    db.commit()

    for i, (first, last, org, title, source, status, rating, value) in enumerate(zimdata.LEADS):
        db.add(Lead(
            first_name=first, last_name=last, company_name=org, job_title=title,
            email=f"{first.lower()}@{org.split()[0].lower()}.co.zw",
            phone=f"07{RNG.choice('1378')}{RNG.randint(1000000, 9999999)}",
            source=source, status=status, rating=rating,
            score=RNG.randint(20, 95), estimated_value=value,
            interest=RNG.choice(["Chronic medicine supply", "Occupational health",
                                 "Staff wellness screening", "First aid restocking"]),
            owner_id=RNG.choice(staff).id,
            marketing_opt_in=True,
            created_at=datetime.now() - timedelta(days=RNG.randint(2, 120)),
        ))
        made["leads"] += 1

    for i, (title, stage, value, probability, source) in enumerate(zimdata.DEALS):
        opened = datetime.now() - timedelta(days=RNG.randint(5, 150))
        db.add(Deal(
            title=title, value=value, stage=stage, probability=probability,
            expected_close_date=(opened + timedelta(days=RNG.randint(20, 90))).date(),
            owner_id=RNG.choice(staff).id, source=source,
            created_at=opened,
            closed_at=(opened + timedelta(days=RNG.randint(20, 90))
                       if stage in ("won", "lost") else None),
            lost_reason=("Went with the incumbent on price" if stage == "lost" else None),
        ))
        made["opportunities"] += 1
    db.commit()
    return dict(made)


def run_if_thin(db: Session, *, days: int = 60) -> dict[str, int]:
    """Load the demonstration pharmacy, but only into a database that has none.

    Called at startup so a fresh deployment comes up with something in it. Every
    seeding run so far has been `python -m app.realseed` on a laptop, which
    writes to the local SQLite file — and production is Neon Postgres, so none of
    it ever arrived. The screens were empty there for exactly that reason and no
    other.

    **Thin, not empty.** A database with the reference data and no trade is what
    a first boot looks like; one with four thousand sales in it is somebody's
    pharmacy and is never touched. The test is transactional volume rather than
    row count anywhere, because the schema seeds itself with schemes, a chart of
    accounts and a shorthand table before anybody has sold anything.

    Never destructive. `--wipe-all` is a thing a person types, deliberately, at a
    terminal; it is not something a deploy does on its own.
    """
    sales = db.query(Sale).count()
    if sales >= 200:
        return {}
    made: dict[str, int] = {}
    schemes = _schemes(db)
    products = _catalogue(db)
    staff = _staff(db)
    _prescribers(db)
    _branch(db)
    _suppliers(db)
    _people(db, schemes, target=180)

    patients = db.query(Patient).all()
    doctors = db.query(Doctor).all()
    cashiers = [u for u in staff if u.active]
    made["sales"] = _trading(db, days, products, patients, cashiers)
    made.update(_dispensary(db, days, products, patients, doctors, cashiers))
    made.update(_stock_and_supply(db, products, cashiers))
    made.update(_outreach(db, patients, products, cashiers))
    made.update(_laybys(db, patients, products, cashiers))
    made.update(_shifts(db, cashiers, days))
    made.update(_crm(db, cashiers))
    return made


def run(wipe_all: bool = False, days: int = 60) -> None:
    db = SessionLocal()
    try:
        if wipe_all:
            # Before the placeholder clear, not after. Emptying the transactional
            # tables removes most of what points at a placeholder product, so the
            # clear that follows has almost nothing left to untangle.
            print("clearing the transactional history…")
            # Children before parents, all the way down. The foreign keys were
            # read out of the schema rather than remembered: a dispensing points
            # at a prescription item, a batch allocation points at a sale item,
            # and deleting either parent first is a constraint failure halfway
            # through a wipe, which leaves the database in a worse state than it
            # started in.
            for table in [
                "batch_allocations", "stock_batches", "purchase_order_items",
                "purchase_orders", "campaigns",
                "register_entries", "dispensings",
                "owed_items", "script_changes", "reprints", "waybills",
                "message_acknowledgements", "sale_tenders", "fiscal_receipts",
                "claim_lines", "claims",
                "layby_payments", "layby_items", "laybys", "otc_sales",
                "sale_items", "sales",
                "prescription_items", "prescriptions", "messages",
            ]:
                try:
                    n = db.execute(text(f"DELETE FROM {table}")).rowcount
                    # Committed per table, not once at the end.
                    #
                    # A rollback undoes everything since the last commit, so one
                    # table failing on a constraint threw away the nine that had
                    # already succeeded — and the next run met the same wall with
                    # the same rows behind it. Committing each table means a
                    # failure costs that table and nothing else.
                    db.commit()
                except Exception as exc:  # noqa: BLE001 - a table this build lacks
                    print(f"  could not empty {table}: {str(exc).splitlines()[0][:70]}")
                    db.rollback()
                    continue
                if n:
                    print(f"  emptied {table} ({n})")

        print("clearing the placeholder rows…")
        cleared = _clear_placeholders(db)
        for k, v in cleared.items():
            print(f"  removed {v} {k}")

        print("loading reference data…")
        schemes = _schemes(db)
        print(f"  {len(schemes)} medical aid schemes")
        products = _catalogue(db)
        print(f"  {len(products)} products")
        staff = _staff(db)
        print(f"  {len(staff)} staff")
        retired = _retire_expired_demos(db)
        if retired:
            print(f"  deactivated {retired} expired demo account(s)")
        _prescribers(db)
        _branch(db)
        _suppliers(db)
        print(f"  {len(zimdata.DOCTORS)} prescribers, {len(zimdata.SUPPLIERS)} suppliers")

        made = _people(db, schemes, target=180)
        print(f"  {len(made)} new patients")

        patients = db.query(Patient).all()
        cashiers = (db.query(User)
                      .filter(User.active.is_(True), User.is_demo.is_(False))
                      .all())

        # `_trading` skips any day that already has sales, so this can be run
        # again after an interruption and will fill only the gaps. The old guard
        # counted total sales and refused once there were two hundred, which
        # blocked exactly the resume it was written to protect.
        print(f"filling in {days} days of counter trade…")
        n = _trading(db, days, products, patients, cashiers)
        print(f"  {n} sales" if n else "  every day already has trade")

        doctors = db.query(Doctor).all()
        # No wipe. `_dispensary` skips any day that already has scripts, the same
        # way trading does, so this resumes instead of starting over.
        #
        # It used to delete every prescription and dispensing before rebuilding,
        # which is defensible on a laptop where the whole stage takes twelve
        # seconds. Against a hosted database it is not: seed_remote retries on a
        # dropped connection, and every retry threw away the work of the one
        # before it. Watching it, the dispensing count went 30, then 0, then 56 —
        # a stage that could never finish while the connection kept dropping.
        print("filling in the dispensary…")
        for k, v in _dispensary(db, days, products, patients, doctors, cashiers).items():
                print(f"  {v} {k}")
        print("receiving stock…")
        for k, v in _stock_and_supply(db, products, cashiers).items():
            print(f"  {v} {k}")

        print("linking batches to what was sold…")
        for k, v in _allocate_batches(db).items():
            print(f"  {v} {k}")

        if db.query(Message).count() < 50:
            print("writing reminders and campaigns…")
            for k, v in _outreach(db, patients, products, cashiers).items():
                print(f"  {v} {k}")

        if db.query(LayBy).count() < 5:
            print("opening lay-bys…")
            for k, v in _laybys(db, patients, products, cashiers).items():
                print(f"  {v} {k}")

        if db.query(Shift).count() < 10:
            print("cashing up…")
            for k, v in _shifts(db, cashiers, days).items():
                print(f"  {v} {k}")

        if db.query(Lead).filter(Lead.company_name.like("%Zimplats%")).count() == 0:
            print("replacing the CRM fixtures…")
            for k, v in _crm(db, cashiers).items():
                print(f"  {v} {k}")

        print("writing up the compounding bench…")
        gone = _drop_sweep_mixtures(db)
        if gone:
            print(f"  removed {gone} placeholder mixture(s)")
        added = _raw_materials(db)
        if added:
            print(f"  {added} raw materials")
        products = db.query(Product).filter(Product.active.is_(True)).all()
        for k, v in _compounding(db, products).items():
            print(f"  {v} {k}")

        print("writing up the counter sales…")
        for k, v in _otc(db, products, staff, days).items():
            print(f"  {v} {k}")

        print("importing the remittance advices…")
        for k, v in _remittances(db).items():
            print(f"  {v} {k}")

        print("filling the delivery book…")
        for k, v in _deliveries(db, staff).items():
            print(f"  {v} {k}")

        print("invoicing the deliveries…")
        for k, v in _payables(db).items():
            print(f"  {v} {k}")

        # Last, because it reads what every stage before it wrote.
        print("writing up the books…")
        for k, v in _ledger(db).items():
            print(f"  {v} {k}")

        print("done.")
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wipe-all", action="store_true",
                    help="empty sales, scripts and messages first")
    ap.add_argument("--days", type=int, default=60)
    args = ap.parse_args()
    run(wipe_all=args.wipe_all, days=args.days)
    sys.exit(0)
