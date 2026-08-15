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
    Dispensing, Patient, PrescriptionItem, Product, Sale, SaleItem, StockBatch,
    StockMovement, Supplier, User,
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
    buckets: dict[int, dict] = {
        h: {"hour": f"{h:02d}:00", "transactions": 0, "units": 0, "amount": 0.0}
        for h in range(24)
    }
    for sale in _sales_in(db, p).all():
        bucket = buckets[sale.created_at.hour]
        bucket["transactions"] += 1
        bucket["amount"] = round(bucket["amount"] + (sale.total or 0), 2)
        bucket["units"] += sum(i.quantity or 0 for i in sale.items)
    rows = []
    for bucket in buckets.values():
        # An hour the shop was shut is not a finding, it is noise.
        if not bucket["transactions"]:
            continue
        bucket["average"] = round(bucket["amount"] / bucket["transactions"], 2)
        rows.append(bucket)
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
    groups: dict[str, dict] = {}
    for sale in _sales_in(db, p).all():
        for item in sale.items:
            product = item.product
            key = (product.category if product else "") or "uncategorised"
            row = groups.setdefault(key, {
                "department": key.replace("_", " "),
                "units": 0, "amount": 0.0, "cost": 0.0,
            })
            quantity = item.quantity or 0
            row["units"] += quantity
            row["amount"] = round(row["amount"] + (item.unit_price or 0) * quantity, 2)
            row["cost"] = round(
                row["cost"] + ((product.cost_price if product else 0) or 0) * quantity, 2)
    rows = []
    for row in groups.values():
        row["profit"] = round(row["amount"] - row["cost"], 2)
        row["margin"] = round(row["profit"] / row["amount"] * 100, 1) if row["amount"] else 0.0
        rows.append(row)
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

    rows = []
    for entry in (
        db.query(RegisterEntry)
        .filter(func.date(RegisterEntry.created_at) >= p["date_from"])
        .filter(func.date(RegisterEntry.created_at) <= p["date_to"])
        .order_by(RegisterEntry.created_at.desc())
        .all()
    ):
        product = db.query(Product).get(entry.product_id)
        patient = (
            db.query(Patient).get(entry.patient_id)
            if getattr(entry, "patient_id", None) else None
        )
        user = db.query(User).get(entry.user_id) if entry.user_id else None
        rows.append({
            "date": entry.created_at.isoformat(sep=" ", timespec="minutes"),
            "product": product.name if product else f"#{entry.product_id}",
            "schedule": f"S{entry.schedule}",
            "quantity": abs(entry.quantity_delta or 0),
            "patient": f"{patient.first_name} {patient.last_name}" if patient else "—",
            "dispenser": (user.full_name or user.username) if user else "—",
            "reference": getattr(entry, "reference", "") or "",
        })
    return rows
