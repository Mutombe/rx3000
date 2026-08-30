export interface User {
  id: number;
  username: string;
  full_name: string;
  role: string;
  /** A time-limited demo account. Absent on every account in a real pharmacy. */
  is_demo?: boolean;
  /** When the demo stops working, as naive UTC from the server. */
  demo_expires_at?: string | null;
}

export interface MedicalAid {
  id: number;
  name: string;
  scheme_code: string;
  phone: string;
}

export interface Doctor {
  id: number;
  name: string;
  practice_number: string;
  phone: string;
  email: string;
}

export interface Supplier {
  id: number;
  name: string;
  contact_person: string;
  phone: string;
  email: string;
}

export interface Patient {
  id: number;
  first_name: string;
  last_name: string;
  id_number: string;
  date_of_birth: string | null;
  phone: string;
  email: string;
  address: string;
  allergies: string;
  chronic_conditions: string;
  medical_aid_id: number | null;
  medical_aid_number: string;
  dependent_code: string;
  /** Who to deal with when it is not the patient — used for reminders, delivery
   *  signatures and follow-up calls. Empty for a patient who manages their own. */
  caregiver_name: string;
  caregiver_phone: string;
  caregiver_relationship: string;
  contact_caregiver_first: boolean;
  loyalty_points: number;
  medical_aid?: MedicalAid | null;
}

export interface Product {
  /** The department it is filed under — as against `category`, which is free
   *  text for the therapeutic class. This is the one the shop is laid out by. */
  category_id?: number | null;
  id: number;
  name: string;
  nappi_code: string;
  barcode: string;
  category: string;
  schedule: number;
  dosage_form: string;
  strength: string;
  pack_size: string;
  unit_price: number;
  cost_price: number;
  vat_rate: number;
  quantity_on_hand: number;
  reorder_level: number;
  reorder_quantity: number;
  supplier_id: number | null;
  /** Shelf position and maker. Optional — a pharmacy that does not use bin
   *  locations should not be made to invent them. */
  bin_location: string;
  manufacturer: string;
  /** What the medicine actually is. The only thing that makes two products
   *  interchangeable, so it is what variants are grouped on. */
  active_ingredient: string;
  /** Published ceiling and molecule reference price, both loaded from a price
   *  file rather than typed. Zero means none is published. */
  sep_price: number;
  mmap_price: number;
  active?: boolean;
}

export interface PrescriptionItem {
  id: number;
  product_id: number;
  dosage_instructions: string;
  quantity: number;
  repeats_allowed: number;
  repeats_used: number;
  repeat_interval_days: number;
  next_repeat_date: string | null;
  auto_refill: boolean;
  product?: Product;
  prescription?: { id: number; rx_number: string; patient?: Patient };
}

export interface Prescription {
  id: number;
  rx_number: string;
  /** A draft has no Rx number — the register is a numbered sequence and an
   *  unfinished script must not consume one — so it carries a working
   *  reference instead, and its status says which it is. Both were on the
   *  model and in the response, and typed nowhere. */
  draft_ref?: string;
  status?: string;
  patient_id: number;
  doctor_id: number;
  date_prescribed: string;
  notes: string;
  items: PrescriptionItem[];
  patient?: Patient;
  doctor?: Doctor;
}

export interface Claim {
  id: number;
  claim_number: string;
  amount_claimed: number;
  amount_approved: number;
  patient_liable: number;
  status: string;
  response_message: string;
}

export interface SaleItem {
  id: number;
  product_id: number;
  description: string;
  quantity: number;
  unit_price: number;
  vat_rate: number;
  line_total: number;
}

export interface Sale {
  id: number;
  sale_number: string;
  patient_id: number | null;
  created_at: string;
  subtotal: number;
  vat_amount: number;
  total: number;
  payment_method: string;
  amount_tendered: number;
  change_due: number;
  loyalty_points_earned: number;
  loyalty_points_redeemed: number;
  status: string;
  card_auth_code: string;
  card_reference: string;
  card_last4: string;
  card_scheme: string;
  terminal_id: string;
  card_batch: string;
  /** When this sale was moved onto the customer's account. It stays `pending`
   *  either way — transferred means it has moved from money expected at the
   *  door to money owed on an account, not that it has been paid. */
  transferred_at?: string | null;
  items: SaleItem[];
  claim?: Claim | null;
  patient?: Patient | null;
}

export interface StockBatch {
  id: number;
  product_id: number;
  batch_number: string;
  expiry_date: string | null;
  quantity_received: number;
  quantity_remaining: number;
  unit_cost: number;
  reference: string;
  received_at: string;
  product?: Product;
}

export interface StockMovement {
  id: number;
  product_id: number;
  movement_type: string;
  quantity_delta: number;
  balance_after: number;
  reference: string;
  notes: string;
  created_at: string;
  product?: Product;
}

export interface POItem {
  id: number;
  product_id: number;
  quantity_ordered: number;
  quantity_received: number;
  unit_cost: number;
  product?: Product;
}

export interface PurchaseOrder {
  id: number;
  order_number: string;
  supplier_id: number;
  status: string;
  created_at: string;
  received_at: string | null;
  notes: string;
  items: POItem[];
  supplier?: Supplier;
}

export interface RegisterEntry {
  id: number;
  schedule: number;
  entry_type: string;
  quantity_delta: number;
  balance_after: number;
  reference: string;
  created_at: string;
  product?: Product;
  patient?: Patient | null;
  doctor?: Doctor | null;
}

export interface Message {
  id: number;
  patient_id: number;
  channel: string;
  message_type: string;
  subject: string;
  body: string;
  status: string;
  detail: string;
  scheduled_for: string;
  sent_at: string | null;
  patient?: Patient;
}

export interface Shift {
  id: number;
  user_id: number;
  opened_at: string;
  closed_at: string | null;
  opening_float: number;
  counted_cash: number;
  expected_cash: number;
  variance: number;
  card_total: number;
  medical_aid_total: number;
  sales_count: number;
  notes: string;
  status: string;
  /** Till / Run / Draw. Runs are numbered per till, so a run number only means
   *  something alongside its till. Pre-existing shifts have no till and run 0. */
  till_no: string;
  run_number: number;
  draw_no: string;
  user?: User;
}

export interface AuditEntry {
  id: number;
  username: string;
  action: string;
  path: string;
  summary: string;
  status_code: number;
  ip_address: string;
  created_at: string;
}

export interface PriceImportLine {
  row: number;
  key: string;
  product_name: string;
  matched: boolean;
  old_cost: number | null;
  new_cost: number | null;
  old_price: number | null;
  new_price: number | null;
  /** Published ceiling and molecule reference price. Separate from the selling
   *  price because they are a different decision — the most the pharmacy may
   *  charge, not what it does charge. */
  old_sep: number | null;
  new_sep: number | null;
  old_mmap: number | null;
  new_mmap: number | null;
  message: string;
}

export interface PriceImportResult {
  applied: boolean;
  total_rows: number;
  matched: number;
  unmatched: number;
  updated: number;
  lines: PriceImportLine[];
}

export interface Backup {
  filename: string;
  size_bytes: number;
  created_at: string;
  /** Opened and proven restorable, not merely written. */
  verified: boolean;
  checked_at: string | null;
  problem: string;
}

export interface Label {
  patient_name: string;
  patient_id_number: string;
  rx_number: string;
  product_name: string;
  strength: string;
  dosage_form: string;
  quantity: number;
  dosage_instructions: string;
  warnings: string;
  schedule: number;
  batch_number: string;
  expiry_date: string | null;
  repeats_remaining: number;
  next_repeat_date: string | null;
  doctor_name: string;
  dispensed_by: string;
  dispensed_at: string;
  pharmacy_name: string;
  pharmacy_reg_no: string;
  /** Printed at the foot of the sticker and in the audit block, so a patient
   *  holding the box has the shop, the script and which item of how many. */
  pharmacy_address: string;
  pharmacy_phone: string;
  item_number: number;
  item_count: number;
  doctor_practice_no: string;
  unit_price: number;
  line_total: number;
  /** The shop that handed it over. On a chain this is not the company on the
   *  licence, and it is the number a patient rings about their box. */
  branch_code: string;
  branch_name: string;
  branch_address: string;
  branch_phone: string;
  branch_reg_no: string;
  dispensing_id: number | null;
}

export interface SchedulePolicy {
  schedule: number;
  label: string;
  route: string;
  requires_prescription: boolean;
  requires_pharmacist: boolean;
  register_entry: boolean;
  max_repeats: number;
  max_repeat_months: number;
  requires_id_verification: boolean;
  requires_script_sighted: boolean;
  requires_prescriber_verification: boolean;
  requires_witness: boolean;
  counselling_required: boolean;
  notes: string;
}

export interface OTCSale {
  id: number;
  product_id: number;
  quantity: number;
  schedule: number;
  patient_id: number | null;
  customer_name: string;
  indication: string;
  counselling_given: boolean;
  referred_to_doctor: boolean;
  notes: string;
  sale_id: number | null;
  created_at: string;
  product?: Product;
  patient?: Patient | null;
  pharmacist?: User | null;
}

export interface ControlledDispensing {
  id: number;
  quantity: number;
  dispensed_at: string;
  is_repeat: boolean;
  dispense_type: string;
  schedule: number;
  id_verified: boolean;
  id_number_seen: string;
  script_sighted: boolean;
  prescriber_verified: boolean;
  compliance_notes: string;
  /** Initials of the pharmacist who checked it. Replaced the witness; `witness`
   *  remains only so rows recorded before the change still display one. */
  pharmacist_initial: string;
  dispensed_by?: User | null;
  witness?: User | null;
}

// ===== CRM =====
export interface Company {
  id: number;
  name: string;
  account_type: string;
  phone: string;
  email: string;
  address: string;
  vat_number: string;
  credit_terms_days: number;
  owner_id: number | null;
  status: string;
  notes: string;
  created_at: string;
  owner?: User | null;
}

export interface CompanyLite {
  id: number;
  name: string;
  account_type: string;
}

export interface ContactLite {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
}

export interface Contact {
  id: number;
  first_name: string;
  last_name: string;
  job_title: string;
  email: string;
  phone: string;
  company_id: number | null;
  patient_id: number | null;
  lifecycle_stage: string;
  source: string;
  owner_id: number | null;
  marketing_opt_in: boolean;
  notes: string;
  created_at: string;
  company?: CompanyLite | null;
  owner?: User | null;
}

export interface Deal {
  id: number;
  title: string;
  company_id: number | null;
  contact_id: number | null;
  value: number;
  stage: string;
  probability: number;
  expected_close_date: string | null;
  owner_id: number | null;
  source: string;
  notes: string;
  lost_reason: string;
  created_at: string;
  closed_at: string | null;
  company?: CompanyLite | null;
  contact?: ContactLite | null;
  owner?: User | null;
  items: DealItem[];
}

export interface Activity {
  id: number;
  activity_type: string;
  subject: string;
  body: string;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
  company_id: number | null;
  contact_id: number | null;
  deal_id: number | null;
  ticket_id: number | null;
  patient_id: number | null;
  owner?: User | null;
  company?: CompanyLite | null;
  contact?: ContactLite | null;
}

export interface Segment {
  key: string;
  label: string;
  description: string;
  size: number;
}

export interface Campaign {
  id: number;
  name: string;
  channel: string;
  segment: string;
  subject: string;
  body: string;
  status: string;
  audience_size: number;
  sent_count: number;
  failed_count: number;
  created_at: string;
  sent_at: string | null;
  created_by?: User | null;
}

export interface TicketMessage {
  id: number;
  from_customer: boolean;
  internal_note: boolean;
  body: string;
  created_at: string;
  author?: User | null;
}

export interface Ticket {
  id: number;
  ticket_number: string;
  subject: string;
  description: string;
  category: string;
  priority: string;
  status: string;
  channel: string;
  patient_id: number | null;
  created_at: string;
  due_at: string | null;
  first_response_at: string | null;
  resolved_at: string | null;
  satisfaction: number | null;
  patient?: Patient | null;
  contact?: ContactLite | null;
  company?: CompanyLite | null;
  assigned_to?: User | null;
  messages: TicketMessage[];
}

export interface Lead {
  id: number;
  first_name: string;
  last_name: string;
  company_name: string;
  job_title: string;
  email: string;
  phone: string;
  source: string;
  status: string;
  rating: string;
  score: number;
  estimated_value: number;
  interest: string;
  owner_id: number | null;
  campaign_id: number | null;
  marketing_opt_in: boolean;
  disqualified_reason: string;
  converted_at: string | null;
  converted_company_id: number | null;
  converted_contact_id: number | null;
  converted_deal_id: number | null;
  created_at: string;
  owner?: User | null;
}

export interface CompanyOverview {
  company: {
    id: number; name: string; account_type: string; status: string;
    phone: string; email: string; address: string;
    credit_terms_days: number; notes: string; owner: string | null;
  };
  contacts: { id: number; name: string; job_title: string; email: string; phone: string; lifecycle_stage: string }[];
  deals: { id: number; title: string; value: number; stage: string; probability: number; expected_close_date: string | null }[];
  tickets: { id: number; ticket_number: string; subject: string; status: string; priority: string; created_at: string }[];
  totals: { open_pipeline: number; won_value: number; open_tickets: number; contacts: number };
}

export interface CoverageAlternative {
  product_id: number;
  name: string;
  strength: string;
  status: string;
  unit_price: number;
  saving: number;
}

export interface CoverageLine {
  product_id: number;
  product: string;
  status: string;
  claimable: boolean;
  reason: string;
  reference_price: number;
  max_quantity: number;
  quantity_exceeded: boolean;
  requires_authorisation: boolean;
  formulary: string;
  alternatives: CoverageAlternative[];
}

export interface CoverageReport {
  scheme: string | null;
  formulary: string | null;
  lines: CoverageLine[];
  all_claimable: boolean;
  blocked_count: number;
  authorisation_required: boolean;
}

export interface DiagnosisCode {
  id: number;
  code: string;
  description: string;
  chapter: string;
  valid_primary: boolean;
}

export interface CurrencyOption {
  code: string;
  symbol: string;
  decimals: number;
  rate: number;
  is_base: boolean;
}

export interface CurrencyState {
  base: string;
  currencies: CurrencyOption[];
  multi_currency: boolean;
}

export interface ShiftTakingsBucket {
  currency: string;
  cash: number;
  card: number;
  mobile_money: number;
  medical_aid: number;
  other: number;
  total: number;
  in_base: number;
  is_base: boolean;
  opening_float: number;
  expected_cash: number;
}

export interface ShiftTakings {
  shift_id: number;
  base_currency: string;
  sales_count: number;
  currencies: ShiftTakingsBucket[];
  /** What the money actually came in on — the wallet, the bank — rather than
   *  the method alone. A teller's own sheet has a column per instrument. */
  instruments?: {
    method: string; instrument: string; currency: string;
    amount: number; in_base: number; count: number;
  }[];
}

export interface ReconMatch {
  sale_id: number; sale_number: string; sale_total: number;
  statement_amount: number; difference: number; matched_on: string;
  auth_code: string; reference: string; statement_line: number; created_at: string;
}

export interface ReconStatementLine {
  line: number; auth_code: string; reference: string; amount: number;
  txn_date: string | null; last4: string; terminal: string; batch: string;
}

export interface ReconUnbanked {
  sale_id: number; sale_number: string; sale_total: number;
  auth_code: string; reference: string; terminal_id: string; created_at: string;
}

export interface CardReconciliationReport {
  statement_lines: number; card_sales: number;
  statement_total: number; system_total: number; variance: number;
  matched: ReconMatch[]; mismatched: ReconMatch[];
  missing_in_system: ReconStatementLine[]; missing_in_statement: ReconUnbanked[];
  weak_matches: number; warnings: string[];
}

export interface ProductDetail {
  product: Product;
  batches: StockBatch[];
  movements: StockMovement[];
  units_dispensed: number;
  units_sold: number;
  stock_value: number;
}

export interface LeadScoreFactor {
  label: string;
  points: number;
  max: number;
  group: string;
}

export interface LeadScoreExplanation {
  score: number;
  raw_score: number;
  rating: string;
  capped: boolean;
  factors: LeadScoreFactor[];
}

export interface DuplicateWarning {
  field: string;
  value: string;
  existing_type: string;
  existing_id: number;
  existing_label: string;
}

export interface DealItem {
  id: number;
  product_id: number | null;
  description: string;
  quantity: number;
  unit_price: number;
  discount_percent: number;
  line_total: number;
  product?: Product;
}

export interface Quote {
  id: number;
  quote_number: string;
  deal_id: number;
  version: number;
  status: string;
  valid_until: string | null;
  subtotal: number;
  vat_amount: number;
  total: number;
  terms: string;
  created_at: string;
  sent_at: string | null;
  decided_at: string | null;
  created_by?: User | null;
}

export interface EmailTemplate {
  id: number;
  name: string;
  category: string;
  channel: string;
  subject: string;
  body: string;
  created_at: string;
}

export interface AutomationRule {
  id: number;
  name: string;
  rule_type: string;
  trigger_field: string;
  trigger_value: string;
  action: string;
  action_value: string;
  active: boolean;
  sort_order: number;
  times_fired: number;
  created_at: string;
}

export interface TimelineEntry {
  id: number;
  type: string;
  subject: string;
  body: string;
  owner: string | null;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface AccountOverview {
  company: {
    id: number; name: string; account_type: string; status: string;
    phone: string; email: string; address: string;
    credit_terms_days: number; notes: string; owner: string | null;
  };
  contacts: { id: number; name: string; job_title: string; email: string; phone: string; lifecycle_stage: string }[];
  deals: { id: number; title: string; value: number; stage: string; probability: number; expected_close_date: string | null }[];
  tickets: { id: number; ticket_number: string; subject: string; status: string; priority: string; created_at: string }[];
  totals: { open_pipeline: number; won_value: number; open_tickets: number; contacts: number };
}

export interface ForecastMonth {
  month: string;
  open_value: number;
  weighted_value: number;
  won_value: number;
  deals: number;
}

export interface FunnelReport {
  stages: { stage: string; count: number; conversion: number }[];
  disqualified: number;
  lead_to_customer_rate: number;
}

export interface OwnerReport {
  user_id: number;
  name: string;
  role: string;
  open_deals: number;
  pipeline_value: number;
  weighted_value: number;
  won_value: number;
  won_count: number;
  win_rate: number;
  open_leads: number;
  open_tickets: number;
  overdue_tasks: number;
}

export interface CampaignROI {
  campaign_id: number;
  name: string;
  channel: string;
  segment: string;
  sent: number;
  leads: number;
  converted_leads: number;
  opportunities: number;
  pipeline_value: number;
  won_value: number;
  response_rate: number;
}

export interface CrmDashboard {
  pipeline_value: number;
  weighted_value: number;
  open_deals: number;
  won_value: number;
  won_count: number;
  win_rate: number;
  by_stage: { stage: string; count: number; value: number }[];
  companies: number;
  contacts: number;
  leads: number;
  open_tickets: number;
  sla_breached: number;
  my_open_tasks: number;
  marketable_patients: number;
  open_leads: number;
  hot_leads: number;
  converted_leads: number;
}

export interface HelpdeskStats {
  open: number;
  awaiting_first_response: number;
  sla_breached: number;
  due_within_2h: number;
  resolved_total: number;
  avg_first_response_mins: number | null;
  avg_resolution_hours: number | null;
  csat: number | null;
  by_priority: Record<string, number>;
  by_category: Record<string, number>;
  sla_hours: Record<string, number>;
}

export interface Dashboard {
  sales_today_count: number;
  sales_today_total: number;
  scripts_today: number;
  low_stock_count: number;
  repeats_due_count: number;
  pending_sales: number;
  messages_pending: number;
  expiring_soon_count: number;
  week_sales: { day: string; total: number }[];
  currency: string;
  pharmacy_name: string;
}
