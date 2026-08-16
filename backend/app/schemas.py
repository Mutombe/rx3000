from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(ORM):
    id: int
    username: str
    full_name: str
    role: str


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    role: str = "assistant"


# ---------- reference data ----------
class MedicalAidOut(ORM):
    id: int
    name: str
    scheme_code: str
    phone: str = ""


class DoctorBase(BaseModel):
    name: str
    practice_number: str = ""
    phone: str = ""
    email: str = ""


class DoctorOut(ORM, DoctorBase):
    id: int


class SupplierBase(BaseModel):
    name: str
    contact_person: str = ""
    phone: str = ""
    email: str = ""


class SupplierOut(ORM, SupplierBase):
    id: int


# ---------- patients ----------
class PatientBase(BaseModel):
    first_name: str
    last_name: str
    id_number: str = ""
    date_of_birth: Optional[date] = None
    phone: str = ""
    email: str = ""
    address: str = ""
    allergies: str = ""
    chronic_conditions: str = ""
    medical_aid_id: Optional[int] = None
    medical_aid_number: str = ""
    dependent_code: str = "00"


class PatientCreate(PatientBase):
    pass


class PatientOut(ORM, PatientBase):
    id: int
    loyalty_points: int = 0
    medical_aid: Optional[MedicalAidOut] = None


# ---------- products / stock ----------
class ProductBase(BaseModel):
    # A blank name was accepted, which puts an unnameable line in the catalogue:
    # it cannot be searched for, cannot be recognised on a shelf, and prints as
    # an empty row on a receipt. Whitespace is stripped first so " " is caught
    # too — the constraint has to reject what the user can actually type.
    name: str = Field(min_length=1, max_length=200)
    nappi_code: str = ""
    barcode: str = ""
    category: str = "medicine"
    schedule: int = 0
    dosage_form: str = ""
    strength: str = ""
    active_ingredient: str = ""
    pack_size: str = ""
    unit_price: float = 0.0
    cost_price: float = 0.0
    vat_rate: float = 0.15
    reorder_level: int = 10
    reorder_quantity: int = 20
    supplier_id: Optional[int] = None


class ProductCreate(ProductBase):
    quantity_on_hand: int = 0


class ProductOut(ORM, ProductBase):
    id: int
    quantity_on_hand: int
    active: bool = True


class StockAdjust(BaseModel):
    product_id: int
    quantity_delta: int
    movement_type: str = "adjustment"  # receive | adjustment | return
    reference: str = ""
    notes: str = ""
    batch_number: str = ""              # used when receiving stock
    expiry_date: Optional[date] = None  # used when receiving stock


class BatchOut(ORM):
    id: int
    product_id: int
    batch_number: str
    expiry_date: Optional[date] = None
    quantity_received: int
    quantity_remaining: int
    unit_cost: float
    reference: str
    received_at: datetime
    product: Optional[ProductOut] = None


class BatchLite(ORM):
    batch_number: str
    expiry_date: Optional[date] = None


class AllocationOut(ORM):
    quantity: int
    batch: Optional[BatchLite] = None


class StockMovementOut(ORM):
    id: int
    product_id: int
    movement_type: str
    quantity_delta: int
    balance_after: int
    reference: str
    notes: str
    created_at: datetime
    product: Optional[ProductOut] = None


class ProductDetail(BaseModel):
    """Everything the product record page renders, in one response."""
    product: ProductOut
    batches: list[BatchOut]
    movements: list[StockMovementOut]
    units_dispensed: int
    units_sold: int
    stock_value: float


# ---------- prescriptions ----------
class PrescriptionItemCreate(BaseModel):
    product_id: int
    dosage_instructions: str = ""
    quantity: int = 1
    repeats_allowed: int = 0
    repeat_interval_days: int = 30
    auto_refill: bool = False
    # Diagnosis for this line — schemes reject a claim line without one.
    icd10_code: str = ""
    # Days this quantity should last. Schemes adjudicate on it, and it is what
    # makes a repeat due on the right date rather than a fixed interval.
    supply_days: int = 30
    no_claim: bool = False
    not_dispensed: bool = False


class PrescriptionCreate(BaseModel):
    patient_id: int
    # A draft may not have a prescriber yet — often the thing still being chased.
    doctor_id: Optional[int] = None
    date_prescribed: Optional[date] = None
    notes: str = ""
    # Save what has been captured so far and come back to it. The script takes
    # no Rx number and cannot be dispensed until it is finished.
    draft: bool = False
    items: list[PrescriptionItemCreate] = []


class PrescriptionRef(ORM):
    id: int
    rx_number: Optional[str] = None
    patient: Optional[PatientOut] = None


class PrescriptionItemOut(ORM):
    id: int
    product_id: int
    dosage_instructions: str
    quantity: int
    repeats_allowed: int
    repeats_used: int
    repeat_interval_days: int
    next_repeat_date: Optional[date] = None
    auto_refill: bool
    icd10_code: str = ""
    supply_days: int = 30
    no_claim: bool = False
    not_dispensed: bool = False
    product: Optional[ProductOut] = None
    prescription: Optional[PrescriptionRef] = None


class PrescriptionOut(ORM):
    id: int
    rx_number: Optional[str] = None
    status: str = "active"
    draft_ref: str = ""
    patient_id: int
    doctor_id: Optional[int] = None
    date_prescribed: date
    notes: str
    items: list[PrescriptionItemOut] = []
    patient: Optional[PatientOut] = None
    doctor: Optional[DoctorOut] = None


class DispenseRequest(BaseModel):
    item_ids: list[int]
    payment_method: str = "cash"  # settled at POS; sale created as pending
    # Hand over less than the script asks and owe the balance, keyed by
    # prescription item id. The patient pays for the whole quantity; what was
    # not handed over becomes a "to follow". Omit an item to supply it in full.
    supply: dict[int, int] = {}
    # What the patient was told, per item. Shown on the to-follow queue.
    promised_for: Optional[date] = None
    # Controlled-substance (S5/S6) compliance — required when the script
    # contains a dangerous drug; ignored otherwise.
    id_verified: bool = False
    id_number_seen: str = ""
    script_sighted: bool = False
    prescriber_verified: bool = False
    witness_id: Optional[int] = None
    compliance_notes: str = ""


class SchedulePolicyOut(BaseModel):
    schedule: int
    # What a human sees: "S5" in South Africa, "PP10" in Zimbabwe. Display this,
    # never `schedule` — that is an internal ordinal, not a legal classification.
    code: str = ""
    label: str
    route: str
    requires_prescription: bool
    requires_pharmacist: bool
    register_entry: bool
    max_repeats: int
    max_repeat_months: int
    requires_id_verification: bool
    requires_script_sighted: bool
    requires_prescriber_verification: bool
    requires_witness: bool
    counselling_required: bool
    notes: str


class OTCSaleCreate(BaseModel):
    product_id: int
    quantity: int = 1
    patient_id: Optional[int] = None
    customer_name: str = ""
    indication: str = ""
    counselling_given: bool = False
    referred_to_doctor: bool = False
    notes: str = ""
    payment_method: str = "cash"
    amount_tendered: float = 0.0


class OTCSaleOut(ORM):
    id: int
    product_id: int
    quantity: int
    schedule: int
    patient_id: Optional[int] = None
    customer_name: str
    indication: str
    counselling_given: bool
    referred_to_doctor: bool
    notes: str
    sale_id: Optional[int] = None
    created_at: datetime
    product: Optional[ProductOut] = None
    patient: Optional[PatientOut] = None
    pharmacist: Optional[UserOut] = None


class DispensingOut(ORM):
    id: int
    quantity: int
    dispensed_at: datetime
    is_repeat: bool
    dispense_type: str
    schedule: int
    id_verified: bool
    id_number_seen: str
    script_sighted: bool
    prescriber_verified: bool
    compliance_notes: str
    dispensed_by: Optional[UserOut] = None
    witness: Optional[UserOut] = None


# ---------- currency ----------
class ExchangeRateCreate(BaseModel):
    currency_code: str
    units_per_base: float
    effective_from: Optional[datetime] = None
    source: str = "manual"
    note: str = ""


class ExchangeRateOut(ORM):
    id: int
    currency_code: str
    units_per_base: float
    effective_from: datetime
    source: str
    note: str
    created_by: Optional[UserOut] = None


class CurrencyOut(BaseModel):
    code: str
    symbol: str
    decimals: int
    rate: float
    is_base: bool


class CurrencyState(BaseModel):
    base: str
    currencies: list[CurrencyOut]
    multi_currency: bool


class TenderIn(BaseModel):
    """One payment on a sale. Several may be supplied to split a tender."""
    method: str = "cash"
    currency_code: str = ""       # defaults to the base currency
    amount: float = 0.0
    reference: str = ""


class TenderOut(ORM):
    id: int
    method: str
    currency_code: str
    amount: float
    rate_used: float
    amount_in_base: float
    is_change: bool
    reference: str


# ---------- POS ----------
class SaleItemIn(BaseModel):
    product_id: int
    quantity: int = 1


class CardTender(BaseModel):
    """Detail read off the terminal slip, needed to reconcile card takings."""
    card_auth_code: str = ""
    card_reference: str = ""
    card_last4: str = ""
    card_scheme: str = ""
    terminal_id: str = ""
    card_batch: str = ""


class SaleCreate(CardTender):
    patient_id: Optional[int] = None
    items: list[SaleItemIn]
    payment_method: str = "cash"
    amount_tendered: float = 0.0
    loyalty_points_redeemed: int = 0
    # Split tender. When supplied this replaces payment_method/amount_tendered;
    # the single-tender fields remain for callers that do not need it.
    tenders: list[TenderIn] = []
    change_currency: str = ""
    # Hold the claim instead of sending it: the switch is down, or the member's
    # card is not present. The medicine goes out, the patient settles in full,
    # and the claim is submitted when it can be.
    claim_later: bool = False
    claim_later_reason: str = ""
    # Set by a till replaying a sale it took while offline. Same value on every
    # retry, which is what lets the server recognise a repeat.
    client_ref: str = ""
    taken_offline_at: Optional[datetime] = None


class SaleItemOut(ORM):
    id: int
    product_id: int
    description: str
    quantity: int
    unit_price: float
    unit_cost: float = 0.0
    vat_rate: float
    line_total: float
    # Which script line this came from, where there was one. Exposed because a
    # sale that cannot be traced to what was prescribed cannot be queried, and
    # the per-line billing decisions live on the script.
    prescription_item_id: Optional[int] = None
    allocations: list[AllocationOut] = []


class ClaimOut(ORM):
    id: int
    claim_number: str
    amount_claimed: float
    amount_approved: float
    patient_liable: float
    status: str
    response_message: str


class SaleOut(ORM):
    id: int
    sale_number: str
    patient_id: Optional[int] = None
    created_at: datetime
    subtotal: float
    vat_amount: float
    total: float
    payment_method: str
    amount_tendered: float
    change_due: float
    loyalty_points_earned: int
    loyalty_points_redeemed: int
    status: str
    card_auth_code: str = ""
    card_reference: str = ""
    card_last4: str = ""
    card_scheme: str = ""
    terminal_id: str = ""
    card_batch: str = ""
    currency_code: str = ""
    tenders: list[TenderOut] = []
    items: list[SaleItemOut] = []
    claim: Optional[ClaimOut] = None
    patient: Optional[PatientOut] = None


class CardReconcileRequest(BaseModel):
    csv_text: str
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class ReconMatch(BaseModel):
    sale_id: int
    sale_number: str
    sale_total: float
    statement_amount: float
    difference: float
    matched_on: str
    auth_code: str = ""
    reference: str = ""
    statement_line: int
    created_at: datetime


class ReconStatementLine(BaseModel):
    line: int
    auth_code: str = ""
    reference: str = ""
    amount: float
    # NB: not named `date` — a Pydantic field whose name matches its own type
    # resolves the annotation against the class namespace, where the default has
    # already bound the name, silently turning Optional[date] into Optional[None].
    txn_date: Optional[date] = None
    last4: str = ""
    terminal: str = ""
    batch: str = ""


class ReconUnbanked(BaseModel):
    sale_id: int
    sale_number: str
    sale_total: float
    auth_code: str = ""
    reference: str = ""
    terminal_id: str = ""
    created_at: datetime


class CardReconciliation(BaseModel):
    statement_lines: int
    card_sales: int
    statement_total: float
    system_total: float
    variance: float
    matched: list[ReconMatch]
    mismatched: list[ReconMatch]
    missing_in_system: list[ReconStatementLine]
    missing_in_statement: list[ReconUnbanked]
    weak_matches: int
    warnings: list[str]


class PayRequest(CardTender):
    payment_method: str = "cash"
    amount_tendered: float = 0.0
    loyalty_points_redeemed: int = 0
    tenders: list[TenderIn] = []
    change_currency: str = ""
    # Hold the claim instead of sending it: the switch is down, or the member's
    # card is not present. The medicine goes out, the patient settles in full,
    # and the claim is submitted when it can be.
    claim_later: bool = False
    claim_later_reason: str = ""


# ---------- purchase orders ----------
class POItemIn(BaseModel):
    product_id: int
    quantity_ordered: int
    unit_cost: float = 0.0


class POCreate(BaseModel):
    supplier_id: int
    items: list[POItemIn]
    notes: str = ""


class ReceiveLine(BaseModel):
    item_id: int
    batch_number: str = ""
    expiry_date: Optional[date] = None


class ReceiveOrderBody(BaseModel):
    lines: list[ReceiveLine] = []


class POItemOut(ORM):
    id: int
    product_id: int
    quantity_ordered: int
    quantity_received: int
    unit_cost: float
    product: Optional[ProductOut] = None


class POOut(ORM):
    id: int
    order_number: str
    supplier_id: int
    status: str
    created_at: datetime
    received_at: Optional[datetime] = None
    notes: str
    items: list[POItemOut] = []
    supplier: Optional[SupplierOut] = None


# ---------- register ----------
class RegisterEntryOut(ORM):
    id: int
    schedule: int
    entry_type: str
    quantity_delta: int
    balance_after: int
    reference: str
    created_at: datetime
    product: Optional[ProductOut] = None
    patient: Optional[PatientOut] = None
    doctor: Optional[DoctorOut] = None


# ---------- messages ----------
class MessageCreate(BaseModel):
    patient_id: int
    channel: str = "sms"
    subject: str = ""
    body: str
    message_type: str = "custom"


class MessageOut(ORM):
    id: int
    patient_id: int
    channel: str
    message_type: str
    subject: str
    body: str
    status: str
    detail: str
    scheduled_for: datetime
    sent_at: Optional[datetime] = None
    patient: Optional[PatientOut] = None


# ---------- shifts / cash-up ----------
class ShiftOpen(BaseModel):
    opening_float: float = 0.0


class ShiftClose(BaseModel):
    counted_cash: float
    notes: str = ""


class ShiftOut(ORM):
    id: int
    user_id: int
    opened_at: datetime
    closed_at: Optional[datetime] = None
    opening_float: float
    counted_cash: float
    expected_cash: float
    variance: float
    card_total: float
    medical_aid_total: float
    sales_count: int
    notes: str
    status: str
    user: Optional[UserOut] = None


# ---------- audit ----------
class AuditLogOut(ORM):
    id: int
    username: str
    action: str
    path: str
    summary: str
    status_code: int
    ip_address: str
    created_at: datetime


# ---------- admin: price import & backups ----------
class PriceImportRequest(BaseModel):
    csv_text: str
    apply: bool = False        # False = dry-run preview
    update_cost: bool = True
    update_selling: bool = True


class PriceImportLine(BaseModel):
    row: int
    key: str
    product_name: str = ""
    matched: bool
    old_cost: Optional[float] = None
    new_cost: Optional[float] = None
    old_price: Optional[float] = None
    new_price: Optional[float] = None
    message: str = ""


class PriceImportResult(BaseModel):
    applied: bool
    total_rows: int
    matched: int
    unmatched: int
    updated: int
    lines: list[PriceImportLine]


class BackupOut(BaseModel):
    filename: str
    size_bytes: int
    created_at: datetime
    # Whether this file was opened and proven restorable, not merely
    # whether it was written.
    verified: bool = False
    checked_at: Optional[datetime] = None
    problem: str = ""


# ---------- labels ----------
class LabelOut(BaseModel):
    patient_name: str
    patient_id_number: str = ""
    rx_number: str
    product_name: str
    strength: str = ""
    dosage_form: str = ""
    quantity: int
    dosage_instructions: str
    warnings: str = ""
    schedule: int = 0
    batch_number: str = ""
    expiry_date: Optional[date] = None
    repeats_remaining: int = 0
    next_repeat_date: Optional[date] = None
    doctor_name: str = ""
    dispensed_by: str = ""
    dispensed_at: datetime
    pharmacy_name: str
    pharmacy_reg_no: str


# ==================== CRM ====================
class CompanyBase(BaseModel):
    name: str
    account_type: str = "business"
    phone: str = ""
    email: str = ""
    address: str = ""
    vat_number: str = ""
    credit_terms_days: int = 30
    owner_id: Optional[int] = None
    status: str = "active"
    notes: str = ""


class CompanyOut(ORM, CompanyBase):
    id: int
    created_at: datetime
    owner: Optional[UserOut] = None


class ContactBase(BaseModel):
    first_name: str
    last_name: str
    job_title: str = ""
    email: str = ""
    phone: str = ""
    company_id: Optional[int] = None
    patient_id: Optional[int] = None
    lifecycle_stage: str = "lead"
    source: str = ""
    owner_id: Optional[int] = None
    marketing_opt_in: bool = False
    notes: str = ""


class CompanyLite(ORM):
    id: int
    name: str
    account_type: str = "business"


class ContactOut(ORM, ContactBase):
    id: int
    created_at: datetime
    company: Optional[CompanyLite] = None
    owner: Optional[UserOut] = None


class ContactLite(ORM):
    id: int
    first_name: str
    last_name: str
    email: str = ""
    phone: str = ""


class DealBase(BaseModel):
    title: str
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    value: float = 0.0
    stage: str = "new"
    probability: int = 10
    expected_close_date: Optional[date] = None
    owner_id: Optional[int] = None
    source: str = ""
    notes: str = ""


class DealOut(ORM, DealBase):
    id: int
    lost_reason: str = ""
    campaign_id: Optional[int] = None
    created_at: datetime
    closed_at: Optional[datetime] = None
    company: Optional[CompanyLite] = None
    contact: Optional[ContactLite] = None
    owner: Optional[UserOut] = None
    items: list["DealItemOut"] = []


class DealStageUpdate(BaseModel):
    stage: str
    lost_reason: str = ""


class ActivityBase(BaseModel):
    activity_type: str = "note"
    subject: str
    body: str = ""
    due_at: Optional[datetime] = None
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    deal_id: Optional[int] = None
    ticket_id: Optional[int] = None
    patient_id: Optional[int] = None


class ActivityOut(ORM, ActivityBase):
    id: int
    completed_at: Optional[datetime] = None
    created_at: datetime
    owner: Optional[UserOut] = None
    company: Optional[CompanyLite] = None
    contact: Optional[ContactLite] = None


# ---------- leads ----------
class LeadBase(BaseModel):
    first_name: str
    last_name: str
    company_name: str = ""
    job_title: str = ""
    email: str = ""
    phone: str = ""
    source: str = ""
    interest: str = ""
    estimated_value: float = 0.0
    owner_id: Optional[int] = None
    campaign_id: Optional[int] = None
    marketing_opt_in: bool = False


class LeadOut(ORM, LeadBase):
    id: int
    status: str
    rating: str
    score: int
    disqualified_reason: str = ""
    converted_at: Optional[datetime] = None
    converted_company_id: Optional[int] = None
    converted_contact_id: Optional[int] = None
    converted_deal_id: Optional[int] = None
    created_at: datetime
    owner: Optional[UserOut] = None


class LeadStatusUpdate(BaseModel):
    status: str
    disqualified_reason: str = ""


class LeadConvert(BaseModel):
    create_company: bool = True
    create_deal: bool = True
    deal_title: str = ""
    deal_value: Optional[float] = None
    account_type: str = "business"


class LeadConvertResult(BaseModel):
    lead_id: int
    company_id: Optional[int] = None
    contact_id: int
    deal_id: Optional[int] = None


class DuplicateWarning(BaseModel):
    field: str
    value: str
    existing_type: str
    existing_id: int
    existing_label: str


class LeadScoreFactor(BaseModel):
    label: str
    points: int
    max: int
    group: str


class LeadScoreExplanation(BaseModel):
    score: int
    raw_score: int
    rating: str
    capped: bool
    factors: list[LeadScoreFactor]


class LeadBulkAssign(BaseModel):
    lead_ids: list[int]
    owner_id: int


# ---------- deal line items & quotes ----------
class DealItemIn(BaseModel):
    product_id: Optional[int] = None
    description: str = ""
    quantity: int = 1
    unit_price: float = 0.0
    discount_percent: float = 0.0


class DealItemOut(ORM):
    id: int
    product_id: Optional[int] = None
    description: str
    quantity: int
    unit_price: float
    discount_percent: float
    line_total: float
    product: Optional[ProductOut] = None


class QuoteCreate(BaseModel):
    valid_days: int = 30
    terms: str = ""


class QuoteOut(ORM):
    id: int
    quote_number: str
    deal_id: int
    version: int
    status: str
    valid_until: Optional[date] = None
    subtotal: float
    vat_amount: float
    total: float
    terms: str
    created_at: datetime
    sent_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    created_by: Optional[UserOut] = None


# ---------- templates & automation ----------
class EmailTemplateBase(BaseModel):
    name: str
    category: str = "general"
    channel: str = "email"
    subject: str = ""
    body: str = ""


class EmailTemplateOut(ORM, EmailTemplateBase):
    id: int
    created_at: datetime


class AutomationRuleBase(BaseModel):
    name: str
    rule_type: str
    trigger_field: str = ""
    trigger_value: str = ""
    action: str = ""
    action_value: str = ""
    active: bool = True
    sort_order: int = 100


class AutomationRuleOut(ORM, AutomationRuleBase):
    id: int
    times_fired: int
    created_at: datetime


# ---------- web-to-lead / web-to-case ----------
class WebLeadIn(BaseModel):
    first_name: str
    last_name: str
    company_name: str = ""
    email: str = ""
    phone: str = ""
    interest: str = ""
    source: str = "web"
    marketing_opt_in: bool = False


class WebCaseIn(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    subject: str
    description: str = ""
    category: str = "query"


# ---------- marketing ----------
class SegmentOut(BaseModel):
    key: str
    label: str
    description: str
    size: int


class CampaignCreate(BaseModel):
    name: str
    channel: str = "sms"
    segment: str = "all_patients"
    subject: str = ""
    body: str


class CampaignOut(ORM):
    id: int
    name: str
    channel: str
    segment: str
    subject: str
    body: str
    status: str
    audience_size: int
    sent_count: int
    failed_count: int
    created_at: datetime
    sent_at: Optional[datetime] = None
    created_by: Optional[UserOut] = None


# ---------- help desk ----------
class TicketCreate(BaseModel):
    subject: str
    description: str = ""
    category: str = "query"
    priority: str = "normal"
    channel: str = "walk_in"
    patient_id: Optional[int] = None
    contact_id: Optional[int] = None
    company_id: Optional[int] = None
    assigned_to_id: Optional[int] = None


class TicketUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    assigned_to_id: Optional[int] = None
    satisfaction: Optional[int] = None


class TicketMessageCreate(BaseModel):
    body: str
    from_customer: bool = False
    internal_note: bool = False


class TicketMessageOut(ORM):
    id: int
    from_customer: bool
    internal_note: bool
    body: str
    created_at: datetime
    author: Optional[UserOut] = None


class TicketOut(ORM):
    id: int
    ticket_number: str
    subject: str
    description: str
    category: str
    priority: str
    status: str
    channel: str
    patient_id: Optional[int] = None
    created_at: datetime
    due_at: Optional[datetime] = None
    first_response_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    satisfaction: Optional[int] = None
    patient: Optional[PatientOut] = None
    contact: Optional[ContactLite] = None
    company: Optional[CompanyLite] = None
    assigned_to: Optional[UserOut] = None
    messages: list[TicketMessageOut] = []


# ---------- AI ----------
class AIAskRequest(BaseModel):
    question: str


class AIInteractionRequest(BaseModel):
    patient_id: int
    product_ids: list[int]


class AITextResponse(BaseModel):
    text: str
    enabled: bool = True

# ---------- claiming ----------
class DiagnosisCodeOut(ORM):
    id: int
    code: str
    description: str
    chapter: str = ""
    valid_primary: bool = True


class PayOfficeBase(BaseModel):
    code: str
    name: str
    submission: str = "manual"
    contact: str = ""
    phone: str = ""
    email: str = ""
    active: bool = True


class PayOfficeOut(ORM, PayOfficeBase):
    id: int


class FeeTierIn(BaseModel):
    up_to: Optional[float] = None
    percentage: float = 0.0
    fixed_fee: float = 0.0
    min_fee: float = 0.0
    max_fee: Optional[float] = None


class FeeTierOut(ORM, FeeTierIn):
    id: int


class FeeModelCreate(BaseModel):
    code: str
    name: str
    basis: str = "sep"
    vat_on_fee: bool = True
    apply_mmap: bool = False
    notes: str = ""
    active: bool = True
    tiers: list[FeeTierIn] = []


class FeeModelOut(ORM):
    id: int
    code: str
    name: str
    basis: str
    vat_on_fee: bool
    apply_mmap: bool
    notes: str = ""
    active: bool
    tiers: list[FeeTierOut] = []


class PriceItem(BaseModel):
    product_id: int
    quantity: int = 1


class PriceRequest(BaseModel):
    items: list[PriceItem]
    medical_aid_id: Optional[int] = None


class PricedLineOut(BaseModel):
    product_id: int
    description: str
    quantity: int
    base_price: float
    mmap_cap: float
    mmap_excess: float
    medicine_portion: float
    dispensing_fee: float
    markup: float
    gross: float
    discount: float
    levy: float
    claimable: float
    patient_portion: float
    fee_model: str
    basis: str
    notes: str = ""


class PricedBasket(BaseModel):
    lines: list[PricedLineOut]
    gross: float
    dispensing_fee: float
    discount: float
    levy: float
    mmap_excess: float
    claimable: float
    patient_portion: float
    scheme: Optional[str] = None
    fee_model: Optional[str] = None


class ClaimBatchCreate(BaseModel):
    pay_office_id: int
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    notes: str = ""


class BatchSettlement(BaseModel):
    amount: float
    reference: str = ""


class ClaimBatchOut(ORM):
    id: int
    batch_number: str
    pay_office_id: int
    status: str
    claim_count: int
    total_gross: float
    total_discount: float
    total_levy: float
    total_claimed: float
    total_settled: float
    period_from: Optional[datetime] = None
    period_to: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None
    reference: str = ""
    notes: str = ""
    created_at: datetime
    pay_office: Optional[PayOfficeOut] = None


class ClaimBatchDetail(BaseModel):
    batch: ClaimBatchOut
    shortfall: float
    claims: list[ClaimOut] = []


class FormularyCreate(BaseModel):
    code: str
    name: str
    default_rule: str = "covered"     # covered = open, excluded = closed
    active: bool = True
    notes: str = ""


class FormularyOut(ORM):
    id: int
    code: str
    name: str
    default_rule: str
    active: bool
    notes: str = ""


class FormularyEntryIn(BaseModel):
    product_id: int
    status: str = "covered"
    reference_price: float = 0.0
    max_quantity: int = 0
    requires_authorisation: bool = False
    note: str = ""


class FormularyEntryOut(ORM, FormularyEntryIn):
    id: int
    formulary_id: int
    product: Optional[ProductOut] = None


class CoverageAlternative(BaseModel):
    product_id: int
    name: str
    strength: str
    status: str
    unit_price: float
    saving: float


class CoverageLine(BaseModel):
    product_id: int
    product: str
    status: str
    claimable: bool
    reason: str
    reference_price: float = 0.0
    max_quantity: int = 0
    quantity_exceeded: bool = False
    requires_authorisation: bool = False
    formulary: str = ""
    alternatives: list[CoverageAlternative] = []


class CoverageReport(BaseModel):
    scheme: Optional[str] = None
    formulary: Optional[str] = None
    lines: list[CoverageLine]
    all_claimable: bool
    blocked_count: int
    authorisation_required: bool


# ---------- compounding ----------
class MixtureIngredientIn(BaseModel):
    product_id: int
    quantity: float = 1.0
    unit: str = "ml"
    note: str = ""


class MixtureIngredientOut(ORM, MixtureIngredientIn):
    id: int
    product: Optional[ProductOut] = None


class MixtureCreate(BaseModel):
    code: str
    name: str
    form: str = "mixture"
    yield_quantity: float = 1.0
    yield_unit: str = "ml"
    compounding_fee: float = 0.0
    shelf_life_days: int = 30
    method: str = ""
    directions: str = ""
    active: bool = True
    ingredients: list[MixtureIngredientIn] = []


class MixtureOut(ORM):
    id: int
    code: str
    name: str
    form: str
    yield_quantity: float
    yield_unit: str
    compounding_fee: float
    shelf_life_days: int
    method: str = ""
    directions: str = ""
    active: bool
    ingredients: list[MixtureIngredientOut] = []


# ---------- clearinghouse gateway ----------
class ClientCredentials(BaseModel):
    grant_type: str = "client_credentials"
    client_id: str
    client_secret: str


class TokenGrant(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class GatewayProvider(BaseModel):
    ahfoz_number: str
    bhasco_code: str = ""


class GatewayMember(BaseModel):
    policy_number: str
    dependent_code: str = "00"
    first_name: str = ""
    last_name: str = ""
    national_id: str = ""


class BiometricCapture(BaseModel):
    """One fingerprint impression, in transit only.

    It arrives from the till's reader, goes to the switch, and is redacted
    before anything is recorded. Nothing in RX3000 stores a template.
    """
    template: str = ""
    format: str = ""
    quality: Optional[int] = None
    finger: str = "right_index"
    device_id: str = ""


class EligibilityRequest(BaseModel):
    funder_id: str
    switch_id: str = ""
    provider: GatewayProvider
    member: GatewayMember
    biometric: Optional[BiometricCapture] = None


class BenefitDetails(BaseModel):
    global_limit: float
    available_balance: float
    co_payment_required: bool = False
    co_payment_percentage: float = 0.0


class EligibilityResponse(BaseModel):
    status: str
    transaction_id: str
    funder_response_code: str
    benefit_details: BenefitDetails
    # Present only when a print was submitted and the funder matched it.
    biometric_verification: Optional[dict] = None


class TransactionHeader(BaseModel):
    source_system: str = ""
    timestamp: Optional[datetime] = None
    switch_destination: str = ""
    funder_id: str


class ProviderDetails(BaseModel):
    ahfoz_number: str
    practice_type: str = ""
    facility_name: str = ""


class PatientDetails(BaseModel):
    policy_number: str
    dependent_code: str = "00"
    first_name: str = ""
    last_name: str = ""


class ClinicalData(BaseModel):
    primary_icd10: str
    secondary_icd10: str = ""
    referral_number: str = ""


class ClaimLine(BaseModel):
    line_number: int
    service_date: date
    tariff_code: str
    description: str = ""
    quantity: float = 1
    unit_price: float
    total_price: float


class ClaimTotals(BaseModel):
    currency: str = "USD"
    gross_amount: float


class ClaimRequest(BaseModel):
    transaction_header: TransactionHeader
    provider_details: ProviderDetails
    patient_details: PatientDetails
    clinical_data: ClinicalData
    claim_lines: list[ClaimLine]
    totals: ClaimTotals
    biometric: Optional[BiometricCapture] = None


class AdjudicationSummary(BaseModel):
    status: str
    amount_claimed: float
    amount_approved: float
    shortfall_amount: float
    rejection_reason: Optional[str] = None


class AdjudicatedLine(BaseModel):
    line_number: int
    status: str
    approved_amount: float
    msg: str = ""


class ClaimResponse(BaseModel):
    gateway_status: str
    transaction_id: str
    switch_reference: str
    funder_reference: str
    adjudication_summary: AdjudicationSummary
    adjudicated_lines: list[AdjudicatedLine]


class FunderOut(ORM):
    id: int
    funder_id: str
    name: str
    switch_id: str
    currency_code: str
    realtime: bool
    biometric_required: bool = False
    active: bool


class TariffOut(ORM):
    id: int
    tariff_code: str
    description: str
    financial_year: int
    currency_code: str
    unit_price: float
    min_price: float
    max_price: float
    practice_type: str = ""


# ---------- pre-authorisation ----------

class AuthorisationRequest(BaseModel):
    funder_id: str
    switch_id: str = ""
    patient_id: Optional[int] = None
    policy_number: str = ""
    dependent_code: str = ""
    product_id: Optional[int] = None
    description: str = ""
    icd10_code: str = ""
    motivation: str = ""
    requested_quantity: float = 0.0
    requested_amount: float = 0.0
    currency_code: str = ""


class AuthorisationUseIn(BaseModel):
    quantity: float = 0.0
    amount: float = 0.0
    reference: str = ""
    claim_id: Optional[int] = None


# ---------- remittance advice ----------

class RemittanceLineIn(BaseModel):
    line_number: int = 0
    claim_reference: str = ""
    policy_number: str = ""
    member_name: str = ""
    # Named to avoid shadowing `date` in this namespace, which would resolve the
    # annotation to Optional[None].
    service_date: Optional[date] = None
    amount_claimed: float = 0.0
    amount_allowed: float = 0.0
    amount_paid: float = 0.0
    reason_code: str = ""
    reason: str = ""


class RemittanceImport(BaseModel):
    funder_id: str
    remittance_number: str
    payment_reference: str = ""
    payment_date: Optional[date] = None
    currency_code: str = "USD"
    notes: str = ""
    lines: list[RemittanceLineIn]


class RemittanceCsvImport(BaseModel):
    funder_id: str
    remittance_number: str
    payment_reference: str = ""
    payment_date: Optional[date] = None
    currency_code: str = "USD"
    notes: str = ""
    content: str
