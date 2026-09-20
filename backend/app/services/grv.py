"""The delivery, written down as a document.

Receiving already worked. Stock went on the shelf, batches were created,
outstanding quantities were tracked, and an order stayed open until all of it
arrived. What was missing was the thing in somebody's hand at the back door:
the delivery note, the invoice number on it, the date, and the signature. The
goods carried the ORDER number into the batch table, so two vans a week apart
against one order were indistinguishable afterwards.

This module is that record and nothing else. It does not move stock: the
callers already do, correctly, and a second module writing quantities is how
a shelf figure ends up counted twice. `line()` is told what the caller has
just booked in, and files it.

THE SHAPE OF A DELIVERY

One GRV per van. A keyed delivery is one call and closes at the end of it. A
scanned delivery is thirty calls over twenty minutes as somebody works down a
pallet, so `open_for` finds the receipt that person already has open against
that order and adds to it, rather than leaving thirty one-line documents.

WHAT "OPEN" MEANS, AND WHY IT EXPIRES

Open means somebody is still unloading. It stops being true overnight, so an
open receipt older than the cutoff is not reused: the next scan starts a
fresh GRV. Otherwise a Tuesday delivery joins Monday's document, which is
exactly the merge this module exists to prevent.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..models import (GoodsReceipt, GoodsReceiptLine, Product, PurchaseOrder,
                      StockBatch, Supplier, SupplierInvoice, User)

#: How long a part-finished receipt stays the one to add to. Long enough for a
#: big delivery and a tea break, short enough that tomorrow is a new document.
STILL_UNLOADING = timedelta(hours=8)

#: What a line can be received as.
CONDITIONS = ("good", "damaged")


def open_for(db: Session, *, supplier_id: int, user: User,
             order: PurchaseOrder | None = None,
             branch_id: int | None = None,
             delivery_note: str = "", invoice_number: str = "") -> GoodsReceipt:
    """The receipt this delivery belongs on, opening one if there is none."""
    from .. import helpers

    since = datetime.utcnow() - STILL_UNLOADING
    found = (db.query(GoodsReceipt)
             .filter(GoodsReceipt.status == "open",
                     GoodsReceipt.supplier_id == supplier_id,
                     GoodsReceipt.received_by_id == getattr(user, "id", None),
                     GoodsReceipt.received_at >= since))
    if order is not None:
        found = found.filter(GoodsReceipt.order_id == order.id)
    else:
        found = found.filter(GoodsReceipt.order_id.is_(None))
    grv = found.order_by(GoodsReceipt.received_at.desc()).first()
    if grv is not None:
        # Numbers written on the paperwork can arrive after the first carton
        # has been scanned. Fill a blank; never overwrite what is there.
        if delivery_note and not grv.delivery_note:
            grv.delivery_note = delivery_note.strip()[:40]
        if invoice_number and not grv.invoice_number:
            grv.invoice_number = invoice_number.strip()[:40]
        return grv

    grv = GoodsReceipt(
        grv_number=helpers.next_number(db, GoodsReceipt, "GRV", "grv_number"),
        supplier_id=supplier_id,
        order_id=order.id if order is not None else None,
        branch_id=branch_id if branch_id is not None
        else getattr(order, "branch_id", None),
        status="open",
        delivery_note=(delivery_note or "").strip()[:40],
        invoice_number=(invoice_number or "").strip()[:40],
        received_by_id=getattr(user, "id", None),
        received_at=datetime.utcnow(),
    )
    db.add(grv)
    db.flush()
    return grv


def line(db: Session, grv: GoodsReceipt, *, product: Product,
         packs: int, unit_cost: float | None = None,
         batch: StockBatch | None = None, batch_number: str = "",
         expiry_date: date | None = None, order_item_id: int | None = None,
         condition: str = "good") -> GoodsReceiptLine:
    """File one lot that the caller has already put on the shelf."""
    if condition not in CONDITIONS:
        condition = "good"
    row = GoodsReceiptLine(
        receipt_id=grv.id,
        product_id=product.id,
        order_item_id=order_item_id,
        batch_id=getattr(batch, "id", None),
        quantity=int(packs or 0),
        unit_cost=round(float(unit_cost or 0.0), 4),
        batch_number=(batch_number or getattr(batch, "batch_number", "") or "")[:50],
        expiry_date=expiry_date or getattr(batch, "expiry_date", None),
        condition=condition,
        pharmacy_id=grv.pharmacy_id,
    )
    db.add(row)
    grv.goods_total = round((grv.goods_total or 0.0) + row.line_total, 2)
    return row


def close(db: Session, grv: GoodsReceipt, *, delivery_note: str = "",
          invoice_number: str = "", notes: str = "") -> GoodsReceipt:
    """Sign for it. The goods are on the shelf and the document is final."""
    if delivery_note:
        grv.delivery_note = delivery_note.strip()[:40]
    if invoice_number:
        grv.invoice_number = invoice_number.strip()[:40]
    if notes:
        grv.notes = notes[:2000]
    grv.status = "received"
    return grv


def match_invoice(db: Session, grv: GoodsReceipt,
                  invoice: SupplierInvoice) -> GoodsReceipt:
    """Say which bill this delivery is on.

    Kept apart from closing because it happens weeks later, and a delivery
    that has no invoice against it yet is a normal state rather than a gap.
    """
    grv.invoice_id = invoice.id
    if not grv.invoice_number:
        grv.invoice_number = (invoice.invoice_number or "")[:40]
    return grv


def for_batch(db: Session, batch_id: int) -> GoodsReceipt | None:
    """Which delivery a lot on the shelf came off.

    This is what a supplier return is for: the blueprint asks that a return be
    raised against the GRV the goods arrived on, and a credit claim that can
    name the delivery note is one a wholesaler settles rather than argues.
    """
    row = (db.query(GoodsReceiptLine)
           .filter(GoodsReceiptLine.batch_id == batch_id)
           .order_by(GoodsReceiptLine.id.desc()).first())
    return row.parent if row is not None else None


def shape(grv: GoodsReceipt) -> dict:
    """One delivery, as a screen needs it."""
    damaged = sum(l.quantity or 0 for l in grv.lines if l.condition == "damaged")
    return {
        "id": grv.id,
        "grv_number": grv.grv_number,
        "status": grv.status,
        "supplier_id": grv.supplier_id,
        "supplier": grv.supplier.name if grv.supplier else "",
        "order_id": grv.order_id,
        "order_number": grv.order.order_number if grv.order else "",
        "delivery_note": grv.delivery_note or "",
        "invoice_number": grv.invoice_number or "",
        "invoice_id": grv.invoice_id,
        "goods_total": round(grv.goods_total or 0.0, 2),
        "notes": grv.notes or "",
        "received_by": grv.received_by.username if grv.received_by else "",
        "received_at": grv.received_at.isoformat() if grv.received_at else "",
        "lines": len(grv.lines),
        "packs": sum(l.quantity or 0 for l in grv.lines),
        "damaged": damaged,
        "items": [{
            "product_id": l.product_id,
            "product": l.product.name if l.product else "",
            "batch_id": l.batch_id,
            "batch": l.batch_number or "",
            "expiry": l.expiry_date.isoformat() if l.expiry_date else "",
            "quantity": l.quantity or 0,
            "unit_cost": round(l.unit_cost or 0.0, 4),
            "line_total": l.line_total,
            "condition": l.condition or "good",
        } for l in grv.lines],
    }
