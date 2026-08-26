"""Recall: from a batch number to the people holding it, and back again.

A manufacturer withdraws batch A4471. The pharmacy has to answer two questions
that afternoon, and the paper answer to both is somebody reading a shelf and a
day book:

  **Forward — who has it?**   Every patient dispensed from that batch, with a
  telephone number, so they can be called. This is the one with a clock on it.

  **Backward — where did it come from and what is left?**  The supplier, the
  order, the date received, and how much is still on the shelf to quarantine.

Every fact needed already existed in this database and nothing joined them up.
A batch allocation knows which sale line it served; the sale line knows the sale;
the sale knows the patient. Three joins nobody had written, which meant a recall
was answered by memory.

**It reports what it cannot see.** Stock received before batch allocation was
recorded, or dispensed without a batch, cannot be traced to a patient — and a
recall report that quietly omits those reads as "nobody else has it", which is
the most dangerous sentence this module could produce. Untraceable quantity is
counted and stated in the same breath as the traceable.

The financial side is deliberately not automatic. What a recall costs depends on
whether the manufacturer credits it, and posting a write-off before that is known
turns one uncertainty into a wrong number in the ledger. The figure is shown; the
posting is a decision.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from ..models import (
    Dispensing, Patient, PrescriptionItem, Prescription, Product,
    PurchaseOrder, PurchaseOrderItem, Sale, SaleItem, StockBatch, Supplier,
)


def find_batches(db: Session, query: str, *, limit: int = 40) -> list[dict]:
    """Batches matching a number or a product name.

    Matched loosely on purpose: a recall notice gives a batch number in the
    manufacturer's format and the pharmacy typed whatever was on the box.
    """
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    rows = (db.query(StockBatch, Product)
              .join(Product, StockBatch.product_id == Product.id)
              .filter(or_(StockBatch.batch_number.ilike(like),
                          Product.name.ilike(like)))
              .order_by(StockBatch.expiry_date.asc().nullslast())
              .limit(limit).all())
    return [{
        "batch_id": b.id,
        "batch_number": b.batch_number or "",
        "product_id": p.id,
        "product": f"{p.name} {p.strength or ''}".strip(),
        "expiry_date": b.expiry_date,
        "quantity_received": b.quantity_received,
        "quantity_remaining": b.quantity_remaining,
        "received_at": b.received_at,
    } for b, p in rows]


def _origin(db: Session, batch: StockBatch) -> dict:
    """Where the batch came from: the order and the supplier, where recorded."""
    order = None
    if batch.reference:
        order = (db.query(PurchaseOrder)
                   .filter(PurchaseOrder.order_number == batch.reference)
                   .first())
    if order is None and batch.product_id:
        # Fall back to the most recent received order carrying this product.
        order = (db.query(PurchaseOrder)
                   .join(PurchaseOrderItem, PurchaseOrderItem.order_id == PurchaseOrder.id)
                   .filter(PurchaseOrderItem.product_id == batch.product_id,
                           PurchaseOrder.status == "received")
                   .order_by(PurchaseOrder.created_at.desc())
                   .first())
    supplier = db.get(Supplier, order.supplier_id) if order else None
    return {
        "order_number": order.order_number if order else "",
        "ordered_on": order.created_at if order else None,
        "received_on": batch.received_at,
        "supplier": supplier.name if supplier else "",
        "supplier_phone": supplier.phone if supplier else "",
        "supplier_email": supplier.email if supplier else "",
        # Said rather than left blank. "No supplier recorded" is a fact the
        # pharmacy needs at the moment it is trying to return stock.
        "certain": bool(order and supplier),
    }


def trace(db: Session, batch_id: int) -> dict:
    """Everything known about one batch: where it came from, where it went.

    The counts are reconciled out loud. Received, still on the shelf, traced to a
    named patient, and a remainder that left the building without a batch
    allocation. That remainder is the honest part of the answer.
    """
    batch = db.get(StockBatch, batch_id)
    if not batch:
        return {}
    product = db.get(Product, batch.product_id)

    # Forward: allocations link a batch to the sale line it served, and the sale
    # line to the sale and the patient. This is the join nobody had written.
    rows = db.execute(
        text("""
        SELECT ba.quantity      AS qty,
               s.id             AS sale_id,
               s.sale_number    AS sale_number,
               s.created_at     AS sold_at,
               p.id             AS patient_id,
               p.first_name     AS first_name,
               p.last_name      AS last_name,
               p.phone          AS phone,
               rx.rx_number     AS rx_number
          FROM batch_allocations ba
          JOIN sale_items si ON si.id = ba.sale_item_id
          JOIN sales      s  ON s.id  = si.sale_id
          LEFT JOIN patients p ON p.id = s.patient_id
          LEFT JOIN prescription_items pi ON pi.id = si.prescription_item_id
          LEFT JOIN prescriptions rx ON rx.id = pi.prescription_id
         WHERE ba.batch_id = :batch
         ORDER BY s.created_at DESC
        """),
        {"batch": batch_id},
    ).mappings().all() if _has_allocations(db) else []

    recipients = []
    traced_units = 0
    anonymous_units = 0
    for r in rows:
        traced_units += r["qty"] or 0
        if r["patient_id"] is None:
            # A walk-in. The batch went out and there is no one to telephone;
            # that is a real outcome and is counted separately rather than
            # dropped, because it changes what the pharmacy can promise.
            anonymous_units += r["qty"] or 0
            continue
        recipients.append({
            "patient_id": r["patient_id"],
            "patient": f"{r['first_name']} {r['last_name']}",
            "phone": r["phone"] or "",
            "quantity": r["qty"],
            "sale_number": r["sale_number"],
            "rx_number": r["rx_number"] or "",
            "sold_at": r["sold_at"],
        })

    received = batch.quantity_received or 0
    remaining = batch.quantity_remaining or 0
    # What left the shelf but no allocation accounts for. Stock received before
    # allocations were recorded, or written off, or dispensed without a batch.
    unaccounted = max(0, received - remaining - traced_units)

    return {
        "batch": {
            "batch_id": batch.id,
            "batch_number": batch.batch_number or "",
            "product": f"{product.name} {product.strength or ''}".strip() if product else "",
            "product_id": batch.product_id,
            "schedule": product.schedule if product else None,
            "expiry_date": batch.expiry_date,
            "unit_cost": batch.unit_cost or 0,
        },
        "origin": _origin(db, batch),
        "quantities": {
            "received": received,
            "on_shelf": remaining,
            "traced_to_a_patient": traced_units - anonymous_units,
            "sold_to_a_walk_in": anonymous_units,
            # Named, not hidden. A recall report that quietly omits what it
            # cannot see reads as "nobody else has it".
            "unaccounted": unaccounted,
        },
        "recipients": recipients,
        "to_call": len({r["patient_id"] for r in recipients if r["phone"]}),
        "no_phone": len([r for r in recipients if not r["phone"]]),
        "value_on_shelf": round(remaining * (batch.unit_cost or 0), 2),
        "value_dispensed": round(traced_units * (batch.unit_cost or 0), 2),
        "warnings": _warnings(remaining, unaccounted, anonymous_units,
                              [r for r in recipients if not r["phone"]]),
    }


def _has_allocations(db: Session) -> bool:
    """Whether this build records which batch served which sale line."""
    try:
        db.execute(text("SELECT 1 FROM batch_allocations LIMIT 1"))
        return True
    except Exception:
        db.rollback()
        return False


def _warnings(remaining: int, unaccounted: int, anonymous: int, unreachable: list) -> list[str]:
    out = []
    if remaining:
        out.append(f"{remaining} unit(s) are still on the shelf. Quarantine them "
                   "before anything else, because that is the part still capable "
                   "of reaching somebody.")
    if unaccounted:
        out.append(f"{unaccounted} unit(s) left the shelf with no batch recorded "
                   "against the sale, so who received them cannot be established "
                   "from this system.")
    if anonymous:
        out.append(f"{anonymous} unit(s) went to walk-in customers with no patient "
                   "record. There is nobody to telephone.")
    if unreachable:
        out.append(f"{len(unreachable)} patient(s) have no telephone number on "
                   "file and will have to be reached another way.")
    return out
