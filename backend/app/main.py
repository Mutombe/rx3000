import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import schedule_policy
from .audit import AuditMiddleware
from .config import settings
from .database import Base, SessionLocal, engine
from .migrate import run_migrations
from .routers import (
    admin_router, ai_router, auth_router, claiming_router, claims_admin_router,
    compounding_router,
    crm_router, currency_router, deferred_router,
    dispensing_extras_router, gateway_router,
    dispensing_router,
    fiscal_router,
    helpdesk_router, leads_router, ledger_router, marketing_router,
    messages_router,
    patients_router,
    periods_router, pos_router,
    prescriptions_router, register_router, reminders_router, reports_router,
    portal_router,
    profile_router,
    shifts_router, stock_router, system_router, to_follows_router,
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
    db = SessionLocal()
    try:
        seed(db)
        seed_crm_if_empty(db)
        seed_claiming_if_empty(db)
        seed_formulary_if_empty(db)
        seed_gateway_if_empty(db)
        from .services.ledger import ensure_chart
        ensure_chart(db)
        from .helpers import ensure_opening_batches
        if ensure_opening_batches(db):
            db.commit()
    finally:
        db.close()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="RX3000 Pharmacy Management System", version="1.0.0", lifespan=lifespan)

app.add_middleware(AuditMiddleware)

app.add_middleware(
    CORSMiddleware,
    # Development origins, plus whatever the deployment says its site is. A
    # hosted API and a hosted static site are two different origins, so without
    # the deployed hostname here every request from the browser is blocked by
    # CORS and the application looks broken with no error in the server log.
    allow_origins=[
        "http://localhost:5180", "http://127.0.0.1:5180",
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
):
    app.include_router(router_module.router)

app.include_router(portal_router.admin)  # staff-side link issuing
app.include_router(leads_router.public)  # unauthenticated web-to-lead / web-to-case


@app.get("/api/health")
def health():
    return {"status": "ok", "pharmacy": settings.PHARMACY_NAME}


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
