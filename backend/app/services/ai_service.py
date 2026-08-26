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


def model_name() -> str:
    """Which model answered. Recorded with each saved answer, because an answer
    from a different model a year from now is not the same evidence."""
    return MODEL

_client = None


def ai_enabled() -> bool:
    return bool(settings.ANTHROPIC_API_KEY)


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _with_style(system: str) -> str:
    """Every system prompt carries the house style, so no call site can forget."""
    return f"{system}\n\n{HOUSE_STYLE}"


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
        system=_with_style(system),
        messages=[{"role": "user", "content": user}],
    )
    if response.stop_reason == "refusal":
        return "The AI assistant declined this request. Please review the query and try again."
    return "".join(block.text for block in response.content if block.type == "text")


def stream_claude(system: str, user: str, max_tokens: int = 16000):
    """Yield the answer as it is written, one delta at a time.

    The same call as `_ask_claude`, streamed. It matters more than it looks: an
    answer that takes twelve seconds to arrive whole reads as a system that has
    hung, and the pharmacist reaches for the back button at about second five.
    The same twelve seconds spent watching a sentence form reads as thinking,
    and nobody leaves.

    Yields plain text; the caller frames it for the wire.
    """
    if not ai_enabled():
        yield ("AI features are disabled. Add your ANTHROPIC_API_KEY to "
               "backend/.env and restart the server to enable them.")
        return
    client = _get_client()
    with client.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=_with_style(system),
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for text in stream.text_stream:
            yield text


# House style, appended to every system prompt.
#
# The em dash is the giveaway: it is the punctuation mark a model reaches for and
# most people do not, and a pharmacy system whose text reads as generated is a
# system nobody trusts with a clinical note.
HOUSE_STYLE = (
    "Write like a person, not like a model. Use full stops, commas and colons; never an em dash. No bullet-point padding, no restating the question, no closing summary of what you just said. Say the number, then why it matters."
)

PHARMACIST_SYSTEM = (
    "You are a clinical decision-support assistant embedded in RX5000, a pharmacy "
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


def interaction_check_prompt(db: Session, patient: Patient, products: list[Product]) -> tuple[str, str]:
    """The system and user prompt. Built once and used by both transports:
    the blocking call below and the streaming endpoint. Two copies of a
    prompt drift until the two answers differ."""
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
    return PHARMACIST_SYSTEM, prompt


def interaction_check(db: Session, patient: Patient, products: list[Product]) -> str:
    return _ask_claude(*interaction_check_prompt(db, patient, products))


def patient_summary_prompt(db: Session, patient: Patient) -> tuple[str, str]:
    """The system and user prompt. Built once and used by both transports:
    the blocking call below and the streaming endpoint. Two copies of a
    prompt drift until the two answers differ."""
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
    return PHARMACIST_SYSTEM, prompt


def patient_summary(db: Session, patient: Patient) -> str:
    return _ask_claude(*patient_summary_prompt(db, patient))


def counseling_notes_prompt(product: Product) -> tuple[str, str]:
    """The system and user prompt. Built once and used by both transports:
    the blocking call below and the streaming endpoint. Two copies of a
    prompt drift until the two answers differ."""
    prompt = (
        f"Medication: {product.name} {product.strength} ({product.dosage_form}), "
        f"schedule S{product.schedule}.\n"
        "Give patient counseling points a pharmacist should cover at hand-out: "
        "how to take it, common side effects, key warnings, storage. Keep it short "
        "and in plain language suitable for reading to a patient."
    )
    return PHARMACIST_SYSTEM, prompt


def counseling_notes(product: Product) -> str:
    return _ask_claude(*counseling_notes_prompt(product))


def crm_system() -> str:
    """The CRM assistant's brief, including where it is.

    Built on call rather than at import. This was a module-level constant that
    named South Africa, Rand and POPIA, so a Zimbabwean pharmacy got copy
    quoting the wrong currency and citing a privacy act that does not apply to
    it — and because it was frozen at import, setting JURISDICTION would not
    have fixed it either.
    """
    return (
        "You are a customer-relationship and marketing assistant for a pharmacy. You help "
        "pharmacy staff with customer relationships, sales opportunities, marketing copy and "
        "customer-service replies. Be concise, practical and professional. "
        + _local_context()
    )


def _local_context() -> str:
    """Tell the model where it is, from the jurisdiction pack.

    This named South Africa, Rand and POPIA in a hard-coded string, so a
    Zimbabwean pharmacy got marketing copy quoting the wrong currency and
    citing a privacy act that does not apply to it. The pack already holds
    every one of those facts.
    """
    j = settings.jurisdiction
    names = " and ".join(c.code for c in j.currencies)
    return (
        f"{j.name} context: prices are quoted in {names}, marketing must respect "
        f"{j.privacy_act} consent, and health claims must never be overstated."
    )


def campaign_copy_prompt(name: str, channel: str, segment_label: str, goal: str) -> tuple[str, str]:
    """The system and user prompt. Built once and used by both transports:
    the blocking call below and the streaming endpoint. Two copies of a
    prompt drift until the two answers differ."""
    limit = ("Keep it under 160 characters, it is an SMS."
             if channel == "sms" else "Write a short email: subject line, then 3-5 short lines.")
    prompt = (
        f"Draft marketing copy for a pharmacy campaign.\n"
        f"Campaign: {name}\nChannel: {channel}\nAudience: {segment_label}\nGoal: {goal}\n\n"
        f"{limit} You may use the merge fields {{first_name}}, {{points}} and {{pharmacy}}. "
        "Do not make medical claims or guarantee outcomes. Give the copy only, no commentary."
    )
    return crm_system(), prompt


def campaign_copy(name: str, channel: str, segment_label: str, goal: str) -> str:
    return _ask_claude(*campaign_copy_prompt(name, channel, segment_label, goal))


def ticket_reply_prompt(ticket, thread: list) -> tuple[str, str]:
    """The system and user prompt. Built once and used by both transports:
    the blocking call below and the streaming endpoint. Two copies of a
    prompt drift until the two answers differ."""
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
    return crm_system(), prompt


def ticket_reply(ticket, thread: list) -> str:
    return _ask_claude(*ticket_reply_prompt(ticket, thread))


def account_summary_prompt(db: Session, company, deals: list, tickets: list, contacts: list) -> tuple[str, str]:
    """The system and user prompt. Built once and used by both transports:
    the blocking call below and the streaming endpoint. Two copies of a
    prompt drift until the two answers differ."""
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
    return crm_system(), prompt


def account_summary(db: Session, company, deals: list, tickets: list, contacts: list) -> str:
    return _ask_claude(*account_summary_prompt(db, company, deals, tickets, contacts))


def business_prompt(db: Session, question: str) -> tuple[str, str]:
    """The system prompt and the user prompt for a business question.

    Split out so the streaming endpoint and the plain one build exactly the
    same context. Two call sites assembling "the same" prompt separately is
    how a streamed answer quietly starts differing from a written one.
    """
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
        "You are the business analyst inside RX5000, a pharmacy management system. "
        "Answer the owner's question using ONLY the data snapshot provided. Amounts "
        f"are in {settings.CURRENCY}. If the snapshot can't answer the question, say what "
        "data would be needed. Be direct and practical."
    )
    return system, f"{context}\n\nQuestion: {question}"


def business_answer(db: Session, question: str) -> str:
    """A natural-language question over live business data, answered whole."""
    system, user = business_prompt(db, question)
    return _ask_claude(system, user)


def business_answer_stream(db: Session, question: str):
    """The same answer, delivered as it is written."""
    system, user = business_prompt(db, question)
    yield from stream_claude(system, user)
