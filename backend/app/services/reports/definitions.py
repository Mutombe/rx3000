"""The report catalogue.

Each entry is a declaration. If one of these needs more than about forty lines,
that is a signal the engine is missing something the report should not have to
solve on its own.

This first batch is chosen to exercise every part of the engine — a date range,
a select, a branch filter, money and percent columns, footer totals, a
drill-down and a step-up — so that the reports added after it have a worked
example of every shape they might need.
"""
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ...models import (
    Dispensing, Patient, Prescription, PrescriptionItem, Product, Sale, SaleItem,
    SaleTender, StockBatch, StockMovement, Supplier, User,
)
from .engine import Column, Param, Report, days_ago, month_start, register, today


def _branch_options(db: Session):
    from ...models import Branch
    return [{"value": "", "label": "All branches"}] + [
        {"value": b.id, "label": b.name}
        for b in db.query(Branch).order_by(Branch.name).all()
    ]


DATE_FROM = Param("date_from", "From", "date", default=month_start)
DATE_TO = Param("date_to", "To", "date", default=today)
BRANCH = Param("branch_id", "Branch", "select", options=_branch_options)


def line_cost():
    """What a sold line cost us, as one rule used by every margin report.

    Two sources, and neither is right on its own. `SaleItem.unit_cost` is the
    cost captured when the sale happened, which is the correct figure for a
    historical period — but it is absent on 39% of the lines in this database,
    because it was added after trading began. `Product.cost_price` is always
    present but is *today's* cost, which silently restates last year's margin
    every time a supplier raises a price.

    So: the captured cost where there is one, today's cost where there is not.
    Stated once here because two reports using two different rules disagreed
    about the same period's gross profit by more than two hundred thousand, and
    both looked authoritative.
    """
    return func.coalesce(func.nullif(SaleItem.unit_cost, 0), Product.cost_price, 0)


def _sales_in(db: Session, p: dict):
    query = db.query(Sale).filter(
        func.date(Sale.created_at) >= p["date_from"],
        func.date(Sale.created_at) <= p["date_to"],
    )
    if p.get("branch_id"):
        query = query.filter(Sale.branch_id == int(p["branch_id"]))
    return query


# --------------------------------------------------------------- till / POS

register(Report(
    key="sales_by_hour",
    title="Sales by hour",
    module="Till",
    purpose="Which hours actually take money, so staffing matches trade rather "
            "than habit.",
    params=[DATE_FROM, DATE_TO, BRANCH],
    columns=[
        Column("hour", "Hour", "text"),
        Column("transactions", "Transactions", "number", total=True),
        Column("units", "Items", "number", total=True),
        Column("amount", "Takings", "money", total=True),
        Column("average", "Average sale", "money"),
    ],
    rows=lambda db, p: _sales_by_hour(db, p),
))


def _sales_by_hour(db: Session, p: dict):
    # Two aggregate queries rather than a walk over every sale and its items.
    base = (
        db.query(Sale)
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .filter(Sale.status != "void")
    )
    if p.get("branch_id"):
        base = base.filter(Sale.branch_id == int(p["branch_id"]))

    buckets = {}
    for sale_id, created, total in base.with_entities(
            Sale.id, Sale.created_at, Sale.total).all():
        hour = created.hour
        row = buckets.setdefault(hour, {
            "hour": "%02d:00" % hour, "transactions": 0, "units": 0, "amount": 0.0,
        })
        row["transactions"] += 1
        row["amount"] = round(row["amount"] + float(total or 0), 2)

    units_q = (
        db.query(func.sum(SaleItem.quantity), Sale.created_at)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .filter(Sale.status != "void")
    )
    if p.get("branch_id"):
        units_q = units_q.filter(Sale.branch_id == int(p["branch_id"]))
    for quantity, created in units_q.group_by(Sale.created_at).all():
        row = buckets.get(created.hour)
        if row:
            row["units"] += int(quantity or 0)

    rows = []
    for row in buckets.values():
        # An hour the shop was shut is not a finding, it is noise.
        if not row["transactions"]:
            continue
        row["average"] = round(row["amount"] / row["transactions"], 2)
        rows.append(row)
    rows.sort(key=lambda r: r["hour"])
    return rows


register(Report(
    key="department_sales",
    title="Department sales",
    module="Till",
    purpose="What each category contributes, and at what margin.",
    params=[DATE_FROM, DATE_TO, BRANCH],
    columns=[
        Column("department", "Department", "text"),
        Column("units", "Units", "number", total=True),
        Column("amount", "Sales", "money", total=True),
        Column("cost", "Cost", "money", total=True),
        Column("profit", "Gross profit", "money", total=True),
        Column("margin", "Margin", "percent"),
    ],
    rows=lambda db, p: _department_sales(db, p),
))


def _department_sales(db: Session, p: dict):
    # Aggregated in the database rather than by walking every sale in Python.
    # The Python version issued one query per sale to reach its items, which on
    # a few thousand sales was slow enough that the browser gave up on the
    # request before it answered — a report nobody can wait for is a report
    # nobody has.
    query = (
        db.query(
            Product.category,
            func.sum(SaleItem.quantity),
            func.sum(SaleItem.unit_price * SaleItem.quantity),
            func.sum(line_cost() * SaleItem.quantity),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .filter(Sale.status != "void")
    )
    if p.get("branch_id"):
        query = query.filter(Sale.branch_id == int(p["branch_id"]))

    rows = []
    for category, units, amount, cost in query.group_by(Product.category).all():
        amount = round(float(amount or 0), 2)
        cost = round(float(cost or 0), 2)
        rows.append({
            "department": (category or "uncategorised").replace("_", " "),
            "units": int(units or 0),
            "amount": amount,
            "cost": cost,
            "profit": round(amount - cost, 2),
            "margin": round((amount - cost) / amount * 100, 1) if amount else 0.0,
        })
    rows.sort(key=lambda r: -r["amount"])
    return rows


register(Report(
    key="cashier_performance",
    title="Cashier report",
    module="Till",
    purpose="Takings, transaction count and average basket by the person who "
            "served. Also where a variance pattern shows up.",
    params=[DATE_FROM, DATE_TO, BRANCH],
    # Who took how much is about a named person, so it sits behind the same
    # override the incumbent puts on it.
    step_up=True,
    columns=[
        Column("cashier", "Cashier", "text"),
        Column("transactions", "Transactions", "number", total=True),
        Column("amount", "Takings", "money", total=True),
        Column("average", "Average basket", "money"),
        Column("voids", "Voids", "number", total=True),
    ],
    rows=lambda db, p: _cashier_performance(db, p),
))


def _cashier_performance(db: Session, p: dict):
    groups: dict[int, dict] = {}
    for sale in _sales_in(db, p).all():
        key = sale.cashier_id or 0
        row = groups.setdefault(key, {
            "cashier": "(not recorded)", "transactions": 0,
            "amount": 0.0, "voids": 0, "_id": key,
        })
        if (sale.status or "") == "void":
            row["voids"] += 1
            continue
        row["transactions"] += 1
        row["amount"] = round(row["amount"] + (sale.total or 0), 2)
    names = {
        u.id: (u.full_name or u.username)
        for u in db.query(User).filter(User.id.in_([k for k in groups if k])).all()
    }
    rows = []
    for key, row in groups.items():
        row["cashier"] = names.get(key, row["cashier"])
        row["average"] = round(row["amount"] / row["transactions"], 2) if row["transactions"] else 0.0
        row.pop("_id", None)
        rows.append(row)
    rows.sort(key=lambda r: -r["amount"])
    return rows


# ------------------------------------------------------------------- stock

register(Report(
    key="expiring_stock",
    title="Expiring stock",
    module="Stock",
    purpose="What will expire on the shelf, while there is still time to move "
            "it or return it.",
    params=[
        Param("days", "Expiring within (days)", "text", default="90"),
        BRANCH,
    ],
    columns=[
        Column("product", "Product", "text"),
        Column("batch", "Batch", "code"),
        Column("expiry", "Expires", "date"),
        Column("days_left", "Days left", "number"),
        Column("quantity", "On hand", "number", total=True),
        Column("value", "Value at cost", "money", total=True),
    ],
    rows=lambda db, p: _expiring(db, p),
    drill=lambda row: f"/products/{row.get('product_id')}",
))


def _expiring(db: Session, p: dict):
    try:
        days = max(1, int(p.get("days") or 90))
    except (TypeError, ValueError):
        days = 90
    horizon = date.today() + timedelta(days=days)
    query = (
        db.query(StockBatch)
        .filter(StockBatch.quantity_remaining > 0)
        .filter(StockBatch.expiry_date.isnot(None))
        .filter(StockBatch.expiry_date <= horizon)
    )
    if p.get("branch_id"):
        query = query.filter(StockBatch.branch_id == int(p["branch_id"]))
    rows = []
    for batch in query.order_by(StockBatch.expiry_date.asc()).all():
        product = db.query(Product).get(batch.product_id)
        cost = (product.cost_price if product else 0) or 0
        rows.append({
            "product_id": batch.product_id,
            "product": product.name if product else f"#{batch.product_id}",
            "batch": batch.batch_number,
            "expiry": batch.expiry_date.isoformat() if batch.expiry_date else "",
            "days_left": (batch.expiry_date - date.today()).days if batch.expiry_date else None,
            "quantity": batch.quantity_remaining,
            "value": round(cost * batch.quantity_remaining, 2),
        })
    return rows


register(Report(
    key="dead_stock",
    title="Dead stock",
    module="Stock",
    purpose="Money sitting on a shelf that has not moved. The most expensive "
            "thing in a pharmacy that nobody has a report for.",
    params=[
        Param("days", "No movement for (days)", "text", default="90"),
        BRANCH,
    ],
    columns=[
        Column("product", "Product", "text"),
        Column("category", "Department", "text"),
        Column("quantity", "On hand", "number", total=True),
        Column("value", "Value at cost", "money", total=True),
        Column("last_sold", "Last sold", "date"),
        Column("days_idle", "Days idle", "number"),
    ],
    rows=lambda db, p: _dead_stock(db, p),
    drill=lambda row: f"/products/{row.get('product_id')}",
))


def _dead_stock(db: Session, p: dict):
    try:
        days = max(1, int(p.get("days") or 90))
    except (TypeError, ValueError):
        days = 90
    cutoff = date.today() - timedelta(days=days)

    last_sale = dict(
        db.query(StockMovement.product_id, func.max(StockMovement.created_at))
        .filter(StockMovement.movement_type == "sale")
        .group_by(StockMovement.product_id)
        .all()
    )
    rows = []
    for product in db.query(Product).filter(Product.active, Product.quantity_on_hand > 0).all():
        when = last_sale.get(product.id)
        if when and when.date() > cutoff:
            continue
        rows.append({
            "product_id": product.id,
            "product": product.name,
            "category": (product.category or "").replace("_", " "),
            "quantity": product.quantity_on_hand,
            "value": round((product.cost_price or 0) * product.quantity_on_hand, 2),
            "last_sold": when.date().isoformat() if when else "",
            # Never sold is worse than sold long ago, so it sorts to the top
            # rather than being left blank and drifting to the bottom.
            "days_idle": (date.today() - when.date()).days if when else 9999,
        })
    rows.sort(key=lambda r: -r["value"])
    return rows


register(Report(
    key="stock_valuation",
    title="Stock valuation",
    module="Stock",
    purpose="What the shelves are worth, at cost and at retail, with the "
            "margin held in stock.",
    params=[BRANCH],
    columns=[
        Column("category", "Department", "text"),
        Column("lines", "Products", "number", total=True),
        Column("units", "Units", "number", total=True),
        Column("cost_value", "At cost", "money", total=True),
        Column("retail_value", "At retail", "money", total=True),
        Column("margin", "Margin", "percent"),
    ],
    rows=lambda db, p: _valuation(db, p),
))


def _valuation(db: Session, p: dict):
    groups: dict[str, dict] = {}
    for product in db.query(Product).filter(Product.active).all():
        quantity = product.quantity_on_hand or 0
        if quantity <= 0:
            continue
        key = (product.category or "uncategorised").replace("_", " ")
        row = groups.setdefault(key, {
            "category": key, "lines": 0, "units": 0,
            "cost_value": 0.0, "retail_value": 0.0,
        })
        row["lines"] += 1
        row["units"] += quantity
        row["cost_value"] = round(row["cost_value"] + (product.cost_price or 0) * quantity, 2)
        row["retail_value"] = round(row["retail_value"] + (product.unit_price or 0) * quantity, 2)
    rows = []
    for row in groups.values():
        retail = row["retail_value"]
        row["margin"] = round((retail - row["cost_value"]) / retail * 100, 1) if retail else 0.0
        rows.append(row)
    rows.sort(key=lambda r: -r["cost_value"])
    return rows


register(Report(
    key="reorder_suggestions",
    title="Reorder suggestions",
    module="Stock",
    purpose="What to order, how much, and from whom — everything at or below "
            "its reorder level.",
    params=[BRANCH],
    columns=[
        Column("product", "Product", "text"),
        Column("supplier", "Supplier", "text"),
        Column("on_hand", "On hand", "number", total=True),
        Column("reorder_level", "Reorder at", "number"),
        Column("suggested", "Order", "number", total=True),
        Column("cost", "Est. cost", "money", total=True),
    ],
    rows=lambda db, p: _reorder(db, p),
    drill=lambda row: f"/products/{row.get('product_id')}",
))


def _reorder(db: Session, p: dict):
    suppliers = {s.id: s.name for s in db.query(Supplier).all()}
    rows = []
    for product in (
        db.query(Product)
        .filter(Product.active)
        .filter(Product.quantity_on_hand <= Product.reorder_level)
        .all()
    ):
        quantity = product.reorder_quantity or 0
        rows.append({
            "product_id": product.id,
            "product": product.name,
            "supplier": suppliers.get(product.supplier_id, "(none set)"),
            "on_hand": product.quantity_on_hand,
            "reorder_level": product.reorder_level,
            "suggested": quantity,
            "cost": round((product.cost_price or 0) * quantity, 2),
        })
    rows.sort(key=lambda r: (r["supplier"], r["product"]))
    return rows


# -------------------------------------------------------------- dispensary

register(Report(
    key="drug_usage",
    title="Drug usage",
    module="Dispensary",
    purpose="What is actually being dispensed, by volume and by value.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("product", "Product", "text"),
        Column("schedule", "Sch", "text"),
        Column("scripts", "Scripts", "number", total=True),
        Column("units", "Units", "number", total=True),
        Column("value", "Value", "money", total=True),
    ],
    rows=lambda db, p: _drug_usage(db, p),
))


def _drug_usage(db: Session, p: dict):
    # A dispensing does not carry a product. It hangs off a prescription item,
    # and the item is what names the drug — so the join is through the item, not
    # a convenient `.items` collection that does not exist.
    groups: dict[int, dict] = {}
    rows_q = (
        db.query(Dispensing, PrescriptionItem, Product)
        .join(PrescriptionItem, Dispensing.prescription_item_id == PrescriptionItem.id)
        .join(Product, PrescriptionItem.product_id == Product.id)
        .filter(func.date(Dispensing.dispensed_at) >= p["date_from"])
        .filter(func.date(Dispensing.dispensed_at) <= p["date_to"])
    )
    for dispensing, item, product in rows_q.all():
        entry = groups.setdefault(product.id, {
            "product": product.name,
            "schedule": f"S{product.schedule}" if product.schedule else "\u2014",
            "scripts": 0, "units": 0, "value": 0.0,
        })
        quantity = dispensing.quantity or 0
        entry["scripts"] += 1
        entry["units"] += quantity
        entry["value"] = round(entry["value"] + (product.unit_price or 0) * quantity, 2)
    return sorted(groups.values(), key=lambda r: -r["value"])


register(Report(
    key="schedule_register",
    title="Schedule 5 & 6 register",
    module="Dispensary",
    purpose="Every controlled item dispensed, with who dispensed it and to "
            "whom. This is the register an inspector asks for.",
    params=[DATE_FROM, DATE_TO],
    step_up=True,
    columns=[
        Column("date", "Date", "datetime"),
        Column("product", "Product", "text"),
        Column("schedule", "Sch", "text"),
        Column("quantity", "Qty", "number", total=True),
        Column("patient", "Patient", "text"),
        Column("dispenser", "Dispensed by", "text"),
        Column("reference", "Reference", "code"),
    ],
    rows=lambda db, p: _schedule_register(db, p),
))


def _schedule_register(db: Session, p: dict):
    from ...models import RegisterEntry

    entries = (
        db.query(RegisterEntry)
        .filter(func.date(RegisterEntry.created_at) >= p["date_from"])
        .filter(func.date(RegisterEntry.created_at) <= p["date_to"])
        .order_by(RegisterEntry.created_at.desc())
        .all()
    )
    if not entries:
        return []

    # Looked up in three queries rather than three per row. The previous version
    # fetched the product, patient and user individually for every entry, which
    # on six hundred entries is eighteen hundred round trips — slow enough that
    # the browser abandoned the request, and a report nobody can wait for is a
    # report nobody has.
    product_ids = {e.product_id for e in entries if e.product_id}
    patient_ids = {e.patient_id for e in entries if e.patient_id}
    user_ids = {e.user_id for e in entries if e.user_id}

    products = {
        pr.id: pr.name
        for pr in db.query(Product).filter(Product.id.in_(product_ids)).all()
    } if product_ids else {}
    patients = {
        pt.id: (pt.first_name + " " + pt.last_name).strip()
        for pt in db.query(Patient).filter(Patient.id.in_(patient_ids)).all()
    } if patient_ids else {}
    users = {
        u.id: (u.full_name or u.username)
        for u in db.query(User).filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    return [
        {
            "date": e.created_at.isoformat(sep=" ", timespec="minutes"),
            "product": products.get(e.product_id, "#" + str(e.product_id)),
            "schedule": "S" + str(e.schedule),
            "quantity": abs(e.quantity_delta or 0),
            "patient": patients.get(e.patient_id, "-"),
            "dispenser": users.get(e.user_id, "-"),
            "reference": e.reference or "",
        }
        for e in entries
    ]


# --------------------------------------------------------- third batch
#
# Every field referenced below was checked against the model first. Three of the
# defects in this catalogue so far were invented column names that a clean
# typecheck and a green build both waved through.

register(Report(
    key="voids_and_refunds",
    title="Voids and refunds",
    module="Till",
    purpose="Every cancelled sale, with who cancelled it. A void is the easiest "
            "way to take money out of a till, so the report exists whether or "
            "not anyone is suspected.",
    params=[DATE_FROM, DATE_TO],
    step_up=True,
    columns=[
        Column("date", "When", "datetime"),
        Column("sale_number", "Sale", "code"),
        Column("cashier", "Cashier", "text"),
        Column("method", "Tender", "text"),
        Column("amount", "Amount", "money", total=True),
    ],
    rows=lambda db, p: _voids(db, p),
))


def _voids(db: Session, p: dict):
    names = {u.id: (u.full_name or u.username) for u in db.query(User).all()}
    rows = (
        db.query(Sale)
        .filter(Sale.status == "void")
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .order_by(Sale.created_at.desc())
        .all()
    )
    return [
        {
            "date": s.created_at.isoformat(sep=" ", timespec="minutes"),
            "sale_number": s.sale_number or ("#" + str(s.id)),
            "cashier": names.get(s.cashier_id, "-"),
            "method": s.payment_method or "-",
            "amount": round(s.total or 0, 2),
        }
        for s in rows
    ]


register(Report(
    key="payment_mix",
    title="Payment mix",
    module="Till",
    purpose="How customers actually pay. What the pharmacy banks, what it "
            "waits for, and what it pays a fee on.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("method", "Tender", "text"),
        Column("transactions", "Transactions", "number", total=True),
        Column("amount", "Value", "money", total=True),
        Column("share", "Share", "percent"),
        Column("average", "Average", "money"),
    ],
    rows=lambda db, p: _payment_mix(db, p),
))


def _payment_mix(db: Session, p: dict):
    # Tenders where a sale recorded them, because a split payment is two facts
    # about how money arrived and one row on the sale.
    tendered = (
        db.query(SaleTender.method, func.count(SaleTender.id),
                 func.sum(SaleTender.amount_in_base))
        .join(Sale, Sale.id == SaleTender.sale_id)
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .filter(Sale.status != "void")
        .group_by(SaleTender.method)
        .all()
    )
    seen = {
        r[0] for r in
        db.query(SaleTender.sale_id).join(Sale, Sale.id == SaleTender.sale_id)
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .distinct().all()
    }
    groups = {}
    for method, count, amount in tendered:
        row = groups.setdefault(method, {"method": method, "transactions": 0, "amount": 0.0})
        row["transactions"] += int(count or 0)
        row["amount"] = round(row["amount"] + float(amount or 0), 2)

    simple = (
        db.query(Sale.payment_method, func.count(Sale.id), func.sum(Sale.total))
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .filter(Sale.status != "void")
        .filter(~Sale.id.in_(seen) if seen else True)
        .group_by(Sale.payment_method)
        .all()
    )
    for method, count, amount in simple:
        row = groups.setdefault(method or "unrecorded",
                                {"method": method or "unrecorded",
                                 "transactions": 0, "amount": 0.0})
        row["transactions"] += int(count or 0)
        row["amount"] = round(row["amount"] + float(amount or 0), 2)

    total = sum(r["amount"] for r in groups.values()) or 1
    rows = []
    for row in groups.values():
        row["method"] = row["method"].replace("_", " ")
        row["share"] = round(row["amount"] / total * 100, 1)
        row["average"] = (round(row["amount"] / row["transactions"], 2)
                          if row["transactions"] else 0.0)
        rows.append(row)
    rows.sort(key=lambda r: -r["amount"])
    return rows


register(Report(
    key="cashup_history",
    title="Cash-up history",
    module="Till",
    purpose="Every drawer count and what it came to. Where a pattern shows up "
            "that no single cash-up ever would.",
    params=[DATE_FROM, DATE_TO],
    step_up=True,
    columns=[
        Column("opened", "Opened", "datetime"),
        Column("cashier", "Cashier", "text"),
        Column("counted_by", "Counted by", "text"),
        Column("float_amount", "Float", "money", total=True),
        Column("expected", "Expected", "money", total=True),
        Column("counted", "Counted", "money", total=True),
        Column("variance", "Over/short", "money", total=True),
    ],
    rows=lambda db, p: _cashup_history(db, p),
))


def _cashup_history(db: Session, p: dict):
    from ...models import Shift

    names = {u.id: (u.full_name or u.username) for u in db.query(User).all()}
    rows = (
        db.query(Shift)
        .filter(func.date(Shift.opened_at) >= p["date_from"])
        .filter(func.date(Shift.opened_at) <= p["date_to"])
        .order_by(Shift.opened_at.desc())
        .all()
    )
    return [
        {
            "opened": s.opened_at.isoformat(sep=" ", timespec="minutes"),
            "cashier": names.get(s.user_id, "-"),
            "counted_by": names.get(getattr(s, "counted_by_id", None), "-"),
            "float_amount": round(s.opening_float or 0, 2),
            "expected": round(s.expected_cash or 0, 2),
            "counted": round(s.counted_cash or 0, 2),
            "variance": round(s.variance or 0, 2),
        }
        for s in rows
    ]


register(Report(
    key="expired_stock",
    title="Expired stock",
    module="Stock",
    purpose="Batches already past their expiry with units still on hand. This "
            "should be empty, and anything on it is sitting on a shelf where a "
            "dispenser could reach for it.",
    params=[],
    columns=[
        Column("product", "Product", "text"),
        Column("batch", "Batch", "code"),
        Column("expiry", "Expired", "date"),
        Column("days_over", "Days over", "number"),
        Column("quantity", "Still on hand", "number", total=True),
        Column("value", "Value at cost", "money", total=True),
    ],
    rows=lambda db, p: _expired(db, p),
))


def _expired(db: Session, p: dict):
    today_ = date.today()
    rows = []
    for batch in (
        db.query(StockBatch)
        .filter(StockBatch.quantity_remaining > 0)
        .filter(StockBatch.expiry_date.isnot(None))
        .filter(StockBatch.expiry_date < today_)
        .order_by(StockBatch.expiry_date.asc())
        .all()
    ):
        product = db.query(Product).get(batch.product_id)
        cost = (product.cost_price if product else 0) or 0
        rows.append({
            "product_id": batch.product_id,
            "product": product.name if product else "#" + str(batch.product_id),
            "batch": batch.batch_number,
            "expiry": batch.expiry_date.isoformat(),
            "days_over": (today_ - batch.expiry_date).days,
            "quantity": batch.quantity_remaining,
            "value": round(cost * batch.quantity_remaining, 2),
        })
    return rows


register(Report(
    key="top_customers",
    title="Top customers",
    module="CRM",
    purpose="Who actually spends. The list a pharmacy should know by name and "
            "usually does not.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("patient", "Customer", "text"),
        Column("visits", "Visits", "number", total=True),
        Column("spend", "Spend", "money", total=True),
        Column("average", "Average basket", "money"),
        Column("last_seen", "Last seen", "date"),
    ],
    rows=lambda db, p: _top_customers(db, p),
    drill=lambda row: "/patients/" + str(row.get("patient_id")),
))


def _top_customers(db: Session, p: dict):
    agg = (
        db.query(Sale.patient_id, func.count(Sale.id), func.sum(Sale.total),
                 func.max(Sale.created_at))
        .filter(Sale.patient_id.isnot(None))
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .filter(Sale.status != "void")
        .group_by(Sale.patient_id)
        .all()
    )
    ids = [r[0] for r in agg]
    people = {
        pt.id: (pt.first_name + " " + pt.last_name).strip()
        for pt in db.query(Patient).filter(Patient.id.in_(ids)).all()
    } if ids else {}
    rows = []
    for patient_id, visits, spend, last in agg:
        spend = round(float(spend or 0), 2)
        rows.append({
            "patient_id": patient_id,
            "patient": people.get(patient_id, "#" + str(patient_id)),
            "visits": int(visits or 0),
            "spend": spend,
            "average": round(spend / visits, 2) if visits else 0.0,
            "last_seen": last.date().isoformat() if last else "",
        })
    rows.sort(key=lambda r: -r["spend"])
    return rows


# ------------------------------------------------------- stock, second batch
#
# Everything below is a declaration. That is the whole point of the engine:
# these came to about thirty lines each, and every one gets date handling,
# paging, sorting, footer totals, Excel, CSV and print without asking.

register(Report(
    key="slow_movers",
    title="Slow movers",
    module="Stock",
    purpose="Lines that still sell, but too slowly for the money tied up in "
            "them. The step before something becomes dead stock.",
    params=[
        Param("days", "Over the last (days)", "text", default="90"),
        Param("max_turns", "Fewer turns per year than", "text", default="2"),
    ],
    columns=[
        Column("product", "Product", "text"),
        Column("on_hand", "On hand", "number", total=True),
        Column("sold", "Sold in period", "number", total=True),
        Column("turns", "Turns/year", "number"),
        Column("months_cover", "Months of cover", "number"),
        Column("value", "Tied up", "money", total=True),
    ],
    rows=lambda db, p: _slow_movers(db, p),
))


def _slow_movers(db: Session, p: dict):
    try:
        days = max(7, int(p.get("days") or 90))
        max_turns = float(p.get("max_turns") or 2)
    except (TypeError, ValueError):
        days, max_turns = 90, 2.0
    since = date.today() - timedelta(days=days)

    sold = dict(
        db.query(StockMovement.product_id,
                 func.sum(func.abs(StockMovement.quantity_delta)))
        .filter(StockMovement.movement_type == "sale")
        .filter(func.date(StockMovement.created_at) >= since)
        .group_by(StockMovement.product_id)
        .all()
    )
    rows = []
    for product in db.query(Product).filter(
            Product.active, Product.quantity_on_hand > 0).all():
        units = float(sold.get(product.id) or 0)
        # No sales at all is dead stock, which has its own report. Mixing the
        # two makes both harder to act on.
        if units <= 0:
            continue
        annual = units * (365.0 / days)
        turns = round(annual / product.quantity_on_hand, 2) if product.quantity_on_hand else 0.0
        if turns > max_turns:
            continue
        monthly = annual / 12 if annual else 0
        rows.append({
            "product_id": product.id,
            "product": product.name,
            "on_hand": product.quantity_on_hand,
            "sold": int(units),
            "turns": turns,
            "months_cover": round(product.quantity_on_hand / monthly, 1) if monthly else 999,
            "value": round((product.cost_price or 0) * product.quantity_on_hand, 2),
        })
    rows.sort(key=lambda r: -r["value"])
    return rows


register(Report(
    key="stock_movements",
    title="Stock movement history",
    module="Stock",
    purpose="Every movement in and out, with who did it. Where a discrepancy "
            "gets traced back to a decision.",
    params=[
        DATE_FROM, DATE_TO,
        Param("movement_type", "Type", "text", help="receive, sale, adjustment"),
    ],
    columns=[
        Column("date", "When", "datetime"),
        Column("product", "Product", "text"),
        Column("type", "Type", "text"),
        Column("delta", "Change", "number", total=True),
        Column("balance", "Balance after", "number"),
        Column("reference", "Reference", "code"),
        Column("user", "By", "text"),
    ],
    rows=lambda db, p: _movements_report(db, p),
))


def _movements_report(db: Session, p: dict):
    query = (
        db.query(StockMovement)
        .filter(func.date(StockMovement.created_at) >= p["date_from"])
        .filter(func.date(StockMovement.created_at) <= p["date_to"])
    )
    if p.get("movement_type"):
        query = query.filter(StockMovement.movement_type == p["movement_type"])
    names = {u.id: (u.full_name or u.username) for u in db.query(User).all()}
    products = {pr.id: pr.name for pr in db.query(Product).all()}
    return [
        {
            "date": m.created_at.isoformat(sep=" ", timespec="minutes"),
            "product": products.get(m.product_id, "#" + str(m.product_id)),
            "type": m.movement_type,
            "delta": m.quantity_delta,
            "balance": m.balance_after,
            "reference": m.reference or "",
            "user": names.get(m.user_id, "-"),
        }
        # No cap. A limit here makes the footer report the cap as the total,
        # which looks complete and is not — the exact failure this engine
        # exists to prevent. This regressed once already, when restoring
        # this batch from an older copy re-introduced the limit, so it is
        # worth the comment: the date range is what bounds the volume.
        for m in query.order_by(StockMovement.created_at.desc()).all()
    ]


register(Report(
    key="negative_stock",
    title="Stock exceptions",
    module="Stock",
    purpose="Lines below zero, or where the product total and its batches "
            "disagree. Always a fault, never a judgement call.",
    params=[],
    columns=[
        Column("product", "Product", "text"),
        Column("on_hand", "Product says", "number", total=True),
        Column("batches", "Batches say", "number", total=True),
        Column("gap", "Gap", "number", total=True),
        Column("supplier", "Supplier", "text"),
    ],
    rows=lambda db, p: _negative_stock(db, p),
))


def _negative_stock(db: Session, p: dict):
    suppliers = {s.id: s.name for s in db.query(Supplier).all()}
    batched = dict(
        db.query(StockBatch.product_id, func.sum(StockBatch.quantity_remaining))
        .group_by(StockBatch.product_id).all()
    )
    rows = []
    for product in db.query(Product).filter(Product.active).all():
        # Airtime has no batches by design, so it is not an exception.
        if (product.category or "") == "airtime":
            continue
        on_hand = product.quantity_on_hand or 0
        in_batches = int(batched.get(product.id) or 0)
        # Either figure being negative is a fault, and so is the two of them
        # disagreeing: the product row and its batches are meant to be two
        # views of one truth.
        if on_hand >= 0 and in_batches >= 0 and on_hand == in_batches:
            continue
        rows.append({
            "product_id": product.id,
            "product": product.name,
            "on_hand": on_hand,
            "batches": in_batches,
            "gap": on_hand - in_batches,
            "supplier": suppliers.get(product.supplier_id, "-"),
        })
    rows.sort(key=lambda r: (r["on_hand"] >= 0, -abs(r["gap"])))
    return rows


register(Report(
    key="purchases_by_supplier",
    title="Purchases by supplier",
    module="Procurement",
    purpose="What was bought from whom, and how much of it actually arrived.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("supplier", "Supplier", "text"),
        Column("orders", "Orders", "number", total=True),
        Column("ordered", "Units ordered", "number", total=True),
        Column("received", "Units received", "number", total=True),
        Column("fill_rate", "Fill rate", "percent"),
        Column("value", "Value", "money", total=True),
    ],
    rows=lambda db, p: _purchases_by_supplier(db, p),
))


def _purchases_by_supplier(db: Session, p: dict):
    from ...models import PurchaseOrder

    groups = {}
    suppliers = {s.id: s.name for s in db.query(Supplier).all()}
    orders = (
        db.query(PurchaseOrder)
        .filter(func.date(PurchaseOrder.created_at) >= p["date_from"])
        .filter(func.date(PurchaseOrder.created_at) <= p["date_to"])
        .all()
    )
    for order in orders:
        row = groups.setdefault(order.supplier_id, {
            "supplier": suppliers.get(order.supplier_id, "-"),
            "orders": 0, "ordered": 0, "received": 0, "value": 0.0,
        })
        row["orders"] += 1
        for line in order.items:
            row["ordered"] += line.quantity_ordered or 0
            row["received"] += line.quantity_received or 0
            row["value"] = round(
                row["value"] + (line.unit_cost or 0) * (line.quantity_ordered or 0), 2)
    rows = []
    for row in groups.values():
        row["fill_rate"] = (round(row["received"] / row["ordered"] * 100, 1)
                            if row["ordered"] else 0.0)
        rows.append(row)
    rows.sort(key=lambda r: -r["value"])
    return rows


register(Report(
    key="goods_received_not_invoiced",
    title="Received not invoiced",
    module="Procurement",
    purpose="Stock on the shelf that no supplier invoice has arrived for. A "
            "liability the books do not know about yet.",
    params=[],
    columns=[
        Column("order_number", "Order", "code"),
        Column("supplier", "Supplier", "text"),
        Column("received_at", "Received", "date"),
        Column("units", "Units", "number", total=True),
        Column("value", "Value at cost", "money", total=True),
        Column("days", "Days waiting", "number"),
    ],
    rows=lambda db, p: _grni(db, p),
))


def _grni(db: Session, p: dict):
    from ...models import PurchaseOrder

    suppliers = {s.id: s.name for s in db.query(Supplier).all()}
    rows = []
    for order in db.query(PurchaseOrder).filter(
            PurchaseOrder.status == "received").all():
        received = sum(l.quantity_received or 0 for l in order.items)
        if not received:
            continue
        # An invoice reference recorded against the order means it has been
        # billed. The notes field is where that lands today.
        if "invoice" in (order.notes or "").lower():
            continue
        when = order.received_at or order.created_at
        rows.append({
            "order_id": order.id,
            "order_number": order.order_number,
            "supplier": suppliers.get(order.supplier_id, "-"),
            "received_at": when.date().isoformat() if when else "",
            "units": received,
            "value": round(sum((l.unit_cost or 0) * (l.quantity_received or 0)
                               for l in order.items), 2),
            "days": (date.today() - when.date()).days if when else 0,
        })
    rows.sort(key=lambda r: -r["days"])
    return rows


# --------------------------------------------------------- fourth batch

register(Report(
    key="gross_profit_by_product",
    title="Gross profit by product",
    module="Till",
    purpose="What each line actually earns. Volume and profit are different "
            "leagues, and the best seller is often not the best earner.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("product", "Product", "text"),
        Column("category", "Department", "text"),
        Column("units", "Units", "number", total=True),
        Column("revenue", "Revenue", "money", total=True),
        Column("cost", "Cost", "money", total=True),
        Column("profit", "Gross profit", "money", total=True),
        Column("margin", "Margin", "percent"),
    ],
    rows=lambda db, p: _gross_profit(db, p),
    drill=lambda row: "/products/" + str(row.get("product_id")),
))


def _gross_profit(db: Session, p: dict):
    # Aggregated in SQL. Three reports in this catalogue shipped with an N+1
    # before the rule was written down: never reach for a related record inside
    # a loop over rows.
    query = (
        db.query(
            Product.id, Product.name, Product.category,
            func.sum(SaleItem.quantity),
            func.sum(SaleItem.unit_price * SaleItem.quantity),
            func.sum(line_cost() * SaleItem.quantity),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .filter(Sale.status != "void")
        .group_by(Product.id, Product.name, Product.category)
    )
    rows = []
    for pid, name, category, units, revenue, cost in query.all():
        revenue = round(float(revenue or 0), 2)
        cost = round(float(cost or 0), 2)
        rows.append({
            "product_id": pid,
            "product": name,
            "category": (category or "").replace("_", " "),
            "units": int(units or 0),
            "revenue": revenue,
            "cost": cost,
            "profit": round(revenue - cost, 2),
            "margin": round((revenue - cost) / revenue * 100, 1) if revenue else 0.0,
        })
    rows.sort(key=lambda r: -r["profit"])
    return rows


register(Report(
    key="loyalty_summary",
    title="Loyalty points",
    module="Till",
    purpose="Points earned against points redeemed. Unredeemed points are a "
            "promise the pharmacy has made and not yet paid for.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("day", "Day", "date"),
        Column("sales", "Sales", "number", total=True),
        Column("earned", "Earned", "number", total=True),
        Column("redeemed", "Redeemed", "number", total=True),
        Column("net", "Net outstanding", "number", total=True),
    ],
    rows=lambda db, p: _loyalty(db, p),
))


def _loyalty(db: Session, p: dict):
    rows_q = (
        db.query(
            func.date(Sale.created_at),
            func.count(Sale.id),
            func.sum(Sale.loyalty_points_earned),
            func.sum(Sale.loyalty_points_redeemed),
        )
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .filter(Sale.status != "void")
        .group_by(func.date(Sale.created_at))
        .all()
    )
    rows = []
    for day, count, earned, redeemed in rows_q:
        earned = int(earned or 0)
        redeemed = int(redeemed or 0)
        if not earned and not redeemed:
            continue
        rows.append({
            "day": str(day),
            "sales": int(count or 0),
            "earned": earned,
            "redeemed": redeemed,
            "net": earned - redeemed,
        })
    rows.sort(key=lambda r: r["day"], reverse=True)
    return rows


register(Report(
    key="dispenser_activity",
    title="Dispenser activity",
    module="Dispensary",
    purpose="Who dispensed what, and how much of it. Workload, and the first "
            "place to look when a dispensing question needs a person.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("dispenser", "Dispenser", "text"),
        Column("items", "Items dispensed", "number", total=True),
        Column("units", "Units", "number", total=True),
        Column("controlled", "Of which S5/S6", "number", total=True),
        Column("busiest_day", "Busiest day", "date"),
    ],
    rows=lambda db, p: _dispenser_activity(db, p),
))


def _dispenser_activity(db: Session, p: dict):
    rows_q = (
        db.query(Dispensing, Product.schedule)
        .join(PrescriptionItem, Dispensing.prescription_item_id == PrescriptionItem.id)
        .join(Product, PrescriptionItem.product_id == Product.id)
        .filter(func.date(Dispensing.dispensed_at) >= p["date_from"])
        .filter(func.date(Dispensing.dispensed_at) <= p["date_to"])
        .all()
    )
    if not rows_q:
        return []

    groups = {}
    days = {}
    for dispensing, schedule in rows_q:
        key = dispensing.dispensed_by_id or 0
        row = groups.setdefault(key, {
            "_id": key, "items": 0, "units": 0, "controlled": 0,
        })
        row["items"] += 1
        row["units"] += dispensing.quantity or 0
        if (schedule or 0) >= 5:
            row["controlled"] += 1
        day = dispensing.dispensed_at.date().isoformat()
        days.setdefault(key, {}).setdefault(day, 0)
        days[key][day] += 1

    names = {
        u.id: (u.full_name or u.username)
        for u in db.query(User).filter(User.id.in_([k for k in groups if k])).all()
    } if any(groups) else {}

    out = []
    for key, row in groups.items():
        per_day = days.get(key, {})
        busiest = max(per_day, key=per_day.get) if per_day else ""
        out.append({
            "dispenser": names.get(key, "(not recorded)"),
            "items": row["items"],
            "units": row["units"],
            "controlled": row["controlled"],
            "busiest_day": busiest,
        })
    out.sort(key=lambda r: -r["items"])
    return out


# ---------------------------------------------------------- fifth batch

register(Report(
    key="repeats_due",
    title="Repeats due",
    module="Dispensary",
    purpose="Patients with a repeat now due or overdue. The most direct list "
            "of business already won and not yet collected.",
    params=[
        Param("overdue_only", "Overdue only", "bool", default=False),
        Param("horizon", "Due within (days)", "text", default="14"),
    ],
    columns=[
        Column("patient", "Patient", "text"),
        Column("phone", "Phone", "text"),
        Column("product", "Medicine", "text"),
        Column("due", "Due", "date"),
        Column("days", "Days", "number"),
        Column("remaining", "Repeats left", "number", total=True),
    ],
    rows=lambda db, p: _repeats_due(db, p),
    drill=lambda row: "/patients/" + str(row.get("patient_id")),
))


def _repeats_due(db: Session, p: dict):
    from ...models import Prescription

    try:
        horizon = max(0, int(p.get("horizon") or 14))
    except (TypeError, ValueError):
        horizon = 14
    overdue_only = bool(p.get("overdue_only"))
    today_ = date.today()
    cutoff = today_ + timedelta(days=horizon)

    query = (
        db.query(PrescriptionItem, Prescription, Product)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .join(Product, PrescriptionItem.product_id == Product.id)
        .filter(PrescriptionItem.next_repeat_date.isnot(None))
        .filter(PrescriptionItem.next_repeat_date <= cutoff)
        .filter(PrescriptionItem.repeats_used < PrescriptionItem.repeats_allowed)
    )
    if overdue_only:
        query = query.filter(PrescriptionItem.next_repeat_date < today_)

    patient_ids = set()
    found = query.all()
    for item, script, product in found:
        if script.patient_id:
            patient_ids.add(script.patient_id)
    people = {
        pt.id: ((pt.first_name + " " + pt.last_name).strip(), pt.phone or "")
        for pt in db.query(Patient).filter(Patient.id.in_(patient_ids)).all()
    } if patient_ids else {}

    rows = []
    for item, script, product in found:
        name, phone = people.get(script.patient_id, ("(unknown)", ""))
        due = item.next_repeat_date
        rows.append({
            "patient_id": script.patient_id,
            "patient": name,
            "phone": phone,
            "product": product.name,
            "due": due.isoformat(),
            # Negative reads as overdue, which is the ordering that matters.
            "days": (due - today_).days,
            "remaining": (item.repeats_allowed or 0) - (item.repeats_used or 0),
        })
    rows.sort(key=lambda r: r["days"])
    return rows


register(Report(
    key="margin_exceptions",
    title="Selling at or below cost",
    module="Stock",
    purpose="Lines priced at or under what they cost. Every one of these loses "
            "money on every sale, quietly, until somebody looks.",
    params=[
        Param("min_margin", "Flag margin under (%)", "text", default="0"),
    ],
    columns=[
        Column("product", "Product", "text"),
        Column("category", "Department", "text"),
        Column("cost_price", "Cost", "money"),
        Column("unit_price", "Selling", "money"),
        Column("margin", "Margin", "percent"),
        Column("on_hand", "On hand", "number", total=True),
        Column("exposure", "Loss if all sold", "money", total=True),
    ],
    rows=lambda db, p: _margin_exceptions(db, p),
    drill=lambda row: "/products/" + str(row.get("product_id")),
))


def _margin_exceptions(db: Session, p: dict):
    try:
        threshold = float(p.get("min_margin") or 0)
    except (TypeError, ValueError):
        threshold = 0.0
    rows = []
    for product in db.query(Product).filter(Product.active).all():
        cost = product.cost_price or 0
        price = product.unit_price or 0
        # A line with no cost recorded is a different problem — it cannot be
        # said to be selling at a loss, only that nobody knows.
        if cost <= 0 or price <= 0:
            continue
        margin = (price - cost) / price * 100
        if margin > threshold:
            continue
        quantity = product.quantity_on_hand or 0
        rows.append({
            "product_id": product.id,
            "product": product.name,
            "category": (product.category or "").replace("_", " "),
            "cost_price": round(cost, 2),
            "unit_price": round(price, 2),
            "margin": round(margin, 1),
            "on_hand": quantity,
            "exposure": round((cost - price) * quantity, 2),
        })
    rows.sort(key=lambda r: -r["exposure"])
    return rows


register(Report(
    key="uncosted_products",
    title="Products with no cost price",
    module="Stock",
    purpose="Lines the system cannot value or report a margin on. They quietly "
            "distort stock valuation and every profit figure that uses it.",
    params=[],
    columns=[
        Column("product", "Product", "text"),
        Column("category", "Department", "text"),
        Column("unit_price", "Selling", "money"),
        Column("on_hand", "On hand", "number", total=True),
        Column("supplier", "Supplier", "text"),
    ],
    rows=lambda db, p: _uncosted(db, p),
    drill=lambda row: "/products/" + str(row.get("product_id")),
))


def _uncosted(db: Session, p: dict):
    suppliers = {s.id: s.name for s in db.query(Supplier).all()}
    rows = []
    for product in db.query(Product).filter(Product.active).all():
        if (product.cost_price or 0) > 0:
            continue
        # Airtime is bought and sold at face value and has no cost of its own,
        # so it is not a gap in the data.
        if (product.category or "") == "airtime":
            continue
        rows.append({
            "product_id": product.id,
            "product": product.name,
            "category": (product.category or "").replace("_", " "),
            "unit_price": round(product.unit_price or 0, 2),
            "on_hand": product.quantity_on_hand or 0,
            "supplier": suppliers.get(product.supplier_id, "(none set)"),
        })
    rows.sort(key=lambda r: -r["on_hand"])
    return rows


# ---------------------------------------------------------- sixth batch
#
# Finance. The ledger is the best-instrumented part of the system and had no
# reports at all, which meant the only way to answer "who owes us" was to open a
# screen and read it.

def _party_balances(db: Session, subledger: str, p: dict):
    """Net balance per party against a subledger's control accounts.

    Grouped in SQL, then named in one lookup per party type. The alternative —
    a query per party — is the N+1 that three reports in this catalogue shipped
    with before it was written down as a rule.
    """
    from ...models import Account, JournalEntry, JournalLine

    controls = [
        a.code for a in db.query(Account).filter(Account.subledger == subledger).all()
    ]
    if not controls:
        return []

    rows = (
        db.query(
            JournalLine.party_type,
            JournalLine.party_id,
            func.sum(JournalLine.debit),
            func.sum(JournalLine.credit),
            func.max(JournalEntry.entry_date),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .filter(JournalEntry.status == "posted")
        .filter(JournalLine.account_code.in_(controls))
        .filter(JournalEntry.entry_date <= p["as_at"])
        .group_by(JournalLine.party_type, JournalLine.party_id)
        .all()
    )

    # Debtors are debit-positive, creditors credit-positive. Getting this the
    # wrong way round prints every balance as a negative, which is the fastest
    # way to make a finance report unreadable.
    debit_positive = subledger == "debtors"

    wanted = {"patient": set(), "supplier": set(), "scheme": set()}
    for party_type, party_id, _d, _c, _last in rows:
        if party_type in wanted and party_id:
            wanted[party_type].add(party_id)

    names = {}
    if wanted["patient"]:
        for row in db.query(Patient).filter(Patient.id.in_(wanted["patient"])).all():
            names[("patient", row.id)] = (row.first_name + " " + row.last_name).strip()
    if wanted["supplier"]:
        for row in db.query(Supplier).filter(Supplier.id.in_(wanted["supplier"])).all():
            names[("supplier", row.id)] = row.name
    if wanted["scheme"]:
        try:
            from ...models import MedicalAid

            for row in db.query(MedicalAid).filter(MedicalAid.id.in_(wanted["scheme"])).all():
                names[("scheme", row.id)] = row.name
        except Exception:
            # A scheme table that is not there or not shaped as expected must
            # not take the report down; the balance is still the point.
            pass

    out = []
    for party_type, party_id, debit, credit, last in rows:
        balance = float(debit or 0) - float(credit or 0)
        if not debit_positive:
            balance = -balance
        balance = round(balance, 2)
        # Settled parties are not debtors any more, and leaving them in pads the
        # list with rows that need no action.
        if abs(balance) < 0.005:
            continue
        out.append({
            "party": names.get((party_type, party_id))
                     or ("unattributed" if not party_type else party_type + " #" + str(party_id)),
            "kind": party_type or "unattributed",
            "balance": balance,
            "last_movement": str(last) if last else "",
        })
    out.sort(key=lambda r: -abs(r["balance"]))
    return out


AS_AT = Param("as_at", "As at", "date", default=today)


register(Report(
    key="debtor_balances",
    title="Who owes us",
    module="Finance",
    purpose="Every patient and scheme with money outstanding, largest first. "
            "The balance sheet gives the total; this gives the names.",
    params=[AS_AT],
    columns=[
        Column("party", "Account", "text"),
        Column("kind", "Type", "text"),
        Column("balance", "Owing", "money", total=True),
        Column("last_movement", "Last movement", "date"),
    ],
    rows=lambda db, p: _party_balances(db, "debtors", p),
))


register(Report(
    key="creditor_balances",
    title="Who we owe",
    module="Finance",
    purpose="Every supplier with a balance outstanding. What the pharmacy is "
            "carrying, and to whom.",
    params=[AS_AT],
    columns=[
        Column("party", "Supplier", "text"),
        Column("kind", "Type", "text"),
        Column("balance", "Owed", "money", total=True),
        Column("last_movement", "Last movement", "date"),
    ],
    rows=lambda db, p: _party_balances(db, "creditors", p),
))


register(Report(
    key="journal",
    title="Journal",
    module="Finance",
    purpose="Every posting, with what caused it. Where a figure on a statement "
            "is traced back to the event that produced it.",
    params=[
        DATE_FROM, DATE_TO,
        Param("source", "Source", "text", help="sale, stock_receipt, adjustment"),
    ],
    columns=[
        Column("date", "Date", "date"),
        Column("reference", "Reference", "code"),
        Column("account", "Account", "code"),
        Column("description", "Description", "text"),
        Column("debit", "Debit", "money", total=True),
        Column("credit", "Credit", "money", total=True),
        Column("source", "Caused by", "text"),
    ],
    rows=lambda db, p: _journal(db, p),
))


def _journal(db: Session, p: dict):
    from ...models import Account, JournalEntry, JournalLine

    query = (
        db.query(JournalLine, JournalEntry)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .filter(JournalEntry.entry_date >= p["date_from"])
        .filter(JournalEntry.entry_date <= p["date_to"])
    )
    if p.get("source"):
        query = query.filter(JournalEntry.source == p["source"])

    names = {a.code: a.name for a in db.query(Account).all()}
    rows = []
    for line, entry in query.order_by(JournalEntry.entry_date.desc(),
                                      JournalEntry.id.desc()).all():
        rows.append({
            "date": str(entry.entry_date),
            "reference": entry.reference,
            "account": line.account_code + " " + names.get(line.account_code, ""),
            "description": line.description or entry.description or "",
            "debit": round(line.debit or 0, 2),
            "credit": round(line.credit or 0, 2),
            # A reversed entry still shows, because pretending it never happened
            # is exactly what a journal must not do.
            "source": entry.source + (" (reversed)" if entry.status == "reversed" else ""),
        })
    return rows


# ------------------------------------------------- financial statements
#
# These already existed as screens under Ledger, with their own layouts, and
# none of them could be exported. An accountant wants a balance sheet in a
# spreadsheet, and a report that can only be looked at is a report that gets
# retyped. Putting them in the catalogue is not duplication: the screen is for
# reading and this is for taking away.
#
# A statement is hierarchical and a report row is flat, so the section is a
# column rather than a nesting level. That is also how an accountant pastes it
# into a working paper.

def _statement_rows(sections, subtotal_label="Total"):
    """Flatten a statement's sections into rows, keeping the shape legible."""
    rows = []
    for section in sections:
        rows.append({
            "section": section["heading"],
            "line": section["heading"],
            "code": "",
            "amount": section["total"],
            "level": "section",
        })
        for account in section.get("accounts", []):
            rows.append({
                "section": section["heading"],
                "line": account["name"],
                "code": account["code"],
                "amount": account["amount"],
                "level": "account",
            })
    return rows


register(Report(
    key="trial_balance",
    title="Trial balance",
    module="Finance",
    purpose="Every account with a movement, and the proof the whole thing "
            "balances. The statement every other statement is checked against.",
    params=[Param("upto", "Up to", "date", default=today)],
    columns=[
        Column("code", "Code", "code"),
        Column("name", "Account", "text"),
        Column("type", "Type", "text"),
        Column("debit", "Debit", "money", total=True),
        Column("credit", "Credit", "money", total=True),
        # Debits and credits are totalled because their agreement is the point
        # of a trial balance. The balance column is not: summing reader-signed
        # balances across assets, liabilities, equity, income and expense gives
        # a number that looks authoritative and means nothing.
        Column("balance", "Balance", "money"),
    ],
    rows=lambda db, p: _trial_balance(db, p),
))


def _trial_balance(db: Session, p: dict):
    from ...services import ledger

    result = ledger.trial_balance(db, upto=p["upto"])
    return result.get("lines", [])


register(Report(
    key="income_statement_report",
    title="Income statement",
    module="Finance",
    purpose="Revenue through to profit for the financial year, with cost of "
            "sales separated out.",
    params=[
        Param("start", "From", "date", default=None,
              help="Defaults to the start of the financial year"),
        Param("upto", "To", "date", default=today),
    ],
    columns=[
        Column("section", "Section", "text"),
        Column("code", "Code", "code"),
        Column("line", "Line", "text"),
        # Deliberately not totalled. These rows carry section subtotals and the
        # accounts that make them up, so a column sum double counts everything
        # and produces a confident, meaningless figure. The statement states its
        # own totals as rows.
        Column("amount", "Amount", "money"),
    ],
    rows=lambda db, p: _income_rows(db, p),
))


def _income_rows(db: Session, p: dict):
    from ...services import statements
    from ...routers.ledger_router import _year_start

    upto = p["upto"]
    start = p.get("start") or _year_start(upto)
    result = statements.income_statement(db, start=start, upto=upto)
    rows = _statement_rows(result["sections"])
    # The figures a reader actually looks for, stated rather than left to be
    # derived from the sections above them.
    for label, value in (
        ("Gross profit", result["gross_profit"]),
        ("Net profit", result["net_profit"]),
    ):
        rows.append({"section": "Result", "line": label, "code": "",
                     "amount": value, "level": "total"})
    return rows


register(Report(
    key="balance_sheet_report",
    title="Balance sheet",
    module="Finance",
    purpose="What the pharmacy owns and owes at a date, split current and "
            "non-current, including the profit earned so far this year.",
    params=[Param("upto", "As at", "date", default=today)],
    columns=[
        Column("section", "Section", "text"),
        Column("code", "Code", "code"),
        Column("line", "Line", "text"),
        # Deliberately not totalled. These rows carry section subtotals and the
        # accounts that make them up, so a column sum double counts everything
        # and produces a confident, meaningless figure. The statement states its
        # own totals as rows.
        Column("amount", "Amount", "money"),
    ],
    rows=lambda db, p: _balance_rows(db, p),
))


def _balance_rows(db: Session, p: dict):
    from ...services import statements
    from ...routers.ledger_router import _year_start

    upto = p["upto"]
    result = statements.balance_sheet(db, upto=upto, year_start=_year_start(upto))
    rows = _statement_rows(result["sections"])
    rows.append({"section": "Check", "line": "Total assets", "code": "",
                 "amount": result["total_assets"], "level": "total"})
    rows.append({"section": "Check", "line": "Liabilities and equity", "code": "",
                 "amount": round(result["total_liabilities"] + result["total_equity"], 2),
                 "level": "total"})
    # Whether it balances travels with the figures. A balance sheet exported
    # without that is a balance sheet nobody can check.
    rows.append({"section": "Check",
                 "line": result["note"], "code": "",
                 "amount": result["difference"], "level": "note"})
    return rows


register(Report(
    key="cash_flow_report",
    title="Cash flow",
    module="Finance",
    purpose="Why the bank balance moved, which profit alone never explains. "
            "Checked against the actual movement on the cash accounts.",
    params=[
        Param("start", "From", "date", default=None,
              help="Defaults to the start of the financial year"),
        Param("upto", "To", "date", default=today),
    ],
    columns=[
        Column("section", "Section", "text"),
        Column("line", "Line", "text"),
        Column("note", "Effect", "text"),
        # Not totalled, for the same reason as the other statements: the rows
        # include their own subtotals.
        Column("amount", "Amount", "money"),
    ],
    rows=lambda db, p: _cash_flow_rows(db, p),
))


def _cash_flow_rows(db: Session, p: dict):
    from ...services import statements
    from ...routers.ledger_router import _year_start

    upto = p["upto"]
    start = p.get("start") or _year_start(upto)
    result = statements.cash_flow(db, start=start, upto=upto)
    rows = []
    for section in result["sections"]:
        for line in section["lines"]:
            rows.append({
                "section": section["heading"],
                "line": line["label"],
                "note": line.get("note", ""),
                "amount": line["amount"],
            })
        rows.append({"section": section["heading"], "line": "Subtotal",
                     "note": "", "amount": section["total"]})
    rows.append({"section": "Cash", "line": "Opening", "note": start.isoformat(),
                 "amount": result["opening_cash"]})
    rows.append({"section": "Cash", "line": "Closing", "note": upto.isoformat(),
                 "amount": result["closing_cash"]})
    rows.append({"section": "Cash", "line": "Reconciliation", "note": result["note"],
                 "amount": result["difference"]})
    return rows


register(Report(
    key="aged_analysis",
    title="Aged analysis",
    module="Finance",
    purpose="How old the money is, by who owes it. A total is nearly useless "
            "on its own; the buckets are the report.",
    params=[
        Param("subledger", "Ledger", "select", default="debtors",
              options=[{"value": "debtors", "label": "Owed to us"},
                       {"value": "creditors", "label": "Owed by us"}]),
        Param("asof", "As at", "date", default=today),
    ],
    columns=[
        Column("name", "Account", "text"),
        Column("current", "Current", "money", total=True),
        Column("d30", "30 days", "money", total=True),
        Column("d60", "60 days", "money", total=True),
        Column("d90", "90 days", "money", total=True),
        Column("d120", "120+ days", "money", total=True),
        Column("total", "Total", "money", total=True),
    ],
    rows=lambda db, p: _aged_rows(db, p),
))


def _aged_rows(db: Session, p: dict):
    from ...services import ledger, reporting

    which = (p.get("subledger") or "debtors").strip() or "debtors"
    try:
        result = reporting.ageing(db, which, asof=p["asof"])
    except ledger.LedgerError as exc:
        # A missing control account is a configuration fault, not an empty
        # report, and saying so beats returning nothing.
        raise ValueError(str(exc))

    keys = {"current": "current", "30 days": "d30", "60 days": "d60",
            "90 days": "d90", "120+ days": "d120"}
    rows = []
    for party in result["parties"]:
        row = {"name": party["name"], "total": party["total"]}
        for label, key in keys.items():
            row[key] = party["buckets"].get(label, 0.0)
        rows.append(row)
    return rows


register(Report(
    key="vat_return",
    title="VAT return",
    module="Finance",
    purpose="The figures a VAT return is filed from, taken from the ledger so "
            "the return agrees with the accounts behind it.",
    params=[Param("period_code", "Trading period", "text",
                  help="e.g. 202608")],
    columns=[
        Column("line", "Line", "text"),
        Column("amount", "Amount", "money", total=False),
    ],
    rows=lambda db, p: _vat_rows(db, p),
))


def _vat_rows(db: Session, p: dict):
    from ...models import TradingPeriod
    from ...services import ledger, reporting

    code = (p.get("period_code") or "").strip()
    if not code:
        # Default to the period the pharmacy is actually trading in, so the
        # report opens with something rather than an empty form.
        period = (db.query(TradingPeriod)
                  .order_by(TradingPeriod.start_date.desc()).first())
        if not period:
            return []
        code = period.code
    try:
        result = reporting.vat_return(db, code)
    except ledger.LedgerError as exc:
        raise ValueError(str(exc))

    return [
        {"line": "Trading period", "amount": None, "text": result["period_name"]},
        {"line": "Turnover excluding VAT", "amount": result["turnover_excluding_vat"]},
        {"line": "Output tax (on sales)", "amount": result["output_tax"]},
        {"line": "Input tax (on purchases)", "amount": result["input_tax"]},
        {"line": result["direction"], "amount": result["payable"]},
    ]


# ------------------------------------------------------- stock, fourth batch

register(Report(
    key="stock_usage_per_item",
    title="Stock usage per item",
    module="Stock",
    purpose="How much of each line moved, in and out, over a period. What a "
            "reorder level should actually be set from.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("product", "Product", "text"),
        Column("received", "Received", "number", total=True),
        Column("sold", "Sold", "number", total=True),
        Column("adjusted", "Adjusted", "number", total=True),
        Column("on_hand", "On hand now", "number", total=True),
        Column("weeks_cover", "Weeks of cover", "number"),
    ],
    rows=lambda db, p: _usage_per_item(db, p),
    drill=lambda row: "/products/" + str(row.get("product_id")),
))


def _usage_per_item(db: Session, p: dict):
    days = max(1, (p["date_to"] - p["date_from"]).days + 1)
    moved = (
        db.query(StockMovement.product_id, StockMovement.movement_type,
                 func.sum(StockMovement.quantity_delta))
        .filter(func.date(StockMovement.created_at) >= p["date_from"])
        .filter(func.date(StockMovement.created_at) <= p["date_to"])
        .group_by(StockMovement.product_id, StockMovement.movement_type)
        .all()
    )
    if not moved:
        return []
    ids = {m[0] for m in moved}
    products = {pr.id: pr for pr in db.query(Product).filter(Product.id.in_(ids)).all()}

    rows = {}
    for product_id, kind, delta in moved:
        product = products.get(product_id)
        if not product:
            continue
        row = rows.setdefault(product_id, {
            "product_id": product_id, "product": product.name,
            "received": 0, "sold": 0, "adjusted": 0,
            "on_hand": product.quantity_on_hand or 0,
        })
        amount = int(delta or 0)
        if kind == "receive":
            row["received"] += amount
        elif kind == "sale":
            row["sold"] += abs(amount)
        else:
            row["adjusted"] += amount

    for row in rows.values():
        weekly = row["sold"] / (days / 7) if row["sold"] else 0
        # 999 rather than blank for a line that never sells: it sorts to the end
        # and reads as "effectively forever", which is the truth.
        row["weeks_cover"] = round(row["on_hand"] / weekly, 1) if weekly else 999
    return sorted(rows.values(), key=lambda r: -r["sold"])


register(Report(
    key="min_max_order",
    title="Min–max order report",
    module="Stock",
    purpose="Where each line sits against its reorder level and target, and "
            "what ordering to the target would cost.",
    params=[BRANCH],
    columns=[
        Column("product", "Product", "text"),
        Column("supplier", "Supplier", "text"),
        Column("on_hand", "On hand", "number", total=True),
        Column("minimum", "Minimum", "number"),
        Column("target", "Target", "number"),
        Column("shortfall", "Short by", "number", total=True),
        Column("cost", "Cost to fill", "money", total=True),
    ],
    rows=lambda db, p: _min_max(db, p),
    drill=lambda row: "/products/" + str(row.get("product_id")),
))


def _min_max(db: Session, p: dict):
    suppliers = {s.id: s.name for s in db.query(Supplier).all()}
    rows = []
    for product in db.query(Product).filter(Product.active).all():
        on_hand = product.quantity_on_hand or 0
        minimum = product.reorder_level or 0
        target = minimum + (product.reorder_quantity or 0)
        if on_hand > minimum:
            continue
        shortfall = max(0, target - on_hand)
        rows.append({
            "product_id": product.id,
            "product": product.name,
            "supplier": suppliers.get(product.supplier_id, "(none set)"),
            "on_hand": on_hand,
            "minimum": minimum,
            "target": target,
            "shortfall": shortfall,
            "cost": round((product.cost_price or 0) * shortfall, 2),
        })
    rows.sort(key=lambda r: (r["supplier"], -r["cost"]))
    return rows


register(Report(
    key="stock_on_order",
    title="Stock on order",
    module="Stock",
    purpose="What has been ordered and not yet arrived. The stock a reorder "
            "decision should account for and usually does not.",
    params=[],
    columns=[
        Column("product", "Product", "text"),
        Column("supplier", "Supplier", "text"),
        Column("order_number", "Order", "code"),
        Column("ordered", "Ordered", "number", total=True),
        Column("received", "Received", "number", total=True),
        Column("outstanding", "Still due", "number", total=True),
        Column("value", "Value", "money", total=True),
        Column("days", "Days since ordered", "number"),
    ],
    rows=lambda db, p: _on_order(db, p),
))


def _on_order(db: Session, p: dict):
    from ...models import PurchaseOrder, PurchaseOrderItem

    suppliers = {s.id: s.name for s in db.query(Supplier).all()}
    orders = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.status.in_(("draft", "sent")))
        .all()
    )
    if not orders:
        return []
    order_ids = [o.id for o in orders]
    lines = (
        db.query(PurchaseOrderItem)
        .filter(PurchaseOrderItem.order_id.in_(order_ids))
        .all()
    )
    products = {
        pr.id: pr.name for pr in
        db.query(Product).filter(Product.id.in_({l.product_id for l in lines})).all()
    }
    by_order = {o.id: o for o in orders}

    rows = []
    for line in lines:
        outstanding = (line.quantity_ordered or 0) - (line.quantity_received or 0)
        if outstanding <= 0:
            continue
        order = by_order[line.order_id]
        rows.append({
            "product": products.get(line.product_id, "#" + str(line.product_id)),
            "supplier": suppliers.get(order.supplier_id, "-"),
            "order_number": order.order_number,
            "ordered": line.quantity_ordered or 0,
            "received": line.quantity_received or 0,
            "outstanding": outstanding,
            "value": round((line.unit_cost or 0) * outstanding, 2),
            "days": (date.today() - order.created_at.date()).days if order.created_at else 0,
        })
    # Oldest first: an order outstanding for six weeks is the one to chase.
    rows.sort(key=lambda r: -r["days"])
    return rows


register(Report(
    key="stock_write_offs",
    title="Write-offs and adjustments",
    module="Stock",
    purpose="Stock removed without being sold, with who removed it. Shrinkage "
            "is only visible if somebody looks at this.",
    params=[DATE_FROM, DATE_TO],
    step_up=True,
    columns=[
        Column("date", "When", "datetime"),
        Column("product", "Product", "text"),
        Column("delta", "Change", "number", total=True),
        Column("value", "Value at cost", "money", total=True),
        Column("reference", "Reference", "code"),
        Column("user", "By", "text"),
        Column("notes", "Reason", "text"),
    ],
    rows=lambda db, p: _write_offs(db, p),
))


def _write_offs(db: Session, p: dict):
    rows_q = (
        db.query(StockMovement)
        .filter(func.date(StockMovement.created_at) >= p["date_from"])
        .filter(func.date(StockMovement.created_at) <= p["date_to"])
        .filter(StockMovement.movement_type.notin_(("sale", "receive")))
        .order_by(StockMovement.created_at.desc())
        .all()
    )
    if not rows_q:
        return []
    products = {
        pr.id: pr for pr in
        db.query(Product).filter(Product.id.in_({m.product_id for m in rows_q})).all()
    }
    names = {
        u.id: (u.full_name or u.username) for u in
        db.query(User).filter(User.id.in_({m.user_id for m in rows_q if m.user_id})).all()
    }
    out = []
    for m in rows_q:
        product = products.get(m.product_id)
        cost = (product.cost_price if product else 0) or 0
        out.append({
            "date": m.created_at.isoformat(sep=" ", timespec="minutes"),
            "product": product.name if product else "#" + str(m.product_id),
            "delta": m.quantity_delta,
            # Signed, not absolute. abs() valued an opening-stock adjustment as
            # though it were a loss, so the column read 235,000 of shrinkage on a
            # net movement of 332 units — a frightening figure that was wrong.
            "value": round(cost * (m.quantity_delta or 0), 2),
            "reference": m.reference or "",
            "user": names.get(m.user_id, "-"),
            "notes": (m.notes or "")[:120],
        })
    return out


register(Report(
    key="department_stock",
    title="Stock by department",
    module="Stock",
    purpose="Where the money on the shelves actually sits, by category.",
    params=[],
    columns=[
        Column("category", "Department", "text"),
        Column("lines", "Lines", "number", total=True),
        Column("in_stock", "Lines in stock", "number", total=True),
        Column("units", "Units", "number", total=True),
        Column("cost_value", "At cost", "money", total=True),
        Column("share", "Share of stock", "percent"),
    ],
    rows=lambda db, p: _department_stock(db, p),
))


def _department_stock(db: Session, p: dict):
    groups = {}
    for product in db.query(Product).filter(Product.active).all():
        key = (product.category or "uncategorised").replace("_", " ")
        row = groups.setdefault(key, {
            "category": key, "lines": 0, "in_stock": 0, "units": 0, "cost_value": 0.0,
        })
        quantity = product.quantity_on_hand or 0
        row["lines"] += 1
        if quantity > 0:
            row["in_stock"] += 1
            row["units"] += quantity
            row["cost_value"] = round(
                row["cost_value"] + (product.cost_price or 0) * quantity, 2)
    total = sum(r["cost_value"] for r in groups.values()) or 1
    rows = []
    for row in groups.values():
        row["share"] = round(row["cost_value"] / total * 100, 1)
        rows.append(row)
    rows.sort(key=lambda r: -r["cost_value"])
    return rows


register(Report(
    key="supplier_price_variance",
    title="Cost price changes",
    module="Stock",
    purpose="Lines whose cost moved on the last receipt, and by how much. What "
            "a supplier increase looks like before it reaches the margin.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("product", "Product", "text"),
        Column("supplier", "Supplier", "text"),
        Column("old_cost", "Was", "money"),
        Column("new_cost", "Now", "money"),
        Column("change", "Change", "money", total=True),
        Column("percent", "Change", "percent"),
        Column("selling", "Selling", "money"),
        Column("margin_now", "Margin now", "percent"),
    ],
    rows=lambda db, p: _price_variance(db, p),
    drill=lambda row: "/products/" + str(row.get("product_id")),
))


def _price_variance(db: Session, p: dict):
    """Compare each batch's landed cost against the product's current cost.

    Batches carry the cost they were received at, so a change between the
    newest batch in the window and the product's own cost price is a supplier
    price movement that has already happened and not yet been priced for.
    """
    batches = (
        db.query(StockBatch)
        .filter(func.date(StockBatch.received_at) >= p["date_from"])
        .filter(func.date(StockBatch.received_at) <= p["date_to"])
        .filter(StockBatch.unit_cost > 0)
        .order_by(StockBatch.received_at.desc())
        .all()
    )
    if not batches:
        return []

    suppliers = {s.id: s.name for s in db.query(Supplier).all()}
    products = {
        pr.id: pr for pr in
        db.query(Product).filter(Product.id.in_({b.product_id for b in batches})).all()
    }
    seen = set()
    rows = []
    for batch in batches:
        if batch.product_id in seen:
            continue
        seen.add(batch.product_id)
        product = products.get(batch.product_id)
        if not product:
            continue
        old = round(product.cost_price or 0, 2)
        new = round(batch.unit_cost or 0, 2)
        if not old or abs(new - old) < 0.005:
            continue
        selling = round(product.unit_price or 0, 2)
        rows.append({
            "product_id": product.id,
            "product": product.name,
            "supplier": suppliers.get(product.supplier_id, "-"),
            "old_cost": old,
            "new_cost": new,
            "change": round(new - old, 2),
            "percent": round((new - old) / old * 100, 1),
            "selling": selling,
            "margin_now": round((selling - new) / selling * 100, 1) if selling else 0.0,
        })
    rows.sort(key=lambda r: -abs(r["percent"]))
    return rows


# ---------------------------------------------------------- till, second batch

register(Report(
    key="daily_totals",
    title="Daily totals",
    module="Till",
    purpose="One line a day: what was taken, over how many sales, and at what "
            "margin. The report a manager reads first.",
    params=[DATE_FROM, DATE_TO, BRANCH],
    columns=[
        Column("day", "Day", "date"),
        Column("sales", "Sales", "number", total=True),
        Column("items", "Items", "number", total=True),
        Column("takings", "Takings", "money", total=True),
        Column("cost", "Cost", "money", total=True),
        Column("profit", "Gross profit", "money", total=True),
        Column("margin", "Margin", "percent"),
        Column("average", "Average sale", "money"),
        Column("voids", "Voids", "number", total=True),
    ],
    rows=lambda db, p: _daily_totals(db, p),
))


def _daily_totals(db: Session, p: dict):
    day = func.date(Sale.created_at)
    base = (
        db.query(day, func.count(Sale.id), func.sum(Sale.total))
        .filter(day >= p["date_from"]).filter(day <= p["date_to"])
        .filter(Sale.status != "void")
    )
    voided = (
        db.query(day, func.count(Sale.id))
        .filter(day >= p["date_from"]).filter(day <= p["date_to"])
        .filter(Sale.status == "void")
    )
    lines = (
        db.query(day, func.sum(SaleItem.quantity),
                 func.sum(line_cost() * SaleItem.quantity))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(day >= p["date_from"]).filter(day <= p["date_to"])
        .filter(Sale.status != "void")
    )
    if p.get("branch_id"):
        branch = int(p["branch_id"])
        base = base.filter(Sale.branch_id == branch)
        voided = voided.filter(Sale.branch_id == branch)
        lines = lines.filter(Sale.branch_id == branch)

    rows = {}
    for d, count, total in base.group_by(day).all():
        rows[str(d)] = {
            "day": str(d), "sales": int(count or 0),
            "takings": round(float(total or 0), 2),
            "items": 0, "cost": 0.0, "voids": 0,
        }
    for d, quantity, cost in lines.group_by(day).all():
        row = rows.get(str(d))
        if row:
            row["items"] = int(quantity or 0)
            row["cost"] = round(float(cost or 0), 2)
    for d, count in voided.group_by(day).all():
        row = rows.setdefault(str(d), {
            "day": str(d), "sales": 0, "takings": 0.0, "items": 0, "cost": 0.0, "voids": 0,
        })
        row["voids"] = int(count or 0)

    out = []
    for row in rows.values():
        row["profit"] = round(row["takings"] - row["cost"], 2)
        row["margin"] = round(row["profit"] / row["takings"] * 100, 1) if row["takings"] else 0.0
        row["average"] = round(row["takings"] / row["sales"], 2) if row["sales"] else 0.0
        out.append(row)
    out.sort(key=lambda r: r["day"], reverse=True)
    return out


register(Report(
    key="monthly_summary",
    title="Monthly sales summary",
    module="Till",
    purpose="Month against month, with the trend. Where a quiet season shows "
            "up as a season rather than as a bad week.",
    params=[
        Param("months", "Months back", "text", default="12"),
        BRANCH,
    ],
    columns=[
        Column("month", "Month", "text"),
        Column("sales", "Sales", "number", total=True),
        Column("takings", "Takings", "money", total=True),
        Column("average", "Average sale", "money"),
        Column("change", "vs previous", "percent"),
    ],
    rows=lambda db, p: _monthly(db, p),
))


def _monthly(db: Session, p: dict):
    try:
        months = max(1, min(int(p.get("months") or 12), 60))
    except (TypeError, ValueError):
        months = 12
    # Roughly, then trimmed: a month is not a fixed number of days and the
    # report only needs a floor to filter from.
    since = date.today() - timedelta(days=months * 31)

    query = (
        db.query(Sale.created_at, Sale.total)
        .filter(func.date(Sale.created_at) >= since)
        .filter(Sale.status != "void")
    )
    if p.get("branch_id"):
        query = query.filter(Sale.branch_id == int(p["branch_id"]))

    buckets = {}
    for created, total in query.all():
        key = created.strftime("%Y-%m")
        row = buckets.setdefault(key, {"month": key, "sales": 0, "takings": 0.0})
        row["sales"] += 1
        row["takings"] = round(row["takings"] + float(total or 0), 2)

    ordered = sorted(buckets.values(), key=lambda r: r["month"])
    ordered = ordered[-months:]
    for i, row in enumerate(ordered):
        row["average"] = round(row["takings"] / row["sales"], 2) if row["sales"] else 0.0
        previous = ordered[i - 1]["takings"] if i else 0
        row["change"] = round((row["takings"] - previous) / previous * 100, 1) if previous else 0.0
    ordered.reverse()
    return ordered


register(Report(
    key="tender_register",
    title="Tender detail register",
    module="Till",
    purpose="Every payment of one kind, individually. What a cash-up is checked "
            "against when a figure is disputed.",
    params=[
        Param("method", "Tender", "select", default="card",
              options=[{"value": m, "label": l} for m, l in
                       (("cash", "Cash"), ("card", "Card"),
                        ("mobile_money", "Mobile money"), ("medical_aid", "Medical aid"),
                        ("voucher", "Voucher"), ("cheque", "Cheque"),
                        ("direct", "Direct deposit"))]),
        DATE_FROM, DATE_TO,
    ],
    columns=[
        Column("date", "When", "datetime"),
        Column("sale_number", "Sale", "code"),
        Column("cashier", "Cashier", "text"),
        Column("currency", "Currency", "text"),
        Column("amount", "Amount", "money", total=True),
        Column("in_base", "In base", "money", total=True),
        Column("reference", "Reference", "code"),
    ],
    rows=lambda db, p: _tender_register(db, p),
))


def _tender_register(db: Session, p: dict):
    method = (p.get("method") or "card").strip() or "card"
    rows_q = (
        db.query(SaleTender, Sale)
        .join(Sale, Sale.id == SaleTender.sale_id)
        .filter(SaleTender.method == method)
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .order_by(Sale.created_at.desc())
        .all()
    )
    if not rows_q:
        return []
    names = {
        u.id: (u.full_name or u.username) for u in
        db.query(User).filter(User.id.in_({s.cashier_id for _t, s in rows_q if s.cashier_id})).all()
    }
    return [
        {
            "date": sale.created_at.isoformat(sep=" ", timespec="minutes"),
            "sale_number": sale.sale_number or ("#" + str(sale.id)),
            "cashier": names.get(sale.cashier_id, "-"),
            "currency": tender.currency_code or "",
            "amount": round(tender.amount or 0, 2),
            "in_base": round(tender.amount_in_base or 0, 2),
            "reference": tender.reference or "",
        }
        for tender, sale in rows_q
    ]


register(Report(
    key="price_overrides",
    title="Price overrides",
    module="Till",
    purpose="Where a line was sold for something other than its shelf price, "
            "and by whom. Discounting is only visible if somebody looks.",
    params=[DATE_FROM, DATE_TO],
    step_up=True,
    columns=[
        Column("date", "When", "datetime"),
        Column("sale_number", "Sale", "code"),
        Column("product", "Product", "text"),
        Column("shelf_price", "Shelf", "money"),
        Column("sold_at", "Sold at", "money"),
        Column("difference", "Difference", "money", total=True),
        Column("percent", "Discount", "percent"),
        Column("cashier", "Cashier", "text"),
    ],
    rows=lambda db, p: _overrides(db, p),
))


def _overrides(db: Session, p: dict):
    rows_q = (
        db.query(SaleItem, Sale, Product)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(func.date(Sale.created_at) >= p["date_from"])
        .filter(func.date(Sale.created_at) <= p["date_to"])
        .filter(Sale.status != "void")
        .filter(SaleItem.unit_price != Product.unit_price)
        .order_by(Sale.created_at.desc())
        .all()
    )
    if not rows_q:
        return []
    names = {
        u.id: (u.full_name or u.username) for u in
        db.query(User).filter(User.id.in_({s.cashier_id for _i, s, _p in rows_q if s.cashier_id})).all()
    }
    out = []
    for item, sale, product in rows_q:
        shelf = round(product.unit_price or 0, 2)
        sold = round(item.unit_price or 0, 2)
        quantity = item.quantity or 0
        out.append({
            "date": sale.created_at.isoformat(sep=" ", timespec="minutes"),
            "sale_number": sale.sale_number or ("#" + str(sale.id)),
            "product": product.name,
            "shelf_price": shelf,
            "sold_at": sold,
            "difference": round((sold - shelf) * quantity, 2),
            "percent": round((sold - shelf) / shelf * 100, 1) if shelf else 0.0,
            "cashier": names.get(sale.cashier_id, "-"),
        })
    out.sort(key=lambda r: r["difference"])
    return out


register(Report(
    key="audit_log",
    title="Audit log",
    module="Till",
    purpose="Who did what, and whether it worked. The record that answers a "
            "question about an action nobody admits to.",
    params=[
        # A week rather than the month every other report defaults to. This log
        # takes an entry per request, so a month of it is tens of thousands of
        # rows — enough that the browser gives up before the answer arrives, and
        # a report nobody can wait for is a report nobody has. The window is a
        # default and not a cap: widen it and the total widens with it.
        Param("date_from", "From", "date", default=days_ago(7)),
        DATE_TO,
        Param("user", "User", "text", help="username, or leave blank for all"),
        Param("failures_only", "Failures only", "bool", default=False),
    ],
    step_up=True,
    columns=[
        Column("date", "When", "datetime"),
        Column("username", "User", "text"),
        Column("action", "Action", "text"),
        Column("summary", "Detail", "text"),
        Column("status_code", "Result", "number"),
        Column("ip_address", "From", "code"),
    ],
    rows=lambda db, p: _audit(db, p, 0, 200),
    paged_rows=lambda db, p, offset, limit: _audit_page(db, p, offset, limit),
))


def _audit_query(db: Session, p: dict):
    from ...models import AuditLog

    query = (
        db.query(AuditLog)
        .filter(func.date(AuditLog.created_at) >= p["date_from"])
        .filter(func.date(AuditLog.created_at) <= p["date_to"])
    )
    if p.get("user"):
        query = query.filter(AuditLog.username.ilike("%" + str(p["user"]) + "%"))
    if p.get("failures_only"):
        # Anything the server refused. A log filtered to failures is how a
        # question about a refused action gets answered in one screen.
        query = query.filter(AuditLog.status_code >= 400)
    return query.order_by(AuditLog.created_at.desc())


def _audit_shape(rows):
    return [
        {
            "date": a.created_at.isoformat(sep=" ", timespec="minutes"),
            "username": a.username or "-",
            "action": a.action or "",
            "summary": (a.summary or a.path or "")[:140],
            "status_code": a.status_code,
            "ip_address": a.ip_address or "",
        }
        for a in rows
    ]


def _audit_page(db: Session, p: dict, offset: int, limit: int):
    """Count and one page, both in the database.

    The count is a separate query rather than len() of the rows, for the reason
    this engine keeps insisting on: a page that reports its own length as the
    total looks complete and is not.
    """
    query = _audit_query(db, p)
    total = query.order_by(None).count()
    return total, _audit_shape(query.offset(offset).limit(limit).all())


def _audit(db: Session, p: dict, offset: int = 0, limit: int = 200):
    return _audit_shape(_audit_query(db, p).offset(offset).limit(limit).all())


register(Report(
    key="quotes",
    title="Quotes",
    module="Till",
    purpose="Every quote and what became of it. The ones still open are work "
            "that has been done and not yet paid for.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("date", "Raised", "date"),
        Column("quote_number", "Quote", "code"),
        Column("status", "Status", "text"),
        Column("total", "Value", "money", total=True),
        Column("valid_until", "Valid until", "date"),
        Column("days_open", "Days open", "number"),
        Column("raised_by", "Raised by", "text"),
    ],
    rows=lambda db, p: _quotes(db, p),
))


def _quotes(db: Session, p: dict):
    from ...models import Quote

    rows_q = (
        db.query(Quote)
        .filter(func.date(Quote.created_at) >= p["date_from"])
        .filter(func.date(Quote.created_at) <= p["date_to"])
        .order_by(Quote.created_at.desc())
        .all()
    )
    if not rows_q:
        return []
    names = {
        u.id: (u.full_name or u.username) for u in
        db.query(User).filter(User.id.in_({q.created_by_id for q in rows_q if q.created_by_id})).all()
    }
    today_ = date.today()
    return [
        {
            "date": q.created_at.date().isoformat() if q.created_at else "",
            "quote_number": q.quote_number,
            "status": q.status or "",
            "total": round(q.total or 0, 2),
            "valid_until": q.valid_until.isoformat() if q.valid_until else "",
            # Days open stops at the decision, so a quote settled last month is
            # not still ageing.
            "days_open": ((q.decided_at.date() if q.decided_at else today_)
                          - q.created_at.date()).days if q.created_at else 0,
            "raised_by": names.get(q.created_by_id, "-"),
        }
        for q in rows_q
    ]


# ------------------------------------------------- dispensary, second batch

register(Report(
    key="script_analysis",
    title="Script analysis",
    module="Dispensary",
    purpose="Scripts dispensed by day, with how many were repeats. The shape "
            "of the dispensary's work rather than its total.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("day", "Day", "date"),
        Column("scripts", "Scripts", "number", total=True),
        Column("items", "Items", "number", total=True),
        Column("repeats", "Of which repeats", "number", total=True),
        Column("controlled", "Of which S5/S6", "number", total=True),
        Column("value", "Value", "money", total=True),
    ],
    rows=lambda db, p: _script_analysis(db, p),
))


def _script_analysis(db: Session, p: dict):
    rows_q = (
        db.query(Dispensing, PrescriptionItem, Product, Prescription)
        .join(PrescriptionItem, Dispensing.prescription_item_id == PrescriptionItem.id)
        .join(Product, PrescriptionItem.product_id == Product.id)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .filter(func.date(Dispensing.dispensed_at) >= p["date_from"])
        .filter(func.date(Dispensing.dispensed_at) <= p["date_to"])
        .all()
    )
    days = {}
    seen_scripts = {}
    for dispensing, item, product, script in rows_q:
        key = dispensing.dispensed_at.date().isoformat()
        row = days.setdefault(key, {
            "day": key, "scripts": 0, "items": 0,
            "repeats": 0, "controlled": 0, "value": 0.0,
        })
        # A script with four items is one script, not four. Counting items as
        # scripts is the usual way this report ends up quadrupling itself.
        scripts_today = seen_scripts.setdefault(key, set())
        if script.id not in scripts_today:
            scripts_today.add(script.id)
            row["scripts"] += 1
        row["items"] += 1
        if dispensing.is_repeat:
            row["repeats"] += 1
        if (product.schedule or 0) >= 5:
            row["controlled"] += 1
        row["value"] = round(
            row["value"] + (product.unit_price or 0) * (dispensing.quantity or 0), 2)
    out = sorted(days.values(), key=lambda r: r["day"], reverse=True)
    return out


register(Report(
    key="prescriber_activity",
    title="Prescribers",
    module="Dispensary",
    purpose="Which doctors send work, and what they prescribe. The list a "
            "pharmacy should know and rarely has in one place.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("doctor", "Prescriber", "text"),
        Column("practice", "Practice no.", "code"),
        Column("scripts", "Scripts", "number", total=True),
        Column("items", "Items", "number", total=True),
        Column("patients", "Patients", "number", total=True),
        Column("value", "Value", "money", total=True),
    ],
    rows=lambda db, p: _prescribers(db, p),
))


def _prescribers(db: Session, p: dict):
    from ...models import Doctor

    rows_q = (
        db.query(Dispensing, PrescriptionItem, Product, Prescription)
        .join(PrescriptionItem, Dispensing.prescription_item_id == PrescriptionItem.id)
        .join(Product, PrescriptionItem.product_id == Product.id)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .filter(func.date(Dispensing.dispensed_at) >= p["date_from"])
        .filter(func.date(Dispensing.dispensed_at) <= p["date_to"])
        .all()
    )
    if not rows_q:
        return []
    doctors = {
        d.id: d for d in
        db.query(Doctor).filter(
            Doctor.id.in_({s.doctor_id for _d, _i, _p, s in rows_q if s.doctor_id})).all()
    }
    groups = {}
    for dispensing, item, product, script in rows_q:
        key = script.doctor_id or 0
        doctor = doctors.get(key)
        row = groups.setdefault(key, {
            "doctor": doctor.name if doctor else "(not recorded)",
            "practice": doctor.practice_number if doctor else "",
            "scripts": set(), "items": 0, "patients": set(), "value": 0.0,
        })
        row["scripts"].add(script.id)
        row["patients"].add(script.patient_id)
        row["items"] += 1
        row["value"] = round(
            row["value"] + (product.unit_price or 0) * (dispensing.quantity or 0), 2)
    out = []
    for row in groups.values():
        row["scripts"] = len(row["scripts"])
        row["patients"] = len(row["patients"])
        out.append(row)
    out.sort(key=lambda r: -r["value"])
    return out


register(Report(
    key="script_book",
    title="Script book",
    module="Dispensary",
    purpose="Every script dispensed, in order, with who wrote it and who "
            "dispensed it. The chronological record.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("date", "When", "datetime"),
        Column("rx_number", "Script", "code"),
        Column("patient", "Patient", "text"),
        Column("product", "Item", "text"),
        Column("quantity", "Qty", "number", total=True),
        Column("repeat", "Repeat", "text"),
        Column("prescriber", "Prescriber", "text"),
        Column("dispenser", "Dispensed by", "text"),
    ],
    rows=lambda db, p: _script_book(db, p),
))


def _script_book(db: Session, p: dict):
    from ...models import Doctor

    rows_q = (
        db.query(Dispensing, PrescriptionItem, Product, Prescription)
        .join(PrescriptionItem, Dispensing.prescription_item_id == PrescriptionItem.id)
        .join(Product, PrescriptionItem.product_id == Product.id)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .filter(func.date(Dispensing.dispensed_at) >= p["date_from"])
        .filter(func.date(Dispensing.dispensed_at) <= p["date_to"])
        .order_by(Dispensing.dispensed_at.desc())
        .all()
    )
    if not rows_q:
        return []
    doctors = {d.id: d.name for d in db.query(Doctor).all()}
    patients = {
        pt.id: (pt.first_name + " " + pt.last_name).strip() for pt in
        db.query(Patient).filter(
            Patient.id.in_({s.patient_id for _d, _i, _p, s in rows_q if s.patient_id})).all()
    }
    users = {
        u.id: (u.full_name or u.username) for u in
        db.query(User).filter(
            User.id.in_({d.dispensed_by_id for d, _i, _p, _s in rows_q if d.dispensed_by_id})).all()
    }
    return [
        {
            "date": d.dispensed_at.isoformat(sep=" ", timespec="minutes"),
            "rx_number": script.rx_number or ("#" + str(script.id)),
            "patient": patients.get(script.patient_id, "-"),
            "product": product.name,
            "quantity": d.quantity or 0,
            "repeat": "repeat" if d.is_repeat else "",
            "prescriber": doctors.get(script.doctor_id, "-"),
            "dispenser": users.get(d.dispensed_by_id, "-"),
        }
        for d, item, product, script in rows_q
    ]


register(Report(
    key="generic_substitution",
    title="Generic substitution",
    module="Dispensary",
    purpose="How often a molecule was dispensed as a generic rather than the "
            "originator. Margin and adherence both live here.",
    params=[DATE_FROM, DATE_TO],
    columns=[
        Column("ingredient", "Active ingredient", "text"),
        Column("brands", "Products used", "number"),
        Column("items", "Items", "number", total=True),
        Column("cheapest", "Cheapest", "money"),
        Column("dearest", "Dearest", "money"),
        Column("spread", "Spread", "percent"),
    ],
    rows=lambda db, p: _substitution(db, p),
))


def _substitution(db: Session, p: dict):
    rows_q = (
        db.query(Dispensing, Product)
        .join(PrescriptionItem, Dispensing.prescription_item_id == PrescriptionItem.id)
        .join(Product, PrescriptionItem.product_id == Product.id)
        .filter(func.date(Dispensing.dispensed_at) >= p["date_from"])
        .filter(func.date(Dispensing.dispensed_at) <= p["date_to"])
        .filter(Product.active_ingredient != "")
        .all()
    )
    groups = {}
    for dispensing, product in rows_q:
        key = product.active_ingredient
        row = groups.setdefault(key, {
            "ingredient": key, "items": 0, "_prices": [], "_products": set(),
        })
        row["items"] += 1
        row["_products"].add(product.id)
        if product.unit_price:
            row["_prices"].append(product.unit_price)
    out = []
    for row in groups.values():
        prices = row.pop("_prices")
        row["brands"] = len(row.pop("_products"))
        # Only interesting where there was a choice: one product for a molecule
        # is not a substitution decision.
        if row["brands"] < 2 or not prices:
            continue
        row["cheapest"] = round(min(prices), 2)
        row["dearest"] = round(max(prices), 2)
        row["spread"] = round((row["dearest"] - row["cheapest"]) / row["cheapest"] * 100, 1)
        out.append(row)
    out.sort(key=lambda r: -r["spread"])
    return out


register(Report(
    key="controlled_compliance",
    title="Controlled dispensing compliance",
    module="Dispensary",
    purpose="Schedule 5 and 6 items dispensed without the checks recorded. "
            "What an inspector looks for and what a defence rests on.",
    params=[DATE_FROM, DATE_TO],
    step_up=True,
    columns=[
        Column("date", "When", "datetime"),
        Column("product", "Product", "text"),
        Column("schedule", "Sch", "text"),
        Column("quantity", "Qty", "number", total=True),
        Column("dispenser", "Dispensed by", "text"),
        Column("missing", "Not recorded", "text"),
    ],
    rows=lambda db, p: _controlled(db, p),
))


def _controlled(db: Session, p: dict):
    rows_q = (
        db.query(Dispensing, Product)
        .join(PrescriptionItem, Dispensing.prescription_item_id == PrescriptionItem.id)
        .join(Product, PrescriptionItem.product_id == Product.id)
        .filter(func.date(Dispensing.dispensed_at) >= p["date_from"])
        .filter(func.date(Dispensing.dispensed_at) <= p["date_to"])
        .filter(Product.schedule >= 5)
        .order_by(Dispensing.dispensed_at.desc())
        .all()
    )
    if not rows_q:
        return []
    users = {
        u.id: (u.full_name or u.username) for u in
        db.query(User).filter(
            User.id.in_({d.dispensed_by_id for d, _p in rows_q if d.dispensed_by_id})).all()
    }
    out = []
    for dispensing, product in rows_q:
        gaps = []
        if not dispensing.id_verified:
            gaps.append("identity")
        if not dispensing.script_sighted:
            gaps.append("script sighted")
        if not dispensing.prescriber_verified:
            gaps.append("prescriber")
        if (product.schedule or 0) >= 6 and not dispensing.witness_id:
            gaps.append("witness")
        # Only the ones with something missing. A compliance report listing
        # everything that went right is a report nobody reads to the end.
        if not gaps:
            continue
        out.append({
            "date": dispensing.dispensed_at.isoformat(sep=" ", timespec="minutes"),
            "product": product.name,
            "schedule": "S" + str(product.schedule),
            "quantity": dispensing.quantity or 0,
            "dispenser": users.get(dispensing.dispensed_by_id, "-"),
            "missing": ", ".join(gaps),
        })
    return out


register(Report(
    key="patients_by_scheme",
    title="Patients by medical aid",
    module="Dispensary",
    purpose="How the patient book splits across schemes, and which schemes "
            "actually bring dispensing work.",
    params=[],
    columns=[
        Column("scheme", "Medical aid", "text"),
        Column("patients", "Patients", "number", total=True),
        Column("share", "Share", "percent"),
    ],
    rows=lambda db, p: _by_scheme(db, p),
))


def _by_scheme(db: Session, p: dict):
    from ...models import MedicalAid

    schemes = {m.id: m.name for m in db.query(MedicalAid).all()}
    counts = (
        db.query(Patient.medical_aid_id, func.count(Patient.id))
        .group_by(Patient.medical_aid_id)
        .all()
    )
    total = sum(c for _s, c in counts) or 1
    rows = [
        {
            "scheme": schemes.get(scheme_id, "Private / cash"),
            "patients": int(count or 0),
            "share": round(count / total * 100, 1),
        }
        for scheme_id, count in counts
    ]
    rows.sort(key=lambda r: -r["patients"])
    return rows
