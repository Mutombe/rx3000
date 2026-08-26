"""CRM: corporate accounts, contacts, sales pipeline and activities."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import helpers, schemas
from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import (
    Activity, AutomationRule, Campaign, Company, Contact, Deal, DealItem,
    EmailTemplate, Lead, Patient, Product, Quote, Ticket, User,
)
from ..services import automation

router = APIRouter(prefix="/api/crm", tags=["crm"], dependencies=[Depends(get_current_user)])

PIPELINE_STAGES = ["new", "qualified", "proposal", "negotiation", "won", "lost"]
STAGE_PROBABILITY = {"new": 10, "qualified": 30, "proposal": 55, "negotiation": 75, "won": 100, "lost": 0}


# ---------- companies ----------
@router.get("/companies", response_model=list[schemas.CompanyOut])
def list_companies(q: str = "", status: str = "", limit: int = 200, db: Session = Depends(get_db)):
    query = db.query(Company)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Company.name.ilike(like), Company.email.ilike(like), Company.phone.ilike(like)))
    if status:
        query = query.filter(Company.status == status)
    return query.order_by(Company.name).limit(limit).all()


@router.post("/companies", response_model=schemas.CompanyOut)
def create_company(body: schemas.CompanyBase, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    company = Company(**body.model_dump())
    if company.owner_id is None:
        company.owner_id = user.id
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("/companies/{company_id}", response_model=schemas.CompanyOut)
def get_company(company_id: int, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.put("/companies/{company_id}", response_model=schemas.CompanyOut)
def update_company(company_id: int, body: schemas.CompanyBase, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    for key, value in body.model_dump().items():
        setattr(company, key, value)
    db.commit()
    db.refresh(company)
    return company


# ---------- contacts ----------
@router.get("/contacts", response_model=list[schemas.ContactOut])
def list_contacts(
    q: str = "", stage: str = "", company_id: int | None = None,
    limit: int = 200, db: Session = Depends(get_db),
):
    query = db.query(Contact)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Contact.first_name.ilike(like), Contact.last_name.ilike(like),
            Contact.email.ilike(like), Contact.phone.ilike(like),
        ))
    if stage:
        query = query.filter(Contact.lifecycle_stage == stage)
    if company_id:
        query = query.filter(Contact.company_id == company_id)
    return query.order_by(Contact.last_name, Contact.first_name).limit(limit).all()


@router.post("/contacts", response_model=schemas.ContactOut)
def create_contact(body: schemas.ContactBase, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    contact = Contact(**body.model_dump())
    if contact.owner_id is None:
        contact.owner_id = user.id
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.get("/contacts/{contact_id}", response_model=schemas.ContactOut)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.put("/contacts/{contact_id}", response_model=schemas.ContactOut)
def update_contact(contact_id: int, body: schemas.ContactBase, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    for key, value in body.model_dump().items():
        setattr(contact, key, value)
    db.commit()
    db.refresh(contact)
    return contact


# ---------- deals / pipeline ----------
@router.get("/deals", response_model=list[schemas.DealOut])
def list_deals(stage: str = "", open_only: bool = False, limit: int = 300, db: Session = Depends(get_db)):
    query = db.query(Deal)
    if stage:
        query = query.filter(Deal.stage == stage)
    if open_only:
        query = query.filter(Deal.stage.notin_(["won", "lost"]))
    return query.order_by(Deal.created_at.desc()).limit(limit).all()


@router.post("/deals", response_model=schemas.DealOut)
def create_deal(body: schemas.DealBase, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = body.model_dump()
    deal = Deal(**data)
    if deal.owner_id is None:
        deal.owner_id = user.id
    deal.probability = STAGE_PROBABILITY.get(deal.stage, deal.probability)
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal


@router.put("/deals/{deal_id}", response_model=schemas.DealOut)
def update_deal(deal_id: int, body: schemas.DealBase, db: Session = Depends(get_db)):
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    for key, value in body.model_dump().items():
        setattr(deal, key, value)
    db.commit()
    db.refresh(deal)
    return deal


@router.post("/deals/{deal_id}/stage", response_model=schemas.DealOut)
def move_deal(deal_id: int, body: schemas.DealStageUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Move a deal along the pipeline, the kanban drag/drop target."""
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if body.stage not in PIPELINE_STAGES:
        raise HTTPException(status_code=400, detail=f"Stage must be one of: {', '.join(PIPELINE_STAGES)}")

    previous = deal.stage
    deal.stage = body.stage
    deal.probability = STAGE_PROBABILITY[body.stage]
    if body.stage in ("won", "lost"):
        deal.closed_at = datetime.utcnow()
        deal.lost_reason = body.lost_reason if body.stage == "lost" else ""
    else:
        deal.closed_at = None
        deal.lost_reason = ""

    db.add(Activity(
        activity_type="note", subject=f"Stage changed: {previous} → {body.stage}",
        body=body.lost_reason, owner_id=user.id, deal_id=deal.id,
        company_id=deal.company_id, contact_id=deal.contact_id, completed_at=datetime.utcnow(),
    ))
    automation.create_deal_tasks(db, deal, user.id)
    db.commit()
    db.refresh(deal)
    return deal


def _recalc_deal(deal: Deal) -> float:
    """Deal value follows its line items once any exist."""
    if deal.items:
        deal.value = round(sum(i.line_total for i in deal.items), 2)
    return deal.value


@router.get("/deals/{deal_id}", response_model=schemas.DealOut)
def get_deal(deal_id: int, db: Session = Depends(get_db)):
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


@router.post("/deals/{deal_id}/items", response_model=schemas.DealOut)
def add_deal_item(deal_id: int, body: schemas.DealItemIn, db: Session = Depends(get_db)):
    """Add a product line. The opportunity value is recalculated from its lines."""
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if body.quantity < 1:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")
    if not 0 <= body.discount_percent <= 100:
        raise HTTPException(status_code=400, detail="Discount must be between 0 and 100%")

    description, unit_price = body.description, body.unit_price
    if body.product_id:
        product = db.get(Product, body.product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        description = description or f"{product.name} {product.strength}".strip()
        unit_price = unit_price or product.unit_price
    if not description:
        raise HTTPException(status_code=400, detail="A line needs a product or a description")

    gross = unit_price * body.quantity
    line_total = round(gross * (1 - body.discount_percent / 100), 2)
    db.add(DealItem(
        deal_id=deal.id, product_id=body.product_id, description=description,
        quantity=body.quantity, unit_price=unit_price,
        discount_percent=body.discount_percent, line_total=line_total,
    ))
    db.flush()
    db.refresh(deal)
    _recalc_deal(deal)
    db.commit()
    db.refresh(deal)
    return deal


@router.delete("/deals/{deal_id}/items/{item_id}", response_model=schemas.DealOut)
def remove_deal_item(deal_id: int, item_id: int, db: Session = Depends(get_db)):
    item = db.get(DealItem, item_id)
    if not item or item.deal_id != deal_id:
        raise HTTPException(status_code=404, detail="Line item not found")
    db.delete(item)
    db.flush()
    deal = db.get(Deal, deal_id)
    db.refresh(deal)
    _recalc_deal(deal)
    db.commit()
    db.refresh(deal)
    return deal


# ---------- quotes ----------
@router.get("/deals/{deal_id}/quotes", response_model=list[schemas.QuoteOut])
def list_quotes(deal_id: int, db: Session = Depends(get_db)):
    return db.query(Quote).filter(Quote.deal_id == deal_id).order_by(Quote.version.desc()).all()


@router.post("/deals/{deal_id}/quotes", response_model=schemas.QuoteOut)
def create_quote(
    deal_id: int, body: schemas.QuoteCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Generate the next version of a quotation from the deal's line items."""
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal.items:
        raise HTTPException(status_code=400, detail="Add line items to the deal before quoting")

    last = db.query(func.max(Quote.version)).filter(Quote.deal_id == deal_id).scalar() or 0
    total = round(sum(i.line_total for i in deal.items), 2)
    subtotal = round(total / (1 + settings.VAT_RATE), 2)
    quote = Quote(
        quote_number=helpers.next_number(db, Quote, "QTE", "quote_number"),
        deal_id=deal.id, version=last + 1,
        valid_until=date.today() + timedelta(days=body.valid_days),
        subtotal=subtotal, vat_amount=round(total - subtotal, 2), total=total,
        terms=body.terms or f"Valid for {body.valid_days} days. Prices include VAT.",
        created_by_id=user.id,
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return quote


@router.post("/quotes/{quote_id}/status", response_model=schemas.QuoteOut)
def set_quote_status(quote_id: int, status: str, db: Session = Depends(get_db)):
    quote = db.get(Quote, quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    QUOTE_STATUSES = ("draft", "sent", "accepted", "declined", "expired")
    if status not in QUOTE_STATUSES:
        # The valid values are right here in the check; withholding them from the
        # message leaves the caller guessing at something we already know.
        raise HTTPException(
            status_code=400,
            detail=f"'{status}' is not a quote status. Use one of: "
                   f"{', '.join(QUOTE_STATUSES)}.")
    quote.status = status
    now = datetime.utcnow()
    if status == "sent":
        quote.sent_at = now
    if status in ("accepted", "declined"):
        quote.decided_at = now
        deal = db.get(Deal, quote.deal_id)
        if deal and status == "accepted" and deal.stage not in ("won", "lost"):
            deal.stage = "negotiation"
            deal.probability = STAGE_PROBABILITY["negotiation"]
    db.commit()
    db.refresh(quote)
    return quote


# ---------- activities ----------
@router.get("/activities", response_model=list[schemas.ActivityOut])
def list_activities(
    deal_id: int | None = None, company_id: int | None = None, contact_id: int | None = None,
    patient_id: int | None = None, mine: bool = False, open_tasks: bool = False,
    limit: int = 200, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    query = db.query(Activity)
    if deal_id:
        query = query.filter(Activity.deal_id == deal_id)
    if company_id:
        query = query.filter(Activity.company_id == company_id)
    if contact_id:
        query = query.filter(Activity.contact_id == contact_id)
    if patient_id:
        query = query.filter(Activity.patient_id == patient_id)
    if mine:
        query = query.filter(Activity.owner_id == user.id)
    if open_tasks:
        query = query.filter(Activity.completed_at.is_(None), Activity.due_at.isnot(None))
    return query.order_by(Activity.created_at.desc()).limit(limit).all()


@router.post("/activities", response_model=schemas.ActivityOut)
def create_activity(body: schemas.ActivityBase, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    activity = Activity(**body.model_dump(), owner_id=user.id)
    if activity.activity_type in ("note", "email") and activity.due_at is None:
        activity.completed_at = datetime.utcnow()
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


@router.post("/activities/{activity_id}/complete", response_model=schemas.ActivityOut)
def complete_activity(activity_id: int, db: Session = Depends(get_db)):
    activity = db.get(Activity, activity_id)
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    activity.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(activity)
    return activity


# ---------- record 360 ----------
@router.get("/timeline")
def timeline(
    company_id: int | None = None, contact_id: int | None = None,
    deal_id: int | None = None, patient_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Unified activity feed for a record, the 360 view."""
    query = db.query(Activity)
    filters = []
    if company_id:
        filters.append(Activity.company_id == company_id)
    if contact_id:
        filters.append(Activity.contact_id == contact_id)
    if deal_id:
        filters.append(Activity.deal_id == deal_id)
    if patient_id:
        filters.append(Activity.patient_id == patient_id)
    if not filters:
        raise HTTPException(status_code=400, detail="Specify a record to build a timeline for")
    activities = query.filter(or_(*filters)).order_by(Activity.created_at.desc()).limit(100).all()

    return [
        {
            "id": a.id, "type": a.activity_type, "subject": a.subject, "body": a.body,
            "owner": a.owner.full_name if a.owner else None,
            "due_at": a.due_at, "completed_at": a.completed_at, "created_at": a.created_at,
        }
        for a in activities
    ]


@router.get("/companies/{company_id}/overview")
def company_overview(company_id: int, db: Session = Depends(get_db)):
    """Everything about an account on one call, the Salesforce account page."""
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    deals = db.query(Deal).filter(Deal.company_id == company_id).order_by(Deal.created_at.desc()).all()
    tickets = db.query(Ticket).filter(Ticket.company_id == company_id).order_by(Ticket.created_at.desc()).all()
    open_deals = [d for d in deals if d.stage not in ("won", "lost")]
    won = [d for d in deals if d.stage == "won"]
    return {
        "company": {
            "id": company.id, "name": company.name, "account_type": company.account_type,
            "status": company.status, "phone": company.phone, "email": company.email,
            "address": company.address, "credit_terms_days": company.credit_terms_days,
            "notes": company.notes,
            "owner": company.owner.full_name if company.owner else None,
        },
        "contacts": [
            {"id": c.id, "name": f"{c.first_name} {c.last_name}", "job_title": c.job_title,
             "email": c.email, "phone": c.phone, "lifecycle_stage": c.lifecycle_stage}
            for c in company.contacts
        ],
        "deals": [
            {"id": d.id, "title": d.title, "value": d.value, "stage": d.stage,
             "probability": d.probability, "expected_close_date": d.expected_close_date}
            for d in deals
        ],
        "tickets": [
            {"id": t.id, "ticket_number": t.ticket_number, "subject": t.subject,
             "status": t.status, "priority": t.priority, "created_at": t.created_at}
            for t in tickets
        ],
        "totals": {
            "open_pipeline": round(sum(d.value for d in open_deals), 2),
            "won_value": round(sum(d.value for d in won), 2),
            "open_tickets": len([t for t in tickets if t.status in ("open", "pending")]),
            "contacts": len(company.contacts),
        },
    }


# ---------- email templates ----------
@router.get("/templates", response_model=list[schemas.EmailTemplateOut])
def list_templates(category: str = "", db: Session = Depends(get_db)):
    query = db.query(EmailTemplate)
    if category:
        query = query.filter(EmailTemplate.category == category)
    return query.order_by(EmailTemplate.name).all()


@router.post("/templates", response_model=schemas.EmailTemplateOut)
def create_template(body: schemas.EmailTemplateBase, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    template = EmailTemplate(**body.model_dump(), created_by_id=user.id)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    template = db.get(EmailTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    return {"ok": True}


# ---------- automation rules ----------
@router.get("/automation", response_model=list[schemas.AutomationRuleOut])
def list_rules(db: Session = Depends(get_db)):
    return db.query(AutomationRule).order_by(AutomationRule.rule_type, AutomationRule.sort_order).all()


@router.post("/automation", response_model=schemas.AutomationRuleOut)
def create_rule(body: schemas.AutomationRuleBase, db: Session = Depends(get_db)):
    if body.rule_type not in automation.RULE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Rule type must be one of: {', '.join(automation.RULE_TYPES)}",
        )
    rule = AutomationRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/automation/{rule_id}", response_model=schemas.AutomationRuleOut)
def update_rule(rule_id: int, body: schemas.AutomationRuleBase, db: Session = Depends(get_db)):
    rule = db.get(AutomationRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    for key, value in body.model_dump().items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/automation/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(AutomationRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"ok": True}


@router.post("/automation/run-escalations")
def run_escalations(db: Session = Depends(get_db)):
    return {"escalated": automation.escalate_overdue_tickets(db)}


# ---------- reports & forecasting ----------
@router.get("/reports/forecast")
def forecast(months: int = 6, db: Session = Depends(get_db)):
    """Expected revenue by expected-close month, raw and probability-weighted."""
    deals = db.query(Deal).filter(Deal.expected_close_date.isnot(None)).all()
    buckets: dict[str, dict] = {}
    today = date.today()
    for offset in range(months):
        month = (today.replace(day=1) + timedelta(days=32 * offset)).replace(day=1)
        buckets[month.strftime("%Y-%m")] = {
            "month": month.strftime("%Y-%m"), "open_value": 0.0,
            "weighted_value": 0.0, "won_value": 0.0, "deals": 0,
        }
    for deal in deals:
        key = deal.expected_close_date.strftime("%Y-%m")
        if key not in buckets:
            continue
        bucket = buckets[key]
        bucket["deals"] += 1
        if deal.stage == "won":
            bucket["won_value"] += deal.value
        elif deal.stage != "lost":
            bucket["open_value"] += deal.value
            bucket["weighted_value"] += deal.value * (deal.probability or 0) / 100
    return [
        {**b, "open_value": round(b["open_value"], 2),
         "weighted_value": round(b["weighted_value"], 2),
         "won_value": round(b["won_value"], 2)}
        for b in buckets.values()
    ]


@router.get("/reports/funnel")
def funnel(db: Session = Depends(get_db)):
    """Lead → qualified → converted → won conversion funnel."""
    total_leads = db.query(func.count(Lead.id)).scalar() or 0
    working = db.query(func.count(Lead.id)).filter(Lead.status.in_(["working", "nurturing", "converted"])).scalar() or 0
    converted = db.query(func.count(Lead.id)).filter(Lead.status == "converted").scalar() or 0
    disqualified = db.query(func.count(Lead.id)).filter(Lead.status == "disqualified").scalar() or 0
    deals_total = db.query(func.count(Deal.id)).scalar() or 0
    won = db.query(func.count(Deal.id)).filter(Deal.stage == "won").scalar() or 0

    def pct(n, d):
        return round(n / d * 100, 1) if d else 0.0

    return {
        "stages": [
            {"stage": "Leads captured", "count": total_leads, "conversion": 100.0},
            {"stage": "Worked", "count": working, "conversion": pct(working, total_leads)},
            {"stage": "Converted", "count": converted, "conversion": pct(converted, total_leads)},
            {"stage": "Opportunities", "count": deals_total, "conversion": pct(deals_total, total_leads)},
            {"stage": "Won", "count": won, "conversion": pct(won, total_leads)},
        ],
        "disqualified": disqualified,
        "lead_to_customer_rate": pct(won, total_leads),
    }


@router.get("/reports/by-owner")
def by_owner(db: Session = Depends(get_db)):
    """Per-rep performance: pipeline, won, open tickets, overdue tasks.

    Every figure is aggregated by the database over the whole set, grouped by
    owner. It used to run a query per user and sum the results in Python —
    fourteen queries for three reps, and every deal that rep has ever had loaded
    into memory to add up four numbers. That cost grows with the deals, not with
    the number of reps, which is the wrong thing to grow with.
    """
    now = datetime.utcnow()
    users = db.query(User).filter(User.active).all()

    def grouped(query):
        return {row[0]: row[1:] for row in query.all() if row[0] is not None}

    open_stages = ~Deal.stage.in_(("won", "lost"))
    pipeline = grouped(
        db.query(Deal.owner_id,
                 func.count(Deal.id),
                 func.coalesce(func.sum(Deal.value), 0.0),
                 # Weighted by probability, in SQL. The same arithmetic, done
                 # where the rows already are.
                 func.coalesce(func.sum(Deal.value * func.coalesce(Deal.probability, 0) / 100.0), 0.0))
        .filter(open_stages).group_by(Deal.owner_id))
    won = grouped(
        db.query(Deal.owner_id, func.count(Deal.id),
                 func.coalesce(func.sum(Deal.value), 0.0))
        .filter(Deal.stage == "won").group_by(Deal.owner_id))
    lost = grouped(
        db.query(Deal.owner_id, func.count(Deal.id))
        .filter(Deal.stage == "lost").group_by(Deal.owner_id))
    leads = grouped(
        db.query(Lead.owner_id, func.count(Lead.id))
        .filter(Lead.status.in_(["new", "working", "nurturing"])).group_by(Lead.owner_id))
    tickets = grouped(
        db.query(Ticket.assigned_to_id, func.count(Ticket.id))
        .filter(Ticket.status.in_(["open", "pending"])).group_by(Ticket.assigned_to_id))
    overdue = grouped(
        db.query(Activity.owner_id, func.count(Activity.id))
        .filter(Activity.completed_at.is_(None),
                Activity.due_at.isnot(None), Activity.due_at < now)
        .group_by(Activity.owner_id))

    rows = []
    for user in users:
        open_count, open_value, weighted = pipeline.get(user.id, (0, 0.0, 0.0))
        won_count, won_value = won.get(user.id, (0, 0.0))
        (lost_count,) = lost.get(user.id, (0,))
        decided = won_count + lost_count
        rows.append({
            "user_id": user.id, "name": user.full_name, "role": user.role,
            "open_deals": int(open_count),
            "pipeline_value": round(float(open_value), 2),
            "weighted_value": round(float(weighted), 2),
            "won_value": round(float(won_value), 2),
            "won_count": int(won_count),
            "win_rate": round(won_count / decided * 100, 1) if decided else 0.0,
            "open_leads": int(leads.get(user.id, (0,))[0]),
            "open_tickets": int(tickets.get(user.id, (0,))[0]),
            "overdue_tasks": int(overdue.get(user.id, (0,))[0]),
        })
    return sorted(rows, key=lambda r: -r["pipeline_value"])


@router.get("/reports/campaign-roi")
def campaign_roi(db: Session = Depends(get_db)):
    """Attribution: leads and opportunities influenced by each campaign."""
    rows = []
    for campaign in db.query(Campaign).order_by(Campaign.created_at.desc()).all():
        leads = db.query(Lead).filter(Lead.campaign_id == campaign.id).all()
        deals = db.query(Deal).filter(Deal.campaign_id == campaign.id).all()
        won = [d for d in deals if d.stage == "won"]
        rows.append({
            "campaign_id": campaign.id, "name": campaign.name,
            "channel": campaign.channel, "segment": campaign.segment,
            "sent": campaign.sent_count,
            "leads": len(leads),
            "converted_leads": len([l for l in leads if l.status == "converted"]),
            "opportunities": len(deals),
            "pipeline_value": round(sum(d.value for d in deals if d.stage not in ("won", "lost")), 2),
            "won_value": round(sum(d.value for d in won), 2),
            "response_rate": round(len(leads) / campaign.sent_count * 100, 1) if campaign.sent_count else 0.0,
        })
    return rows


# ---------- CRM dashboard ----------
@router.get("/dashboard")
def crm_dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    open_deals = db.query(Deal).filter(Deal.stage.notin_(["won", "lost"])).all()
    pipeline_value = sum(d.value for d in open_deals)
    weighted = sum(d.value * (d.probability or 0) / 100 for d in open_deals)

    won = db.query(Deal).filter(Deal.stage == "won").all()
    lost_count = db.query(func.count(Deal.id)).filter(Deal.stage == "lost").scalar()
    closed = len(won) + (lost_count or 0)

    by_stage = []
    for stage in PIPELINE_STAGES:
        deals = [d for d in open_deals if d.stage == stage] if stage not in ("won", "lost") else []
        if stage == "won":
            deals = won
        elif stage == "lost":
            deals = db.query(Deal).filter(Deal.stage == "lost").all()
        by_stage.append({
            "stage": stage,
            "count": len(deals),
            "value": round(sum(d.value for d in deals), 2),
        })

    now = datetime.utcnow()
    open_tickets = db.query(Ticket).filter(Ticket.status.in_(["open", "pending"])).all()
    breached = [t for t in open_tickets if t.due_at and t.due_at < now]

    return {
        "pipeline_value": round(pipeline_value, 2),
        "weighted_value": round(weighted, 2),
        "open_deals": len(open_deals),
        "won_value": round(sum(d.value for d in won), 2),
        "won_count": len(won),
        "win_rate": round(len(won) / closed * 100, 1) if closed else 0.0,
        "by_stage": by_stage,
        "companies": db.query(func.count(Company.id)).scalar(),
        "contacts": db.query(func.count(Contact.id)).scalar(),
        "leads": db.query(func.count(Contact.id)).filter(Contact.lifecycle_stage.in_(["lead", "qualified"])).scalar(),
        "open_tickets": len(open_tickets),
        "sla_breached": len(breached),
        "my_open_tasks": db.query(func.count(Activity.id)).filter(
            Activity.owner_id == user.id, Activity.completed_at.is_(None), Activity.due_at.isnot(None)
        ).scalar(),
        "marketable_patients": db.query(func.count(Patient.id)).filter(Patient.marketing_opt_in).scalar(),
        "open_leads": db.query(func.count(Lead.id)).filter(
            Lead.status.in_(["new", "working", "nurturing"])).scalar(),
        "hot_leads": db.query(func.count(Lead.id)).filter(
            Lead.rating == "hot", Lead.status.in_(["new", "working", "nurturing"])).scalar(),
        "converted_leads": db.query(func.count(Lead.id)).filter(Lead.status == "converted").scalar(),
    }
