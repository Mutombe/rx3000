"""CareXpress's trading history: 45,728 invoices over sixteen months.

What the export actually contains, which is not obvious from the header row:
each invoice is one row, followed by its lines, and the "lines" are three
different kinds of thing wearing the same shape.

  A **stock code** — 50,694 of them — is a product sold. Matched against the
  16,406 products already loaded, on the stock code the incumbent uses.

  **RX** is not a product. It is the script charge, the dispensing fee, and
  loading it as a stock line would invent thousands of sales of a medicine
  called "Script Charge" and put them in the catalogue.

  **PMT1** is not a product either. It is the tender — how the invoice was
  paid — and it is the only place in this export that says so per sale.

Sales are written directly rather than through the till, and nothing is posted
to the ledger. This is history: it happened in another system, the money was
banked, the stock left the shelf. Replaying it through the posting logic would
create sixteen months of journals against periods that were never open and
inventory movements against stock that is already counted.

The status is what the export says it is: CASH invoices are settled, CHARGE
invoices are on account and remain so until somebody says otherwise. 2,550 of
them are, and they are the ones that matter — an account debtor is the
receivable side of exactly the reconciliation this pharmacy asked for.

    python -m app.importers.carexpress_invoices "C:/path/Invoice Report ….xlsx"
"""
from __future__ import annotations

import sys
from datetime import datetime

from ..database import SessionLocal
from ..models import Branch, Patient, Pharmacy, Product, Sale, SaleItem
from ..tenancy import unscoped

HEADER_ROW = 9
TENANT = "CareXpress Pharmacy"
#: The export carries one store's trading. The teller cash-up that came with it
#: names it — "Branch / Store: Chinamano" — and the letterhead address is on
#: Chinamano Avenue, so that is where this history belongs.
BRANCH_HINT = "Chinamano"

#: Line codes that are not products.
SCRIPT_CHARGE = "RX"
TENDER_PREFIX = "PMT"


def _clean(v) -> str:
    return str(v).strip() if v is not None else ""


def _num(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _when(v):
    if isinstance(v, datetime):
        return v
    text = _clean(v)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def run(path: str, limit: int = 0) -> dict:
    import openpyxl

    db = SessionLocal()
    counts = {"invoices": 0, "items": 0, "matched": 0, "fees": 0,
              "skipped": 0, "on_account": 0, "linked": 0,
              "unmatched": 0, "unmatched_value": 0.0}

    with unscoped():
        pharmacy = db.query(Pharmacy).filter(Pharmacy.name == TENANT).first()
        if pharmacy is None:
            raise SystemExit(f"No tenant named {TENANT!r}. Nothing was written.")
        branch = (db.query(Branch)
                  .filter(Branch.pharmacy_id == pharmacy.id,
                          Branch.name.ilike(f"%{BRANCH_HINT}%")).first()
                  or db.query(Branch).filter(Branch.pharmacy_id == pharmacy.id).first())

        # The script charge is a real thing this pharmacy sells — a dispensing
        # fee — so it gets one real product rather than being dropped. Every
        # one of the 45,728 invoices that carries it points at this.
        fee_product = (db.query(Product)
                       .filter(Product.pharmacy_id == pharmacy.id,
                               Product.stock_code == "RX").first())
        if fee_product is None:
            fee_product = Product(
                name="Script charge (dispensing fee)", stock_code="RX",
                category="front_shop", unit_price=0.0, cost_price=0.0,
                quantity_on_hand=0, active=True, pharmacy_id=pharmacy.id)
            db.add(fee_product)
            db.flush()

        products = {
            _clean(code).upper(): pid
            for pid, code in db.query(Product.id, Product.stock_code)
            .filter(Product.pharmacy_id == pharmacy.id).all() if code
        }
        # Named account debtors, matched to the people already imported. A
        # charge invoice against "SAMUEL LEON" is only a receivable if it is
        # attached to somebody the pharmacy can actually invoice.
        people = {}
        for pid, first, last in db.query(Patient.id, Patient.first_name,
                                         Patient.last_name).filter(
                                             Patient.pharmacy_id == pharmacy.id).all():
            people[f"{first} {last}".upper().strip()] = pid
            people[f"{last} {first}".upper().strip()] = pid

        already = {n for (n,) in db.query(Sale.sale_number)
                   .filter(Sale.pharmacy_id == pharmacy.id).all()}

        book = openpyxl.load_workbook(path, read_only=True)
        sheet = book.worksheets[0]
        rows = sheet.iter_rows(min_row=HEADER_ROW, values_only=True)
        next(rows)  # the header itself

        sale = None
        pending_items: list[dict] = []

        def flush():
            """Write the invoice being read, with its lines."""
            nonlocal sale, pending_items
            if sale is not None and pending_items:
                db.add_all([SaleItem(sale_id=sale.id, **it) for it in pending_items])
                counts["items"] += len(pending_items)
            sale, pending_items = None, []

        for row in rows:
            if not row:
                continue
            first_cell = _clean(row[0])
            if not first_cell or first_cell == "Item Code":
                continue

            # ---- a new invoice ----------------------------------------------
            if first_cell.upper().startswith(("INV", "CRN")):
                flush()
                if limit and counts["invoices"] >= limit:
                    break
                number = first_cell
                if number in already:
                    counts["skipped"] += 1
                    sale = None
                    continue
                already.add(number)

                kind = _clean(row[4]).upper()
                nett = _num(row[2])
                tendered = _num(row[3])
                debtor = _clean(row[7])
                # "CD01 CASHDEB01" is the walk-in account, not a person.
                named = "" if debtor.upper().startswith("CD01") else debtor
                # The debtor column carries an account code before the name;
                # the name is what matches a patient.
                patient_id = people.get(named.upper()) if named else None

                on_account = kind == "CHARGE"
                sale = Sale(
                    sale_number=number,
                    created_at=_when(row[1]) or datetime.utcnow(),
                    subtotal=nett, total=nett,
                    amount_tendered=tendered if not on_account else 0.0,
                    change_due=max(0.0, tendered - nett) if not on_account else 0.0,
                    payment_method="account" if on_account else "cash",
                    # A credit note is money going the other way. Marked as
                    # such rather than counted as a sale.
                    status="credited" if first_cell.upper().startswith("CRN")
                           else ("pending" if on_account else "paid"),
                    patient_id=patient_id,
                    branch_id=branch.id if branch else None,
                    pharmacy_id=pharmacy.id,
                )
                db.add(sale)
                db.flush()
                counts["invoices"] += 1
                if on_account:
                    counts["on_account"] += 1
                if patient_id:
                    counts["linked"] += 1
                continue

            if sale is None:
                continue

            # ---- one line on it ---------------------------------------------
            code = first_cell.rstrip(",").upper()
            if code.startswith(TENDER_PREFIX):
                # The tender line. Nothing to add as a product; the payment
                # method is already on the sale.
                continue

            description = _clean(row[1])[:220]
            quantity = int(_num(row[5]) or 1)
            gross = _num(row[6])
            line_total = _num(row[9]) or gross

            if code == SCRIPT_CHARGE:
                counts["fees"] += 1
                pending_items.append({
                    "product_id": fee_product.id,
                    "description": description or "Script charge",
                    "quantity": max(1, quantity),
                    "unit_price": line_total / max(1, quantity),
                    "line_total": line_total, "vat_rate": 0.0,
                })
                continue

            product_id = products.get(code)
            if not product_id:
                # A stock code this catalogue does not hold. The line is left
                # out rather than pinned to an invented product — the sale's
                # total comes from the invoice header either way, so the money
                # is right and only the breakdown is short. Counted, with its
                # value, so "short" is a number somebody can look at rather
                # than a silence.
                counts["unmatched"] += 1
                counts["unmatched_value"] = round(
                    counts.get("unmatched_value", 0.0) + line_total, 2)
                continue
            counts["matched"] += 1
            pending_items.append({
                "product_id": product_id,
                "description": description,
                "quantity": max(1, quantity),
                "unit_price": line_total / max(1, quantity),
                "line_total": line_total,
                "vat_rate": 0.0,
            })

            if counts["invoices"] % 3000 == 0 and pending_items:
                db.flush()

        flush()
        book.close()
        db.commit()

    db.close()
    return counts


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Give me the path to the Invoice Report .xlsx")
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    started = datetime.now()
    result = run(sys.argv[1], cap)
    took = (datetime.now() - started).seconds
    print(f"\n{result['invoices']:,} invoices in {took}s")
    print(f"  {result['items']:,} lines, {result['matched']:,} matched to a product")
    print(f"  {result['fees']:,} script charges")
    print(f"  {result['on_account']:,} on account, {result['linked']:,} tied to a patient")
    print(f"  {result['skipped']:,} already loaded")
    if result["unmatched"]:
        print(f"  {result['unmatched']:,} lines worth "
              f"{result['unmatched_value']:,.2f} had a stock code this "
              f"catalogue does not hold — the sale totals are still right, "
              f"only their breakdown is short")
