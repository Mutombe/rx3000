"""AHFoZ clearinghouse gateway.

One unified payload in; whichever wire format the destination switch speaks out.
The value is not the transport — it is everything that happens *before* it:

* **Reject early.** A tariff or ICD-10 error caught here costs nothing. The same
  error caught by a switch costs a round trip, a resubmission, and often a
  fortnight of the money not arriving.
* **Normalise what comes back.** Switches return wildly different error strings
  for the same condition. Callers get one vocabulary and clean HTTP statuses.
* **Keep the evidence.** Every call is recorded, because a funder query six
  months later is answered from the record, not from memory.
"""
import hashlib
import json
import random
import secrets
import string
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .. import icd10, integrations
from ..models import DiagnosisCode, Funder, GatewayTransaction, Tariff

SWITCH_TIMEOUT_SECONDS = 15

# Gateway error vocabulary -> HTTP status. One place, so a caller can rely on it.
ERRORS = {
    "INVALID_ICD10":      (400, "The diagnosis code does not exist in the standard lists."),
    "MEMBER_SUSPENDED":   (402, "The funder reports the member's premiums are in arrears."),
    "TARIFF_MISMATCH":    (422, "The price charged deviates from the negotiated AHFoZ band."),
    "TARIFF_UNKNOWN":     (422, "The tariff code is not in the active AHFoZ tariff book."),
    "SWITCH_TIMEOUT":     (504, "The switch did not reply within the timeout."),
    "SWITCH_UNAVAILABLE": (502, "The switch could not be reached."),
    "UNKNOWN_FUNDER":     (400, "No funder is registered under that identifier."),
    "CURRENCY_MISMATCH":  (422, "The claim currency does not match the funder's pool currency."),
    "VALIDATION_FAILED":  (400, "The payload failed validation."),
    "BIOMETRIC_REQUIRED": (428, "The funder requires the member's fingerprint before this transaction."),
    "BIOMETRIC_FAILED":   (401, "The fingerprint did not match the member's enrolled print."),
    "BIOMETRIC_QUALITY":  (422, "The fingerprint image is too poor to submit, scan it again."),
    "AUTH_DECLINED":      (402, "The funder declined the authorisation request."),
    "AUTH_REQUIRED":      (428, "This item needs a pre-authorisation before it can be claimed."),
    "AUTH_INVALID":       (422, "The authorisation held is expired, exhausted or not valid for this claim."),
    "NOT_SUPPORTED":      (501, "The destination switch does not offer this operation."),
}

# Kept as an alias so existing callers keep working; the structure and chapter
# rules themselves live in icd10.py.
ICD10_PATTERN = icd10.PATTERN


class GatewayError(Exception):
    """Carries a gateway error code that maps to a known HTTP status."""

    def __init__(self, code: str, detail: str = "", line_number: int | None = None):
        self.code = code
        status, default = ERRORS.get(code, (400, "Gateway error"))
        self.http_status = status
        self.detail = detail or default
        self.line_number = line_number
        super().__init__(self.detail)


@dataclass
class SwitchResult:
    reference: str
    funder_reference: str
    status: str                     # APPROVED | PARTIAL | REJECTED
    approved: float
    lines: list
    message: str = ""
    rejection_reason: str | None = None


# ---------------------------------------------------------------------------
# Validation engines — everything here runs before a switch is contacted
# ---------------------------------------------------------------------------

def validate_icd10(db: Session, code: str, *, required: bool = True) -> dict:
    """Reject what is definitely wrong; do not reject what is merely unfamiliar.

    The local diagnosis table holds a few dozen of the WHO release's 70,000-odd
    codes. Treating absence from it as invalidity would refuse most real
    prescriptions, so only two things are rejections here: a malformed code, and
    one that falls outside every ICD-10 chapter. Both are errors no clinician
    intended. A well-formed code in a real chapter that we happen not to hold is
    accepted and flagged as undescribed — the funder is the authority on whether
    it is claimable, not our seed data.

    An expired code is still refused: that is a fact we positively know.
    """
    code = icd10.normalise(code)
    if not code:
        if required:
            raise GatewayError("INVALID_ICD10", "A primary diagnosis code is required.")
        return {"code": "", "known": False}

    verdict = icd10.classify(code)
    if not verdict["valid_structure"] or verdict["chapter"] is None:
        raise GatewayError("INVALID_ICD10", verdict["reason"])

    found = db.query(DiagnosisCode).filter(DiagnosisCode.code == code).first()
    if found and not found.active:
        raise GatewayError("INVALID_ICD10",
                           f"ICD-10 code {code} is expired and no longer accepted.")
    return {
        "code": code,
        "known": found is not None,
        "description": found.description if found else "",
        "chapter": verdict["chapter"],
        "chapter_title": verdict["chapter_title"],
        "weak_primary": verdict.get("weak_primary", False),
    }


def validate_tariff(db: Session, line, financial_year: int, currency: str) -> Tariff:
    """Codes must exist in the active book, and prices must sit inside the band."""
    tariff = (
        db.query(Tariff)
        .filter(Tariff.tariff_code == line.tariff_code,
                Tariff.financial_year == financial_year,
                Tariff.active)
        .first()
    )
    if not tariff:
        raise GatewayError(
            "TARIFF_UNKNOWN",
            f"Tariff {line.tariff_code} is not in the {financial_year} AHFoZ tariff book.",
            line.line_number,
        )
    if tariff.currency_code and currency and tariff.currency_code != currency:
        raise GatewayError(
            "CURRENCY_MISMATCH",
            f"Tariff {line.tariff_code} is published in {tariff.currency_code}, "
            f"but the claim is in {currency}.",
            line.line_number,
        )

    low = tariff.min_price or tariff.unit_price
    high = tariff.max_price or tariff.unit_price
    if high and not (low - 0.005 <= line.unit_price <= high + 0.005):
        raise GatewayError(
            "TARIFF_MISMATCH",
            f"Tariff {line.tariff_code} is negotiated at "
            f"{low:.2f}–{high:.2f} {tariff.currency_code}; {line.unit_price:.2f} was charged.",
            line.line_number,
        )

    expected = round(line.unit_price * line.quantity, 2)
    if abs(expected - line.total_price) > 0.01:
        raise GatewayError(
            "TARIFF_MISMATCH",
            f"Line {line.line_number} totals {line.total_price:.2f} but "
            f"{line.quantity} × {line.unit_price:.2f} is {expected:.2f}.",
            line.line_number,
        )
    return tariff


# A fingerprint below this is a sensor problem, not an identity problem. Sending
# it anyway returns a failed match, which reads to the cashier as an accusation.
MIN_BIOMETRIC_QUALITY = 60


def validate_biometric(biometric, funder: Funder) -> None:
    """Enforce the funder's biometric rule before anything is sent.

    Funders that run biometric verification do not accept an unverified member,
    so a claim without a capture is refused here rather than after a round trip.
    """
    present = bool(biometric and biometric.template)
    if not present:
        if funder.biometric_required:
            raise GatewayError(
                "BIOMETRIC_REQUIRED",
                f"{funder.name} verifies members by fingerprint. Capture the "
                "member's print on the reader before submitting.",
            )
        return
    if biometric.quality is not None and biometric.quality < MIN_BIOMETRIC_QUALITY:
        raise GatewayError(
            "BIOMETRIC_QUALITY",
            f"The image scored {biometric.quality}%, below the {MIN_BIOMETRIC_QUALITY}% "
            "a switch will accept. Wipe the sensor and the finger, then scan again.",
        )


def redact(payload: dict) -> dict:
    """Strip biometric templates before anything is written down.

    A fingerprint template is biometric personal data under the Cyber and Data
    Protection Act. It has one legitimate life: captured at the till, sent to
    the switch, discarded. An audit table that quietly accumulated templates
    would turn a useful record into a liability, so the record keeps the fact
    of the verification and never the print itself.
    """
    if not isinstance(payload, dict) or "biometric" not in payload:
        return payload
    block = payload.get("biometric")
    if not isinstance(block, dict):
        return payload
    return {**payload, "biometric": {**{k: v for k, v in block.items() if k != "template"},
                                     "template": "[redacted]" if block.get("template") else ""}}


def resolve_funder(db: Session, funder_id: str) -> Funder:
    funder = (
        db.query(Funder)
        .filter(Funder.funder_id == (funder_id or "").strip().upper(), Funder.active)
        .first()
    )
    if not funder:
        raise GatewayError("UNKNOWN_FUNDER", f"Funder '{funder_id}' is not registered.")
    return funder


# ---------------------------------------------------------------------------
# Switch adapters
#
# The gateway contract above is settled. What each switch expects on the wire is
# not, and is not guessed at: Health 263 and Mediswitch each publish their own
# integration specification, and the transformation belongs in one method per
# adapter. Everything around them — validation, routing, error normalisation,
# audit — is finished and proven against the simulator.
# ---------------------------------------------------------------------------

class SwitchAdapter:
    switch_id = "BASE"

    def eligibility(self, payload: dict, funder: Funder) -> dict:
        raise NotImplementedError

    def claim(self, payload: dict, funder: Funder) -> SwitchResult:
        raise NotImplementedError

    def authorisation(self, payload: dict, funder: Funder) -> dict:
        """Ask the funder to commit before the medicine leaves the shelf.

        Returns the decision: status, the funder's own authorisation number, the
        quantity and amount granted, and the window it is valid for.
        """
        raise GatewayError("NOT_SUPPORTED",
                           f"{self.switch_id} does not offer pre-authorisation.")

    def remittance_advice(self, db: Session, funder: Funder, since=None) -> list:
        """Fetch payment statements the funder has published.

        Each entry is a whole advice - the payment, and the lines it covers - in
        the shape `era.import_advice` takes.
        """
        raise GatewayError("NOT_SUPPORTED",
                           f"{self.switch_id} does not publish remittance advice.")


class SimulatorSwitch(SwitchAdapter):
    """Adjudicates locally so the whole flow is exercisable without a switch.

    Deliberate triggers rather than random failure: a policy number ending 000
    is suspended, and a claim over 1000 is partially approved, so both unhappy
    paths can be reproduced on demand.
    """

    switch_id = "SIMULATOR"

    @staticmethod
    def _refuse_in_production() -> None:
        """Every approval this class returns is fictional. Say so, loudly, once live."""
        try:
            integrations.require_live("switch.simulator")
        except integrations.NotLiveError as exc:
            raise GatewayError("SWITCH_UNAVAILABLE", str(exc)) from exc

    @staticmethod
    def _match(payload: dict) -> dict | None:
        """Stand in for the funder's own enrolment check.

        `right_index` is treated as the enrolled finger for every member, so a
        successful match and a mismatch are both reproducible on demand rather
        than left to chance.
        """
        block = payload.get("biometric") or {}
        if not block.get("template"):
            return None
        finger = (block.get("finger") or "").lower()
        if finger and finger != "right_index":
            raise GatewayError(
                "BIOMETRIC_FAILED",
                f"The {finger.replace('_', ' ')} print does not match the finger "
                "the member enrolled with this funder.",
            )
        return {"verified": True, "method": "fingerprint", "finger": finger or "right_index"}

    def eligibility(self, payload: dict, funder: Funder) -> dict:
        self._refuse_in_production()
        policy = str(payload["member"]["policy_number"])
        if policy.endswith("000"):
            raise GatewayError("MEMBER_SUSPENDED",
                               "Member premiums are in arrears; benefits are suspended.")
        verification = self._match(payload)
        limit = 5000.00
        used = round(len(policy) * 137.45 % 2000, 2)
        return {
            "status": "ELIGIBLE",
            "funder_response_code": "00",
            "biometric_verification": verification,
            "benefit_details": {
                "global_limit": limit,
                "available_balance": round(limit - used, 2),
                "co_payment_required": policy.endswith("5"),
                "co_payment_percentage": 10.0 if policy.endswith("5") else 0.0,
            },
        }

    def claim(self, payload: dict, funder: Funder) -> SwitchResult:
        self._refuse_in_production()
        policy = str(payload["patient_details"]["policy_number"])
        if policy.endswith("000"):
            raise GatewayError("MEMBER_SUSPENDED",
                               "Member premiums are in arrears; the claim cannot be paid.")
        self._match(payload)
        gross = float(payload["totals"]["gross_amount"])
        lines = payload["claim_lines"]

        # Over the per-claim ceiling the funder pays a share, not the lot.
        partial = gross > 1000.0
        factor = 0.8 if partial else 1.0
        adjudicated = []
        approved_total = 0.0
        for line in lines:
            amount = round(float(line["total_price"]) * factor, 2)
            approved_total += amount
            adjudicated.append({
                "line_number": line["line_number"],
                "status": "PAID" if not partial else "PART_PAID",
                "approved_amount": amount,
                "msg": ("Fully covered under basic benefit" if not partial
                        else "Above per-claim ceiling, funder share applied"),
            })
        approved_total = round(approved_total, 2)
        return SwitchResult(
            reference="SIM-" + "".join(random.choices(string.digits, k=7)),
            funder_reference=f"{funder.funder_id.split('_')[0]}-CLM-"
                             + "".join(random.choices(string.ascii_uppercase + string.digits, k=6)),
            status="APPROVED" if not partial else "PARTIAL",
            approved=approved_total,
            lines=adjudicated,
            message="Adjudicated by simulator",
        )


    # ---- pre-authorisation ----
    #
    # Deliberate triggers rather than random outcomes, so a decline and a partial
    # grant can both be reproduced on demand:
    #
    #   requested amount over 2000   granted in part, not in full
    #   ICD-10 beginning with Z      declined as not a covered indication
    #
    def authorisation(self, payload: dict, funder: Funder) -> dict:
        self._refuse_in_production()
        amount = float(payload.get("requested_amount") or 0.0)
        quantity = float(payload.get("requested_quantity") or 0.0)
        icd10 = str(payload.get("icd10_code") or "").upper()
        reference = "SIM-AUTH-" + "".join(random.choices(string.digits, k=6))

        if icd10.startswith("Z"):
            return {
                "status": "declined",
                "authorisation_number": "",
                "approved_quantity": 0.0,
                "approved_amount": 0.0,
                "decision_reason": "The diagnosis given is not a covered indication "
                                   "for this benefit.",
                "switch_reference": reference,
            }

        partial = amount > 2000.0
        factor = 0.5 if partial else 1.0
        today = date.today()
        return {
            "status": "partial" if partial else "approved",
            "authorisation_number": "AUTH-" + "".join(
                random.choices(string.ascii_uppercase + string.digits, k=8)),
            "approved_quantity": round(quantity * factor, 3),
            "approved_amount": round(amount * factor, 2),
            "valid_from": today,
            "valid_to": today + timedelta(days=182),
            "decision_reason": ("Granted in part - the balance needs a motivation from "
                               "the prescriber." if partial else
                               "Approved under the member's chronic benefit."),
            "conditions": "Dispense in the member's name only. Quote this number on every claim.",
            "switch_reference": reference,
        }

    # ---- remittance advice ----
    def remittance_advice(self, db: Session, funder: Funder, since=None) -> list:
        """Build an advice from claims this funder actually adjudicated.

        Derived from the gateway's own audit trail rather than invented, so the
        matching and reconciliation downstream are exercised against references
        that really were submitted - not ones manufactured to match. The funder
        pays what it approved, less a 10% levy on every third line, which is what
        makes the short-payment path real rather than theoretical.
        """
        self._refuse_in_production()
        query = (db.query(GatewayTransaction)
                 .filter(GatewayTransaction.kind == "claim",
                         GatewayTransaction.funder_id == funder.funder_id,
                         GatewayTransaction.amount_approved > 0))
        if since:
            query = query.filter(GatewayTransaction.created_at >= since)
        transactions = query.order_by(GatewayTransaction.created_at.desc()).limit(50).all()
        if not transactions:
            return []

        lines, paid_total, claimed_total = [], 0.0, 0.0
        for index, txn in enumerate(transactions, start=1):
            claimed = round(txn.amount_claimed or 0.0, 2)
            allowed = round(txn.amount_approved or 0.0, 2)
            levied = index % 3 == 0
            paid = round(allowed * 0.9, 2) if levied else allowed
            lines.append({
                "line_number": index,
                "claim_reference": txn.switch_reference or txn.transaction_id,
                "policy_number": "",
                "member_name": "",
                "service_date": txn.created_at.date() if txn.created_at else None,
                "amount_claimed": claimed,
                "amount_allowed": allowed,
                "amount_paid": paid,
                "reason_code": "LEVY" if levied else ("TARIFF" if paid < claimed else "PAID"),
                "reason": "",
            })
            claimed_total += claimed
            paid_total += paid

        # The advice number must be derived from the claims it covers, not from
        # chance. A funder republishing the same payment sends the same number,
        # and that number is the only thing standing between a re-fetch and the
        # money being counted twice. A random number here would make the import
        # guard untestable, and untestable is how it stops working.
        digest = hashlib.sha256(
            "|".join(sorted(line["claim_reference"] for line in lines)).encode()
        ).hexdigest()[:8].upper()
        today = date.today()
        return [{
            "remittance_number": f"{funder.funder_id}-RA-{digest}",
            "funder_id": funder.funder_id,
            "payment_reference": "EFT" + "".join(random.choices(string.digits, k=8)),
            "payment_date": today,
            "currency_code": funder.currency_code or "USD",
            "lines": lines,
            "total_claimed": round(claimed_total, 2),
            "total_paid": round(paid_total, 2),
        }]


class Health263Switch(SwitchAdapter):
    """Health 263 — REST/JSON.

    NOT IMPLEMENTED. Their integration specification defines the endpoint URLs,
    the request envelope, the authentication scheme and the response codes.
    Those are the only unknowns; map them here and nothing else in the gateway
    changes.
    """

    switch_id = "HEALTH_263"

    def eligibility(self, payload: dict, funder: Funder) -> dict:
        raise GatewayError("SWITCH_UNAVAILABLE",
                           "The Health 263 adapter is not implemented, supply their "
                           "REST specification and this adapter is the only change.")

    def claim(self, payload: dict, funder: Funder) -> SwitchResult:
        raise GatewayError("SWITCH_UNAVAILABLE",
                           "The Health 263 adapter is not implemented.")

    def authorisation(self, payload: dict, funder: Funder) -> dict:
        # Health 263 does offer this - clause 1.1.4 of the HSP contract - so it
        # is unavailable rather than unsupported. The distinction matters: one is
        # waiting on a document, the other will never exist.
        raise GatewayError("SWITCH_UNAVAILABLE",
                           "Health 263 offers authorisations, but the adapter is not "
                           "implemented - supply their REST specification.")

    def remittance_advice(self, db: Session, funder: Funder, since=None) -> list:
        raise GatewayError("SWITCH_UNAVAILABLE",
                           "Health 263 publishes remittance advice, but the adapter is "
                           "not implemented - supply their REST specification. Advices "
                           "can be imported as CSV in the meantime.")


class MediswitchSwitch(SwitchAdapter):
    """Mediswitch — SOAP/XML.

    NOT IMPLEMENTED. Needs the WSDL, the SOAP envelope shape, and the fault-code
    vocabulary so faults can be mapped onto the gateway error codes above.
    """

    switch_id = "MEDISWITCH"

    def eligibility(self, payload: dict, funder: Funder) -> dict:
        raise GatewayError("SWITCH_UNAVAILABLE",
                           "The Mediswitch adapter is not implemented, supply the WSDL "
                           "and fault-code list.")

    def claim(self, payload: dict, funder: Funder) -> SwitchResult:
        raise GatewayError("SWITCH_UNAVAILABLE",
                           "The Mediswitch adapter is not implemented.")


class DirectFunderSwitch(SwitchAdapter):
    """A funder integrated directly rather than through a switch."""

    switch_id = "DIRECT"

    def eligibility(self, payload: dict, funder: Funder) -> dict:
        raise GatewayError(
            "SWITCH_UNAVAILABLE",
            f"A direct adapter for {funder.funder_id} is not implemented. This "
            "funder is routed to DIRECT, which means it settles without a switch "
            "— supply that funder's own API specification and add one adapter "
            "class, or route it to a switch instead.")

    def claim(self, payload: dict, funder: Funder) -> SwitchResult:
        raise GatewayError(
            "SWITCH_UNAVAILABLE",
            f"A direct adapter for {funder.funder_id} is not implemented. This "
            "funder is routed to DIRECT, which means it settles without a switch "
            "— supply that funder's own API specification and add one adapter "
            "class, or route it to a switch instead.")


ADAPTERS = {a.switch_id: a for a in (
    SimulatorSwitch(), Health263Switch(), MediswitchSwitch(), DirectFunderSwitch(),
)}


def adapter_for(funder: Funder, override: str = "") -> SwitchAdapter:
    """Routing engine: the payload names a switch, the funder decides by default."""
    switch_id = (override or funder.switch_id or "SIMULATOR").upper()
    adapter = ADAPTERS.get(switch_id)
    if not adapter:
        raise GatewayError("SWITCH_UNAVAILABLE", f"No adapter registered for switch '{switch_id}'.")
    return adapter


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def new_transaction_id() -> str:
    """A transaction reference that will not collide.

    The first version of this was `TXN-<year>-<5 digits>`: ninety thousand
    possible values a year, against a column declared unique. A pharmacy
    submitting a few hundred claims a week reaches a one-in-a-hundred failure
    rate within a month and a one-in-ten within a year — arriving as a random
    500 on a claim the pharmacist has already dispensed against, and getting
    steadily worse in a way that looks like the system degrading with age.

    It is also the reference a funder quotes six months later when they query a
    payment, so two transactions sharing one is worse than a failure: it makes
    the audit trail ambiguous exactly when it is being relied on.

    Dated for readability, then ten hex characters — about a trillion per day.
    """
    return f"TXN-{datetime.utcnow():%Y%m%d}-{secrets.token_hex(5).upper()}"


def record(db: Session, *, transaction_id: str, kind: str, funder_id: str, switch_id: str,
           status: str, http_status: int, request: dict, response: dict,
           started: float, error_code: str = "", claimed: float = 0.0,
           approved: float = 0.0, switch_ref: str = "", funder_ref: str = "") -> None:
    db.add(GatewayTransaction(
        transaction_id=transaction_id, kind=kind, funder_id=funder_id, switch_id=switch_id,
        status=status, error_code=error_code, http_status=http_status,
        amount_claimed=claimed, amount_approved=approved,
        switch_reference=switch_ref, funder_reference=funder_ref,
        request_json=json.dumps(redact(request), default=str)[:8000],
        response_json=json.dumps(response, default=str)[:8000],
        duration_ms=int((time.monotonic() - started) * 1000),
    ))
    db.commit()


def current_financial_year(today: date | None = None) -> int:
    return (today or date.today()).year
