"""Fiscalisation core.

Everything here is authority-neutral. Fiscal regimes differ in their wire
protocol but agree on the mechanics:

* **Fiscal days.** Trading happens inside an open day; closing it produces the
  Z-report totals filed with the authority.
* **Two counters.** A per-day receipt counter that resets, and a global counter
  that never does. Gaps in either are what an auditor looks for.
* **A hash chain.** Each receipt hashes its own contents plus the previous
  receipt's hash. Deleting or editing a receipt after the fact breaks the chain
  and is detectable — which is the entire point of fiscalisation.
* **Queue, don't block.** Connectivity fails; the till must keep trading.
  Receipts are written and hashed locally, then submitted when the authority is
  reachable again.
* **No voids, only credit notes.** Once a receipt is filed it cannot be
  withdrawn. A mistake is reversed by a second, linked receipt.
"""
import base64
import hashlib
import logging
from datetime import datetime

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import FiscalDay, FiscalReceipt, Sale
from . import fiscal_devices

log = logging.getLogger("rx5000.fiscal")

MAX_ATTEMPTS = 10


class FiscalError(RuntimeError):
    """Raised when a fiscal rule would be broken."""


def device() -> fiscal_devices.FiscalDevice:
    return fiscal_devices.get_device(settings.jurisdiction.fiscalisation)


def is_required() -> bool:
    return settings.jurisdiction.fiscalisation is not None


def _hash_receipt(*, device_id: str, global_counter: int, receipt_counter: int,
                  day_number: int, issued_at: datetime, currency: str,
                  total: float, vat: float, previous_hash: str) -> str:
    """SHA-256 over a canonical receipt string, chained to the previous receipt.

    Field order and formatting are fixed — the digest is only meaningful if it
    is reproducible, so amounts are always two decimals and the timestamp is
    always ISO seconds.
    """
    canonical = "|".join([
        device_id,
        str(global_counter),
        str(receipt_counter),
        str(day_number),
        issued_at.replace(microsecond=0).isoformat(),
        currency,
        f"{total:.2f}",
        f"{vat:.2f}",
        previous_hash or "",
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def current_day(db: Session) -> FiscalDay | None:
    return db.query(FiscalDay).filter(FiscalDay.status == "open").first()


def open_day(db: Session) -> FiscalDay:
    existing = current_day(db)
    if existing:
        return existing
    last = db.query(func.max(FiscalDay.day_number)).scalar() or 0
    day = FiscalDay(day_number=last + 1, device_id=getattr(device(), "device_id", ""))
    db.add(day)
    db.commit()
    db.refresh(day)
    log.info("Fiscal day %s opened", day.day_number)
    return day


def _last_receipt(db: Session) -> FiscalReceipt | None:
    return db.query(FiscalReceipt).order_by(desc(FiscalReceipt.global_counter)).first()


def fiscalise(db: Session, sale: Sale, *, receipt_type: str = "sale",
              reverses: FiscalReceipt | None = None) -> FiscalReceipt | None:
    """Create the fiscal record for a sale and try to file it.

    Returns None when the jurisdiction does not require fiscalisation. Never
    raises on a submission failure — the receipt is queued and retried, because
    a till that stops selling when the network drops is worse than a late filing.
    """
    if not is_required():
        return None

    day = current_day(db) or open_day(db)
    previous = _last_receipt(db)
    dev = device()

    receipt = FiscalReceipt(
        sale_id=sale.id,
        fiscal_day_id=day.id,
        receipt_type=receipt_type,
        receipt_counter=day.receipt_count + 1,
        global_counter=(previous.global_counter if previous else 0) + 1,
        currency_code=sale.currency_code or "",
        total=round(sale.total, 2),
        vat_amount=round(sale.vat_amount, 2),
        previous_hash=previous.receipt_hash if previous else "",
        reverses_receipt_id=reverses.id if reverses else None,
    )
    receipt.receipt_hash = _hash_receipt(
        device_id=getattr(dev, "device_id", "") or day.device_id,
        global_counter=receipt.global_counter,
        receipt_counter=receipt.receipt_counter,
        day_number=day.day_number,
        issued_at=datetime.utcnow(),
        currency=receipt.currency_code,
        total=receipt.total,
        vat=receipt.vat_amount,
        previous_hash=receipt.previous_hash,
    )
    db.add(receipt)

    day.receipt_count += 1
    if receipt_type == "credit_note":
        day.total_credit_notes = round(day.total_credit_notes + receipt.total, 2)
    else:
        day.total_sales = round(day.total_sales + receipt.total, 2)
        day.total_vat = round(day.total_vat + receipt.vat_amount, 2)

    db.flush()
    _try_submit(db, receipt, dev)
    db.commit()
    db.refresh(receipt)
    return receipt


def _try_submit(db: Session, receipt: FiscalReceipt, dev=None) -> bool:
    """Attempt one submission. Failure queues rather than raising."""
    dev = dev or device()
    receipt.attempts += 1
    try:
        result = dev.submit_receipt({
            "global_counter": receipt.global_counter,
            "receipt_counter": receipt.receipt_counter,
            "receipt_type": receipt.receipt_type,
            "currency": receipt.currency_code,
            "total": receipt.total,
            "vat": receipt.vat_amount,
            "receipt_hash": receipt.receipt_hash,
            "previous_hash": receipt.previous_hash,
        })
    except NotImplementedError as exc:
        receipt.status = "queued"
        receipt.response_code = "NO_DRIVER"
        receipt.response_message = str(exc)
        log.warning("Fiscal receipt %s queued: %s", receipt.global_counter, exc)
        return False
    except Exception as exc:                       # network, timeout, bad response
        receipt.status = "queued"
        receipt.response_code = "ERROR"
        receipt.response_message = str(exc)[:400]
        log.warning("Fiscal receipt %s queued after error: %s", receipt.global_counter, exc)
        return False

    receipt.response_code = result.get("code", "")
    receipt.response_message = result.get("message", "")
    if result.get("accepted"):
        receipt.status = "accepted"
        receipt.submitted_at = datetime.utcnow()
        receipt.signature = result.get("signature", "")
        receipt.qr_data = result.get("qr_data", "")
        receipt.verification_url = result.get("url", "")
        return True

    # A rejection is final; anything else is worth retrying.
    receipt.status = "rejected" if result.get("code") not in ("", "NETWORK", "ERROR") else "queued"
    return False


def flush_queue(db: Session, limit: int = 100) -> dict:
    """Re-submit queued receipts. Safe to run on a schedule."""
    if not is_required():
        return {"submitted": 0, "still_queued": 0, "given_up": 0}
    dev = device()
    pending = (
        db.query(FiscalReceipt)
        .filter(FiscalReceipt.status == "queued", FiscalReceipt.attempts < MAX_ATTEMPTS)
        .order_by(FiscalReceipt.global_counter)
        .limit(limit)
        .all()
    )
    submitted = 0
    for receipt in pending:
        if _try_submit(db, receipt, dev):
            submitted += 1
    db.commit()
    still = db.query(FiscalReceipt).filter(FiscalReceipt.status == "queued").count()
    given_up = (
        db.query(FiscalReceipt)
        .filter(FiscalReceipt.status == "queued", FiscalReceipt.attempts >= MAX_ATTEMPTS)
        .count()
    )
    if submitted:
        log.info("Filed %d queued fiscal receipt(s)", submitted)
    return {"submitted": submitted, "still_queued": still, "given_up": given_up}


def close_day(db: Session) -> FiscalDay:
    """Close the open fiscal day and file its Z-report."""
    day = current_day(db)
    if not day:
        raise FiscalError("There is no open fiscal day")
    queued = (
        db.query(FiscalReceipt)
        .filter(FiscalReceipt.fiscal_day_id == day.id, FiscalReceipt.status == "queued")
        .count()
    )
    if queued:
        # Closing a day with unfiled receipts would understate the Z-report.
        flush_queue(db)
        queued = (
            db.query(FiscalReceipt)
            .filter(FiscalReceipt.fiscal_day_id == day.id, FiscalReceipt.status == "queued")
            .count()
        )
        if queued:
            raise FiscalError(
                f"{queued} receipt(s) on this day have not been filed yet — "
                "the day cannot be closed until they are"
            )

    day.closed_at = datetime.utcnow()
    day.status = "closed"
    try:
        result = device().close_day({
            "day_number": day.day_number,
            "receipt_count": day.receipt_count,
            "total_sales": day.total_sales,
            "total_vat": day.total_vat,
            "total_credit_notes": day.total_credit_notes,
        })
        if result.get("accepted"):
            day.status = "submitted"
            day.submitted_at = datetime.utcnow()
            day.response_ref = result.get("reference", "")
        else:
            day.error = result.get("message", "")
    except NotImplementedError as exc:
        day.error = str(exc)
    except Exception as exc:
        day.error = str(exc)[:400]
    db.commit()
    db.refresh(day)
    return day


def receipt_for(db: Session, sale_id: int) -> FiscalReceipt | None:
    return (
        db.query(FiscalReceipt)
        .filter(FiscalReceipt.sale_id == sale_id, FiscalReceipt.receipt_type == "sale")
        .first()
    )


def is_locked(db: Session, sale: Sale) -> bool:
    """A filed sale cannot be voided. It must be credit-noted instead."""
    receipt = receipt_for(db, sale.id)
    return bool(receipt and receipt.status in ("accepted", "submitted"))


def verify_chain(db: Session, limit: int = 0) -> dict:
    """Walk the hash chain and report the first break.

    This is what proves nothing has been altered or removed after the fact, and
    it is the whole evidentiary value of fiscalising at all.

    WHAT WAS WRONG WITH THIS, AND WHY IT MATTERED MORE THAN A BUG

    It read the first 5,000 receipts — `order_by(global_counter).limit(5000)` —
    and the screen above it said "All 12,431 receipts verify. Each carries the
    hash of the one before it, so none has been altered or removed."

    Two failures in one sentence. The count was the capped count, so the claim
    described more than was examined. And the 5,000 it read were the OLDEST,
    which are the least interesting receipts in the register: a receipt somebody
    edits is one from last week, and every one of those went unchecked forever.

    An integrity check that quietly stops looking, under a sentence promising it
    looked at everything, is worse than no check. It is the thing a pharmacy
    would point an auditor at.

    Now the whole chain, always. Three columns rather than whole ORM objects, so
    a register of a hundred thousand receipts is one query and a walk rather
    than a hundred thousand instantiated rows — the reason a cap looked
    necessary in the first place. `limit` is kept for a caller that genuinely
    wants a sample, and when it is used the answer says so instead of implying
    completeness.
    """
    query = (db.query(FiscalReceipt.global_counter,
                      FiscalReceipt.previous_hash,
                      FiscalReceipt.receipt_hash)
             .order_by(FiscalReceipt.global_counter))
    total = db.query(func.count(FiscalReceipt.id)).scalar() or 0

    if limit:
        # A deliberate sample takes the MOST RECENT, not the oldest. If only
        # part of the register can be read, it must be the part somebody would
        # have tampered with.
        query = (db.query(FiscalReceipt.global_counter,
                          FiscalReceipt.previous_hash,
                          FiscalReceipt.receipt_hash)
                 .order_by(FiscalReceipt.global_counter.desc())
                 .limit(limit))
        rows = list(reversed(query.all()))
    else:
        rows = query.all()

    partial = bool(limit) and total > len(rows)
    expected_counter = None
    previous_hash = ""
    for counter, prior, own in rows:
        if expected_counter is None:
            expected_counter = counter
            # A sample starts mid-chain, so the first row's `previous_hash`
            # points at a receipt that was not read. Believed rather than
            # checked, and the answer says the check was partial.
            previous_hash = prior if partial else ""
        if counter != expected_counter:
            return _broken(counter, len(rows), total, partial,
                           f"counter gap, expected {expected_counter}")
        if prior != previous_hash:
            return _broken(counter, len(rows), total, partial,
                           "previous hash does not match the preceding receipt")
        previous_hash = own
        expected_counter += 1

    return {
        "ok": True, "checked": len(rows), "total": total,
        "partial": partial, "broken_at": None, "reason": "",
        "says": (
            f"All {total:,} receipts verify. Each carries the hash of the one "
            f"before it, so none has been altered or removed."
            if not partial else
            f"The most recent {len(rows):,} of {total:,} receipts verify. The "
            f"earlier ones were not read on this pass."),
    }


def _broken(counter: int, checked: int, total: int, partial: bool,
            reason: str) -> dict:
    return {
        "ok": False, "checked": checked, "total": total, "partial": partial,
        "broken_at": counter, "reason": reason,
        "says": (f"The chain breaks at receipt {counter}. {reason}. Every "
                 f"receipt from there onwards is unproven, and this is what an "
                 f"auditor looks for."),
    }
