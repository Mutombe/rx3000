"""First-run seed: users, medical aids, doctors, suppliers, and a realistic
product catalogue (medicines across schedules, front shop, airtime)."""
import logging
from datetime import date

from sqlalchemy.orm import Session

from .auth import hash_password
from .models import Doctor, MedicalAid, Patient, Product, Supplier, User

log = logging.getLogger("rx3000.seed")


def seed_crm_if_empty(db: Session) -> None:
    """CRM demo data — runs independently so existing databases get it too."""
    from .models import Company
    if not db.query(Company).count():
        log.info("Seeding CRM data...")
        _seed_crm(db)
        db.commit()
    seed_sales_crm_if_empty(db)


def seed_sales_crm_if_empty(db: Session) -> None:
    """Leads, automation rules and email templates (Salesforce-grade layer)."""
    from datetime import timedelta

    from .models import AutomationRule, EmailTemplate, Lead
    from .services import automation

    admin = db.query(User).filter(User.username == "admin").first()
    pharmacist = db.query(User).filter(User.username == "pharmacist").first()
    if admin is None:
        return

    if not db.query(AutomationRule).count():
        log.info("Seeding CRM automation rules...")
        db.add_all([
            AutomationRule(name="Route referral leads to the owner", rule_type="lead_assignment",
                           trigger_field="source", trigger_value="referral",
                           action="assign", action_value=str(admin.id), sort_order=10),
            AutomationRule(name="Route website leads to the pharmacist", rule_type="lead_assignment",
                           trigger_field="source", trigger_value="web",
                           action="assign", action_value=str(pharmacist.id), sort_order=20),
            AutomationRule(name="Catch-all lead assignment", rule_type="lead_assignment",
                           action="assign", action_value=str(admin.id), sort_order=999),
            AutomationRule(name="Boost tender enquiries", rule_type="lead_scoring",
                           trigger_field="source", trigger_value="event",
                           action="score", action_value="10", sort_order=10),
            AutomationRule(name="Script issues go to the pharmacist", rule_type="ticket_assignment",
                           trigger_field="category", trigger_value="script_issue",
                           action="assign", action_value=str(pharmacist.id), sort_order=10),
            AutomationRule(name="Complaints go to the manager", rule_type="ticket_assignment",
                           trigger_field="category", trigger_value="complaint",
                           action="assign", action_value=str(admin.id), sort_order=20),
            AutomationRule(name="Escalate breached urgent tickets", rule_type="ticket_escalation",
                           trigger_field="priority", trigger_value="high",
                           action="escalate", action_value="urgent", sort_order=10),
            AutomationRule(name="Task on entering Proposal", rule_type="deal_task",
                           trigger_field="stage", trigger_value="proposal",
                           action="create_task", action_value="Prepare and send the proposal document",
                           sort_order=10),
        ])

    if not db.query(EmailTemplate).count():
        db.add_all([
            EmailTemplate(name="Repeat due reminder", category="campaign", channel="sms",
                          body="Hi {first_name}, your repeat is due. Reply or pop in and we'll have it ready. - {pharmacy}",
                          created_by_id=admin.id),
            EmailTemplate(name="Flu vaccination drive", category="campaign", channel="sms",
                          body="Hi {first_name}, flu vaccines are in stock at {pharmacy}. Walk in any weekday 08:00-17:00.",
                          created_by_id=admin.id),
            EmailTemplate(name="Loyalty points balance", category="campaign", channel="sms",
                          body="Hi {first_name}, you have {points} loyalty points to spend at {pharmacy}. See you soon!",
                          created_by_id=admin.id),
            EmailTemplate(name="Ticket acknowledgement", category="ticket", channel="email",
                          subject="We have received your query",
                          body="Good day,\n\nThank you for contacting us. We are looking into this and will "
                               "come back to you shortly.\n\nKind regards\nThe pharmacy team",
                          created_by_id=admin.id),
            EmailTemplate(name="Corporate proposal cover", category="deal", channel="email",
                          subject="Proposal from your pharmacy partner",
                          body="Good day,\n\nPlease find our proposal attached. We have based the pricing on "
                               "the volumes we discussed and it is valid for 30 days.\n\nKind regards",
                          created_by_id=admin.id),
        ])

    if not db.query(Lead).count():
        log.info("Seeding leads...")
        leads = [
            Lead(first_name="Refilwe", last_name="Mokoena", company_name="Bright Futures Creche",
                 job_title="Principal", email="refilwe@brightfutures.example", phone="0824441122",
                 source="referral", interest="First-aid kits and monthly consumables for 3 branches.",
                 estimated_value=42000, marketing_opt_in=True),
            Lead(first_name="Piet", last_name="van Zyl", company_name="Highveld Logistics",
                 job_title="HR Director", email="piet@highveld.example", phone="0833335566",
                 source="event", interest="Driver wellness screening and chronic medication delivery for 300 staff.",
                 estimated_value=185000, marketing_opt_in=True),
            Lead(first_name="Zanele", last_name="Dlamini", company_name="",
                 job_title="", email="zanele.d@example.com", phone="0768889900",
                 source="web", interest="Asked about compounding services for a skin preparation.",
                 estimated_value=3500),
            Lead(first_name="Ahmed", last_name="Patel", company_name="Sunrise Retirement Village",
                 job_title="Finance Manager", email="finance@sunrise.example", phone="0115554401",
                 source="referral", interest="Wants a second quote on the blister-pack renewal.",
                 estimated_value=48000, marketing_opt_in=True),
            Lead(first_name="Grace", last_name="Nkosi", company_name="Nkosi Family Practice",
                 job_title="Practice Manager", email="grace@nkosipractice.example", phone="0117778899",
                 source="walk_in", interest="Enquired about a delivery arrangement for their patients.",
                 estimated_value=12000),
        ]
        for lead in leads:
            db.add(lead)
            db.flush()
            automation.score_lead(db, lead)
            automation.assign_lead(db, lead)
            if lead.owner_id is None:
                lead.owner_id = admin.id
        db.flush()
        leads[1].status = "working"
        leads[2].status = "nurturing"

    db.commit()


def seed(db: Session) -> None:
    if db.query(User).count():
        return
    log.info("Seeding initial data...")

    db.add_all([
        User(username="admin", password_hash=hash_password("admin123"), full_name="System Administrator", role="admin"),
        User(username="pharmacist", password_hash=hash_password("pharm123"), full_name="T. Moyo (Pharmacist)", role="pharmacist"),
        User(username="cashier", password_hash=hash_password("cash123"), full_name="L. Dube (Cashier)", role="cashier"),
    ])

    aids = [
        MedicalAid(name="Discovery Health", scheme_code="DISC", phone="0860 998 877"),
        MedicalAid(name="Bonitas", scheme_code="BON", phone="0860 002 108"),
        MedicalAid(name="GEMS", scheme_code="GEMS", phone="0860 004 367"),
        MedicalAid(name="Momentum Health", scheme_code="MOM", phone="0860 117 859"),
    ]
    db.add_all(aids)

    db.add_all([
        Doctor(name="Dr. S. Naidoo", practice_number="MP0451234", phone="011 555 0101"),
        Doctor(name="Dr. K. van der Merwe", practice_number="MP0567890", phone="012 555 0202"),
        Doctor(name="Dr. A. Chikwava", practice_number="MP0612345", phone="011 555 0303"),
    ])

    suppliers = [
        Supplier(name="UPD (United Pharmaceutical Distributors)", contact_person="Orders Desk", phone="011 555 1000", email="orders@upd.example"),
        Supplier(name="Transpharm", contact_person="Sales", phone="012 555 2000", email="orders@transpharm.example"),
        Supplier(name="CJ Distribution", contact_person="Accounts", phone="011 555 3000", email="sales@cjd.example"),
    ]
    db.add_all(suppliers)
    db.flush()
    upd, trans, cjd = suppliers

    def med(name, strength, form, schedule, price, cost, qty, supplier, nappi, barcode, pack=""):
        return Product(
            name=name, strength=strength, dosage_form=form, schedule=schedule,
            unit_price=price, cost_price=cost, quantity_on_hand=qty,
            supplier_id=supplier.id, nappi_code=nappi, barcode=barcode,
            pack_size=pack, category="medicine", reorder_level=15, reorder_quantity=30,
        )

    db.add_all([
        med("Paracetamol", "500mg", "Tablets", 0, 24.95, 14.50, 120, upd, "701985", "6001234500017", "24s"),
        med("Ibuprofen", "400mg", "Tablets", 1, 45.50, 26.00, 80, upd, "702114", "6001234500024", "30s"),
        med("Amoxicillin", "500mg", "Capsules", 4, 89.90, 48.00, 60, upd, "703220", "6001234500031", "15s"),
        med("Amoxicillin/Clavulanate", "875/125mg", "Tablets", 4, 189.00, 110.00, 40, upd, "703445", "6001234500048", "14s"),
        med("Atorvastatin", "20mg", "Tablets", 3, 145.00, 82.00, 55, trans, "704112", "6001234500055", "30s"),
        med("Amlodipine", "5mg", "Tablets", 3, 98.00, 52.00, 70, trans, "704334", "6001234500062", "30s"),
        med("Metformin", "850mg", "Tablets", 3, 76.50, 38.00, 90, trans, "704556", "6001234500079", "60s"),
        med("Losartan", "50mg", "Tablets", 3, 112.00, 61.00, 45, trans, "704778", "6001234500086", "30s"),
        med("Salbutamol Inhaler", "100mcg", "Inhaler", 2, 135.00, 78.00, 35, upd, "705110", "6001234500093", "200 doses"),
        med("Cetirizine", "10mg", "Tablets", 1, 52.00, 27.00, 65, upd, "705332", "6001234500109", "30s"),
        med("Omeprazole", "20mg", "Capsules", 3, 88.00, 45.00, 50, cjd, "705554", "6001234500116", "28s"),
        med("Tramadol", "50mg", "Capsules", 5, 96.00, 51.00, 40, cjd, "706001", "6001234500123", "20s"),
        med("Zolpidem", "10mg", "Tablets", 5, 124.00, 68.00, 30, cjd, "706223", "6001234500130", "14s"),
        med("Morphine Sulphate", "10mg", "Tablets", 6, 210.00, 118.00, 20, cjd, "706445", "6001234500147", "20s"),
        med("Methylphenidate", "10mg", "Tablets", 6, 285.00, 160.00, 25, cjd, "706667", "6001234500154", "30s"),
        med("Fluoxetine", "20mg", "Capsules", 5, 105.00, 55.00, 8, trans, "706889", "6001234500161", "30s"),
    ])

    db.add_all([
        Product(name="Vitamin C Effervescent", strength="1000mg", category="front_shop", unit_price=79.95, cost_price=42.00,
                quantity_on_hand=48, supplier_id=cjd.id, barcode="6009876500011", reorder_level=12, reorder_quantity=24),
        Product(name="Plasters Assorted", category="front_shop", unit_price=32.50, cost_price=16.00,
                quantity_on_hand=60, supplier_id=cjd.id, barcode="6009876500028", reorder_level=15, reorder_quantity=30),
        Product(name="Baby Wipes 80s", category="front_shop", unit_price=45.00, cost_price=24.00,
                quantity_on_hand=40, supplier_id=cjd.id, barcode="6009876500035", reorder_level=10, reorder_quantity=20),
        Product(name="Sunscreen SPF50", strength="", category="front_shop", unit_price=129.00, cost_price=70.00,
                quantity_on_hand=25, supplier_id=cjd.id, barcode="6009876500042", reorder_level=8, reorder_quantity=16),
        Product(name="Vodacom Airtime R29", category="airtime", unit_price=29.00, cost_price=27.55,
                quantity_on_hand=999, barcode="AIRVOD29", vat_rate=0.15, reorder_level=0),
        Product(name="MTN Airtime R30", category="airtime", unit_price=30.00, cost_price=28.50,
                quantity_on_hand=999, barcode="AIRMTN30", vat_rate=0.15, reorder_level=0),
        Product(name="Telkom Airtime R50", category="airtime", unit_price=50.00, cost_price=47.50,
                quantity_on_hand=999, barcode="AIRTEL50", vat_rate=0.15, reorder_level=0),
    ])
    db.flush()

    db.add_all([
        Patient(first_name="Nomsa", last_name="Khumalo", id_number="8203150123081", date_of_birth=date(1982, 3, 15),
                phone="0821234567", email="nomsa.k@example.com", allergies="Penicillin",
                chronic_conditions="Hypertension, Type 2 Diabetes",
                medical_aid_id=aids[0].id, medical_aid_number="123456789", dependent_code="00"),
        Patient(first_name="Johan", last_name="Botha", id_number="7511205045089", date_of_birth=date(1975, 11, 20),
                phone="0837654321", email="johan.b@example.com", allergies="",
                chronic_conditions="Hyperlipidaemia",
                medical_aid_id=aids[1].id, medical_aid_number="987654321", dependent_code="00"),
        Patient(first_name="Thandi", last_name="Mabaso", id_number="9007080234082", date_of_birth=date(1990, 7, 8),
                phone="0619876543", email="thandi.m@example.com", allergies="Sulpha drugs",
                chronic_conditions="Asthma"),
    ])

    db.commit()
    log.info("Seed complete")


def _seed_crm(db: Session) -> None:
    """Corporate accounts, contacts, an open pipeline and live tickets."""
    from datetime import datetime, timedelta

    from .models import Activity, Company, Contact, Deal, Patient, Ticket, TicketMessage

    admin = db.query(User).filter(User.username == "admin").first()
    pharmacist = db.query(User).filter(User.username == "pharmacist").first()

    companies = [
        Company(name="Sunrise Retirement Village", account_type="old_age_home",
                phone="011 555 4400", email="matron@sunrise.example",
                address="12 Rose Ave, Randburg", credit_terms_days=30,
                owner_id=admin.id, status="active",
                notes="120 residents. Monthly blister-pack supply. Matron prefers Monday deliveries."),
        Company(name="Kopano Mining Occupational Health", account_type="employer",
                phone="013 555 7788", email="ohs@kopano.example",
                address="Mine Road, Witbank", credit_terms_days=45,
                owner_id=admin.id, status="prospect",
                notes="1 400 employees. Tendering for annual flu vaccination and chronic screening."),
        Company(name="Little Steps Paediatric Clinic", account_type="clinic",
                phone="011 555 2211", email="admin@littlesteps.example",
                address="Fourways Life Centre", credit_terms_days=30,
                owner_id=pharmacist.id, status="active",
                notes="Refers scripts daily. Wants a courier slot before 10:00."),
    ]
    db.add_all(companies)
    db.flush()
    sunrise, kopano, little_steps = companies

    contacts = [
        Contact(first_name="Elaine", last_name="Fourie", job_title="Matron",
                email="matron@sunrise.example", phone="0825551200", company_id=sunrise.id,
                lifecycle_stage="customer", source="referral", owner_id=admin.id, marketing_opt_in=True),
        Contact(first_name="Sipho", last_name="Ndlovu", job_title="Occupational Health Manager",
                email="ohs@kopano.example", phone="0835557788", company_id=kopano.id,
                lifecycle_stage="qualified", source="event", owner_id=admin.id, marketing_opt_in=True,
                notes="Met at the Mine Health Expo. Budget approved for Q4."),
        Contact(first_name="Dr Anita", last_name="Reddy", job_title="Practice Owner",
                email="admin@littlesteps.example", phone="0845552211", company_id=little_steps.id,
                lifecycle_stage="customer", source="walk_in", owner_id=pharmacist.id, marketing_opt_in=False),
        Contact(first_name="Marius", last_name="Steyn", job_title="Procurement Officer",
                email="marius@corpwell.example", phone="0715559090",
                lifecycle_stage="lead", source="website", owner_id=admin.id, marketing_opt_in=True,
                notes="Enquired about a corporate wellness day for 200 staff."),
    ]
    db.add_all(contacts)
    db.flush()

    today = date.today()
    deals = [
        Deal(title="Sunrise — monthly blister-pack supply renewal", company_id=sunrise.id,
             contact_id=contacts[0].id, value=48000, stage="negotiation", probability=75,
             expected_close_date=today + timedelta(days=14), owner_id=admin.id, source="renewal",
             notes="12-month renewal. They want a 4% discount for annual prepayment."),
        Deal(title="Kopano — annual flu vaccination programme", company_id=kopano.id,
             contact_id=contacts[1].id, value=126000, stage="proposal", probability=55,
             expected_close_date=today + timedelta(days=30), owner_id=admin.id, source="tender",
             notes="1 400 employees at R90 per vaccination. Tender closes month-end."),
        Deal(title="Little Steps — courier script delivery contract", company_id=little_steps.id,
             contact_id=contacts[2].id, value=18000, stage="qualified", probability=30,
             expected_close_date=today + timedelta(days=45), owner_id=pharmacist.id, source="referral"),
        Deal(title="CorpWell — corporate wellness day", contact_id=contacts[3].id,
             value=35000, stage="new", probability=10,
             expected_close_date=today + timedelta(days=60), owner_id=admin.id, source="website"),
        Deal(title="Sunrise — chronic medication review service", company_id=sunrise.id,
             contact_id=contacts[0].id, value=22000, stage="won", probability=100,
             expected_close_date=today - timedelta(days=10), owner_id=admin.id, source="upsell",
             closed_at=datetime.utcnow() - timedelta(days=10)),
    ]
    db.add_all(deals)
    db.flush()

    db.add_all([
        Activity(activity_type="call", subject="Discuss renewal discount with matron",
                 body="Agreed to send revised quote with 4% annual-prepayment discount.",
                 owner_id=admin.id, company_id=sunrise.id, contact_id=contacts[0].id,
                 deal_id=deals[0].id, completed_at=datetime.utcnow() - timedelta(days=2)),
        Activity(activity_type="task", subject="Submit Kopano tender documents",
                 body="Attach BEE certificate, pricing schedule and cold-chain policy.",
                 due_at=datetime.utcnow() + timedelta(days=3), owner_id=admin.id,
                 company_id=kopano.id, deal_id=deals[1].id),
        Activity(activity_type="meeting", subject="Site visit — Little Steps courier slots",
                 due_at=datetime.utcnow() + timedelta(days=5), owner_id=pharmacist.id,
                 company_id=little_steps.id, deal_id=deals[2].id),
    ])

    patients = db.query(Patient).order_by(Patient.id).all()
    tickets = [
        Ticket(ticket_number="TKT260800001", subject="Repeat not ready for collection",
               description="I came in this morning and my chronic repeat had not been prepared.",
               category="script_issue", priority="high", status="open", channel="walk_in",
               patient_id=patients[0].id if patients else None, assigned_to_id=pharmacist.id,
               created_by_id=admin.id, created_at=datetime.utcnow() - timedelta(hours=3),
               due_at=datetime.utcnow() + timedelta(hours=5)),
        Ticket(ticket_number="TKT260800002", subject="Query on medical aid co-payment",
               description="My scheme says they paid in full but I was charged a levy of R26.78.",
               category="complaint", priority="normal", status="pending", channel="phone",
               patient_id=patients[1].id if len(patients) > 1 else None, assigned_to_id=admin.id,
               created_by_id=admin.id, created_at=datetime.utcnow() - timedelta(hours=20),
               due_at=datetime.utcnow() + timedelta(hours=4),
               first_response_at=datetime.utcnow() - timedelta(hours=18)),
        Ticket(ticket_number="TKT260800003", subject="Delivery to Sunrise arrived late",
               description="The Monday blister-pack delivery reached us after 16:00.",
               category="delivery", priority="urgent", status="open", channel="email",
               company_id=sunrise.id, contact_id=contacts[0].id, assigned_to_id=admin.id,
               created_by_id=admin.id, created_at=datetime.utcnow() - timedelta(hours=9),
               due_at=datetime.utcnow() - timedelta(hours=5)),  # SLA breached on purpose
        Ticket(ticket_number="TKT260800004", subject="Thank you for the flu vaccine service",
               description="Excellent service from your team.", category="query", priority="low",
               status="resolved", channel="web", assigned_to_id=pharmacist.id, created_by_id=admin.id,
               created_at=datetime.utcnow() - timedelta(days=4),
               due_at=datetime.utcnow() - timedelta(days=1),
               first_response_at=datetime.utcnow() - timedelta(days=4) + timedelta(minutes=25),
               resolved_at=datetime.utcnow() - timedelta(days=3), satisfaction=5),
    ]
    db.add_all(tickets)
    db.flush()

    db.add_all([
        TicketMessage(ticket_id=tickets[0].id, from_customer=True,
                      body="I came in this morning and my chronic repeat had not been prepared."),
        TicketMessage(ticket_id=tickets[1].id, from_customer=True,
                      body="My scheme says they paid in full but I was charged a levy of R26.78."),
        TicketMessage(ticket_id=tickets[1].id, author_id=admin.id,
                      body="Thank you for flagging this — I am requesting the remittance advice "
                           "from the scheme and will confirm within one working day."),
        TicketMessage(ticket_id=tickets[2].id, from_customer=True,
                      body="The Monday blister-pack delivery reached us after 16:00."),
    ])


def seed_claiming_if_empty(db):
    """Reference data for claiming: pay offices, fee models and ICD-10.

    The fee bands below are illustrative placeholders shaped like a real
    regulated schedule — they are NOT the gazetted figures. Load the actual
    bands for the jurisdiction before claiming against them.
    """
    from .models import DiagnosisCode, FeeModel, FeeTier, MedicalAid, PayOffice

    if db.query(PayOffice).count() == 0:
        offices = [
            PayOffice(code="CIMAS", name="CIMAS Medical Aid Society", submission="realtime",
                      phone="+263 4 700 000"),
            PayOffice(code="PSMAS", name="Premier Service Medical Aid Society"),
            PayOffice(code="FIRSTMUT", name="First Mutual Health"),
            PayOffice(code="PRIVATE", name="Private / cash patients", submission="manual"),
        ]
        db.add_all(offices)
        db.flush()

        # A single-band model (the common "base plus a percentage" shape) and a
        # tiered one that tapers on expensive lines.
        flat = FeeModel(code="SEP+50", name="Single exit price plus 50%", basis="sep",
                        apply_mmap=False, notes="Illustrative — replace with gazetted bands.")
        tiered = FeeModel(code="SEP-TIER", name="Single exit price, tapered fee", basis="sep",
                          apply_mmap=True, notes="Illustrative — replace with gazetted bands.")
        db.add_all([flat, tiered])
        db.flush()
        db.add_all([
            FeeTier(fee_model_id=flat.id, up_to=None, percentage=50.0, min_fee=1.0),
            FeeTier(fee_model_id=tiered.id, up_to=100.0, percentage=46.0, min_fee=5.0),
            FeeTier(fee_model_id=tiered.id, up_to=500.0, percentage=33.0, fixed_fee=8.0),
            FeeTier(fee_model_id=tiered.id, up_to=None, percentage=15.0, fixed_fee=40.0, max_fee=200.0),
        ])
        db.flush()

        by_code = {o.code: o for o in offices}
        for aid in db.query(MedicalAid).all():
            name = aid.name.upper()
            office = (by_code["CIMAS"] if "CIMAS" in name
                      else by_code["PSMAS"] if "PSMAS" in name or "PREMIER" in name
                      else by_code["FIRSTMUT"] if "FIRST" in name
                      else by_code["PRIVATE"])
            aid.pay_office_id = office.id
            aid.fee_model_id = tiered.id if office.code == "CIMAS" else flat.id
            aid.realtime = office.submission == "realtime"
            aid.levy_fixed = 0.0
            aid.levy_percent = 10.0
            aid.discount_percent = 0.0
        db.commit()

    if db.query(DiagnosisCode).count() == 0:
        # A working starter set. A live install imports the full ICD-10 release.
        codes = [
            ("Z76.0", "Issue of repeat prescription", "Factors influencing health status"),
            ("Z76.9", "Person encountering health services in unspecified circumstances",
             "Factors influencing health status"),
            ("J00", "Acute nasopharyngitis (common cold)", "Respiratory"),
            ("J02.9", "Acute pharyngitis, unspecified", "Respiratory"),
            ("J06.9", "Acute upper respiratory infection, unspecified", "Respiratory"),
            ("J45.9", "Asthma, unspecified", "Respiratory"),
            ("I10", "Essential (primary) hypertension", "Circulatory"),
            ("I25.9", "Chronic ischaemic heart disease, unspecified", "Circulatory"),
            ("E11.9", "Type 2 diabetes mellitus without complications", "Endocrine"),
            ("E78.5", "Hyperlipidaemia, unspecified", "Endocrine"),
            ("B54", "Unspecified malaria", "Infectious"),
            ("A09", "Infectious gastroenteritis and colitis, unspecified", "Infectious"),
            ("B20", "HIV disease resulting in infectious/parasitic disease", "Infectious"),
            ("N39.0", "Urinary tract infection, site not specified", "Genitourinary"),
            ("M54.5", "Low back pain", "Musculoskeletal"),
            ("R51", "Headache", "Symptoms and signs"),
            ("R50.9", "Fever, unspecified", "Symptoms and signs"),
            ("K21.9", "Gastro-oesophageal reflux disease without oesophagitis", "Digestive"),
            ("L23.9", "Allergic contact dermatitis, unspecified cause", "Skin"),
            ("F41.9", "Anxiety disorder, unspecified", "Mental and behavioural"),
        ]
        db.add_all([
            DiagnosisCode(code=c, description=d, chapter=ch) for c, d, ch in codes
        ])
        db.commit()


def seed_formulary_if_empty(db):
    """A worked formulary so coverage and substitution can be exercised.

    Active ingredients are set from the product name where they are obvious —
    without them there is no way to offer a generic alternative, which is the
    whole value of a coverage check.
    """
    from .models import Formulary, FormularyEntry, MedicalAid, Product

    # Molecule for the seeded catalogue. A live install loads this from the
    # medicine register rather than inferring it.
    INGREDIENTS = {
        "Amlodipine": "amlodipine", "Amoxicillin": "amoxicillin",
        "Amoxicillin/Clavulanate": "amoxicillin+clavulanate",
        "Atorvastatin": "atorvastatin", "Cetirizine": "cetirizine",
        "Paracetamol": "paracetamol", "Ibuprofen": "ibuprofen",
        "Metformin": "metformin", "Omeprazole": "omeprazole",
        "Simvastatin": "simvastatin", "Tramadol": "tramadol",
        "Fluoxetine": "fluoxetine", "Methylphenidate": "methylphenidate",
    }
    for product in db.query(Product).all():
        if product.active_ingredient:
            continue
        for name, molecule in sorted(INGREDIENTS.items(), key=lambda kv: -len(kv[0])):
            if product.name.lower().startswith(name.lower()):
                product.active_ingredient = molecule
                break
    db.commit()

    if db.query(Formulary).count() > 0:
        return

    formulary = Formulary(
        code="STD", name="Standard benefit formulary", default_rule="covered",
        notes="Open formulary — anything not listed is paid. Listed items carry a rule.",
    )
    db.add(formulary)
    db.flush()

    def by_name(prefix):
        return db.query(Product).filter(Product.name.ilike(f"{prefix}%")).first()

    rules = [
        ("Atorvastatin", "reference", "Paid to the reference price for statins."),
        ("Tramadol", "authorisation", "Controlled analgesic — authorisation required."),
        ("Methylphenidate", "authorisation", "Requires scheme authorisation."),
    ]
    for prefix, status, note in rules:
        product = by_name(prefix)
        if product:
            db.add(FormularyEntry(
                formulary_id=formulary.id, product_id=product.id, status=status,
                reference_price=round((product.unit_price or 0) * 0.6, 2) if status == "reference" else 0.0,
                requires_authorisation=status == "authorisation",
                note=note,
            ))

    # One outright exclusion with a covered sibling, so substitution has
    # something real to find.
    excluded = by_name("Amoxicillin/Clavulanate")
    if excluded:
        db.add(FormularyEntry(
            formulary_id=formulary.id, product_id=excluded.id, status="excluded",
            note="Combination antibiotic not on benefit — use plain amoxicillin.",
        ))

    # A cheaper generic of the reference-priced statin. Same molecule, so it is
    # a legitimate substitution — which is what makes the coverage check useful
    # rather than merely informative.
    originator = by_name("Atorvastatin")
    if originator and not by_name("Atorva-Gen"):
        generic = Product(
            name="Atorva-Gen", strength=originator.strength,
            dosage_form=originator.dosage_form, category="medicine",
            schedule=originator.schedule, active_ingredient="atorvastatin",
            unit_price=round((originator.unit_price or 0) * 0.55, 2),
            cost_price=round((originator.cost_price or 0) * 0.55, 2),
            vat_rate=originator.vat_rate, quantity_on_hand=40,
            reorder_level=10, reorder_quantity=20,
            supplier_id=originator.supplier_id,
        )
        db.add(generic)
        db.flush()
        db.add(FormularyEntry(formulary_id=formulary.id, product_id=generic.id,
                              status="covered", note="Preferred generic."))

    for aid in db.query(MedicalAid).all():
        aid.formulary_id = formulary.id
    db.commit()


def seed_gateway_if_empty(db):
    """Funders, their switch routing, and a starter AHFoZ tariff book.

    The tariff prices below are illustrative. The real book is published per
    financial year and must be loaded before claiming — a wrong band rejects
    every claim that touches it.
    """
    from datetime import date

    from .models import Funder, MedicalAid, Tariff

    # Funders are added by identifier rather than all-or-nothing, so a pharmacy
    # already running RX3000 picks up a newly registered funder on upgrade
    # instead of only on a fresh database.
    known = {f.funder_id for f in db.query(Funder).all()}
    aids = {a.name.upper(): a for a in db.query(MedicalAid).all()}

    def aid_id(fragment):
        for name, aid in aids.items():
            if fragment in name:
                return aid.id
        return None

    for funder in [
        Funder(funder_id="CIMAS_ZW", name="CIMAS Medical Aid Society",
               switch_id="SIMULATOR", currency_code="USD", medical_aid_id=aid_id("CIMAS")),
        Funder(funder_id="PSMAS_ZW", name="Premier Service Medical Aid Society",
               switch_id="SIMULATOR", currency_code="USD", medical_aid_id=aid_id("PSMAS")),
        Funder(funder_id="FIRSTMUT_ZW", name="First Mutual Health",
               switch_id="SIMULATOR", currency_code="USD", medical_aid_id=aid_id("FIRST")),
        Funder(funder_id="ALLIANCE_ZW", name="Alliance Health",
               switch_id="SIMULATOR", currency_code="USD"),
        # Verifies its members by fingerprint: nothing is adjudicated for this
        # funder without a print from the reader at the till.
        Funder(funder_id="FIDELITY_ZW", name="Fidelity Life Medical Aid",
               switch_id="SIMULATOR", currency_code="USD", biometric_required=True),
        # Routed to the real switches — these fail until their adapters exist.
        Funder(funder_id="CIMAS_ZW_H263", name="CIMAS (via Health 263)",
               switch_id="HEALTH_263", currency_code="USD"),
        Funder(funder_id="PSMAS_ZW_MEDI", name="PSMAS (via Mediswitch)",
               switch_id="MEDISWITCH", currency_code="USD"),
        Funder(funder_id="CIMAS_ZWG", name="CIMAS (ZiG pool)",
               switch_id="SIMULATOR", currency_code="ZWG"),
    ]:
        if funder.funder_id not in known:
            db.add(funder)
    db.commit()

    year = date.today().year
    if db.query(Tariff).filter(Tariff.financial_year == year).count() == 0:
        book = [
            ("0101", "New consultation - Rooms", 35.00, 30.00, 40.00, "General Practitioner"),
            ("0102", "Follow-up consultation - Rooms", 25.00, 20.00, 30.00, "General Practitioner"),
            ("0201", "Blood pressure monitoring", 10.00, 8.00, 12.00, "General Practitioner"),
            ("0202", "Blood glucose test", 8.00, 6.00, 10.00, "General Practitioner"),
            ("0301", "Dispensing fee - acute", 5.00, 4.00, 6.00, "Pharmacy"),
            ("0302", "Dispensing fee - chronic", 7.50, 6.00, 9.00, "Pharmacy"),
            ("0401", "Wound dressing - minor", 15.00, 12.00, 18.00, "Pharmacy"),
            ("0501", "Vaccination administration", 12.00, 10.00, 15.00, "Pharmacy"),
        ]
        db.add_all([
            Tariff(tariff_code=code, description=desc, financial_year=year,
                   currency_code="USD", unit_price=price, min_price=lo, max_price=hi,
                   practice_type=practice)
            for code, desc, price, lo, hi, practice in book
        ])
        db.commit()
