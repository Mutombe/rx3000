"""Claude-powered clinical and business intelligence.

Uses claude-opus-5 with server-side refusal fallbacks enabled (a policy
decline is transparently re-served by the recommended fallback model).
Every helper returns plain text; when no ANTHROPIC_API_KEY is configured the
caller receives a clear "AI disabled" message instead of an exception.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Dispensing, Patient, PrescriptionItem, Product, Sale, SaleItem,
)

MODEL = "claude-opus-5"

_client = None


def ai_enabled() -> bool:
    return bool(settings.ANTHROPIC_API_KEY)


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _ask_claude(system: str, user: str, max_tokens: int = 16000) -> str:
    if not ai_enabled():
        return (
            "AI features are disabled. Add your ANTHROPIC_API_KEY to backend/.env "
            "and restart the server to enable them."
        )
    client = _get_client()
    # Plain messages.create. The beta server-side fallback parameters this used
    # to pass are not accepted by the installed SDK, so every AI call died with
    # `TypeError: unexpected keyword argument 'fallbacks'` — a 500 that reached
    # the pharmacist as "something went wrong at our end" and never named the
    # cause. If fallbacks are wanted later, pin the SDK version that supports
    # them rather than passing arguments hopefully.
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if response.stop_reason == "refusal":
        return "The AI assistant declined this request. Please review the query and try again."
    return "".join(block.text for block in response.content if block.type == "text")


PHARMACIST_SYSTEM = (
    "You are a clinical decision-support assistant embedded in RX3000, a pharmacy "
    "management system. Your audience is a licensed pharmacist. Be concise, "
    "structured and practical. Flag severity clearly (e.g. CONTRAINDICATED, MAJOR, "
    "MODERATE, MINOR). Always end with a one-line reminder that this is decision "
    "support and the pharmacist's professional judgement prevails."
)


def _patient_medication_context(db: Session, patient: Patient) -> str:
    items = (
        db.query(PrescriptionItem)
        .join(PrescriptionItem.prescription)
        .filter_by(patient_id=patient.id)
        .all()
    )
    current = [
        f"- {i.product.name} {i.product.strength} ({i.product.dosage_form}); "
        f"dosage: {i.dosage_instructions or 'n/a'}; repeats {i.repeats_used}/{i.repeats_allowed}"
        for i in items
    ]
    age = ""
    if patient.date_of_birth:
        age = f", age {(date.today() - patient.date_of_birth).days // 365}"
    return (
        f"Patient: {patient.first_name} {patient.last_name}{age}\n"
        f"Known allergies: {patient.allergies or 'none recorded'}\n"
        f"Chronic conditions: {patient.chronic_conditions or 'none recorded'}\n"
        f"Medication history:\n" + ("\n".join(current) or "- none on file")
    )


def interaction_check(db: Session, patient: Patient, products: list[Product]) -> str:
    new_meds = "\n".join(
        f"- {p.name} {p.strength} ({p.dosage_form}), schedule S{p.schedule}" for p in products
    )
    prompt = (
        f"{_patient_medication_context(db, patient)}\n\n"
        f"The pharmacist is about to dispense:\n{new_meds}\n\n"
        "Check for: (1) drug-drug interactions with the medication history, "
        "(2) allergy conflicts, (3) therapeutic duplication, (4) condition cautions. "
        "Give a short verdict first (SAFE TO DISPENSE / DISPENSE WITH COUNSELING / REVIEW REQUIRED), "
        "then bullet findings."
    )
    return _ask_claude(PHARMACIST_SYSTEM, prompt)


def patient_summary(db: Session, patient: Patient) -> str:
    recent_sales = (
        db.query(Sale).filter(Sale.patient_id == patient.id, Sale.status == "paid")
        .order_by(Sale.created_at.desc()).limit(10).all()
    )
    sales_lines = [
        f"- {s.created_at:%Y-%m-%d}: {settings.CURRENCY}{s.total:.2f} ({s.payment_method})"
        for s in recent_sales
    ]
    prompt = (
        f"{_patient_medication_context(db, patient)}\n\n"
        f"Recent purchases:\n" + ("\n".join(sales_lines) or "- none") + "\n\n"
        "Write a brief clinical hand-over summary of this patient for a pharmacist "
        "seeing them for the first time: adherence signals, likely counseling points, "
        "and anything to watch for."
    )
    return _ask_claude(PHARMACIST_SYSTEM, prompt)


def counseling_notes(product: Product) -> str:
    prompt = (
        f"Medication: {product.name} {product.strength} ({product.dosage_form}), "
        f"schedule S{product.schedule}.\n"
        "Give patient counseling points a pharmacist should cover at hand-out: "
        "how to take it, common side effects, key warnings, storage. Keep it short "
        "and in plain language suitable for reading to a patient."
    )
    return _ask_claude(PHARMACIST_SYSTEM, prompt)


CRM_SYSTEM = (
    "You are a CRM assistant inside RX3000, a pharmacy management system. You help "
    "pharmacy staff with customer relationships, sales opportunities, marketing copy and "
    "customer-service replies. Be concise, practical and professional. South African "
    "context: currency is Rand, marketing must respect POPIA consent, and health claims "
    "must never be overstated."
)


def campaign_copy(name: str, channel: str, segment_label: str, goal: str) -> str:
    limit = ("Keep it under 160 characters — it is an SMS."
             if channel == "sms" else "Write a short email: subject line, then 3-5 short lines.")
    prompt = (
        f"Draft marketing copy for a pharmacy campaign.\n"
        f"Campaign: {name}\nChannel: {channel}\nAudience: {segment_label}\nGoal: {goal}\n\n"
        f"{limit} You may use the merge fields {{first_name}}, {{points}} and {{pharmacy}}. "
        "Do not make medical claims or guarantee outcomes. Give the copy only — no commentary."
    )
    return _ask_claude(CRM_SYSTEM, prompt)


def ticket_reply(ticket, thread: list) -> str:
    lines = [
        f"{'Customer' if m.from_customer else 'Staff'}: {m.body}"
        for m in thread if not m.internal_note
    ]
    prompt = (
        f"A customer-service ticket needs a reply.\n"
        f"Subject: {ticket.subject}\nCategory: {ticket.category}\nPriority: {ticket.priority}\n"
        f"Customer: {ticket.patient.first_name + ' ' + ticket.patient.last_name if ticket.patient else 'Unknown'}\n\n"
        "Conversation so far:\n" + ("\n".join(lines) or f"Customer: {ticket.description}") + "\n\n"
        "Draft a warm, professional reply the staff member can send. Acknowledge the issue, "
        "state what will happen next, and give a realistic timeframe. If clinical judgement "
        "is needed, say a pharmacist will follow up rather than giving clinical advice."
    )
    return _ask_claude(CRM_SYSTEM, prompt)


def account_summary(db: Session, company, deals: list, tickets: list, contacts: list) -> str:
    deal_lines = [
        f"- {d.title}: {settings.CURRENCY}{d.value:.2f}, stage {d.stage}, "
        f"{d.probability}% probability, expected {d.expected_close_date or 'unset'}"
        for d in deals
    ]
    ticket_lines = [f"- [{t.status}/{t.priority}] {t.subject}" for t in tickets]
    contact_lines = [f"- {c.first_name} {c.last_name}, {c.job_title or 'role unknown'}" for c in contacts]
    prompt = (
        f"Account: {company.name} ({company.account_type}), status {company.status}\n"
        f"Notes: {company.notes or 'none'}\n\n"
        "Contacts:\n" + ("\n".join(contact_lines) or "- none") + "\n\n"
        "Open and closed deals:\n" + ("\n".join(deal_lines) or "- none") + "\n\n"
        "Support tickets:\n" + ("\n".join(ticket_lines) or "- none") + "\n\n"
        "Write a short account review for the account owner: where the relationship stands, "
        "what the risks are, and the two or three highest-value next actions."
    )
    return _ask_claude(CRM_SYSTEM, prompt)


def business_answer(db: Session, question: str) -> str:
    """Natural-language Q&A over live business data."""
    today = date.today()
    month_start = today.replace(day=1)
    week_ago = datetime.utcnow() - timedelta(days=7)

    sales_today = db.query(func.count(Sale.id), func.coalesce(func.sum(Sale.total), 0.0)).filter(
        Sale.status == "paid", func.date(Sale.created_at) == today.isoformat()
    ).one()
    sales_month = db.query(func.count(Sale.id), func.coalesce(func.sum(Sale.total), 0.0)).filter(
        Sale.status == "paid", func.date(Sale.created_at) >= month_start.isoformat()
    ).one()
    top_products = (
        db.query(Product.name, func.sum(SaleItem.quantity).label("qty"), func.sum(SaleItem.line_total).label("rev"))
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.status == "paid", Sale.created_at >= week_ago)
        .group_by(Product.name).order_by(func.sum(SaleItem.line_total).desc()).limit(10).all()
    )
    low_stock = (
        db.query(Product).filter(Product.active, Product.quantity_on_hand <= Product.reorder_level)
        .order_by(Product.quantity_on_hand).limit(15).all()
    )
    scripts_week = db.query(func.count(Dispensing.id)).filter(Dispensing.dispensed_at >= week_ago).scalar()
    patient_count = db.query(func.count(Patient.id)).scalar()

    context = (
        f"Snapshot for {settings.PHARMACY_NAME} on {today}:\n"
        f"- Sales today: {sales_today[0]} transactions, {settings.CURRENCY}{sales_today[1]:.2f}\n"
        f"- Sales this month: {sales_month[0]} transactions, {settings.CURRENCY}{sales_month[1]:.2f}\n"
        f"- Scripts dispensed last 7 days: {scripts_week}\n"
        f"- Registered patients: {patient_count}\n"
        f"- Top sellers (7 days): "
        + "; ".join(f"{n} x{int(q)} ({settings.CURRENCY}{r:.2f})" for n, q, r in top_products)
        + "\n- Low / at reorder stock: "
        + "; ".join(f"{p.name} ({p.quantity_on_hand} on hand, reorder at {p.reorder_level})" for p in low_stock)
    )
    system = (
        "You are the business analyst inside RX3000, a pharmacy management system. "
        "Answer the owner's question using ONLY the data snapshot provided. Amounts "
        f"are in {settings.CURRENCY}. If the snapshot can't answer the question, say what "
        "data would be needed. Be direct and practical."
    )
    return _ask_claude(system, f"{context}\n\nQuestion: {question}")
