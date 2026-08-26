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
import collections
import random
import re
import sys
from datetime import date, datetime, timedelta

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from . import auth, zimdata
from .database import SessionLocal
from .models import (
    Campaign, Claim, Deal, Dispensing, Doctor, LayBy, LayByItem, LayByPayment,
    Lead, MedicalAid, Message, OwedItem, Patient, Prescription, PrescriptionItem,
    Product, PurchaseOrder, PurchaseOrderItem, RegisterEntry, Sale, SaleItem,
    Shift, StockBatch, Supplier, User,
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
    db.commit()
    return {k: v for k, v in counts.items() if v}


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
    rx_seq, claim_seq, owed_seq = 38100, 9100, 400
    balances: dict[int, int] = {}

    for back in range(days, -1, -1):
        day = start - timedelta(days=back)
        # 434 scripts in a fortnight at the pharmacy the figures came from, so
        # about thirty a day, and a Sunday is quieter.
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
        sales = (db.query(Sale)
                   .filter(Sale.patient_id.in_(list(by_id)))
                   .order_by(Sale.created_at.desc())
                   .limit(420).all())
        for sale in sales:
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
                settled_amount=(claimed if status == "approved" else
                                round(claimed * 0.6, 2) if status == "partial" else 0),
                settled_at=(sale.created_at + timedelta(days=RNG.randint(14, 45))
                            if status in ("approved", "partial") else None),
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

    today = date.today()
    for i, product in enumerate(products):
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

    low = [p for p in products if (p.quantity_on_hand or 0) <= (p.reorder_level or 0)]
    for n, supplier in enumerate(suppliers):
        lines = RNG.sample(low, min(len(low), RNG.randint(3, 8))) if low else []
        if not lines:
            continue
        status = RNG.choice(["draft", "sent", "sent", "received"])
        order = PurchaseOrder(
            order_number=f"PO2026{1000 + n}",
            supplier_id=supplier.id,
            status=status,
            created_at=datetime.now() - timedelta(days=RNG.randint(1, 30)),
        )
        db.add(order)
        db.flush()
        for product in lines:
            want = RNG.choice([20, 30, 50, 100])
            db.add(PurchaseOrderItem(
                order_id=order.id, product_id=product.id,
                quantity_ordered=want,
                quantity_received=want if status == "received" else 0,
                unit_cost=product.cost_price or 0,
            ))
        made["purchase orders"] += 1
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
        if db.query(Prescription).count() < 50 or db.query(Dispensing).count() < 50:
            print("filling in the dispensary…")
            # Rebuilding means the old scripts go too, or the next run stacks a
            # second set of items on prescriptions that already have them.
            for table in ["register_entries", "owed_items", "dispensings",
                          "prescription_items", "prescriptions"]:
                _delete_where_in(db, table, "id",
                                 [r[0] for r in db.execute(text(f"SELECT id FROM {table}"))])
            for k, v in _dispensary(db, days, products, patients, doctors, cashiers).items():
                print(f"  {v} {k}")
        else:
            print("skipping the dispensary: scripts already recorded")

        if wipe_all or db.query(StockBatch).count() < 50:
            print("receiving stock…")
            for k, v in _stock_and_supply(db, products, cashiers).items():
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
