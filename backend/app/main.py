import logging
import time
from datetime import datetime
from pathlib import Path
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from .middleware_tenancy import TenancyMiddleware
from fastapi.responses import JSONResponse

from . import schedule_policy
from .audit import AuditMiddleware
from .config import settings
from sqlalchemy.orm import Session

from .auth import get_current_user
from .database import Base, SessionLocal, engine, get_db
from .models import User
from .limits import RequestSizeLimit
from .migrate import run_migrations
from .routers import (
    admin_router, ai_router, auth_router, claiming_router, claims_admin_router,
    compounding_router,
    crm_router, currency_router, deferred_router,
    dispensing_extras_router, gateway_router,
    dispensing_router,
    fiscal_router,
    helpdesk_router, leads_router, ledger_router, marketing_router, payables_router,
    clinical_terms_router,
    scorecard_router,
    detail_router,
    messages_router,
    patients_router,
    periods_router, pos_router,
    prescriptions_router, register_router, reminders_router, reports_router,
    branches_router,
    portal_router,
    profile_router,
    layby_router,
    settings_router,
    stocktake_router,
    scan_router,
    shifts_router, stock_router, system_router, to_follows_router,
    samples_router,
)
from .seed import (
    seed, seed_claiming_if_empty, seed_crm_if_empty, seed_formulary_if_empty,
    seed_gateway_if_empty,
)
from .services import scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    # Before anything serves a request. The scoping narrows a query with no
    # pharmacy in force to nothing, so a deployment that adds the column and
    # stops there comes up with every screen empty and every patient apparently
    # gone — which is a worse morning than a failed migration.
    from .tenancy_backfill import run as _backfill_tenants
    from . import tenancy as _tenancy
    stamped, founding_pharmacy = _backfill_tenants(engine)
    if stamped:
        log.info("Tenancy backfill stamped %s row(s)", stamped)

    # The rest of startup runs *as* the founding pharmacy.
    #
    # Boot-time work — the default branch, the chart of accounts, the
    # demonstration data — writes rows like any request does, and a row written
    # with no pharmacy in force belongs to nobody and is visible to nobody. The
    # first symptom of getting this wrong is not an error: it is
    # `default_branch` failing to see the branch that already exists, deciding
    # there is none, and colliding with its unique code.
    _tenant_token = _tenancy.set_current_pharmacy(founding_pharmacy)
    # Every pre-branch row gets a home. A batch belonging to no branch is stock
    # that has vanished from the system while sitting on a shelf.
    from .database import SessionLocal
    from .services import branches as _branches
    with SessionLocal() as _db:
        moved = _branches.ensure_backfilled(_db)
        if moved:
            log.info("Backfilled %s row(s) to the default branch", moved)
    db = SessionLocal()
    try:
        seed(db)
        seed_crm_if_empty(db)
        seed_claiming_if_empty(db)
        seed_formulary_if_empty(db)
        seed_gateway_if_empty(db)
        # The vocabulary behind the allergy and condition fields. Added on
        # every boot rather than only a fresh one, so an existing pharmacy
        # picks up terms shipped in a later release.
        from .routers.clinical_terms_router import seed_if_empty as _terms
        _terms(db)
        from .services.ledger import ensure_chart
        ensure_chart(db)
        from .services import sig as _sig
        _sig.seed_if_empty(db)
        from .helpers import ensure_opening_batches
        if ensure_opening_batches(db):
            db.commit()

        # A deployment with nothing in it gets the demonstration pharmacy.
        #
        # Until now this only ever ran from a laptop, against the local SQLite
        # file, while production runs Postgres — so every screen was empty there
        # and the reason was invisible from either side. It refuses to touch a
        # database that already has trade in it.
        if settings.SEED_DEMO_DATA:
            try:
                from .realseed import run_if_thin
                made = run_if_thin(db)
                if made:
                    log.info("Seeded the demonstration pharmacy: %s",
                             ", ".join(f"{v} {k}" for k, v in made.items() if v))
            except Exception:  # noqa: BLE001 - seed data is never worth the server
                log.exception("Could not seed demonstration data; starting anyway")
                db.rollback()
    finally:
        db.close()
        _tenancy.reset_current_pharmacy(_tenant_token)
    scheduler.start()
    yield
    scheduler.stop()


# When this process began, as an epoch and as a readable time.
#
# Two values on purpose. `datetime.utcnow().timestamp()` reads a naive UTC time as
# local, which here shifted the comparison by two hours and reported a
# just-started server as stale — the check accusing itself of the fault it exists
# to find.
_STARTED_EPOCH = time.time()
_STARTED = datetime.utcnow()

app = FastAPI(title="RX5000 Pharmacy Management System", version="1.0.0", lifespan=lifespan)

# Bounds every size parameter before a handler sees it. Above the audit log so
# what is recorded is what was actually served.
# Outermost of the application middlewares, so the pharmacy is in force before
# anything else — including the audit log — reads a row.
app.add_middleware(TenancyMiddleware)
app.add_middleware(RequestSizeLimit)

app.add_middleware(AuditMiddleware)

app.add_middleware(
    CORSMiddleware,
    # Development origins, plus whatever the deployment says its site is. A
    # hosted API and a hosted static site are two different origins, so without
    # the deployed hostname here every request from the browser is blocked by
    # CORS and the application looks broken with no error in the server log.
    allow_origins=[
        "http://localhost:5180", "http://127.0.0.1:5180",
        # The desktop shell. Its webview is a real browser with a real origin,
        # so the API has to allow it like any other: Tauri serves the bundled
        # front end from tauri://localhost on macOS and Linux and from
        # http://tauri.localhost on Windows. Without these the till renders,
        # the user types a password, and fetch fails before a request ever
        # leaves the machine — reported only as "Failed to fetch", with nothing
        # in the server log because the server was never reached.
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        *[o for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()],
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router_module in (
    auth_router, patients_router, prescriptions_router, dispensing_router, pos_router,
    stock_router, register_router, reminders_router, reports_router,
    shifts_router, admin_router, crm_router, leads_router, marketing_router,
    helpdesk_router, ai_router, currency_router, fiscal_router, claiming_router,
    compounding_router, gateway_router, claims_admin_router, periods_router,
    to_follows_router, deferred_router, messages_router, ledger_router,
    dispensing_extras_router, system_router, profile_router, portal_router,
    branches_router, scan_router, layby_router, stocktake_router,
    settings_router, payables_router, detail_router, clinical_terms_router,
    scorecard_router,
):
    app.include_router(router_module.router)
app.include_router(samples_router.router)

app.include_router(portal_router.admin)  # staff-side link issuing
app.include_router(leads_router.public)  # unauthenticated web-to-lead / web-to-case


log = logging.getLogger("rx5000")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Return a real response for an unhandled error, not a bare 500.

    Starlette's default error handler sits *outside* the CORS middleware, so an
    unhandled exception reaches the browser with no Access-Control-Allow-Origin
    header. Chrome then reports it as a CORS failure — and you go looking for a
    configuration problem that does not exist while the actual traceback sits in
    the server log. Handling it here means the response passes back through the
    middleware stack, keeps its CORS headers, and says what it is.

    The message is deliberately generic: the log has the detail, and a stack
    trace on a public endpoint tells an attacker about your dependencies.
    """
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong at our end. The pharmacy's "
                           "support log has the detail."},
    )


def _code_stamp() -> dict:
    """When the code this process is running was last written.

    A server left running while the code moves on answers every request happily
    with yesterday's behaviour, and the symptom is a 404 on an endpoint that
    plainly exists. That has cost five separate diagnoses here, and once left
    production serving an API three days older than the front end talking to it.

    The newest mtime across the app is a good enough stamp and needs no build
    tooling: it is exactly the question being asked — is this process older than
    the code on disk?
    """
    here = Path(__file__).resolve().parent
    newest = 0.0
    for path in here.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return {
        "code_written_at": datetime.utcfromtimestamp(newest).isoformat() + "Z" if newest else None,
        "process_started_at": _STARTED.isoformat() + "Z",
        # The comparison a caller actually wants, made here rather than left to
        # every client to get right.
        # Both epochs, so no timezone assumption enters the comparison. A second
        # of slack: writing a file during startup is not staleness.
        "running_stale_code": bool(newest and newest > _STARTED_EPOCH + 1),
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "pharmacy": settings.PHARMACY_NAME, **_code_stamp()}


@app.get("/api/nav/counts")
def nav_counts_endpoint(db: Session = Depends(get_db),
                        _: User = Depends(get_current_user)):
    """What needs doing, per navigation entry.

    One call rather than fourteen: the sidebar asks once and every badge is
    consistent with the others, which a badge-per-request cannot promise.
    Counted in SQL — none of these load rows to measure their length.
    """
    from .services import nav_counts

    return nav_counts.for_nav(db)


@app.get("/api/jurisdiction")
def jurisdiction():
    """The regulatory pack this installation runs under.

    The front end reads this for currency, locale and statute wording instead of
    hard-coding a country, and surfaces `caveat` when the pack is unverified.
    """
    j = settings.jurisdiction
    return {
        "code": j.code, "name": j.name, "regulator": j.regulator,
        "privacy_act": j.privacy_act, "product_code_label": j.product_code_label,
        "id_number_label": j.id_number_label, "locale": j.locale,
        "currencies": [{"code": c.code, "symbol": c.symbol, "decimals": c.decimals}
                       for c in j.currencies],
        "base_currency": {"code": j.base_currency.code, "symbol": j.base_currency.symbol,
                          "decimals": j.base_currency.decimals},
        "vat_rate": settings.VAT_RATE,
        "tax_year_start": f"{j.tax_year_start_day:02d}-{j.tax_year_start_month:02d}",
        "medical_schemes": j.medical_schemes,
        # Routes are stable across packs; the schedules behind them are not.
        # Publishing the mapping is what lets a caller label a screen "Schedule
        # 6-7" in Zimbabwe and "Schedule 5-6" in South Africa without knowing
        # which country it is in.
        "schedule_routes": {
            route: schedule_policy.schedules_for_route(route)
            for route in ("otc", "prescription", "controlled", "prohibited")
        },
        "register_schedules": sorted(
            s for s, p in j.schedules.items() if p.register_entry
        ),
        # The label for each class. Zimbabwe classifies by MCAZ letter category,
        # not by number, so a caller that renders the ordinal would show a South
        # African schedule number that does not exist in Zimbabwean law.
        "schedule_codes": {s: p.code for s, p in sorted(j.schedules.items())},
        "classification": ("MCAZ distribution category" if j.code == "ZW"
                           else "Schedule"),
        "fiscalisation": j.fiscalisation,
        "verified": j.verified,
        "caveat": j.caveat,
        "pharmacy_name": settings.PHARMACY_NAME,
        "pharmacy_reg_no": settings.PHARMACY_REG_NO,
    }
