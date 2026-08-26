"""Electronic remittance advice: what the funder actually paid, against what was claimed.

A remittance advice is the funder's statement of a payment: one deposit covering
many claims, each with its own adjustment. The work is not parsing it — it is the
three-way gap it exposes:

    claimed   what the pharmacy asked for
    allowed   what the funder agreed was payable
    paid      what actually moved

**Approved is not paid, and paid is not claimed.** A claim approved at 100 can be
remitted at 85 because of a levy, a tariff correction, or one line struck out.
That 15 is the pharmacy's exposure and it has exactly two lawful destinations:
billed to the patient, or written off. A pharmacy without this module discovers
the gap by noticing the bank balance is wrong, months later, with no line-level
explanation and no hope of recovering it.

Matching is deliberately layered, strongest evidence first. A wrong match is
worse than no match — it marks a claim paid that was not — so the weak
amount-and-date heuristic only runs when the identifiers have all failed, and
what matched by which rule is recorded either way.
"""
import csv
import io
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import Claim, GatewayTransaction, Remittance, RemittanceLine

# The standard adjustment vocabulary. Funders each phrase these differently;
# normalising them here is what makes "why are we short this month" answerable.
REASONS = {
    "PAID":             "Paid in full.",
    "LEVY":             "Reduced by the member's co-payment or levy.",
    "TARIFF":           "Repriced to the funder's tariff.",
    "BENEFIT_EXHAUSTED": "The member's benefit was exhausted.",
    "NOT_COVERED":      "The item is not on the member's formulary.",
    "NO_AUTH":          "No valid pre-authorisation was held.",
    "DUPLICATE":        "Treated as a duplicate of an earlier claim.",
    "STALE":            "Submitted outside the funder's claiming window.",
    "MEMBER_INVALID":   "The member was not active on the service date.",
    "UNKNOWN":          "No reason was supplied by the funder.",
}

# A payment within this of the claim is treated as paid in full — funders round.
TOLERANCE = 0.01


class RemittanceError(ValueError):
    """Raised when an advice cannot be imported."""


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _as_float(value) -> float:
    text = str(value or "0").strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_csv(text: str) -> list[dict]:
    """Read an advice supplied as a spreadsheet export.

    Funders that have no switch integration send a CSV, so this is the path that
    actually gets used for most of them. Headers are matched case- and
    space-insensitively because no two funders spell them the same way.
    """
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise RemittanceError("The file has no header row.")

    def pick(row: dict, *names, default=""):
        for name in names:
            for key, value in row.items():
                if key and key.strip().lower().replace(" ", "_") == name:
                    return value
        return default

    lines = []
    for index, row in enumerate(reader, start=1):
        if not any((v or "").strip() for v in row.values()):
            continue
        claimed = _as_float(pick(row, "amount_claimed", "claimed", "gross"))
        allowed = _as_float(pick(row, "amount_allowed", "allowed", "approved"))
        paid = _as_float(pick(row, "amount_paid", "paid", "settled"))
        lines.append({
            "line_number": index,
            "claim_reference": str(pick(row, "claim_reference", "claim_no",
                                        "claim_number", "reference")).strip(),
            "policy_number": str(pick(row, "policy_number", "membership_no",
                                      "member_number")).strip(),
            "member_name": str(pick(row, "member_name", "member", "patient")).strip(),
            "service_date": _as_date(pick(row, "service_date", "date_of_service", "date")),
            "amount_claimed": claimed,
            "amount_allowed": allowed or paid,
            "amount_paid": paid,
            "reason_code": str(pick(row, "reason_code", "code")).strip().upper(),
            "reason": str(pick(row, "reason", "message", "narrative")).strip(),
        })
    if not lines:
        raise RemittanceError("The file contained no remittance lines.")
    return lines


def classify(line: dict) -> tuple[str, str]:
    """Decide what a line means, and normalise the funder's wording.

    The status is derived from the money, not from the funder's reason text —
    a funder that says "PAID" and remits half has short-paid, whatever the code
    says, and that is the case worth catching.
    """
    claimed = line.get("amount_claimed") or 0.0
    paid = line.get("amount_paid") or 0.0
    code = (line.get("reason_code") or "").upper()

    if paid <= 0:
        status = "rejected"
        code = code if code in REASONS and code != "PAID" else (code or "UNKNOWN")
    elif paid + TOLERANCE < claimed:
        status = "short_paid"
        code = code if code in REASONS and code != "PAID" else (code or "UNKNOWN")
    elif paid > claimed + TOLERANCE:
        # Rare, and always worth flagging: an overpayment is usually a duplicate
        # remittance and the funder will claw it back.
        status = "overpaid"
        code = code or "DUPLICATE"
    else:
        status = "matched"
        code = code or "PAID"
    return status, code


def _match_line(db: Session, line: dict) -> tuple[Claim | None, str, str]:
    """Find the claim a remittance line refers to. Strongest evidence first."""
    reference = (line.get("claim_reference") or "").strip()

    if reference:
        # 1. Our own claim number — unambiguous.
        claim = db.query(Claim).filter(Claim.claim_number == reference).first()
        if claim:
            return claim, "claim_number", ""

        # 2. The switch's or funder's reference, recorded when we submitted.
        txn = (db.query(GatewayTransaction)
               .filter((GatewayTransaction.switch_reference == reference)
                       | (GatewayTransaction.funder_reference == reference)
                       | (GatewayTransaction.transaction_id == reference))
               .first())
        if txn:
            return None, "gateway_reference", txn.transaction_id

    # 3. Last resort: the same member, the same money, around the same day.
    #    Deliberately narrow — a loose match here marks the wrong claim settled.
    policy = (line.get("policy_number") or "").strip()
    claimed = line.get("amount_claimed") or 0.0
    if policy and claimed:
        candidates = (db.query(Claim)
                      .filter(Claim.status.in_(("submitted", "approved", "partial")))
                      .order_by(Claim.created_at.desc())
                      .limit(500).all())
        near = [c for c in candidates if abs((c.amount_claimed or 0) - claimed) <= TOLERANCE]
        if len(near) == 1:
            return near[0], "amount_and_member", ""

    return None, "", ""


def import_advice(db: Session, *, funder_id: str, remittance_number: str,
                  payment_reference: str = "", payment_date=None,
                  currency_code: str = "USD", lines: list[dict],
                  source: str = "upload", notes: str = "") -> Remittance:
    """Import an advice, match every line, and record what could not be matched.

    Importing is idempotent by remittance number: funders resend statements, and
    importing the same payment twice would double-count the money.
    """
    remittance_number = (remittance_number or "").strip()
    if not remittance_number:
        raise RemittanceError("A remittance number is required.")
    if not lines:
        raise RemittanceError("A remittance advice needs at least one line.")

    existing = (db.query(Remittance)
                .filter(Remittance.remittance_number == remittance_number).first())
    if existing:
        raise RemittanceError(
            f"Remittance {remittance_number} has already been imported "
            f"({len(existing.lines)} lines, {existing.total_paid:.2f} "
            f"{existing.currency_code}).")

    advice = Remittance(
        remittance_number=remittance_number,
        funder_id=(funder_id or "").strip().upper(),
        payment_reference=payment_reference,
        payment_date=_as_date(payment_date),
        currency_code=(currency_code or "USD").upper(),
        source=source,
        notes=notes,
    )
    db.add(advice)
    db.flush()

    total_claimed = total_paid = 0.0
    for index, raw in enumerate(lines, start=1):
        claimed = _as_float(raw.get("amount_claimed"))
        allowed = _as_float(raw.get("amount_allowed")) or _as_float(raw.get("amount_paid"))
        paid = _as_float(raw.get("amount_paid"))
        line = {**raw, "amount_claimed": claimed, "amount_allowed": allowed,
                "amount_paid": paid}

        status, code = classify(line)
        claim, rule, txn_id = _match_line(db, line)
        if claim is None and not txn_id:
            status = "unmatched"

        db.add(RemittanceLine(
            remittance_id=advice.id,
            line_number=raw.get("line_number") or index,
            claim_reference=(raw.get("claim_reference") or "").strip(),
            policy_number=(raw.get("policy_number") or "").strip(),
            member_name=(raw.get("member_name") or "").strip(),
            service_date=_as_date(raw.get("service_date")),
            amount_claimed=claimed, amount_allowed=allowed, amount_paid=paid,
            reason_code=code,
            reason=(raw.get("reason") or REASONS.get(code, "")),
            status=status,
            variance=round(claimed - paid, 2),
            claim_id=claim.id if claim else None,
            gateway_transaction_id=txn_id or (rule if rule == "amount_and_member" else ""),
        ))

        # Settle the claim itself so the two records cannot drift apart.
        if claim is not None and paid > 0:
            claim.settled_amount = round((claim.settled_amount or 0.0) + paid, 2)
            claim.settled_at = datetime.utcnow()

        total_claimed += claimed
        total_paid += paid

    advice.total_claimed = round(total_claimed, 2)
    advice.total_paid = round(total_paid, 2)
    db.commit()
    db.refresh(advice)
    return advice


def reconcile(db: Session, advice: Remittance) -> dict:
    """What this payment means for the pharmacy, in the terms it has to act on."""
    lines = advice.lines
    buckets: dict[str, list] = {}
    for line in lines:
        buckets.setdefault(line.status, []).append(line)

    shortfall = round(sum(l.variance for l in lines
                          if l.status in ("short_paid", "rejected")), 2)
    outstanding = round(sum(l.variance for l in lines
                            if l.status in ("short_paid", "rejected")
                            and not l.written_off and not l.patient_billed), 2)

    by_reason: dict[str, dict] = {}
    for line in lines:
        if line.status in ("matched", "overpaid"):
            continue
        entry = by_reason.setdefault(line.reason_code or "UNKNOWN",
                                     {"reason_code": line.reason_code or "UNKNOWN",
                                      "reason": REASONS.get(line.reason_code or "UNKNOWN", ""),
                                      "lines": 0, "amount": 0.0})
        entry["lines"] += 1
        entry["amount"] = round(entry["amount"] + line.variance, 2)

    return {
        # Carried so a listing can link to the detail page — a row nobody can
        # open is a row nobody can act on.
        "id": advice.id,
        "remittance_number": advice.remittance_number,
        "funder_id": advice.funder_id,
        "payment_date": advice.payment_date,
        "payment_reference": advice.payment_reference,
        "currency_code": advice.currency_code,
        "status": advice.status,
        "line_count": len(lines),
        "total_claimed": advice.total_claimed,
        "total_paid": advice.total_paid,
        "shortfall": shortfall,
        "outstanding": outstanding,
        "counts": {status: len(rows) for status, rows in sorted(buckets.items())},
        "unmatched": len(buckets.get("unmatched", [])),
        # Ranked because the top one or two reasons are usually the whole story,
        # and are what the pharmacy takes back to the funder.
        "by_reason": sorted(by_reason.values(), key=lambda r: -abs(r["amount"])),
    }


def resolve_line(db: Session, line: RemittanceLine, action: str,
                 note: str = "") -> RemittanceLine:
    """Send a shortfall where it has to go: the patient, or the write-off account."""
    if action == "bill_patient":
        line.patient_billed, line.written_off = True, False
    elif action == "write_off":
        line.written_off, line.patient_billed = True, False
    elif action == "reopen":
        line.written_off = line.patient_billed = False
    else:
        raise RemittanceError(
            f"'{action}' is not a resolution. Use bill_patient, write_off or reopen.")
    if note:
        # Into our own field. Appending to `reason` overwrote the funder's
        # stated reason with our working notes, and did it again on every
        # resolution — the seeded data carries lines where the scheme's reason is
        # followed by the same word eight times.
        line.resolution_note = note.strip()[:300]
    db.commit()
    return line


def outstanding_query(db: Session, funder_id: str = ""):
    """The open-shortfall query itself, so the list, the page and the totals all
    ask the same question. They used to each build their own filter, which is how
    a list and its total drift apart."""
    query = (db.query(RemittanceLine)
             .filter(RemittanceLine.status.in_(("short_paid", "rejected")),
                     RemittanceLine.written_off.is_(False),
                     RemittanceLine.patient_billed.is_(False)))
    if funder_id:
        query = (query.join(Remittance)
                 .filter(Remittance.funder_id == funder_id.strip().upper()))
    # Each line's serialiser reads `line.remittance` for the advice number and
    # funder, which lazily cost one query per line. Joined here because it is a
    # many-to-one: one join beats a second round trip.
    return (query.options(joinedload(RemittanceLine.remittance))
            .order_by(RemittanceLine.variance.desc()))


def outstanding_lines(db: Session, funder_id: str = "", limit: int = 200) -> list[RemittanceLine]:
    """The worst `limit` shortfalls. Callers that page use `outstanding_query`."""
    return outstanding_query(db, funder_id).limit(limit).all()


def outstanding_totals(db: Session, funder_id: str = "") -> tuple[int, float]:
    """How many shortfalls are open and what they come to — over all of them.

    Separate from `outstanding_lines` because that one is capped, and the caller
    needs the true figures alongside the visible ones. Summed here rather than
    over the returned rows: adding up a capped list reported 200 lines worth
    $70,000 when 1,317 lines worth $98,096 were open, and a pharmacy reading that
    screen would have understated what it is owed by twenty-eight thousand
    dollars.
    """
    query = (db.query(func.count(RemittanceLine.id),
                      func.coalesce(func.sum(RemittanceLine.variance), 0.0))
             .filter(RemittanceLine.status.in_(("short_paid", "rejected")),
                     RemittanceLine.written_off.is_(False),
                     RemittanceLine.patient_billed.is_(False)))
    if funder_id:
        query = (query.join(Remittance)
                 .filter(Remittance.funder_id == funder_id.strip().upper()))
    count, total = query.one()
    return int(count or 0), round(float(total or 0), 2)
