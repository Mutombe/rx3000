"""Clearinghouse gateway endpoints.

The contract is what the caller sees: one unified payload, one error vocabulary,
and clean HTTP statuses regardless of which switch answered.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import create_token, get_current_user, verify_password
from ..config import settings
from ..database import get_db
from ..services import paging
from ..models import Funder, GatewayTransaction, Tariff, User
from .. import integrations, parity
from ..services import gateway

router = APIRouter(prefix="", tags=["gateway"])


def _fail(exc: gateway.GatewayError) -> HTTPException:
    """One shape for every gateway rejection, whatever caused it."""
    detail = {"error_code": exc.code, "message": exc.detail}
    if exc.line_number is not None:
        detail["line_number"] = exc.line_number
    return HTTPException(status_code=exc.http_status, detail=detail)


@router.post("/auth/token", response_model=schemas.TokenGrant)
def issue_token(body: schemas.ClientCredentials, db: Session = Depends(get_db)):
    """OAuth2 client credentials — the client id is a user, the secret its password."""
    if body.grant_type != "client_credentials":
        raise HTTPException(status_code=400, detail={
            "error_code": "UNSUPPORTED_GRANT",
            "message": "Only client_credentials is supported.",
        })
    user = db.query(User).filter(User.username == body.client_id, User.active).first()
    if not user or not verify_password(body.client_secret, user.password_hash):
        raise HTTPException(status_code=401, detail={
            "error_code": "INVALID_CLIENT",
            "message": "Client credentials were not accepted.",
        })
    return {
        "access_token": create_token(user),
        "token_type": "Bearer",
        "expires_in": settings.TOKEN_TTL_HOURS * 3600,
    }


@router.post("/eligibility/verify", response_model=schemas.EligibilityResponse,
             dependencies=[Depends(get_current_user)])
def verify_eligibility(body: schemas.EligibilityRequest, db: Session = Depends(get_db)):
    """Check benefits before dispensing — a rejection here costs nothing."""
    started = time.monotonic()
    txn = gateway.new_transaction_id()
    try:
        funder = gateway.resolve_funder(db, body.funder_id)
        gateway.validate_biometric(body.biometric, funder)
        adapter = gateway.adapter_for(funder, body.switch_id)
        result = adapter.eligibility(body.model_dump(), funder)
    except gateway.GatewayError as exc:
        gateway.record(db, transaction_id=txn, kind="eligibility", funder_id=body.funder_id,
                       switch_id=body.switch_id or "", status="REJECTED",
                       http_status=exc.http_status, error_code=exc.code,
                       request=body.model_dump(), response={"error": exc.detail},
                       started=started)
        raise _fail(exc) from exc

    payload = {"transaction_id": txn, **result}
    gateway.record(db, transaction_id=txn, kind="eligibility", funder_id=funder.funder_id,
                   switch_id=adapter.switch_id, status=result["status"], http_status=200,
                   request=body.model_dump(), response=payload, started=started)
    return payload


@router.post("/claims/submit", response_model=schemas.ClaimResponse,
             dependencies=[Depends(get_current_user)])
def submit_claim(body: schemas.ClaimRequest, db: Session = Depends(get_db)):
    """Validate, route, adjudicate — and keep the evidence either way."""
    started = time.monotonic()
    txn = gateway.new_transaction_id()
    header = body.transaction_header
    payload = body.model_dump()

    try:
        funder = gateway.resolve_funder(db, header.funder_id)
        gateway.validate_biometric(body.biometric, funder)

        currency = body.totals.currency.upper()
        if funder.currency_code and currency != funder.currency_code:
            raise gateway.GatewayError(
                "CURRENCY_MISMATCH",
                f"{funder.name} settles in {funder.currency_code}; the claim is in {currency}.",
            )

        # Everything below is rejected here rather than by the switch.
        gateway.validate_icd10(db, body.clinical_data.primary_icd10, required=True)
        if body.clinical_data.secondary_icd10:
            gateway.validate_icd10(db, body.clinical_data.secondary_icd10, required=False)

        if not body.claim_lines:
            raise gateway.GatewayError("VALIDATION_FAILED", "A claim needs at least one line.")

        year = gateway.current_financial_year()
        for line in body.claim_lines:
            gateway.validate_tariff(db, line, year, currency)

        declared = round(sum(line.total_price for line in body.claim_lines), 2)
        if abs(declared - body.totals.gross_amount) > 0.01:
            raise gateway.GatewayError(
                "VALIDATION_FAILED",
                f"Lines total {declared:.2f} but the header declares "
                f"{body.totals.gross_amount:.2f}.",
            )

        adapter = gateway.adapter_for(funder, header.switch_destination)
        result = adapter.claim(payload, funder)

    except gateway.GatewayError as exc:
        gateway.record(db, transaction_id=txn, kind="claim", funder_id=header.funder_id,
                       switch_id=header.switch_destination or "", status="REJECTED",
                       http_status=exc.http_status, error_code=exc.code,
                       claimed=body.totals.gross_amount,
                       request=payload, response={"error": exc.detail}, started=started)
        raise _fail(exc) from exc

    shortfall = round(body.totals.gross_amount - result.approved, 2)
    out = {
        "gateway_status": "PROCESSED",
        "transaction_id": txn,
        "switch_reference": result.reference,
        "funder_reference": result.funder_reference,
        "adjudication_summary": {
            "status": result.status,
            "amount_claimed": round(body.totals.gross_amount, 2),
            "amount_approved": result.approved,
            "shortfall_amount": shortfall,
            "rejection_reason": result.rejection_reason,
        },
        "adjudicated_lines": result.lines,
    }
    gateway.record(db, transaction_id=txn, kind="claim", funder_id=funder.funder_id,
                   switch_id=adapter.switch_id, status=result.status, http_status=200,
                   claimed=body.totals.gross_amount, approved=result.approved,
                   switch_ref=result.reference, funder_ref=result.funder_reference,
                   request=payload, response=out, started=started)
    return out


@router.get("/api/gateway/funders", response_model=list[schemas.FunderOut],
            dependencies=[Depends(get_current_user)])
def list_funders(db: Session = Depends(get_db)):
    return db.query(Funder).filter(Funder.active).order_by(Funder.name).all()


@router.get("/api/gateway/tariffs", response_model=list[schemas.TariffOut],
            dependencies=[Depends(get_current_user)])
def list_tariffs(q: str = "", year: int = 0, limit: int = 100,
                 db: Session = Depends(get_db)):
    query = db.query(Tariff).filter(
        Tariff.active,
        Tariff.financial_year == (year or gateway.current_financial_year()),
    )
    if q:
        query = query.filter(or_(Tariff.description.ilike(f"%{q}%"),
                                 Tariff.tariff_code.ilike(f"{q}%")))
    return query.order_by(Tariff.tariff_code).limit(limit).all()


def _txn_row(t):
    return {
        "transaction_id": t.transaction_id, "kind": t.kind, "funder_id": t.funder_id,
        "switch_id": t.switch_id, "status": t.status, "error_code": t.error_code,
        "http_status": t.http_status, "amount_claimed": t.amount_claimed,
        "amount_approved": t.amount_approved, "switch_reference": t.switch_reference,
        "funder_reference": t.funder_reference, "duration_ms": t.duration_ms,
        "created_at": t.created_at,
    }


def _txn_query(db, kind):
    query = db.query(GatewayTransaction)
    if kind:
        query = query.filter(GatewayTransaction.kind == kind)
    return query.order_by(desc(GatewayTransaction.created_at))


@router.get("/api/gateway/transactions", dependencies=[Depends(get_current_user)])
def list_transactions(kind: str = "", limit: int = 100, db: Session = Depends(get_db)):
    """The audit trail — what was sent, what came back, and how long it took."""
    return [_txn_row(t) for t in _txn_query(db, kind).limit(limit).all()]


@router.get("/api/gateway/transactions/paged", dependencies=[Depends(get_current_user)])
def list_transactions_paged(kind: str = "", page: int = 1,
                            per_page: int = paging.DEFAULT_PER_PAGE,
                            db: Session = Depends(get_db)):
    """The switch audit trail, paged. 3,276 behind a cap of 100.

    When a claim is queried weeks later, the request and response that settled
    it are the evidence — and they are not in the most recent hundred.
    """
    result = paging.page(_txn_query(db, kind), page=page, per_page=per_page)
    return result.envelope(_txn_row)


@router.get("/api/integrations", dependencies=[Depends(get_current_user)])
def list_integrations():
    """What is real and what is pretended, on this installation, right now.

    Published rather than kept in comments, because the answer decides whether a
    pharmacy can go live — and because "the demo worked" is not evidence that
    anything was filed with a funder or a revenue authority.
    """
    return {
        **integrations.production_readiness(),
        "integrations": [{
            "key": i.key, "name": i.name, "category": i.category, "state": i.state,
            "module": i.module, "blocked_on": list(i.blocked_on),
            "unblocks": i.unblocks, "notes": i.notes,
            "production_safe": i.production_safe,
        } for i in sorted(integrations.REGISTRY.values(),
                          key=lambda x: (x.category, x.name))],
    }


@router.get("/api/parity", dependencies=[Depends(get_current_user)])
def feature_parity(area: str = "", state: str = ""):
    """Where RX3000 stands against the system it has to displace.

    Published rather than kept in a document, because the honest answer changes
    every week and a stale document is worse than none.
    """
    features = [f for f in parity.REGISTRY.values()
                if (not area or f.area == area) and (not state or f.state == state)]
    return {
        **parity.summary(),
        "features": [{
            "key": f.key, "name": f.name, "area": f.area, "state": f.state,
            "incumbent": f.incumbent, "shortcut": f.shortcut,
            "why_it_matters": f.why_it_matters, "rx3000": f.rx3000,
        } for f in sorted(features, key=lambda x: (x.area, x.state != "missing", x.name))],
    }


@router.get("/api/gateway/errors", dependencies=[Depends(get_current_user)])
def error_vocabulary():
    """The full error contract, so a caller can code against it."""
    return [{"error_code": code, "http_status": status, "context": context}
            for code, (status, context) in sorted(gateway.ERRORS.items(),
                                                  key=lambda kv: kv[1][0])]
