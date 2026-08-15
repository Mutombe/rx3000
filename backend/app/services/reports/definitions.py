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
    Dispensing, Patient, PrescriptionItem, Product, Sale, SaleItem, SaleTender,
    StockBatch, StockMovement, Supplier, User,
)
from .engine import Column, Param, Report, month_start, register, today


def _branch_options(db: Session):
    from ...models import Branch
    return [{"value": "", "label": "All branches"}] + [
        {"value": b.id, "label": b.name}
        for b in db.query(Branch).order_by(Branch.name).all()
    ]


DATE_FROM = Param("date_from", "From", "date", default=month_start)
DATE_TO = Param("date_to", "To", "date", default=today)
BRANCH = Param("branch_id", "Branch", "select", options=_branch_options)


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
            func.sum(func.coalesce(Product.cost_price, 0) * SaleItem.quantity),
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
