"""Dispense for real, against the real database, and put it all back.

    python rehearse_remote.py --pharmacy 5
    python rehearse_remote.py --pharmacy 5 --branch 6

Every check runs the pharmacy's OWN code against the pharmacy's OWN data inside
a transaction that is rolled back at the end. Nothing is committed: no sale, no
stock movement, no register entry, no number burned. What it proves is that the
paths a counter uses would work today, on this data, at each branch, which is
not a thing a local test on seeded data can tell anybody.

It exists because the faults that actually reached CareXpress were all of this
shape. The stock was on one branch and the dispenser stood at another; the
opening batches were undated so nothing could be drawn; the search counted the
whole pharmacy while the counter drew from one shelf. Each was invisible to a
test suite and obvious the moment somebody tried to dispense.

    python rehearse_remote.py --pharmacy 5
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
parser.add_argument("--branch", type=int, default=None, help="only this branch")
args = parser.parse_args()

os.environ["DATABASE_URL"] = _target()

from sqlalchemy import func                                      # noqa: E402
from app.database import SessionLocal                            # noqa: E402
from app import helpers, models as m, schedule_policy            # noqa: E402
from app.services import branches as branch_svc, pricing         # noqa: E402
from app.tenancy import set_current_pharmacy, unscoped           # noqa: E402

fails: list[str] = []
notes: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}"
          + (f"   ({detail})" if detail and not ok else
             f"   {detail}" if detail else ""))
    if not ok:
        fails.append(label)
    return ok


print(f"target: {os.environ['DATABASE_URL'].split('@')[-1].split('/')[0]}")

with unscoped():
    token = set_current_pharmacy(args.pharmacy)
    db = SessionLocal()
    try:
        pharmacy = db.get(m.Pharmacy, args.pharmacy)
        print(f"pharmacy: {pharmacy.name if pharmacy else args.pharmacy}\n")

        shops = (db.query(m.Branch)
                 .filter(m.Branch.pharmacy_id == args.pharmacy)
                 .order_by(m.Branch.id).all())
        if args.branch:
            shops = [b for b in shops if b.id == args.branch]

        for branch in shops:
            print(f"\n=== {branch.name} (branch {branch.id}) "
                  f"{'[default]' if branch.is_default else ''} ===")

            held = (db.query(func.coalesce(func.sum(m.StockBatch.quantity_remaining), 0))
                    .filter(m.StockBatch.branch_id == branch.id).scalar() or 0)
            lines = (db.query(func.count(func.distinct(m.StockBatch.product_id)))
                     .filter(m.StockBatch.branch_id == branch.id,
                             m.StockBatch.quantity_remaining > 0).scalar() or 0)
            dated = (db.query(func.coalesce(func.sum(m.StockBatch.quantity_remaining), 0))
                     .filter(m.StockBatch.branch_id == branch.id,
                             m.StockBatch.expiry_date >= date.today()).scalar() or 0)
            undated = (db.query(func.coalesce(func.sum(m.StockBatch.quantity_remaining), 0))
                       .filter(m.StockBatch.branch_id == branch.id,
                               m.StockBatch.expiry_date.is_(None)).scalar() or 0)
            expired = (db.query(func.coalesce(func.sum(m.StockBatch.quantity_remaining), 0))
                       .filter(m.StockBatch.branch_id == branch.id,
                               m.StockBatch.expiry_date < date.today()).scalar() or 0)
            print(f"  shelf: {int(held):,} units over {lines:,} products "
                  f"({int(dated):,} in date, {int(undated):,} undated, {int(expired):,} expired)")

            staff = (db.query(m.User)
                     .filter(m.User.pharmacy_id == args.pharmacy,
                             m.User.branch_id == branch.id,
                             m.User.active.is_(True)).all())
            check("somebody works at this branch", bool(staff),
                  f"{len(staff)} active" if staff else "nobody is posted here")
            if not staff:
                notes.append(f"{branch.name}: no active staff are posted here, so "
                             "nobody would draw from this shelf")
                continue
            who = staff[0]

            if lines == 0:
                check("this branch has stock to dispense", False,
                      "the shelf is empty, so every dispensing here would be refused")
                notes.append(f"{branch.name}: the shelf is empty")
                continue

            # A medicine this branch actually holds, that the dispensary would
            # offer on a script.
            candidates = (db.query(m.Product, m.StockBatch)
                          .join(m.StockBatch, m.StockBatch.product_id == m.Product.id)
                          .filter(m.Product.pharmacy_id == args.pharmacy,
                                  m.Product.active.is_(True),
                                  m.StockBatch.branch_id == branch.id,
                                  m.StockBatch.quantity_remaining >= 5)
                          .limit(400).all())
            dispensable = []
            for product, batch in candidates:
                policy = schedule_policy.policy_for(product.schedule or 0)
                if policy.route != "prohibited":
                    dispensable.append((product, batch))
            check("the shelf holds medicines a script may carry", bool(dispensable),
                  f"{len(dispensable)} of {len(candidates)} sampled")
            if not dispensable:
                continue

            product, batch = dispensable[0]
            print(f"  rehearsing on: {product.name[:44]}")

            # --- what the counter would be told -----------------------------
            here_dated = helpers.dated_stock(db, product, branch.id)
            here_undated, here_expired = helpers.stock_without_a_good_date(db, product, branch.id)
            print(f"    this branch holds: {here_dated} in date, "
                  f"{here_undated} undated, {here_expired} expired")

            # --- the draw itself, rolled back -------------------------------
            want = 1
            before = int(product.quantity_on_hand or 0)
            if here_dated >= want:
                try:
                    helpers.consume_stock_fefo(db, product, want, "sale", who.id,
                                               reference="REHEARSAL", branch_id=branch.id)
                    db.flush()
                    db.refresh(product)
                    check("a dispensing draws from this branch's shelf",
                          int(product.quantity_on_hand or 0) == before - want,
                          f"{before} to {product.quantity_on_hand}")
                except Exception as exc:                          # noqa: BLE001
                    check("a dispensing draws from this branch's shelf", False,
                          str(getattr(exc, "detail", exc))[:110])
                db.rollback()
                db.expire_all()
            else:
                # Undated stock is the CareXpress case: real stock the counter
                # cannot draw until somebody reads the date off the pack.
                refused = ""
                try:
                    helpers.consume_stock_fefo(db, product, want, "sale", who.id,
                                               reference="REHEARSAL", branch_id=branch.id)
                except Exception as exc:                          # noqa: BLE001
                    refused = str(getattr(exc, "detail", exc))
                db.rollback()
                db.expire_all()
                check("undated stock is refused with the reason, not a bare shortage",
                      "expiry" in refused.lower() or "no expiry" in refused.lower(),
                      refused[:104] or "it was not refused at all")
                check("…and the refusal tells the counter what to do about it",
                      "pack" in refused.lower(),
                      refused[:104])

                # And the counter's own remedy: read the date off the pack.
                try:
                    helpers.date_undated_stock(db, product, date.today() + timedelta(days=365),
                                               who.id, branch_id=branch.id)
                    db.flush()
                    now_dated = helpers.dated_stock(db, product, branch.id)
                    ok = now_dated > 0
                    if ok:
                        helpers.consume_stock_fefo(db, product, want, "sale", who.id,
                                                   reference="REHEARSAL", branch_id=branch.id)
                        db.flush()
                    check("dating it from the pack makes it dispensable", ok,
                          f"{here_undated} undated became {now_dated} in date")
                except Exception as exc:                          # noqa: BLE001
                    check("dating it from the pack makes it dispensable", False,
                          str(getattr(exc, "detail", exc))[:110])
                db.rollback()
                db.expire_all()

            # --- pricing, which is what the patient is charged ---------------
            each = product.per_unit()
            check("the medicine carries a price", each > 0, f"{each:.4f} a unit")
            aid = db.query(m.MedicalAid).order_by(m.MedicalAid.id).first()
            if aid:
                priced = pricing.price_line(db, product, 1, aid)
                check(f"a {aid.name} line prices without error",
                      priced.gross >= 0, f"gross {priced.gross:.2f}, "
                      f"scheme {priced.claimable:.2f}, patient {priced.patient_portion:.2f}")

            # --- the numbers a dispensing needs ------------------------------
            try:
                number = helpers.next_number(db, m.Sale, "INV", "sale_number")
                check("an invoice number can be issued", bool(number), number)
            except Exception as exc:                              # noqa: BLE001
                check("an invoice number can be issued", False, str(exc)[:110])
            db.rollback()

        # --- things that are true of the whole pharmacy ----------------------
        print("\n=== the pharmacy as a whole ===")
        ledger = (db.query(func.coalesce(func.sum(m.StockBatch.quantity_remaining), 0))
                  .join(m.Product, m.Product.id == m.StockBatch.product_id)
                  .filter(m.Product.pharmacy_id == args.pharmacy).scalar() or 0)
        onhand = (db.query(func.coalesce(func.sum(m.Product.quantity_on_hand), 0))
                  .filter(m.Product.pharmacy_id == args.pharmacy).scalar() or 0)
        check("the batch ledger agrees with what the products claim",
              abs(int(ledger) - int(onhand)) <= max(50, int(onhand) * 0.005),
              f"batches {int(ledger):,} against on-hand {int(onhand):,}")

        orphans = (db.query(func.count(m.StockBatch.id))
                   .join(m.Product, m.Product.id == m.StockBatch.product_id)
                   .filter(m.Product.pharmacy_id == args.pharmacy,
                           m.StockBatch.branch_id.is_(None)).scalar() or 0)
        check("no batch is sitting at no branch at all", orphans == 0, f"{orphans:,}")

        dupes = (db.query(m.StockBatch.product_id, m.StockBatch.branch_id)
                 .join(m.Product, m.Product.id == m.StockBatch.product_id)
                 .filter(m.Product.pharmacy_id == args.pharmacy,
                         m.StockBatch.batch_number == "OPENING")
                 .group_by(m.StockBatch.product_id, m.StockBatch.branch_id)
                 .having(func.count(m.StockBatch.id) > 1).count())
        check("no product has the same opening batch twice", dupes == 0, f"{dupes:,}")

        priced = (db.query(func.count(m.Product.id))
                  .filter(m.Product.pharmacy_id == args.pharmacy,
                          m.Product.active.is_(True),
                          m.Product.unit_price > 0).scalar() or 0)
        live = (db.query(func.count(m.Product.id))
                .filter(m.Product.pharmacy_id == args.pharmacy,
                        m.Product.active.is_(True)).scalar() or 0)
        check("nearly every product on sale carries a price",
              live and priced / live > 0.95, f"{priced:,} of {live:,}")

        prescribers = (db.query(func.count(m.Doctor.id))
                       .filter(m.Doctor.pharmacy_id == args.pharmacy,
                               m.Doctor.active.is_(True)).scalar() or 0)
        check("there are prescribers to capture a script against", prescribers > 0,
              f"{prescribers:,} not retired")
    finally:
        db.rollback()
        db.close()

print("\n" + ("=" * 60))
if notes:
    print("\nworth knowing:")
    for n in notes:
        print(f"  - {n}")
print(f"\n{len(fails)} check(s) failed" if fails else "\nevery check passed")
for f in fails:
    print(f"    {f}")
print("nothing was committed: every change was rolled back.")
sys.exit(1 if fails else 0)
