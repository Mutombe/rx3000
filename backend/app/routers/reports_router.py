from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import (
    Claim, Dispensing, Message, Patient, PrescriptionItem, Product, Sale, SaleItem, StockBatch,
)

router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(get_current_user)])


def _range(date_from: str, date_to: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.fromisoformat(date_from) if date_from else datetime.utcnow() - timedelta(days=30)
        end = datetime.fromisoformat(date_to + "T23:59:59") if date_to else datetime.utcnow()
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")
    return start, end


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    # A date object, not a string. SQLite compares a DATE column to '2026-08-11'
    # happily; Postgres refuses with `operator does not exist: date = character
    # varying`, which surfaces in the browser as a CORS error because the 500
    # never reaches the CORS middleware.
    today = date.today()
    week_ago = datetime.utcnow() - timedelta(days=7)

    sales_today = db.query(func.count(Sale.id), func.coalesce(func.sum(Sale.total), 0.0)).filter(
        Sale.status == "paid", func.date(Sale.created_at) == today
    ).one()
    scripts_today = db.query(func.count(Dispensing.id)).filter(
        func.date(Dispensing.dispensed_at) == today
    ).scalar()
    low_stock = db.query(func.count(Product.id)).filter(
        Product.active, Product.quantity_on_hand <= Product.reorder_level
    ).scalar()
    repeats_due = db.query(func.count(PrescriptionItem.id)).filter(
        PrescriptionItem.next_repeat_date.isnot(None),
        PrescriptionItem.next_repeat_date <= date.today() + timedelta(days=7),
        PrescriptionItem.repeats_used < PrescriptionItem.repeats_allowed,
    ).scalar()
    pending_sales = db.query(func.count(Sale.id)).filter(Sale.status == "pending").scalar()
    messages_pending = db.query(func.count(Message.id)).filter(Message.status == "pending").scalar()
    expiring_soon = db.query(func.count(StockBatch.id)).filter(
        StockBatch.quantity_remaining > 0,
        StockBatch.expiry_date <= date.today() + timedelta(days=90),
    ).scalar()

    daily = (
        db.query(func.date(Sale.created_at).label("day"), func.coalesce(func.sum(Sale.total), 0.0))
        .filter(Sale.status == "paid", Sale.created_at >= week_ago)
        .group_by(func.date(Sale.created_at)).order_by("day").all()
    )
    return {
        "sales_today_count": sales_today[0],
        "sales_today_total": round(sales_today[1], 2),
        "scripts_today": scripts_today,
        "low_stock_count": low_stock,
        "repeats_due_count": repeats_due,
        "pending_sales": pending_sales,
        "messages_pending": messages_pending,
        "expiring_soon_count": expiring_soon,
        "week_sales": [{"day": d, "total": round(t, 2)} for d, t in daily],
        "currency": settings.CURRENCY,
        "pharmacy_name": settings.PHARMACY_NAME,
    }


@router.get("/daily-totals")
def daily_totals(date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
    start, end = _range(date_from, date_to)
    rows = (
        db.query(
            func.date(Sale.created_at).label("day"),
            Sale.payment_method,
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.total), 0.0),
            func.coalesce(func.sum(Sale.vat_amount), 0.0),
        )
        .filter(Sale.status == "paid", Sale.created_at >= start, Sale.created_at <= end)
        .group_by(func.date(Sale.created_at), Sale.payment_method)
        .order_by(func.date(Sale.created_at).desc())
        .all()
    )
    days: dict[str, dict] = {}
    for day, method, count, total, vat in rows:
        entry = days.setdefault(day, {"day": day, "transactions": 0, "total": 0.0, "vat": 0.0, "by_method": {}})
        entry["transactions"] += count
        entry["total"] = round(entry["total"] + total, 2)
        entry["vat"] = round(entry["vat"] + vat, 2)
        entry["by_method"][method] = round(entry["by_method"].get(method, 0.0) + total, 2)
    return list(days.values())


@router.get("/vat")
def vat_report(date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
    start, end = _range(date_from, date_to)
    totals = db.query(
        func.coalesce(func.sum(Sale.subtotal), 0.0),
        func.coalesce(func.sum(Sale.vat_amount), 0.0),
        func.coalesce(func.sum(Sale.total), 0.0),
        func.count(Sale.id),
    ).filter(Sale.status == "paid", Sale.created_at >= start, Sale.created_at <= end).one()
    return {
        "date_from": start.date().isoformat(),
        "date_to": end.date().isoformat(),
        "sales_ex_vat": round(totals[0], 2),
        "vat_collected": round(totals[1], 2),
        "sales_inc_vat": round(totals[2], 2),
        "transactions": totals[3],
        "vat_rate": settings.VAT_RATE,
    }


@router.get("/patient/{patient_id}/tax")
def patient_tax_report(patient_id: int, year: int | None = None, db: Session = Depends(get_db)):
    """Medical expense statement for a patient (SARS-style tax certificate data)."""
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    year = year or date.today().year
    # The tax year window comes from the jurisdiction pack — South Africa runs
    # 1 March to end February, Zimbabwe runs the calendar year.
    j = settings.jurisdiction
    start = datetime(year, j.tax_year_start_month, j.tax_year_start_day)
    if (j.tax_year_start_month, j.tax_year_start_day) == (1, 1):
        end = datetime(year, 12, 31, 23, 59, 59)
    else:
        end = datetime(year + 1, j.tax_year_start_month, j.tax_year_start_day) - timedelta(seconds=1)

    sales = (
        db.query(Sale)
        .filter(Sale.patient_id == patient_id, Sale.status == "paid",
                Sale.created_at >= start, Sale.created_at <= end)
        .order_by(Sale.created_at)
        .all()
    )
    claims = {c.sale_id: c for c in db.query(Claim).filter(
        Claim.patient_id == patient_id, Claim.created_at >= start, Claim.created_at <= end
    ).all()}

    lines = []
    total_spent = total_claimed = total_out_of_pocket = 0.0
    for sale in sales:
        claim = claims.get(sale.id)
        approved = claim.amount_approved if claim and claim.status in ("approved", "partial") else 0.0
        out_of_pocket = round(sale.total - approved, 2)
        total_spent += sale.total
        total_claimed += approved
        total_out_of_pocket += out_of_pocket
        lines.append({
            "date": sale.created_at.date().isoformat(),
            "invoice": sale.sale_number,
            "total": sale.total,
            "medical_aid_paid": round(approved, 2),
            "out_of_pocket": out_of_pocket,
            "items": [i.description for i in sale.items],
        })
    return {
        "patient": f"{patient.first_name} {patient.last_name}",
        "id_number": patient.id_number,
        "medical_aid": patient.medical_aid.name if patient.medical_aid else None,
        "medical_aid_number": patient.medical_aid_number,
        "tax_year": f"{start.date()} to {end.date()}",
        "total_spent": round(total_spent, 2),
        "total_medical_aid_paid": round(total_claimed, 2),
        "total_out_of_pocket": round(total_out_of_pocket, 2),
        "lines": lines,
    }


@router.get("/patient/{patient_id}/history")
def patient_history(patient_id: int, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    # Joined for filtering AND loaded for reading.
    #
    # The joins below narrow to one patient; they do not populate anything. So
    # every one of the two hundred rows then went back to the database four
    # times over — for its line, that line's product, the script it belongs to
    # and who handed it over. Eight hundred round trips to draw one table. On
    # SQLite that is invisible; on the hosted database it is over a minute, and
    # a patient's history is opened at the counter with somebody waiting.
    dispensings = (
        db.query(Dispensing)
        .join(Dispensing.prescription_item)
        .join(PrescriptionItem.prescription)
        .filter_by(patient_id=patient_id)
        .options(
            joinedload(Dispensing.prescription_item)
            .joinedload(PrescriptionItem.product),
            joinedload(Dispensing.prescription_item)
            .joinedload(PrescriptionItem.prescription),
            joinedload(Dispensing.dispensed_by),
        )
        .order_by(Dispensing.dispensed_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "date": d.dispensed_at.isoformat(),
            # Every name here is a record somebody will want to open. The ids
            # were all in hand and none of them were sent, so a pharmacist
            # asking "which script was this?" had to go and search for it by
            # number on another screen.
            "product": d.prescription_item.product.name,
            "product_id": d.prescription_item.product_id,
            "strength": d.prescription_item.product.strength,
            "quantity": d.quantity,
            "dosage": d.prescription_item.dosage_instructions,
            "is_repeat": d.is_repeat,
            "rx_number": d.prescription_item.prescription.rx_number,
            "prescription_id": d.prescription_item.prescription_id,
            "dispensed_by": d.dispensed_by.full_name if d.dispensed_by else "",
            "dispensed_by_id": d.dispensed_by_id,
        }
        for d in dispensings
    ]


@router.get("/stock-valuation")
def stock_valuation(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.active).all()
    lines = [
        {
            "product": p.name,
            "on_hand": p.quantity_on_hand,
            "cost_price": p.cost_price,
            "value_at_cost": round(p.quantity_on_hand * p.cost_price, 2),
            "value_at_retail": round(p.quantity_on_hand * p.unit_price, 2),
        }
        for p in products if p.quantity_on_hand > 0
    ]
    return {
        "total_at_cost": round(sum(l["value_at_cost"] for l in lines), 2),
        "total_at_retail": round(sum(l["value_at_retail"] for l in lines), 2),
        "lines": sorted(lines, key=lambda l: -l["value_at_cost"]),
    }


# ---------------------------------------------------------- report engine
#
# Three endpoints serve the whole catalogue, however large it grows. Adding a
# report means declaring it, never touching this file — which is the difference
# between a catalogue that can reach a hundred reports and one that cannot.
from fastapi import Query, Request, Response  # noqa: E402
from ..services import reports as report_engine  # noqa: E402


@router.get("/catalogue")
def report_catalogue():
    """Every report the system can run, for the reports index."""
    return {"reports": report_engine.catalogue()}


@router.get("/run/{key}")
def run_report(
    key: str,
    request: Request,
    page: int = 1, per_page: int = 100,
    sort: str = "", desc: bool = False,
    db: Session = Depends(get_db),
):
    """Run a report. Report-specific parameters arrive as ordinary query
    parameters and are validated by the report's own declaration."""
    given = {
        k: v for k, v in request.query_params.items()
        if k not in ("page", "per_page", "sort", "desc")
    }
    try:
        return report_engine.run(db, key, given, page=page, per_page=per_page,
                                 sort=sort, desc=desc)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        # A bad parameter is the user's mistake and is worth saying plainly,
        # rather than arriving as a 500 with no sentence in it.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/export/{key}")
def export_report(
    key: str,
    request: Request,
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    sort: str = "", desc: bool = False,
    db: Session = Depends(get_db),
):
    """The same query the screen ran, as a file.

    Deliberately not a second implementation. An export that re-derives its own
    rows is an export that can disagree with what the person exporting it was
    looking at, and they are the last people who would notice.
    """
    given = {
        k: v for k, v in request.query_params.items()
        if k not in ("format", "sort", "desc")
    }
    try:
        report = report_engine.REGISTRY[key]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"There is no report called '{key}'.")

    stamp = date.today().isoformat()
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in report.title).strip("-")
    try:
        if format == "csv":
            body = report_engine.to_csv(db, key, given, sort=sort, desc=desc)
            return Response(
                content=body, media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{safe}-{stamp}.csv"'},
            )
        body = report_engine.to_xlsx(db, key, given, sort=sort, desc=desc)
        return Response(
            content=body,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{safe}-{stamp}.xlsx"'},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
