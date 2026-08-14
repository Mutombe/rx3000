"""Card settlement reconciliation.

An acquirer settles in batches and sends a statement — a CSV listing every
approved transaction. This matches that file against the card sales RX3000
recorded, so the pharmacy can see exactly which takings banked, which are
missing, and where the amounts disagree.

Matching is deliberately layered: auth code first (the strongest identifier a
terminal slip carries), then the acquirer's own reference, then a same-day
amount match as a last resort. Anything that only matches on amount is
reported as `weak` so it can be eyeballed rather than trusted.
"""
import csv
import io
from datetime import date, datetime

from sqlalchemy.orm import Session

from . import currency
from ..models import Sale

# Header aliases — acquirers all name these columns differently
FIELD_ALIASES = {
    "auth_code": {"auth_code", "authcode", "auth", "authorisation", "authorization", "approval_code", "approval"},
    "reference": {"reference", "ref", "rrn", "retrieval_reference", "transaction_id", "txn_id", "trace"},
    "amount": {"amount", "value", "total", "transaction_amount", "amt"},
    "date": {"date", "transaction_date", "txn_date", "datetime", "timestamp"},
    "last4": {"last4", "card_last4", "pan", "masked_pan", "card_number"},
    "terminal": {"terminal", "terminal_id", "tid", "device"},
    "batch": {"batch", "batch_number", "batch_no"},
}

TOLERANCE = 0.01  # cents rounding between acquirer and till


def _normalise_header(name: str) -> str:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    for field, aliases in FIELD_ALIASES.items():
        if key in aliases:
            return field
    return key


def _to_amount(raw: str) -> float | None:
    if raw is None:
        return None
    cleaned = currency.strip_symbols(raw)
    if not cleaned:
        return None
    try:
        return abs(round(float(cleaned), 2))
    except ValueError:
        return None


def _to_date(raw: str) -> date | None:
    if not raw:
        return None
    text = str(raw).strip()[:19]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _last4(raw: str) -> str:
    digits = "".join(c for c in str(raw or "") if c.isdigit())
    return digits[-4:] if len(digits) >= 4 else ""


def parse_statement(csv_text: str) -> tuple[list[dict], list[str]]:
    """Turn an acquirer CSV into normalised rows, plus any parse warnings."""
    warnings: list[str] = []
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return [], ["The file has no header row"]

    mapping = {name: _normalise_header(name) for name in reader.fieldnames}
    found = set(mapping.values())
    if "amount" not in found:
        warnings.append("No amount column found — every line will be unmatched")
    if not ({"auth_code", "reference"} & found):
        warnings.append("No auth code or reference column — matching falls back to amount only")

    rows: list[dict] = []
    for line_no, raw in enumerate(reader, start=2):
        row = {mapping[k]: v for k, v in raw.items() if k in mapping}
        amount = _to_amount(row.get("amount", ""))
        if amount is None:
            warnings.append(f"Line {line_no}: unreadable amount {row.get('amount', '')!r}")
            continue
        rows.append({
            "line": line_no,
            "auth_code": (row.get("auth_code") or "").strip(),
            "reference": (row.get("reference") or "").strip(),
            "amount": amount,
            "txn_date": _to_date(row.get("date", "")),
            "last4": _last4(row.get("last4", "")),
            "terminal": (row.get("terminal") or "").strip(),
            "batch": (row.get("batch") or "").strip(),
        })
    return rows, warnings


def reconcile(db: Session, csv_text: str,
              date_from: date | None = None, date_to: date | None = None) -> dict:
    statement, warnings = parse_statement(csv_text)

    query = db.query(Sale).filter(Sale.payment_method == "card", Sale.status == "paid")
    if date_from:
        query = query.filter(Sale.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(Sale.created_at <= datetime.combine(date_to, datetime.max.time()))
    sales = query.order_by(Sale.created_at).all()

    unmatched_sales = {s.id: s for s in sales}
    by_auth = {s.card_auth_code.strip().upper(): s for s in sales if s.card_auth_code}
    by_ref = {s.card_reference.strip().upper(): s for s in sales if s.card_reference}

    matched: list[dict] = []
    mismatched: list[dict] = []
    missing_in_system: list[dict] = []

    for row in statement:
        sale = None
        how = ""
        auth = row["auth_code"].upper()
        ref = row["reference"].upper()

        if auth and auth in by_auth and by_auth[auth].id in unmatched_sales:
            sale, how = by_auth[auth], "auth code"
        elif ref and ref in by_ref and by_ref[ref].id in unmatched_sales:
            sale, how = by_ref[ref], "reference"
        else:
            # last resort: same amount, same day, nothing else claimed it
            for candidate in unmatched_sales.values():
                same_day = row["txn_date"] is None or candidate.created_at.date() == row["txn_date"]
                if same_day and abs(candidate.total - row["amount"]) <= TOLERANCE:
                    sale, how = candidate, "weak"
                    break

        if not sale:
            missing_in_system.append(row)
            continue

        unmatched_sales.pop(sale.id, None)
        entry = {
            "sale_id": sale.id,
            "sale_number": sale.sale_number,
            "sale_total": round(sale.total, 2),
            "statement_amount": row["amount"],
            "difference": round(sale.total - row["amount"], 2),
            "matched_on": how,
            "auth_code": row["auth_code"] or sale.card_auth_code,
            "reference": row["reference"] or sale.card_reference,
            "statement_line": row["line"],
            "created_at": sale.created_at,
        }
        if abs(entry["difference"]) > TOLERANCE:
            mismatched.append(entry)
        else:
            matched.append(entry)

    missing_in_statement = [
        {
            "sale_id": s.id, "sale_number": s.sale_number, "sale_total": round(s.total, 2),
            "auth_code": s.card_auth_code, "reference": s.card_reference,
            "terminal_id": s.terminal_id, "created_at": s.created_at,
        }
        for s in unmatched_sales.values()
    ]

    statement_total = round(sum(r["amount"] for r in statement), 2)
    system_total = round(sum(s.total for s in sales), 2)

    return {
        "statement_lines": len(statement),
        "card_sales": len(sales),
        "statement_total": statement_total,
        "system_total": system_total,
        "variance": round(system_total - statement_total, 2),
        "matched": matched,
        "mismatched": mismatched,
        "missing_in_system": missing_in_system,
        "missing_in_statement": missing_in_statement,
        "weak_matches": len([m for m in matched if m["matched_on"] == "weak"]),
        "warnings": warnings,
    }
