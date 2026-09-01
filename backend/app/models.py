from datetime import datetime, date

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base
from .tenancy import TenantMixin


class User(Base, TenantMixin):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    full_name = Column(String(120), nullable=False)
    role = Column(String(20), nullable=False, default="assistant")  # admin | pharmacist | assistant | cashier
    active = Column(Boolean, default=True)

    # ---- what KIND of user this is -------------------------------------
    #
    # `role` says what a member of staff may do. It cannot say what somebody
    # IS, and the three kinds who sign in here are not variations of one
    # another — they arrive by different doors, prove themselves differently,
    # and reach different halves of the system.
    #
    #   staff       username and password, then a PIN at the till. Reaches the
    #               application; `role` and the capability grants decide how
    #               much of it.
    #   patient     a signed link and a four-digit code. Reaches their own
    #               record and nothing else — never the application.
    #   prescriber  their own account tied to a practice number, because a
    #               link that can prescribe is a prescription pad held by
    #               everybody it was ever forwarded to.
    #
    # Held as a column rather than inferred from whether `patient_id` is set,
    # because "this is a patient login" is a fact somebody decided, and a fact
    # inferred from a null is a fact that changes when somebody fixes a null.
    user_type = Column(String(16), nullable=False, default="staff", index=True)
    #: The patient this login belongs to, where it is a patient's.
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)
    #: The prescriber it belongs to, where it is a prescriber's.
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True, index=True)
    # A short code for the till, hashed like any other secret.
    #
    # Not a replacement for the password: the password starts a session, the PIN
    # says who is standing at a machine that is already signed in. On a shared
    # till that is the only honest way to attribute an action — logging out
    # between customers loses the basket, so nobody does it, and every action
    # then belongs to whoever opened the shop.
    pin_hash = Column(String(255), nullable=True)
    pin_set_at = Column(DateTime, nullable=True)
    # Consecutive failures, and the lock that follows them. Four digits is ten
    # thousand combinations; without a lockout that is an afternoon's work.
    pin_failures = Column(Integer, default=0)
    pin_locked_until = Column(DateTime, nullable=True)
    # A demo account, and when it stops working.
    #
    # Kept on the user rather than only in the token because a token is a copy:
    # once issued it says what it said, and a demo that could be extended by
    # holding on to an old one is not a demo. Every request re-reads this, so
    # revoking a demo early is a single UPDATE.
    #: Operates the platform, not a pharmacy.
    #:
    #: Deliberately a flag and not a role. `admin` already means "runs this
    #: pharmacy" and is held by a customer; whoever sells the system to them is
    #: a different kind of person entirely, and conflating the two would let any
    #: customer's administrator create tenants and move users between them —
    #: which is the whole tenancy undone from inside.
    is_platform_admin = Column(Boolean, default=False, index=True)
    is_demo = Column(Boolean, default=False)
    demo_expires_at = Column(DateTime, nullable=True)


class PayOffice(Base):
    """Who actually settles a claim.

    Several schemes are administered, and paid, by one office, so claims are
    batched and reconciled per pay office rather than per scheme. This is the
    unit an administrator sends a claim batch to.
    """
    __tablename__ = "pay_offices"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(160), nullable=False)
    submission = Column(String(20), default="manual")   # manual | realtime
    contact = Column(String(160), default="")
    phone = Column(String(30), default="")
    email = Column(String(160), default="")
    active = Column(Boolean, default=True)

    schemes = relationship("MedicalAid", back_populates="pay_office")


class FeeModel(Base):
    """How a dispensed price is built from the base price.

    Medicine pricing is regulated and derived, never typed: a base price (the
    single exit price) plus a professional fee that steps by price band. The
    bands are data because they are set by regulation and change — hard-coding
    a percentage would make every fee revision a code release.
    """
    __tablename__ = "fee_models"
    id = Column(Integer, primary_key=True)
    code = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(160), nullable=False)
    basis = Column(String(20), default="sep")     # sep | cost | list
    vat_on_fee = Column(Boolean, default=True)
    # Cap the medicine portion at the reference price for the molecule where the
    # scheme applies one (maximum medical aid price).
    apply_mmap = Column(Boolean, default=False)
    notes = Column(Text, default="")
    active = Column(Boolean, default=True)

    tiers = relationship("FeeTier", back_populates="fee_model",
                         cascade="all, delete-orphan",
                         order_by="FeeTier.up_to.is_(None), FeeTier.up_to")


class FeeTier(Base):
    """One price band of a fee model. `up_to` NULL means the open-ended top band."""
    __tablename__ = "fee_tiers"
    id = Column(Integer, primary_key=True)
    fee_model_id = Column(Integer, ForeignKey("fee_models.id"), nullable=False, index=True)
    up_to = Column(Float, nullable=True)
    percentage = Column(Float, default=0.0)
    fixed_fee = Column(Float, default=0.0)
    min_fee = Column(Float, default=0.0)
    max_fee = Column(Float, nullable=True)

    fee_model = relationship("FeeModel", back_populates="tiers")


class Funder(Base):
    """A medical aid funder as the clearinghouse sees it.

    `switch_id` is the routing decision: the same unified payload goes to a
    different platform, and a different wire format, depending on it.
    """
    __tablename__ = "funders"
    id = Column(Integer, primary_key=True)
    funder_id = Column(String(40), unique=True, nullable=False, index=True)  # CIMAS_ZW
    name = Column(String(160), nullable=False)
    switch_id = Column(String(40), default="SIMULATOR")   # HEALTH_263 | MEDISWITCH | DIRECT
    medical_aid_id = Column(Integer, ForeignKey("medical_aids.id"), nullable=True)
    currency_code = Column(String(5), default="USD")
    realtime = Column(Boolean, default=True)
    # Funders on a biometric switch will not adjudicate for an unverified member,
    # so the gateway refuses the claim here rather than after a round trip.
    biometric_required = Column(Boolean, default=False)
    active = Column(Boolean, default=True)

    medical_aid = relationship("MedicalAid")


class Tariff(Base):
    """AHFoZ global tariff book entry for a financial year.

    A price outside the negotiated band is rejected before it reaches a switch —
    a downstream rejection costs a round trip and a resubmission.
    """
    __tablename__ = "tariffs"
    id = Column(Integer, primary_key=True)
    tariff_code = Column(String(20), nullable=False, index=True)
    description = Column(String(300), nullable=False)
    financial_year = Column(Integer, nullable=False, index=True)
    currency_code = Column(String(5), default="USD")
    unit_price = Column(Float, default=0.0)
    # Prices are negotiated bands, not fixed points.
    min_price = Column(Float, default=0.0)
    max_price = Column(Float, default=0.0)
    practice_type = Column(String(80), default="")
    active = Column(Boolean, default=True)


class GatewayTransaction(Base, TenantMixin):
    """Every call through the gateway, kept for dispute and audit.

    A funder query six months later is answered from here, not from memory.
    """
    __tablename__ = "gateway_transactions"
    id = Column(Integer, primary_key=True)
    transaction_id = Column(String(40), unique=True, nullable=False, index=True)
    kind = Column(String(20), default="claim")        # eligibility | claim
    funder_id = Column(String(40), default="", index=True)
    switch_id = Column(String(40), default="")
    status = Column(String(30), default="")           # PROCESSED | REJECTED | ERROR
    error_code = Column(String(40), default="")
    http_status = Column(Integer, default=200)
    amount_claimed = Column(Float, default=0.0)
    amount_approved = Column(Float, default=0.0)
    switch_reference = Column(String(60), default="")
    funder_reference = Column(String(60), default="")
    request_json = Column(Text, default="")
    response_json = Column(Text, default="")
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Mixture(Base, TenantMixin):
    """An extemporaneous preparation: a recipe made up in the dispensary.

    A compound is not a product on a shelf: it is assembled from ingredients at
    the moment it is needed. Two consequences drive the design. Its cost is the
    sum of what went into it plus the labour, and **its schedule is the highest
    schedule of any ingredient** — a cream containing a controlled substance is
    dispensed under controlled rules, not as a cream.
    """
    __tablename__ = "mixtures"
    id = Column(Integer, primary_key=True)
    code = Column(String(30), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    form = Column(String(40), default="mixture")   # mixture | ointment | cream | capsules
    yield_quantity = Column(Float, default=1.0)    # how much one preparation makes
    yield_unit = Column(String(20), default="ml")
    compounding_fee = Column(Float, default=0.0)
    shelf_life_days = Column(Integer, default=30)
    method = Column(Text, default="")              # how to make it up
    directions = Column(Text, default="")          # what goes on the label
    active = Column(Boolean, default=True)

    ingredients = relationship("MixtureIngredient", back_populates="mixture",
                               cascade="all, delete-orphan")


class MixtureIngredient(Base, TenantMixin):
    """One component of a recipe, drawn from ordinary stock when prepared."""
    __tablename__ = "mixture_ingredients"
    id = Column(Integer, primary_key=True)
    mixture_id = Column(Integer, ForeignKey("mixtures.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Float, default=1.0)
    unit = Column(String(20), default="ml")
    note = Column(String(200), default="")

    mixture = relationship("Mixture", back_populates="ingredients")
    product = relationship("Product")


class Formulary(Base):
    """A scheme's list of what it will pay for.

    `default_rule` decides what happens to a product with no explicit entry:
    an open formulary pays unless told otherwise, a closed one pays only what is
    listed. Getting this backwards is the difference between over-claiming and
    rejecting everything.
    """
    __tablename__ = "formularies"
    id = Column(Integer, primary_key=True)
    code = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(160), nullable=False)
    default_rule = Column(String(20), default="covered")   # covered | excluded
    active = Column(Boolean, default=True)
    notes = Column(Text, default="")

    entries = relationship("FormularyEntry", back_populates="formulary",
                           cascade="all, delete-orphan")


class FormularyEntry(Base):
    """One product's standing on a formulary."""
    __tablename__ = "formulary_entries"
    id = Column(Integer, primary_key=True)
    formulary_id = Column(Integer, ForeignKey("formularies.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    # covered      — paid in full at the scheme's fee model
    # reference    — paid up to a reference price, patient pays the difference
    # authorisation— paid only against an authorisation number
    # excluded     — the scheme will not pay for this at all
    status = Column(String(20), default="covered")
    reference_price = Column(Float, default=0.0)
    max_quantity = Column(Integer, default=0)      # 0 = no limit, per dispensing
    requires_authorisation = Column(Boolean, default=False)
    note = Column(String(300), default="")

    formulary = relationship("Formulary", back_populates="entries")
    product = relationship("Product")


class DiagnosisCode(Base):
    """ICD-10. A claim line without one is rejected by the scheme."""
    __tablename__ = "diagnosis_codes"
    id = Column(Integer, primary_key=True)
    code = Column(String(12), unique=True, nullable=False, index=True)
    description = Column(String(300), nullable=False)
    chapter = Column(String(160), default="")
    # Some codes may not be used as the primary reason for a claim.
    valid_primary = Column(Boolean, default=True)
    active = Column(Boolean, default=True)


class MedicalAid(Base):
    __tablename__ = "medical_aids"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    scheme_code = Column(String(20), nullable=False)
    phone = Column(String(30), default="")

    pay_office_id = Column(Integer, ForeignKey("pay_offices.id"), nullable=True, index=True)
    fee_model_id = Column(Integer, ForeignKey("fee_models.id"), nullable=True)
    formulary_id = Column(Integer, ForeignKey("formularies.id"), nullable=True)
    # Schemes are commonly offered in more than one currency; each variant
    # claims separately and settles separately.
    currency_code = Column(String(5), default="")
    biometric_required = Column(Boolean, default=False)
    realtime = Column(Boolean, default=False)
    # Patient levy: a fixed amount or a percentage of the claim, whichever the
    # scheme uses. Both may be zero.
    levy_fixed = Column(Float, default=0.0)
    levy_percent = Column(Float, default=0.0)
    discount_percent = Column(Float, default=0.0)   # scheme discount off the claim
    extra_markup_percent = Column(Float, default=0.0)
    # How much unsettled claim value the pharmacy is willing to carry for this
    # scheme. Zero means no limit has been set, not a limit of nothing — a
    # scheme with no agreed ceiling is the normal starting state, and treating
    # zero as "stop dispensing" would close the counter on day one.
    #
    # This is the pharmacy's exposure, not the patient's benefit. A scheme that
    # pays ninety days late is lending money from the dispensary, and until now
    # there was nowhere to record how much of that was acceptable.
    credit_limit = Column(Float, default=0.0)
    active = Column(Boolean, default=True)

    # The agreement, and the two dates a pharmacy actually plans around.
    #
    # Claiming is not continuous: a pharmacy signs terms with each funder that
    # say when a month's claims must be in by and when the money comes back.
    # Miss the cut-off and the claim waits a whole extra cycle, which for a
    # shop running on its float is the difference between paying staff and not.
    # None of that was written down anywhere, so "when does CIMAS pay" was
    # answered from somebody's memory.
    #: Day of the month claims must be submitted by. 0 when there is no cut-off.
    claim_cutoff_day = Column(Integer, default=0)
    #: Day of the month the funder settles. 0 when it is terms-based instead.
    settlement_day = Column(Integer, default=0)
    #: Days after submission the funder is expected to pay, where the agreement
    #: is expressed as terms rather than a fixed day.
    settlement_days = Column(Integer, default=0)
    #: The memorandum this was agreed in, so somebody can find the paper.
    agreement_reference = Column(String(60), default="")
    agreement_note = Column(Text, default="")

    patients = relationship("Patient", back_populates="medical_aid")
    pay_office = relationship("PayOffice", back_populates="schemes")
    fee_model = relationship("FeeModel")
    formulary = relationship("Formulary")


class Doctor(Base, TenantMixin):
    __tablename__ = "doctors"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    practice_number = Column(String(30), default="")
    phone = Column(String(30), default="")
    email = Column(String(120), default="")
    # Prescriber portal. Null until the pharmacy enables it — a prescriber who
    # can write into this system is a decision the pharmacy makes, never a
    # self-service signup.
    portal_password_hash = Column(String(255))
    portal_active = Column(Boolean, default=False)
    # A prescriber who has retired, moved abroad or been struck off should stop
    # appearing when a script is captured, while every script they ever wrote
    # still says who wrote it. Retired, never deleted.
    active = Column(Boolean, default=True, index=True)


class Patient(Base, TenantMixin):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(80), nullable=False)
    last_name = Column(String(80), nullable=False, index=True)
    id_number = Column(String(30), default="", index=True)
    date_of_birth = Column(Date, nullable=True)
    phone = Column(String(30), default="")
    email = Column(String(120), default="")
    address = Column(Text, default="")
    allergies = Column(Text, default="")
    chronic_conditions = Column(Text, default="")
    medical_aid_id = Column(Integer, ForeignKey("medical_aids.id"), nullable=True)
    medical_aid_number = Column(String(40), default="")
    dependent_code = Column(String(10), default="00")
    loyalty_points = Column(Integer, default=0)

    # ---- the portal ---------------------------------------------------
    #
    # A four-digit code, given to the patient with the link.
    #
    # The link used to be secured by date of birth, which is the wrong second
    # factor twice over: a forwarded WhatsApp message usually reaches somebody
    # who knows the patient's birthday, and a patient who mistypes it is told
    # their own date of birth is wrong, which is the most insulting error a
    # system can produce. A code the pharmacy hands over is known by exactly
    # the people who should know it, and can be changed the moment a phone is
    # lost.
    portal_code = Column(String(8), default="")
    portal_code_set_at = Column(DateTime, nullable=True)
    #: Wrong codes in a row. A link that reaches the wrong phone should not be
    #: guessable at ten thousand tries; five is generous for four digits.
    portal_failed = Column(Integer, default=0)
    portal_locked_until = Column(DateTime, nullable=True)
    portal_last_seen = Column(DateTime, nullable=True)
    # Who looks after this patient. Not next of kin and not an emergency
    # contact: the person who actually collects the medicine, signs for a
    # delivery, takes the reminder call and answers the survey. For an elderly
    # or paediatric patient that is almost never the patient, and a reminder
    # placed to the patient's own number reaches nobody.
    caregiver_name = Column(String(120), default="")
    caregiver_phone = Column(String(30), default="")
    caregiver_relationship = Column(String(40), default="")
    # Whether the caregiver is the right person to contact by default. A patient
    # who manages their own medicine should not have calls diverted.
    contact_caregiver_first = Column(Boolean, default=False)
    marketing_opt_in = Column(Boolean, default=True)  # POPIA consent for campaigns
    created_at = Column(DateTime, default=datetime.utcnow)

    medical_aid = relationship("MedicalAid", back_populates="patients")
    prescriptions = relationship("Prescription", back_populates="patient")


class Supplier(Base, TenantMixin):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    contact_person = Column(String(120), default="")
    phone = Column(String(30), default="")
    email = Column(String(120), default="")
    # Where money is sent, and on what terms.
    #
    # A supplier record with no bank details is one where the details live in
    # somebody's email, which is exactly the message a fraudster imitates, and
    # a wholesaler genuinely changing its account is indistinguishable from one
    # pretending to. Held here, changed deliberately, and visible to whoever
    # pays.
    account_number = Column(String(60), default="")
    payment_terms = Column(String(60), default="")
    notes = Column(Text, default="")
    # Retired, never deleted: the name is on every order they ever fulfilled.
    active = Column(Boolean, default=True, index=True)


class StockCategory(Base, TenantMixin):
    """What kind of thing a product is, as the pharmacy itself groups them.

    Every pharmacy already has this and calls it a department: dispensary, over
    the counter, cosmetics, consignment. It decides where a line sits on a
    stocktake sheet, which margin is expected of it, and which report it lands
    in, so a catalogue where the answer lives in a free-text field is one where
    "COSMETICS", "Cosmetics" and "cosmetic" become three departments and no
    total is right.

    Deliberately separate from `Product.category`, which asks a different
    question with a confusingly similar name. That one says whether a line is a
    medicine, a front-shop item or airtime, and code branches on it — airtime is
    kept out of stocktakes, only medicines reach the dispensing routes. This one
    is the pharmacy's own grouping and is theirs to rename.
    """
    __tablename__ = "stock_categories"

    id = Column(Integer, primary_key=True)
    #: The pharmacy's own department code, as it appears on their reports.
    code = Column(String(20), default="", index=True)
    name = Column(String(80), nullable=False)
    #: The margin expected of this department, where a pharmacy works that way.
    #: A cosmetics line and a dispensary line are not judged on the same number.
    target_margin = Column(Float, default=0.0)
    notes = Column(Text, default="")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    products = relationship("Product", back_populates="stock_category")


class Product(Base, TenantMixin):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    nappi_code = Column(String(30), default="", index=True)
    barcode = Column(String(40), default="", index=True)
    # Where it lives on the shelf. A picking list in bin order is walked once;
    # a picking list in product order is walked three times.
    bin_location = Column(String(20), default="", index=True)
    # Who makes it, as against who sells it to us. Two suppliers can carry the
    # same manufacturer's product, and a recall names the manufacturer.
    manufacturer = Column(String(120), default="", index=True)
    # The regulated maximum, where one is published. Zimbabwe does not operate a
    # single exit price the way South Africa does, so this is left blank rather
    # than invented, and the comparison report says so when nothing is set.
    sep_price = Column(Float, default=0.0)

    category = Column(String(40), default="medicine")  # medicine | front_shop | airtime
    #: The pharmacy's own department. See StockCategory for why this is separate
    #: from `category` above.
    category_id = Column(Integer, ForeignKey("stock_categories.id"),
                         nullable=True, index=True)
    #: The code this pharmacy knows the line by — what is on their shelf labels
    #: and their own reports. Not the NAPPI code, which is national.
    stock_code = Column(String(40), default="", index=True)
    #: What the stock cost on average, as against the last price paid. A
    #: pharmacy values its shelf on this, and the two differ enough to matter.
    average_cost = Column(Float, default=0.0)
    schedule = Column(Integer, default=0)  # 0-6 (S5/S6 tracked in register)
    dosage_form = Column(String(60), default="")
    strength = Column(String(60), default="")
    # The molecule, not the brand. Two products sharing this are substitutable,
    # which is what makes a formulary rejection actionable rather than a dead end.
    active_ingredient = Column(String(160), default="", index=True)
    pack_size = Column(String(60), default="")
    unit_price = Column(Float, default=0.0)      # single exit price
    cost_price = Column(Float, default=0.0)
    # Reference price for the molecule. Where a scheme applies MMAP the medicine
    # portion is capped here, and the patient pays the difference.
    mmap_price = Column(Float, default=0.0)
    vat_rate = Column(Float, default=0.15)
    quantity_on_hand = Column(Integer, default=0)
    reorder_level = Column(Integer, default=10)
    reorder_quantity = Column(Integer, default=20)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    active = Column(Boolean, default=True)

    supplier = relationship("Supplier")
    stock_category = relationship("StockCategory", back_populates="products")
    barcodes = relationship(
        "ProductBarcode", back_populates="product", cascade="all, delete-orphan"
    )


class ProductBarcode(Base, TenantMixin):
    """The other codes a product answers to.

    `Product.barcode` stays where it is and stays authoritative — it is what
    prints on a shelf label and what an operator sees on the product page. This
    table is for everything else the same article legitimately scans as: the
    originator's pack alongside the generic, the outer carton's ITF-14 next to
    the inner EAN-13, and the pharmacy's own label on a repack.

    Learned codes matter as much as imported ones. When a scan misses and the
    operator picks the product by hand, we can offer to remember the pairing, so
    the second person to scan that pack does not have to search. `source` keeps
    those distinguishable from codes that came off a supplier's price file.
    """
    __tablename__ = "product_barcodes"
    __table_args__ = (UniqueConstraint("code", name="uq_product_barcode_code"),)

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    code = Column(String(64), nullable=False, index=True)
    # How many dispensing units this pack contains. Scanning an outer carton at
    # goods receipt should book in the case, not one tablet, and that number is
    # the only thing standing between a delivery and a stock count that is wrong
    # by a factor of twenty.
    pack_size = Column(Integer, default=1)
    label = Column(String(80), default="")       # "Outer carton", "Cipla pack"
    source = Column(String(20), default="manual")  # manual | learned | import
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    product = relationship("Product", back_populates="barcodes")


class Prescription(Base, TenantMixin):
    __tablename__ = "prescriptions"
    id = Column(Integer, primary_key=True)
    rx_number = Column(String(30), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    # A draft may not know the prescriber yet — that is often the field
    # the pharmacist is still chasing when they are interrupted.
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    date_prescribed = Column(Date, default=date.today)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    # draft | active | cancelled
    #
    # A script half-captured when the phone rings has to be resumable, or the
    # pharmacist re-keys it, and re-keying is where dispensing errors come from.
    status = Column(String(12), default="active", index=True)
    # A draft holds no Rx number. The register is a numbered sequence, and a
    # number burnt on a capture somebody abandoned leaves a gap that has to be
    # explained to an inspector. Drafts carry a working reference instead and
    # take their number only when they become real.
    draft_ref = Column(String(30), default="", index=True)
    started_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)
    finalised_at = Column(DateTime, nullable=True)

    patient = relationship("Patient", back_populates="prescriptions")
    started_by = relationship("User")
    doctor = relationship("Doctor")
    items = relationship("PrescriptionItem", back_populates="prescription", cascade="all, delete-orphan")


class PrescriptionItem(Base, TenantMixin):
    __tablename__ = "prescription_items"
    id = Column(Integer, primary_key=True)
    prescription_id = Column(Integer, ForeignKey("prescriptions.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    dosage_instructions = Column(Text, default="")
    quantity = Column(Integer, default=1)
    repeats_allowed = Column(Integer, default=0)
    repeats_used = Column(Integer, default=0)
    repeat_interval_days = Column(Integer, default=30)
    next_repeat_date = Column(Date, nullable=True)
    auto_refill = Column(Boolean, default=False)
    # Diagnosis for this line. Schemes reject a claim line without one.
    icd10_code = Column(String(12), default="", index=True)
    # How many days this quantity is meant to last. Schemes adjudicate on days
    # of supply as much as on quantity, and it drives when a repeat is due.
    supply_days = Column(Integer, default=30)
    # Per-line billing decisions. One line of a script can be cash while the
    # rest is claimed, or not be supplied at all — without these the pharmacist
    # has to split the script by hand, which is where mistakes come from.
    no_claim = Column(Boolean, default=False)
    not_dispensed = Column(Boolean, default=False)

    prescription = relationship("Prescription", back_populates="items")
    product = relationship("Product")
    dispensings = relationship("Dispensing", back_populates="prescription_item")


class Dispensing(Base, TenantMixin):
    __tablename__ = "dispensings"
    id = Column(Integer, primary_key=True)
    prescription_item_id = Column(Integer, ForeignKey("prescription_items.id"), nullable=False)
    quantity = Column(Integer, default=1)
    dispensed_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # --- the will-call shelf ------------------------------------------------
    #
    # Dispensed is not collected. Medicine is checked, labelled and bagged, and
    # then it sits on a shelf behind the counter until somebody comes for it —
    # sometimes that afternoon, sometimes never. Until now the system treated
    # the moment of dispensing as the end of the story, so a bag nobody came
    # back for was indistinguishable from one handed over, and the only way to
    # find it was to look at the shelf.
    #
    # That matters three ways: the patient is not taking their medicine, the
    # stock is off the shelf and unsellable, and on a scheme script the claim has
    # been made for medicine the patient never received.
    #
    # Collection belongs here rather than on the prescription because a script
    # can be dispensed in parts — two items today, the third when stock lands —
    # and each bag is collected separately or not at all.
    collected_at = Column(DateTime, nullable=True, index=True)
    collected_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Who actually took it. Often not the patient: a relative, a driver, a
    # neighbour going that way. Recorded as typed, because on a controlled item
    # this is the answer to "who had it".
    collected_name = Column(String(120), default="")
    dispensed_at = Column(DateTime, default=datetime.utcnow)
    is_repeat = Column(Boolean, default=False)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True)

    # Controlled-substance compliance record (S5/S6 "dangerous drugs")
    dispense_type = Column(String(20), default="prescription")  # prescription | controlled
    schedule = Column(Integer, default=0)
    id_verified = Column(Boolean, default=False)
    id_number_seen = Column(String(30), default="")
    script_sighted = Column(Boolean, default=False)
    prescriber_verified = Column(Boolean, default=False)
    # The dispensing pharmacist's initials, typed at the point of handover.
    #
    # This replaces a second user acting as witness. A witness requirement that
    # cannot be met, one pharmacist on a Sunday, is either ignored or worked
    # around by sharing a login, and a shared login is worse than no control at
    # all because it makes the record actively wrong. An initial is a claim by a
    # named, logged-in person that they checked it, which is what the record
    # needs to say.
    pharmacist_initial = Column(String(8), default="")
    # Kept for scripts dispensed before the change. Nothing writes to it.
    witness_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    compliance_notes = Column(Text, default="")

    prescription_item = relationship("PrescriptionItem", back_populates="dispensings")
    dispensed_by = relationship("User", foreign_keys=[dispensed_by_id])
    collected_by = relationship("User", foreign_keys=[collected_by_id])
    witness = relationship("User", foreign_keys=[witness_id])


class OTCSale(Base, TenantMixin):
    """Pharmacy-medicine (S1/S2) counter-sale record — no script, but the
    pharmacist, indication and counselling must be recorded."""
    __tablename__ = "otc_sales"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=1)
    schedule = Column(Integer, default=0)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    customer_name = Column(String(160), default="")
    pharmacist_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    indication = Column(String(200), default="")
    counselling_given = Column(Boolean, default=False)
    referred_to_doctor = Column(Boolean, default=False)
    notes = Column(Text, default="")
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    product = relationship("Product")
    patient = relationship("Patient")
    pharmacist = relationship("User")


class Sale(Base, TenantMixin):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True)
    sale_number = Column(String(30), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    cashier_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    subtotal = Column(Float, default=0.0)          # ex VAT
    vat_amount = Column(Float, default=0.0)
    total = Column(Float, default=0.0)             # inc VAT
    payment_method = Column(String(20), default="cash")  # cash | card | medical_aid | account
    amount_tendered = Column(Float, default=0.0)
    change_due = Column(Float, default=0.0)
    loyalty_points_earned = Column(Integer, default=0)
    loyalty_points_redeemed = Column(Integer, default=0)
    status = Column(String(20), default="pending")  # pending | paid | void

    # The till's own reference for this sale, generated before it was first
    # sent. A sale taken while the line was down is retried until the server
    # confirms it, and a retry cannot tell "never arrived" apart from "arrived,
    # and the reply was lost". Without this, the second case posts the sale
    # twice: stock decremented twice, takings overstated, a phantom transaction
    # on a patient's record. Unique, so the database refuses a duplicate even if
    # the application logic is wrong.
    client_ref = Column(String(64), unique=True, nullable=True, index=True)
    # A sale awaiting payment is a COD — cash on delivery. Its state is already
    # carried by `status`: pending is outstanding, paid is settled, void is
    # cancelled. Adding a second status column to say the same thing again
    # would give two fields that can disagree, and the one on the report is the
    # one nobody checks.
    #
    # Transfer is the exception: moving an unpaid sale onto a debtor's account
    # is a real event that nothing else records, so it gets a column and no
    # more than that.
    transferred_at = Column(DateTime, nullable=True, index=True)
    transferred_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # When the till actually took the money, as against when the server heard
    # about it. On a queued sale these are hours apart, and the first is the one
    # that belongs on the receipt and in the day's figures.
    taken_offline_at = Column(DateTime, nullable=True)
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=True, index=True)

    # Card tender detail — what the terminal slip carries. Without these a card
    # sale can be totalled but never matched against the acquirer's settlement.
    card_auth_code = Column(String(20), default="", index=True)
    card_reference = Column(String(40), default="", index=True)
    card_last4 = Column(String(4), default="")
    card_scheme = Column(String(20), default="")     # visa | mastercard | amex …
    terminal_id = Column(String(30), default="")
    card_batch = Column(String(30), default="")

    # Currency of the sale total. Line prices are held in the base currency;
    # tenders may arrive in any trading currency and are converted on the way in.
    currency_code = Column(String(5), default="")
    # Which shop sold it. Drives the branch takings and the branch VAT return.
    branch_id = Column(Integer, ForeignKey("branches.id"), index=True)

    patient = relationship("Patient")
    # Two columns point at users now, who rang it up, and who moved it to an
    # account, so the join has to say which one it means. Adding the second
    # FK without this broke every report in the catalogue at once.
    cashier = relationship("User", foreign_keys=[cashier_id])
    transferred_by = relationship("User", foreign_keys=[transferred_by_id])
    tenders = relationship("SaleTender", back_populates="sale", cascade="all, delete-orphan")
    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")
    claim = relationship("Claim", back_populates="sale", uselist=False)


class SaleItem(Base, TenantMixin):
    __tablename__ = "sale_items"
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    description = Column(String(220), default="")
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, default=0.0)   # inc VAT
    vat_rate = Column(Float, default=0.15)
    line_total = Column(Float, default=0.0)   # inc VAT
    # How much of this line has come back over the counter.
    #
    # A customer returning one of four things was impossible: void and the
    # fiscal credit note both take back the whole sale, so the pharmacy
    # reversed all four and rang three up again, which changes the receipt
    # number, reverses the claim, earns the loyalty points twice and counts the
    # day's sales wrong in both directions. In practice it was done on paper,
    # and the stock drifted. Held per line so a second return cannot take back
    # more than was sold.
    quantity_returned = Column(Integer, default=0)
    # What the goods cost *at the moment they were sold*. Frozen here rather
    # than read from the product later, because a product's cost price changes
    # every time stock is bought, and computing last month's margin from this
    # month's cost price gives an answer that is confidently wrong.
    unit_cost = Column(Float, default=0.0)
    # Which script line this came from, where there was one. Without it a sale
    # line cannot be traced back to what was prescribed, so the per-line
    # billing decisions on the script have nothing to attach to, and a query
    # about what was dispensed against a script has to be answered by matching
    # product and date and hoping.
    prescription_item_id = Column(Integer, ForeignKey("prescription_items.id"),
                                  nullable=True, index=True)

    sale = relationship("Sale", back_populates="items")
    product = relationship("Product")
    prescription_item = relationship("PrescriptionItem")


class ClaimBatch(Base, TenantMixin):
    """A set of claims submitted to one pay office as a unit.

    Realtime schemes settle line by line; the rest are batched, sent, and
    reconciled against a remittance. The batch is what an administrator
    acknowledges, so it carries its own number and running totals.
    """
    __tablename__ = "claim_batches"
    id = Column(Integer, primary_key=True)
    batch_number = Column(String(30), nullable=False, index=True)
    pay_office_id = Column(Integer, ForeignKey("pay_offices.id"), nullable=False, index=True)
    period_from = Column(DateTime, nullable=True)
    period_to = Column(DateTime, nullable=True)
    status = Column(String(20), default="open")   # open | submitted | settled | rejected
    claim_count = Column(Integer, default=0)
    total_gross = Column(Float, default=0.0)
    total_discount = Column(Float, default=0.0)
    total_levy = Column(Float, default=0.0)
    total_claimed = Column(Float, default=0.0)
    total_settled = Column(Float, default=0.0)
    submitted_at = Column(DateTime, nullable=True)
    settled_at = Column(DateTime, nullable=True)
    reference = Column(String(80), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    pay_office = relationship("PayOffice")
    claims = relationship("Claim", back_populates="batch")


class Claim(Base, TenantMixin):
    __tablename__ = "claims"
    id = Column(Integer, primary_key=True)
    claim_number = Column(String(30), nullable=False, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    medical_aid_id = Column(Integer, ForeignKey("medical_aids.id"), nullable=False)
    amount_claimed = Column(Float, default=0.0)
    amount_approved = Column(Float, default=0.0)
    patient_liable = Column(Float, default=0.0)
    # submitted | approved | partial | rejected | reversed | deferred
    #
    # `deferred` is the one that earns its keep. The switch is down, or the
    # member has left their card at home, and the medicine still has to go out.
    # Without it the pharmacy either turns the patient away or loses the claim,
    # and in practice they do the second and never notice.
    status = Column(String(20), default="submitted")
    # Why it is being held, and what to tell the pharmacist when they look.
    deferred_reason = Column(String(200), default="")
    deferred_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    submit_attempts = Column(Integer, default=0)
    response_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Priced breakdown — what the scheme is actually being asked to pay.
    gross = Column(Float, default=0.0)          # before scheme discount
    discount = Column(Float, default=0.0)
    levy = Column(Float, default=0.0)           # patient co-payment
    dispensing_fee = Column(Float, default=0.0)
    icd10_code = Column(String(12), default="")
    authorisation = Column(String(40), default="")
    batch_id = Column(Integer, ForeignKey("claim_batches.id"), nullable=True, index=True)
    settled_amount = Column(Float, default=0.0)
    settled_at = Column(DateTime, nullable=True)

    sale = relationship("Sale", back_populates="claim")
    patient = relationship("Patient")
    medical_aid = relationship("MedicalAid")
    batch = relationship("ClaimBatch", back_populates="claims")


class StockMovement(Base, TenantMixin):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    movement_type = Column(String(20), nullable=False)  # receive | sale | adjustment | return
    quantity_delta = Column(Integer, nullable=False)
    balance_after = Column(Integer, default=0)
    reference = Column(String(60), default="")
    notes = Column(Text, default="")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), index=True)

    product = relationship("Product")
    user = relationship("User")


class PurchaseOrder(Base, TenantMixin):
    __tablename__ = "purchase_orders"
    id = Column(Integer, primary_key=True)
    order_number = Column(String(30), nullable=False, index=True)
    #: Which shop raised it, and which shop the goods are for.
    #:
    #: Purchasing was the one measure on the branch scorecard that genuinely
    #: could not be split by branch — because an order recorded none. A group
    #: buying for three shops through one system could not see which of them
    #: was ordering what. "We cannot measure that" was true only in the sense
    #: that nothing had been written down, which is a gap and not a law.
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    status = Column(String(20), default="draft")  # draft | sent | received | cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    received_at = Column(DateTime, nullable=True)
    notes = Column(Text, default="")

    supplier = relationship("Supplier")
    items = relationship("PurchaseOrderItem", back_populates="order", cascade="all, delete-orphan")


class PurchaseOrderItem(Base, TenantMixin):
    __tablename__ = "purchase_order_items"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity_ordered = Column(Integer, default=0)
    quantity_received = Column(Integer, default=0)
    unit_cost = Column(Float, default=0.0)

    order = relationship("PurchaseOrder", back_populates="items")
    product = relationship("Product")


class SupplierInvoice(Base, TenantMixin):
    """What the supplier says is owed, as against what we thought we ordered.

    The purchase order is our intention and the goods receipt is what arrived.
    Neither is a bill. Until this table existed the ledger raised the creditor
    from the order's own costs, which quietly assumes the supplier charged what
    we expected, so a price rise between ordering and delivery was absorbed
    without anybody seeing it, and a supplier who billed for twelve when ten
    arrived was paid for twelve.
    """
    __tablename__ = "supplier_invoices"
    id = Column(Integer, primary_key=True)
    #: The supplier's number, not ours. Two suppliers may well use the same one.
    invoice_number = Column(String(40), nullable=False, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)
    #: The order it bills for. Nullable: some invoices arrive for stock nobody
    #: raised an order against, and refusing to record those would push them
    #: back onto the spike on the counter, which is where they were before.
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True, index=True)
    invoice_date = Column(Date, default=date.today, index=True)
    due_date = Column(Date, nullable=True, index=True)
    #: As billed, gross of tax, in the invoice's own currency.
    total = Column(Float, default=0.0)
    vat_total = Column(Float, default=0.0)
    currency_code = Column(String(3), default="USD")
    #: unmatched | matched | queried | approved | paid
    #:
    #: `queried` is a real state, not a failure: a disputed invoice is not
    #: unmatched, and the difference between the two is whether anybody has
    #: telephoned the supplier yet.
    status = Column(String(20), default="unmatched", index=True)
    query_note = Column(Text, default="")
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    posted_reference = Column(String(30), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    supplier = relationship("Supplier")
    order = relationship("PurchaseOrder")
    items = relationship("SupplierInvoiceItem", back_populates="invoice",
                         cascade="all, delete-orphan")


class SupplierInvoiceItem(Base, TenantMixin):
    """A billed line. Optional, and the match says so when they are absent.

    Entering every line off a wholesaler's invoice is real work, so a pharmacy
    is allowed to record the total alone. What it must not do is call that a
    three-way match, because a total that agrees can still hide two errors
    cancelling out.
    """
    __tablename__ = "supplier_invoice_items"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("supplier_invoices.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    #: What the invoice calls it, kept verbatim: matching by name is how an
    #: unrecognised line gets identified later.
    description = Column(String(200), default="")
    quantity = Column(Integer, default=0)
    unit_cost = Column(Float, default=0.0)
    line_total = Column(Float, default=0.0)

    invoice = relationship("SupplierInvoice", back_populates="items")
    product = relationship("Product")


class SupplierPayment(Base, TenantMixin):
    """Money going out. Before this, trade creditors only ever grew."""
    __tablename__ = "supplier_payments"
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)
    paid_on = Column(Date, default=date.today, index=True)
    amount = Column(Float, default=0.0)
    #: bank | cash | ecocash | cheque
    method = Column(String(20), default="bank")
    reference = Column(String(60), default="")
    currency_code = Column(String(3), default="USD")
    posted_reference = Column(String(30), default="")
    notes = Column(Text, default="")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    supplier = relationship("Supplier")
    allocations = relationship("SupplierPaymentAllocation", back_populates="payment",
                               cascade="all, delete-orphan")


class SupplierPaymentAllocation(Base, TenantMixin):
    """Which invoice a payment settled.

    Kept separate from the payment because one transfer routinely settles five
    invoices, and a remittance advice the supplier can reconcile is the whole
    reason to record it at that grain. An unallocated payment is still a real
    payment; it sits against the supplier until somebody says what it was for.
    """
    __tablename__ = "supplier_payment_allocations"
    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey("supplier_payments.id"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("supplier_invoices.id"), nullable=False, index=True)
    amount = Column(Float, default=0.0)

    payment = relationship("SupplierPayment", back_populates="allocations")
    invoice = relationship("SupplierInvoice")


class RegisterEntry(Base, TenantMixin):
    """Electronic schedule register, immutable log for S5/S6 substances."""
    __tablename__ = "register_entries"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    schedule = Column(Integer, nullable=False)
    entry_type = Column(String(20), nullable=False)  # dispense | receive | adjustment
    quantity_delta = Column(Integer, nullable=False)
    balance_after = Column(Integer, default=0)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    prescription_item_id = Column(Integer, ForeignKey("prescription_items.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reference = Column(String(60), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    product = relationship("Product")
    patient = relationship("Patient")
    doctor = relationship("Doctor")
    user = relationship("User")


# ==================== CRM ====================

class Company(Base, TenantMixin):
    """A corporate account, clinic, old-age home, employer, wholesale buyer."""
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False, index=True)
    account_type = Column(String(30), default="business")  # clinic | old_age_home | employer | wholesale | business
    phone = Column(String(30), default="")
    email = Column(String(120), default="")
    address = Column(Text, default="")
    vat_number = Column(String(30), default="")
    credit_terms_days = Column(Integer, default=30)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="active")  # active | prospect | dormant
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User")
    contacts = relationship("Contact", back_populates="company")


class Contact(Base, TenantMixin):
    """A person in the CRM. A lead, a corporate contact, or a linked patient."""
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(80), nullable=False)
    last_name = Column(String(80), nullable=False, index=True)
    job_title = Column(String(120), default="")
    email = Column(String(120), default="")
    phone = Column(String(30), default="")
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    lifecycle_stage = Column(String(20), default="lead")  # lead | qualified | customer | lost
    source = Column(String(40), default="")  # walk_in | referral | website | campaign | event
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    marketing_opt_in = Column(Boolean, default=False)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="contacts")
    patient = relationship("Patient")
    owner = relationship("User")


class Lead(Base, TenantMixin):
    """An unqualified enquiry, converts into Account + Contact + Opportunity."""
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(80), nullable=False)
    last_name = Column(String(80), nullable=False, index=True)
    company_name = Column(String(160), default="")
    job_title = Column(String(120), default="")
    email = Column(String(120), default="", index=True)
    phone = Column(String(30), default="")
    source = Column(String(40), default="")     # web | referral | event | campaign | walk_in | phone
    status = Column(String(20), default="new")  # new | working | nurturing | converted | disqualified
    rating = Column(String(10), default="cold")  # hot | warm | cold — derived from score
    score = Column(Integer, default=0)
    estimated_value = Column(Float, default=0.0)
    interest = Column(Text, default="")
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    marketing_opt_in = Column(Boolean, default=False)
    disqualified_reason = Column(String(200), default="")
    converted_at = Column(DateTime, nullable=True)
    converted_company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    converted_contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    converted_deal_id = Column(Integer, ForeignKey("deals.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    owner = relationship("User")
    campaign = relationship("Campaign")


class DealItem(Base, TenantMixin):
    """A product line on an opportunity. The deal value is the sum of its lines."""
    __tablename__ = "deal_items"
    id = Column(Integer, primary_key=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    description = Column(String(220), default="")
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, default=0.0)
    discount_percent = Column(Float, default=0.0)
    line_total = Column(Float, default=0.0)

    deal = relationship("Deal", back_populates="items")
    product = relationship("Product")


class Quote(Base, TenantMixin):
    """A versioned quotation generated from an opportunity."""
    __tablename__ = "quotes"
    id = Column(Integer, primary_key=True)
    quote_number = Column(String(30), nullable=False, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=False)
    version = Column(Integer, default=1)
    status = Column(String(20), default="draft")  # draft | sent | accepted | declined | expired
    valid_until = Column(Date, nullable=True)
    subtotal = Column(Float, default=0.0)
    vat_amount = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    terms = Column(Text, default="")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    decided_at = Column(DateTime, nullable=True)

    deal = relationship("Deal")
    created_by = relationship("User")


class EmailTemplate(Base, TenantMixin):
    """Reusable message templates for campaigns and ticket replies."""
    __tablename__ = "email_templates"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    category = Column(String(30), default="general")  # campaign | ticket | deal | general
    channel = Column(String(10), default="email")
    subject = Column(String(200), default="")
    body = Column(Text, default="")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    created_by = relationship("User")


class AutomationRule(Base, TenantMixin):
    """Declarative CRM automation, assignment, escalation and lead scoring."""
    __tablename__ = "automation_rules"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    rule_type = Column(String(30), nullable=False)  # lead_assignment | lead_scoring | ticket_assignment | ticket_escalation | deal_task
    trigger_field = Column(String(60), default="")   # e.g. source, category, priority, stage
    trigger_value = Column(String(120), default="")  # matched case-insensitively; blank = any
    action = Column(String(30), default="")          # assign | score | escalate | create_task
    action_value = Column(String(160), default="")   # user id, score delta, priority, task subject
    active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=100)
    times_fired = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Deal(Base, TenantMixin):
    """A sales opportunity, supply contract, wellness programme, chronic delivery."""
    __tablename__ = "deals"
    id = Column(Integer, primary_key=True)
    title = Column(String(180), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    value = Column(Float, default=0.0)
    stage = Column(String(20), default="new", index=True)  # new|qualified|proposal|negotiation|won|lost
    probability = Column(Integer, default=10)
    expected_close_date = Column(Date, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    source = Column(String(40), default="")
    notes = Column(Text, default="")
    lost_reason = Column(String(200), default="")
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    company = relationship("Company")
    contact = relationship("Contact")
    owner = relationship("User")
    campaign = relationship("Campaign")
    items = relationship("DealItem", back_populates="deal",
                         cascade="all, delete-orphan", order_by="DealItem.id")


class Activity(Base, TenantMixin):
    """A call, meeting, task or note against any CRM record."""
    __tablename__ = "activities"
    id = Column(Integer, primary_key=True)
    activity_type = Column(String(20), default="note")  # call | meeting | task | note | email
    subject = Column(String(200), nullable=False)
    body = Column(Text, default="")
    due_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User")
    company = relationship("Company")
    contact = relationship("Contact")
    deal = relationship("Deal")


class Campaign(Base, TenantMixin):
    """A marketing campaign to a data-driven segment of patients/contacts."""
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    channel = Column(String(10), default="sms")  # sms | email
    segment = Column(String(40), default="all_patients")
    subject = Column(String(200), default="")
    body = Column(Text, default="")
    status = Column(String(20), default="draft")  # draft | sent
    audience_size = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    created_by = relationship("User")


class Ticket(Base, TenantMixin):
    """A customer-service / help-desk ticket with an SLA target."""
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    ticket_number = Column(String(30), nullable=False, index=True)
    subject = Column(String(200), nullable=False)
    description = Column(Text, default="")
    category = Column(String(30), default="query")  # query | complaint | refund | script_issue | delivery | stock | other
    priority = Column(String(10), default="normal")  # low | normal | high | urgent
    status = Column(String(20), default="open", index=True)  # open | pending | resolved | closed
    channel = Column(String(20), default="walk_in")  # walk_in | phone | email | sms | web
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    due_at = Column(DateTime, nullable=True)
    first_response_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    satisfaction = Column(Integer, nullable=True)  # 1-5 CSAT

    patient = relationship("Patient")
    contact = relationship("Contact")
    company = relationship("Company")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    messages = relationship("TicketMessage", back_populates="ticket",
                            cascade="all, delete-orphan", order_by="TicketMessage.created_at")


class TicketMessage(Base, TenantMixin):
    __tablename__ = "ticket_messages"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    from_customer = Column(Boolean, default=False)
    internal_note = Column(Boolean, default=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="messages")
    author = relationship("User")


class AuditLog(Base, TenantMixin):
    """Immutable per-user action log for every state-changing API call."""
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(50), default="", index=True)
    action = Column(String(10), nullable=False)       # HTTP method
    path = Column(String(200), nullable=False)
    summary = Column(String(200), default="")         # human-readable description
    status_code = Column(Integer, default=0)
    ip_address = Column(String(45), default="")

    # Who was REALLY doing this.
    #
    # When head office signs in as a branch user to see what they see, every
    # row they write would otherwise be attributed to that user, so the trail
    # would say a cashier in Bulawayo voided a sale at two in the morning when
    # it was actually somebody at head office. An impersonated action has to
    # name both people or the audit log is actively misleading, which is worse
    # than not having one.
    acted_as_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    acted_as = Column(String(50), default="")

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Two columns point at users now, who the action was recorded against,
    # and who was really doing it, so the join has to say which one it means.
    user = relationship("User", foreign_keys=[user_id])
    acted_as_user = relationship("User", foreign_keys=[acted_as_id])


class FiscalDay(Base, TenantMixin):
    """A trading day as the revenue authority sees it.

    Fiscalisation regimes work in days: you open one, submit receipts against
    it, and close it with totals (the Z-report). Receipt counters reset per day;
    the global counter never does.
    """
    __tablename__ = "fiscal_days"
    id = Column(Integer, primary_key=True)
    day_number = Column(Integer, nullable=False, index=True)
    device_id = Column(String(40), default="")
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="open")     # open | closed | submitted | rejected
    receipt_count = Column(Integer, default=0)
    total_sales = Column(Float, default=0.0)        # base currency
    total_vat = Column(Float, default=0.0)
    total_credit_notes = Column(Float, default=0.0)
    submitted_at = Column(DateTime, nullable=True)
    response_ref = Column(String(80), default="")
    error = Column(Text, default="")

    receipts = relationship("FiscalReceipt", back_populates="fiscal_day")


class FiscalReceipt(Base, TenantMixin):
    """The fiscal record of one sale — immutable once accepted.

    `previous_hash` chains each receipt to the one before it, so removing or
    editing a receipt after the fact breaks the chain and is detectable. This
    is the core of every fiscal-device regime and is why a fiscalised sale can
    never be voided — it is reversed with a credit note instead.
    """
    __tablename__ = "fiscal_receipts"
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False, index=True)
    fiscal_day_id = Column(Integer, ForeignKey("fiscal_days.id"), nullable=False, index=True)
    receipt_type = Column(String(20), default="sale")   # sale | credit_note
    receipt_counter = Column(Integer, default=0)        # resets each fiscal day
    global_counter = Column(Integer, default=0)         # never resets
    currency_code = Column(String(5), default="")
    total = Column(Float, default=0.0)
    vat_amount = Column(Float, default=0.0)
    previous_hash = Column(String(64), default="")
    receipt_hash = Column(String(64), default="", index=True)
    signature = Column(Text, default="")
    qr_data = Column(Text, default="")
    verification_url = Column(String(300), default="")
    # queued keeps the till trading while the authority is unreachable
    status = Column(String(20), default="queued")       # queued | submitted | accepted | rejected
    attempts = Column(Integer, default=0)
    submitted_at = Column(DateTime, nullable=True)
    response_code = Column(String(40), default="")
    response_message = Column(Text, default="")
    reverses_receipt_id = Column(Integer, ForeignKey("fiscal_receipts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    sale = relationship("Sale")
    fiscal_day = relationship("FiscalDay", back_populates="receipts")


class ExchangeRate(Base, TenantMixin):
    """A dated exchange rate against the base currency.

    Rates are appended, never edited, so a sale settled last week keeps the rate
    that applied at the time. In a fast-moving currency that is the difference
    between books that reconcile and books that do not.

    `units_per_base` is how the rate is actually quoted on the street: how many
    units of this currency buy one unit of the base. 26 ZiG to the USD is 26.0.
    """
    __tablename__ = "exchange_rates"
    id = Column(Integer, primary_key=True)
    currency_code = Column(String(5), nullable=False, index=True)
    units_per_base = Column(Float, nullable=False)
    effective_from = Column(DateTime, default=datetime.utcnow, index=True)
    source = Column(String(40), default="manual")
    note = Column(String(200), default="")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_by = relationship("User")


class SaleTender(Base, TenantMixin):
    """One payment against a sale.

    A sale can be settled with several of these at once — part USD cash, part
    ZiG cash, part card, which is ordinary behaviour in a dual-currency market.
    Each records the rate used so the base-currency value never drifts.
    """
    __tablename__ = "sale_tenders"
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False, index=True)
    method = Column(String(20), default="cash")      # cash | card | mobile_money | medical_aid | loyalty
    currency_code = Column(String(5), nullable=False)
    amount = Column(Float, default=0.0)              # as handed over, in that currency
    rate_used = Column(Float, default=1.0)           # units of this currency per base
    amount_in_base = Column(Float, default=0.0)
    is_change = Column(Boolean, default=False)       # change given back, held as a negative tender
    reference = Column(String(60), default="")       # auth code, EcoCash reference…
    # WHICH ecocash, WHICH bank. The wallet used to be parsed back out of the
    # first word of `reference`, which meant a cashier typing "Ecocash-0779"
    # moved the money to a wallet the pharmacy does not have — silently, and
    # only on the screen that did the parsing. It is a fact about the payment,
    # so it is a column. See PaymentInstrument.
    instrument = Column(String(30), default="", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sale = relationship("Sale", back_populates="tenders")


class Shift(Base, TenantMixin):
    """Cashier shift with opening float and end-of-shift cash-up."""
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    opening_float = Column(Float, default=0.0)
    counted_cash = Column(Float, default=0.0)
    expected_cash = Column(Float, default=0.0)
    variance = Column(Float, default=0.0)
    card_total = Column(Float, default=0.0)
    medical_aid_total = Column(Float, default=0.0)
    sales_count = Column(Integer, default=0)
    notes = Column(Text, default="")
    status = Column(String(10), default="open")  # open | closed

    # Which drawer, on which till, on which run. The incumbent keys its whole
    # cash-up on these three and it is the right key: a till can be cashed up
    # more than once a day, and two people can share one till across a
    # handover, so "today's takings" is not a unit anyone can reconcile.
    till_no = Column(String(10), default="")
    run_number = Column(Integer, default=0, index=True)
    draw_no = Column(String(10), default="")
    branch_id = Column(Integer, ForeignKey("branches.id"), index=True)
    # The full reconciliation as counted, including the denomination breakdown.
    # "The drawer was 12 short" is not a useful record without knowing whether
    # that was one missing twenty and eight extra singles.
    cashup_json = Column(Text, default="")
    counted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    counted_at = Column(DateTime, nullable=True)
    # Two columns now point at users, whose shift it is, and who counted
    # the drawer, so the join has to say which one it means.
    user = relationship("User", foreign_keys=[user_id])
    counted_by = relationship("User", foreign_keys=[counted_by_id])


class StockBatch(Base, TenantMixin):
    """A received lot of a product with its own expiry date. FEFO consumption."""
    __tablename__ = "stock_batches"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    batch_number = Column(String(60), nullable=False)
    expiry_date = Column(Date, nullable=True, index=True)
    quantity_received = Column(Integer, default=0)
    quantity_remaining = Column(Integer, default=0)
    unit_cost = Column(Float, default=0.0)
    reference = Column(String(60), default="")
    received_at = Column(DateTime, default=datetime.utcnow)
    # Stock is held per branch. A batch without one is stock nobody can locate.
    branch_id = Column(Integer, ForeignKey("branches.id"), index=True)

    product = relationship("Product")


class BatchAllocation(Base, TenantMixin):
    """Which batch(es) a stock-out drew from, enables exact void restoration."""
    __tablename__ = "batch_allocations"
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("stock_batches.id"), nullable=False)
    sale_item_id = Column(Integer, ForeignKey("sale_items.id"), nullable=True, index=True)
    quantity = Column(Integer, nullable=False)
    reference = Column(String(60), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    batch = relationship("StockBatch")
    sale_item = relationship("SaleItem", backref="allocations")


class Message(Base, TenantMixin):
    """Outbound patient communication: repeat reminders, birthdays, free-type."""
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    channel = Column(String(10), nullable=False, default="sms")  # sms | email
    message_type = Column(String(20), default="custom")  # repeat | birthday | custom | auto_refill
    subject = Column(String(200), default="")
    body = Column(Text, default="")
    status = Column(String(20), default="pending")  # pending | sent | failed
    detail = Column(String(200), default="")
    scheduled_for = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)

    patient = relationship("Patient")


# ---------------------------------------------------------------------------
# Pre-authorisation
#
# An authorisation is not a number to file against a claim — it is a promise
# with an expiry date and a balance. A pharmacy that stores only the number will
# dispense against an authorisation that has run out or lapsed, and find out
# when the claim is rejected weeks later. So what was authorised and what has
# been drawn against it are both tracked, and the draw is what the claim checks.
# ---------------------------------------------------------------------------

class Authorisation(Base, TenantMixin):
    __tablename__ = "authorisations"
    id = Column(Integer, primary_key=True)
    reference = Column(String(40), nullable=False, index=True)
    authorisation_number = Column(String(60), default="", index=True)  # the funder's own
    funder_id = Column(String(40), default="", index=True)
    switch_id = Column(String(40), default="")
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    policy_number = Column(String(40), default="")
    dependent_code = Column(String(10), default="")
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    description = Column(String(200), default="")
    icd10_code = Column(String(12), default="")
    motivation = Column(Text, default="")             # why it is being asked for

    requested_quantity = Column(Float, default=0.0)
    approved_quantity = Column(Float, default=0.0)
    requested_amount = Column(Float, default=0.0)
    approved_amount = Column(Float, default=0.0)
    currency_code = Column(String(5), default="USD")

    valid_from = Column(Date, nullable=True)
    valid_to = Column(Date, nullable=True)
    # requested | approved | partial | declined | expired | exhausted | cancelled
    status = Column(String(20), default="requested", index=True)
    decision_reason = Column(Text, default="")
    conditions = Column(Text, default="")

    switch_reference = Column(String(60), default="")
    transaction_id = Column(String(40), default="")
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    decided_at = Column(DateTime, nullable=True)

    patient = relationship("Patient")
    product = relationship("Product")
    requested_by = relationship("User")
    uses = relationship("AuthorisationUse", back_populates="authorisation",
                        cascade="all, delete-orphan")


class AuthorisationUse(Base, TenantMixin):
    """One draw against an authorisation, so the remaining balance is a fact."""
    __tablename__ = "authorisation_uses"
    id = Column(Integer, primary_key=True)
    authorisation_id = Column(Integer, ForeignKey("authorisations.id"), nullable=False, index=True)
    quantity = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    reference = Column(String(60), default="")        # sale, claim or dispensing reference
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=True)
    reversed = Column(Boolean, default=False)         # released when the sale is reversed
    created_at = Column(DateTime, default=datetime.utcnow)

    authorisation = relationship("Authorisation", back_populates="uses")


# ---------------------------------------------------------------------------
# Electronic remittance advice
#
# Approved is not paid. A claim approved at 100 can be remitted at 85 because of
# a levy, a tariff adjustment or a line struck out, and the 15 is the
# pharmacy's exposure, to bill or to write off. Without the advice parsed and
# matched, that gap is invisible until someone reads a bank statement.
# ---------------------------------------------------------------------------

class Remittance(Base, TenantMixin):
    __tablename__ = "remittances"
    id = Column(Integer, primary_key=True)
    remittance_number = Column(String(60), nullable=False, index=True)
    funder_id = Column(String(40), default="", index=True)
    payment_reference = Column(String(60), default="")
    payment_date = Column(Date, nullable=True)
    currency_code = Column(String(5), default="USD")
    total_claimed = Column(Float, default=0.0)
    total_paid = Column(Float, default=0.0)
    # imported | reconciled | disputed
    status = Column(String(20), default="imported", index=True)
    source = Column(String(20), default="switch")     # switch | upload
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    lines = relationship("RemittanceLine", back_populates="remittance",
                         cascade="all, delete-orphan")


class RemittanceLine(Base, TenantMixin):
    __tablename__ = "remittance_lines"
    id = Column(Integer, primary_key=True)
    remittance_id = Column(Integer, ForeignKey("remittances.id"), nullable=False, index=True)
    line_number = Column(Integer, default=0)
    claim_reference = Column(String(60), default="", index=True)
    policy_number = Column(String(40), default="")
    member_name = Column(String(120), default="")
    service_date = Column(Date, nullable=True)
    amount_claimed = Column(Float, default=0.0)
    amount_allowed = Column(Float, default=0.0)
    amount_paid = Column(Float, default=0.0)
    reason_code = Column(String(30), default="")
    reason = Column(String(200), default="")
    # matched | short_paid | rejected | unmatched | overpaid
    status = Column(String(20), default="unmatched", index=True)
    variance = Column(Float, default=0.0)             # claimed - paid
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=True)
    gateway_transaction_id = Column(String(40), default="")
    written_off = Column(Boolean, default=False)
    patient_billed = Column(Boolean, default=False)
    # Our note about how the shortfall was settled, kept apart from `reason`.
    # It used to be appended to the funder's own words, which meant every
    # resolution rewrote what the scheme had said and a line resolved a few times
    # ended up reading "Reduced by the member's levy. | uneconomic | uneconomic |
    # uneconomic". The funder's reason is evidence; ours is a working note, and
    # the two must not be mixed.
    resolution_note = Column(String(300), default="")

    remittance = relationship("Remittance", back_populates="lines")
    claim = relationship("Claim")


# ---------------------------------------------------------------------------
# Trading periods
#
# The accounting period everything is filed under. A pharmacy reconciles by
# period, not by date range: "August" must mean the same set of transactions
# every time it is asked for, and must stop meaning something new once the
# month has been signed off. That only holds if a closed period refuses to
# accept new postings — otherwise a backdated sale silently changes a figure
# somebody has already reported.
# ---------------------------------------------------------------------------

class TradingPeriod(Base, TenantMixin):
    __tablename__ = "trading_periods"
    id = Column(Integer, primary_key=True)
    code = Column(String(10), nullable=False, index=True)   # 202608
    name = Column(String(60), default="")                                # August 2026
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    # open   — trading; postings allowed
    # closed — signed off; no new postings, but can be reopened by an admin
    # locked — permanently sealed, typically after a tax return or an audit
    status = Column(String(10), default="open", index=True)
    opened_at = Column(DateTime, default=datetime.utcnow)
    opened_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, default="")

    # Totals frozen at close, so a report of a closed period never has to be
    # recomputed, and any later disagreement is itself the evidence.
    closing_sales = Column(Float, default=0.0)
    closing_vat = Column(Float, default=0.0)
    closing_cost = Column(Float, default=0.0)
    closing_transactions = Column(Integer, default=0)

    opened_by = relationship("User", foreign_keys=[opened_by_id])
    closed_by = relationship("User", foreign_keys=[closed_by_id])


# ---------------------------------------------------------------------------
# Step-up authorisation
#
# Being logged in is not authorisation for everything. Two different needs sit
# behind the same prompt, and conflating them is the usual mistake:
#
#   re-authentication  "prove you are still the person who logged in" — the till
#                      has been unattended, and the action is destructive
#   supervisor override "get someone senior to approve what you cannot" — the
#                      cashier cannot discount, so the manager walks over and
#                      types their own password
#
# The second is the one that actually happens in a pharmacy, and it is why the
# grant records both who performed the action and who approved it.
# ---------------------------------------------------------------------------

class StepUpGrant(Base, TenantMixin):
    __tablename__ = "step_up_grants"
    id = Column(Integer, primary_key=True)
    action = Column(String(40), nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    # Who is at the till, and who authorised them. The same person for a
    # re-authentication; different people for a supervisor override.
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    granted = Column(Boolean, default=False)
    reason = Column(String(200), default="")          # why it was refused, if it was
    context = Column(String(200), default="")         # what it was for: sale 412, product 7
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime, nullable=True)
    used_at = Column(DateTime, nullable=True)

    requested_by = relationship("User", foreign_keys=[requested_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])


class OwedItem(Base, TenantMixin):
    """A "to follow" — medicine the patient has paid for and the pharmacy still owes.

    The pharmacy is out of stock, the patient is at the counter, and the choice
    is to send them away or to supply what there is and owe the rest. Every
    pharmacy chooses the second, which means the debt exists whether or not the
    software knows about it. If the software does not, it lives on a note stuck
    to the till, and it is forgotten, or honoured twice, or argued about.

    This is that debt as a record: what is owed, to whom, against which script
    line, and what has been handed over since.
    """
    __tablename__ = "owed_items"
    id = Column(Integer, primary_key=True)
    reference = Column(String(30), nullable=False, index=True)
    prescription_item_id = Column(Integer, ForeignKey("prescription_items.id"),
                                  nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    # The sale where the patient paid for the whole quantity, including the part
    # not handed over. It is why this is a debt and not simply a short supply.
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True)

    quantity_owed = Column(Integer, default=0)
    quantity_settled = Column(Integer, default=0)
    # outstanding | settled | cancelled
    status = Column(String(20), default="outstanding", index=True)
    promised_for = Column(Date, nullable=True)      # what the patient was told
    notes = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    settled_at = Column(DateTime, nullable=True)
    cancelled_reason = Column(String(200), default="")

    prescription_item = relationship("PrescriptionItem")
    patient = relationship("Patient")
    product = relationship("Product")
    created_by = relationship("User")


class CounterMessage(Base, TenantMixin):
    """A note that must surface at the counter, not one filed somewhere.

    Propharm devotes five tabs to these — patient, member, medical aid, scheme
    user, allergies — because the information that stops a mistake is useless if
    it lives on a record nobody opens mid-transaction. A note the pharmacist has
    to go looking for is not a note.

    `severity` is the part that earns its keep:

        info   shown, and that is all
        warn   shown prominently; the pharmacist may proceed
        stop   dispensing is refused until somebody acknowledges it by name

    `stop` is deliberately rare and deliberately blocking. A patient with a
    documented anaphylactic allergy is not a case for a yellow banner that a
    busy assistant scrolls past.
    """
    __tablename__ = "counter_messages"
    id = Column(Integer, primary_key=True)
    # patient | member | scheme | product | doctor
    scope = Column(String(16), nullable=False, index=True)
    target_id = Column(Integer, nullable=True, index=True)   # null = every target in scope
    severity = Column(String(8), default="info", index=True)  # info | warn | stop
    body = Column(Text, nullable=False)
    category = Column(String(30), default="")   # allergy | debt | scheme_rule | clinical
    active = Column(Boolean, default=True, index=True)
    expires_on = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_by = relationship("User")


class MessageAcknowledgement(Base, TenantMixin):
    """Who read a blocking message, and when. The reason `stop` is worth having."""
    __tablename__ = "message_acknowledgements"
    id = Column(Integer, primary_key=True)
    # No foreign key: a derived warning (an allergy match) has a negative
    # pseudo-id and no stored row, and it still has to be acknowledgeable.
    message_id = Column(Integer, nullable=False, index=True)
    prescription_id = Column(Integer, ForeignKey("prescriptions.id"), nullable=True)
    acknowledged_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    acknowledged_at = Column(DateTime, default=datetime.utcnow)
    note = Column(String(200), default="")

    acknowledged_by = relationship("User")


class Reprint(Base, TenantMixin):
    """Every reprint of a script or a label.

    Labels jam, peel and end up on the wrong box, so reprinting is a daily
    action rather than an exception, but a second label for a controlled
    substance is also the easiest way to make one dispensing look like two.
    Recording who reprinted what costs nothing and answers the question later.
    """
    __tablename__ = "reprints"
    id = Column(Integer, primary_key=True)
    kind = Column(String(12), nullable=False)        # script | label
    prescription_id = Column(Integer, ForeignKey("prescriptions.id"), nullable=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True, index=True)
    reason = Column(String(200), default="")
    printed_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    printed_at = Column(DateTime, default=datetime.utcnow, index=True)

    prescription = relationship("Prescription")
    printed_by = relationship("User")


# ---------------------------------------------------------------------------
# General ledger
#
# Double entry, because it is the only bookkeeping that can tell you it is
# wrong. A single-entry list of transactions always adds up to whatever it adds
# up to; a balanced journal cannot hide a missing side.
# ---------------------------------------------------------------------------

class Account(Base, TenantMixin):
    # A code is unique WITHIN a pharmacy, not across the estate.
    #
    # It was globally unique, which reads as harmless until you notice what it
    # means on a shared database: the first pharmacy to start seeds "1000 Cash
    # on hand" and every pharmacy after it fails to seed anything at all,
    # because 1000 is taken. Seventeen pharmacies on this database and exactly
    # one of them had a chart of accounts. Every ledger screen for the other
    # sixteen was empty and nothing anywhere said why.
    __table_args__ = (
        UniqueConstraint("pharmacy_id", "code", name="uq_accounts_tenant_code"),
    )
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True)
    code = Column(String(10), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    # asset | liability | equity | income | expense
    type = Column(String(12), nullable=False, index=True)
    # A control account is the general ledger's summary of a subledger. Its
    # balance must equal the subledger it controls, and the day it does not is
    # the day something was posted around the subledger instead of through it.
    # That check is the whole reason to keep them separate.
    subledger = Column(String(20), default="", index=True)  # debtors | creditors | stock | vat
    parent_code = Column(String(10), default="")
    # Where this account appears on a statement. `type` says what an account is;
    # this says where a reader expects to find it. Stock and a delivery van are
    # both assets and belong in different halves of the balance sheet, and no
    # amount of inspecting the type column will separate them.
    #
    # current_asset | non_current_asset | current_liability |
    # non_current_liability | equity | revenue | cogs | operating_expense |
    # other_income | other_expense
    section = Column(String(24), default="", index=True)
    # Whether this account IS cash. A cash flow statement has to know, and no
    # combination of type and section can tell it: cash, stock and money owed by
    # a medical scheme are all current assets, and only one of them is something
    # you can pay a supplier with.
    is_cash = Column(Boolean, default=False, index=True)
    active = Column(Boolean, default=True)
    notes = Column(Text, default="")


class JournalEntry(Base, TenantMixin):
    __tablename__ = "journal_entries"
    id = Column(Integer, primary_key=True)
    reference = Column(String(30), nullable=False, index=True)
    period_code = Column(String(10), default="", index=True)
    entry_date = Column(Date, nullable=False, index=True)
    description = Column(String(240), default="")
    # What in the business caused this: sale, credit note, stock receipt.
    source = Column(String(30), default="", index=True)
    source_id = Column(Integer, nullable=True, index=True)
    currency_code = Column(String(5), default="USD")
    # posted | reversed
    status = Column(String(12), default="posted", index=True)
    reverses_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    lines = relationship("JournalLine", back_populates="entry",
                         cascade="all, delete-orphan")
    created_by = relationship("User")


class JournalLine(Base, TenantMixin):
    __tablename__ = "journal_lines"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=False, index=True)
    account_code = Column(String(10), nullable=False, index=True)
    debit = Column(Float, default=0.0)
    credit = Column(Float, default=0.0)
    description = Column(String(240), default="")
    # Which subledger party this line belongs to, where it belongs to one — the
    # patient who owes, the supplier who is owed. Without it a control account
    # can be reconciled in total but never by party, which is the only way an
    # actual disagreement gets found.
    party_type = Column(String(20), default="", index=True)   # patient | supplier | scheme
    party_id = Column(Integer, nullable=True, index=True)

    entry = relationship("JournalEntry", back_populates="lines")


class Waybill(Base, TenantMixin):
    """Medicine leaving the shop for somewhere other than the counter.

    A delivery is the one point where dispensed medicine is out of the
    pharmacy's hands and not yet in the patient's. Without a document there is
    no answer to "who had it and when", which matters ordinarily for a lost
    parcel and considerably more when the parcel held a controlled substance.

    Also the hook the deliverer app will need: a waybill is the unit of work
    that gets assigned, carried and signed for.
    """
    __tablename__ = "waybills"
    id = Column(Integer, primary_key=True)
    waybill_number = Column(String(30), nullable=False, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True, index=True)
    prescription_id = Column(Integer, ForeignKey("prescriptions.id"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)

    recipient = Column(String(160), default="")
    address = Column(Text, default="")
    phone = Column(String(30), default="")
    instructions = Column(Text, default="")
    # pending | out | delivered | failed | cancelled
    status = Column(String(12), default="pending", index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Who actually took it. A delivery signed for by nobody is not a delivery.
    received_by = Column(String(120), default="")
    failure_reason = Column(String(200), default="")
    # A controlled substance leaving the premises needs identity checked at the
    # door, not at the counter it never reached.
    requires_id_check = Column(Boolean, default=False)
    id_number_seen = Column(String(30), default="")

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    dispatched_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)

    # ---- what the round is worth, and what comes back from it ------------
    #
    # A delivery moves two sums of money and the shop needs both. The fee is
    # revenue the pharmacy earns for driving; the COD is the sale itself, paid
    # at the door instead of at the counter. Neither was recorded anywhere, so
    # a shop running twenty deliveries a day could not say what delivering cost
    # it, what it charged for it, or how much of its takings was in a driver's
    # pocket rather than in a till.
    delivery_fee = Column(Float, default=0.0)
    #: What the driver is to collect. Zero on a delivery already paid for.
    cod_amount = Column(Float, default=0.0)
    #: What the driver actually came back with. Not the same figure — that is
    #: the entire point of recording both.
    cod_collected = Column(Float, default=0.0)
    cod_instrument = Column(String(30), default="")
    cod_reference = Column(String(60), default="")
    #: Handed in and reconciled. Until this is set, the money is on the road,
    #: which is why it must not be counted against the counter's drawer.
    cod_settled_at = Column(DateTime, nullable=True)
    cod_shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=True, index=True)

    #: The driver as a person the pharmacy employs or contracts, which is not
    #: the same as a login. See Driver.
    driver_profile_id = Column(Integer, ForeignKey("drivers.id"),
                               nullable=True, index=True)

    sale = relationship("Sale")
    patient = relationship("Patient")
    driver = relationship("User", foreign_keys=[driver_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    driver_profile = relationship("Driver", back_populates="waybills")

    @property
    def cod_outstanding(self) -> float:
        """What this delivery still owes the shop."""
        if self.cod_settled_at:
            return 0.0
        return round((self.cod_amount or 0.0) - (self.cod_collected or 0.0), 2)


class Driver(Base, TenantMixin):
    """Somebody who carries medicine out of the shop.

    A driver was a foreign key to `users`, which meant a driver had to be a
    person with a login, and most are not. The runner on the motorbike does
    not use the dispensing system, the courier the shop uses on Saturdays is
    not staff at all, and neither should need a seat licence to be named on a
    waybill.

    It also meant there was nowhere to keep the things you actually need about
    a driver: which vehicle, whose licence, whether it is still valid, what
    their phone number is when a patient has been waiting two hours. And no way
    to ask the questions a delivery operation is run on, who is out right now,
    who is holding cash, whose deliveries fail.

    The `user_id` link stays optional. A driver who is also a staff member gets
    one; a contractor does not.
    """
    __tablename__ = "drivers"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), default="", index=True)
    full_name = Column(String(120), nullable=False)
    phone = Column(String(30), default="")
    alternate_phone = Column(String(30), default="")
    national_id = Column(String(30), default="")

    #: A staff driver has a login; a contracted one does not.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)

    #: motorbike | car | van | bicycle | on_foot
    vehicle_type = Column(String(20), default="motorbike")
    vehicle_registration = Column(String(20), default="")
    licence_number = Column(String(40), default="")
    #: A licence that expired last month is a driver who should not be sent
    #: out, and nobody finds that out from a filing cabinet.
    licence_expiry = Column(Date, nullable=True)

    #: Cash the driver holds to make change with on a round. Reconciled the
    #: same way a till float is.
    cash_float = Column(Float, default=0.0)
    #: Above this in uncollected COD the driver should be back at the shop.
    #: A round carrying eight hundred dollars is a different risk from one
    #: carrying forty, and somebody should have set the line in advance.
    cod_limit = Column(Float, default=0.0)

    active = Column(Boolean, default=True, index=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    branch = relationship("Branch", foreign_keys=[branch_id])
    waybills = relationship("Waybill", back_populates="driver_profile")


class Setting(Base):
    """Key/value configuration that belongs to the pharmacy, not to the build.

    Columns would need a migration on every customer's database each time one
    pharmacy asks for a field the others do not have. A row does not.
    """
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(120), unique=True, nullable=False, index=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Pharmacy(Base):
    """One pharmacy business. The tenant.

    Everything above a branch: the company that holds the licence, signs the
    medical-aid agreements and owns the patient records. A single-shop pharmacy
    has one of these and one branch under it and never thinks about either.

    This sits above `Branch` rather than replacing it because the two answer
    different questions. A branch is where stock physically is — the Avondale
    shelf tells you nothing about Bulawayo. A pharmacy is who the data belongs
    to, and crossing that line is not an inconvenience, it is one business
    reading another's patients.
    """
    __tablename__ = "pharmacies"

    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    trading_name = Column(String(160), default="")
    # The regulator's number for the business. Branches carry their own too.
    registration_no = Column(String(60), default="")
    phone = Column(String(30), default="")
    email = Column(String(160), default="")
    address = Column(Text, default="")
    city = Column(String(80), default="")
    #: Suspending a tenant has to be possible without deleting their records —
    #: a pharmacy that stops paying still owns its patients' histories, and the
    #: regulator requires those be kept.
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    branches = relationship("Branch", back_populates="pharmacy")


class Branch(Base, TenantMixin):
    """One trading location of the business.

    A single-shop pharmacy has exactly one of these and never thinks about it.
    A group has several, and then the thing that matters is that **stock is held
    per branch**: the Avondale shop having twenty boxes tells you nothing about
    what is on the shelf in Bulawayo. Anything that counts stock has to say which
    branch it is counting, or the number is worse than no number.

    `is_default` exists so that every row written before branches existed, and
    every till that has not been told where it is, has somewhere to belong. A
    nullable branch on a sale would mean "we do not know which shop sold this",
    which is not a state worth allowing.
    """
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True)
    #: Which business this shop belongs to. The anchor of the whole tenancy:
    #: anything reachable from a branch is reachable from exactly one pharmacy.
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id"), nullable=True, index=True)
    code = Column(String(12), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    # Its own registration: a branch is licensed in its own right, and the
    # number that prints on a receipt is the branch's, not the group's.
    registration_no = Column(String(40), default="")
    phone = Column(String(40), default="")
    email = Column(String(120), default="")
    address = Column(Text, default="")
    city = Column(String(80), default="")
    responsible_pharmacist = Column(String(120), default="")
    is_default = Column(Boolean, default=False)
    active = Column(Boolean, default=True)

    # ---- stopped from head office -------------------------------------
    #
    # Distinct from `active`, which means "this shop exists". Frozen means the
    # shop exists and nobody there may write anything: no sale, no dispensing,
    # no stock movement, no cash-up. It is what head office reaches for when a
    # branch is under investigation, when a stock take must not move underneath
    # the counters, or when a manager has walked out with the keys.
    #
    # Reading is deliberately still allowed. A frozen branch that cannot even
    # look up a patient's allergies is a branch that will find a way around the
    # freeze, and the point is to stop the money moving rather than to stop the
    # pharmacists thinking.
    frozen = Column(Boolean, default=False, index=True)
    frozen_at = Column(DateTime, nullable=True)
    frozen_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    #: Never optional in the API. A branch stopped without a stated reason is
    #: an argument nobody can settle afterwards.
    frozen_reason = Column(String(300), default="")

    #: Where the shop is, for the map. Nullable because a pharmacy that has not
    #: pinned its branches yet should not be shown at latitude nought, which is
    #: in the Gulf of Guinea.
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    pharmacy = relationship("Pharmacy", back_populates="branches")
    frozen_by = relationship("User", foreign_keys=[frozen_by_id])


class UserPermission(Base, TenantMixin):
    """One thing a person may do that their role does not already allow.

    A role is a good default and a bad rule. Every pharmacy has the assistant
    who is trusted to void a sale, the locum pharmacist who must not touch
    pricing, the manager who runs two branches and the owner's daughter who
    does the banking on Fridays, and none of them fits a five-word role.

    What happens without this is not that those people are refused. It is that
    somebody gives them an administrator's login, because that is the only
    thing that works, and from then on the audit trail says "admin" for
    everything and the whole control structure is decoration.

    So a grant is one capability, on one person, optionally on one branch, from
    somebody named, with a reason. `allow=False` is the other direction: a
    role that permits something this person specifically may not do.
    """
    __tablename__ = "user_permissions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    #: See services.permissions.CAPABILITIES.
    capability = Column(String(60), nullable=False, index=True)
    #: Scoped to one shop where it should be. A manager who may authorise a
    #: write-off at Avondale should not thereby authorise one in Bulawayo.
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    #: False takes the capability away from somebody whose role would grant it.
    allow = Column(Boolean, default=True)
    reason = Column(String(300), default="")

    # ---- the dimensions a yes/no cannot express ------------------------
    #
    # Real authority in a pharmacy is bounded, and the bound is the whole
    # point. "May void a sale" is not how anybody actually delegates: it is
    # "may void a sale under twenty dollars, at this branch, until the locum
    # leaves, and anything larger needs me". A permission model that can only
    # say yes or no forces every one of those into a yes, which is how an
    # assistant ends up able to void a five-hundred-dollar sale because
    # somebody needed them to void a five-dollar one.
    #
    #: The ceiling, in base currency or in units depending on the capability.
    #: Nought means no ceiling.
    limit_value = Column(Float, default=0.0)
    #: Per day rather than per act, where that is the sensible bound — four
    #: small voids in an afternoon is a pattern a single-transaction limit
    #: cannot see.
    daily_limit = Column(Float, default=0.0)
    #: Above the ceiling, may they proceed with somebody else's approval, or
    #: not at all? A refusal that cannot be escalated is one people work around.
    escalates = Column(Boolean, default=True)
    #: Requires a second named person every time, whatever the amount. For the
    #: acts where one signature was never enough.
    dual_approval = Column(Boolean, default=False)
    #: Only during the hours this person is on. Blank means any time.
    #: "00:00-23:59" style, kept as text because a pharmacy that trades over
    #: midnight makes a time column into two columns and an argument.
    hours = Column(String(20), default="")
    #: Which days, as initials — "MTWTFSS" with blanks for the days off.
    #: Blank means any day.
    days = Column(String(7), default="")

    granted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    granted_at = Column(DateTime, default=datetime.utcnow)
    #: A locum's grant should die with the locum. Nullable for a standing one.
    expires_on = Column(Date, nullable=True, index=True)
    active = Column(Boolean, default=True, index=True)

    user = relationship("User", foreign_keys=[user_id])
    granted_by = relationship("User", foreign_keys=[granted_by_id])
    branch = relationship("Branch", foreign_keys=[branch_id])


class ComplianceDocument(Base, TenantMixin):
    """A licence, certificate or clearance a branch must hold, and when it dies.

    A pharmacy in Zimbabwe trades on a stack of paper that all expires: the
    MCAZ premises licence, the responsible pharmacist's practice certificate,
    the city health shop licence, fire brigade clearance, the ZIMRA tax
    clearance, the dangerous drugs permit. Each has its own issuer, its own
    renewal month and its own consequence for lapsing, and the consequence for
    the first two is that the shop closes.

    Every pharmacy manages this in a lever-arch file and a diary, and the
    failure is always the same: nobody notices a certificate expired until an
    inspector does, or until a wholesaler refuses an order because the licence
    number on file has lapsed. The renewal is rarely difficult. Knowing it is
    due is the whole problem.

    WHY THE DOCUMENT IS STORED HERE AND NOT ONLY THE DATE

    A date without the certificate behind it is a claim. An inspector asks to
    see the licence, not to see a system saying there is one, and the copy in
    the file is at head office while the inspection is at the branch. The file
    is held as bytes on the row for the same reason the logo is: a pharmacy
    running one machine in a back office has no object store, and a path into a
    filesystem is a broken link the first time somebody restores a backup onto
    a different box.
    """
    __tablename__ = "compliance_documents"

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    #: Which of the known kinds this is — see services.compliance.KINDS. Free
    #: text rather than an enum so a pharmacy can hold a document nobody
    #: anticipated without waiting for a release.
    kind = Column(String(40), nullable=False, index=True)
    #: What it is called where a kind does not cover it.
    title = Column(String(160), default="")
    #: The number on the certificate — the thing a wholesaler or an inspector
    #: asks for, and the reason a lapsed one blocks an order.
    reference = Column(String(80), default="")
    issuer = Column(String(120), default="")
    issued_on = Column(Date, nullable=True)
    #: The date everything here exists for. Nullable because some documents do
    #: not expire, and pretending they do puts a false renewal in a diary.
    expires_on = Column(Date, nullable=True, index=True)
    #: What it costs to renew, so a year of compliance can be budgeted rather
    #: than discovered a certificate at a time.
    renewal_cost = Column(Float, default=0.0)

    #: The certificate itself. A date without the document behind it is a
    #: claim; an inspector asks to see the licence.
    file_name = Column(String(200), default="")
    file_type = Column(String(80), default="")
    file_data = Column(Text, default="")          # base64 data URI
    file_bytes = Column(Integer, default=0)

    notes = Column(Text, default="")
    #: Superseded rather than deleted. Last year's certificate is the proof the
    #: shop was licensed last year, which is exactly what an audit asks about.
    superseded_by_id = Column(Integer, ForeignKey("compliance_documents.id"),
                              nullable=True)
    active = Column(Boolean, default=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    branch = relationship("Branch")
    created_by = relationship("User", foreign_keys=[created_by_id])

    @property
    def days_left(self) -> int | None:
        if not self.expires_on:
            return None
        return (self.expires_on - date.today()).days


class BranchTransfer(Base, TenantMixin):
    """Stock moving from one branch to another.

    Deliberately two-sided and not instant. Goods despatched from Avondale are
    not yet on the shelf in Bulawayo, and a system that pretends otherwise will
    show stock at the receiving branch that nobody can physically sell. A
    transfer is raised, then received, and the difference between the two is
    stock in transit, which is a real thing a group needs to see.
    """
    __tablename__ = "branch_transfers"

    id = Column(Integer, primary_key=True)
    reference = Column(String(30), nullable=False, index=True)
    from_branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    to_branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    # despatched | received | cancelled
    status = Column(String(12), default="despatched")
    notes = Column(Text, default="")
    despatched_by_id = Column(Integer, ForeignKey("users.id"))
    received_by_id = Column(Integer, ForeignKey("users.id"))
    despatched_at = Column(DateTime, default=datetime.utcnow)
    received_at = Column(DateTime)

    from_branch = relationship("Branch", foreign_keys=[from_branch_id])
    to_branch = relationship("Branch", foreign_keys=[to_branch_id])
    product = relationship("Product")


class PaymentInstrument(Base, TenantMixin):
    """One thing money can arrive on, named the way the pharmacy names it.

    "Mobile money 119.00" is not a figure anybody can reconcile. EcoCash, Omari
    and InnBucks are three different businesses that settle into three
    different accounts on three different timetables, and the incumbent's own
    cash-up sheet has a column for each — USD, EcoCash USD, Swipe USD, Swipe
    ZWG, EcoCash ZWG — because that is what the bank statements look like.

    The till already knew this and had nowhere to put it, so it wrote the
    wallet into the front of the tender's free-text reference and the takings
    screen read it back out by splitting on the first space. That works until
    somebody types "Ecocash-0779", or a part payment writes "part payment"
    into the same field, and then the money moves to a wallet nobody has, in
    silence. An instrument is a fact about a payment, not a note about it.

    A row rather than a constant because the list is not the same in two
    pharmacies: one banks with CBZ and one with Stanbic, one takes InnBucks and
    one does not, and a new wallet appearing in the market should not need a
    release. Both the till and the cash-up read this table, which is the point
    — they cannot disagree about what the columns are if there is only one list.
    """
    __tablename__ = "payment_instruments"
    __table_args__ = (
        UniqueConstraint("pharmacy_id", "code", name="uq_instrument_code"),
    )

    id = Column(Integer, primary_key=True)
    code = Column(String(30), nullable=False, index=True)
    name = Column(String(60), nullable=False)
    #: Which of the coarse tender families this belongs to. The ledger and the
    #: existing reports group on this, so it stays.
    method = Column(String(20), default="cash", index=True)
    #: Comma-separated currency codes this instrument can actually take.
    #: InnBucks is USD only; offering ZiG on it produces a payment the customer
    #: cannot make.
    currencies = Column(String(60), default="")
    #: Where it lands. A wallet number, a merchant code, a bank account — what
    #: somebody needs in order to tick this column off against a statement.
    settles_to = Column(String(120), default="")
    #: Does this one physically sit in the drawer at close of trade? Cash does.
    #: A swipe does not, and asking somebody to count it is how a cash-up comes
    #: to be signed off without being read.
    is_cash_drawer = Column(Boolean, default=False)
    #: Money the driver collects at the door. Never in the till while the round
    #: is out, and reconciled against the driver rather than the cashier.
    is_delivery = Column(Boolean, default=False)
    active = Column(Boolean, default=True, index=True)
    sort_order = Column(Integer, default=100)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def currency_list(self) -> list:
        return [c.strip().upper() for c in (self.currencies or "").split(",") if c.strip()]


class PettyCash(Base, TenantMixin):
    """Money in or out of the drawer that was not a sale.

    A pharmacy pays the window cleaner out of the till, buys milk, refunds a bus
    fare. Without a record of it the drawer is short at cash-up by exactly that
    amount, every time, and the cashier is asked to explain a variance that is
    not theirs. The incumbent's cash-up screen carries the note "Petty Cash
    Transactions NOT shown in Grid" — it knows the money left and keeps it out
    of the sales list, which is right.

    Signed rather than typed: negative is money out, positive is money in
    (a float top-up, change brought from the safe). One column and a sign beats
    two columns and a rule about which to use.
    """
    __tablename__ = "petty_cash"
    id = Column(Integer, primary_key=True)
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    amount = Column(Float, nullable=False)
    currency_code = Column(String(5), default="")
    category = Column(String(40), default="")     # cleaning, transport, refreshments…
    description = Column(String(240), default="")
    reference = Column(String(60), default="")
    # Whether a receipt or slip was produced. A payout with no receipt is not
    # forbidden, a bus fare rarely has one, but it should be countable.
    receipt_seen = Column(Boolean, default=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User")



class LayBy(Base, TenantMixin):
    """Goods set aside, paid for over time, collected when settled.

    Different from a COD in the way that matters: with a COD the goods have
    gone and the money has not. With a lay-by the money is coming and the goods
    have not gone — they are off the shelf, in the back, belonging to nobody
    until the last instalment.

    Two consequences the accounting has to respect, and both are easy to get
    wrong in a way that flatters the figures:

    **A deposit is not income.** It is money held on behalf of a customer, and
    the pharmacy owes either the goods or the money back. Booking it as revenue
    overstates profit and hides a liability, and the day a lay-by is cancelled
    the "revenue" has to be unwound. Nothing here recognises a sale until the
    final payment.

    **The stock is gone from the shelf the moment the lay-by is raised.** It is
    physically in the back and cannot be sold to anybody else, so it comes out
    of available stock immediately — not on completion. A system that leaves it
    on hand will cheerfully sell the same box twice.
    """
    __tablename__ = "laybys"
    id = Column(Integer, primary_key=True)
    layby_number = Column(String(30), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    # open | completed | cancelled
    status = Column(String(12), default="open", index=True)
    total = Column(Float, default=0.0)
    # What the customer must have paid before the goods can leave. Held on the
    # record rather than recomputed, because a policy that changes next month
    # must not retrospectively alter an agreement made today.
    minimum_deposit = Column(Float, default=0.0)
    due_date = Column(Date, nullable=True, index=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    # Kept when a lay-by is cancelled, where the pharmacy's terms allow it. The
    # rest is refunded.
    cancellation_fee = Column(Float, default=0.0)
    # The sale raised on completion, so the two records point at each other.
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True)

    patient = relationship("Patient")
    created_by = relationship("User", foreign_keys=[created_by_id])
    items = relationship("LayByItem", back_populates="layby",
                         cascade="all, delete-orphan")
    payments = relationship("LayByPayment", back_populates="layby",
                            cascade="all, delete-orphan")

    @property
    def paid(self) -> float:
        return round(sum(p.amount for p in self.payments), 2)

    @property
    def balance(self) -> float:
        return round((self.total or 0) - self.paid, 2)


class LayByItem(Base, TenantMixin):
    """A line on a lay-by, priced when it was agreed.

    The price is copied rather than looked up, because a lay-by is an agreement
    made on a day. A customer paying over three months should not find the
    balance has moved because the shelf price did.
    """
    __tablename__ = "layby_items"
    id = Column(Integer, primary_key=True)
    layby_id = Column(Integer, ForeignKey("laybys.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, default=0.0)

    layby = relationship("LayBy", back_populates="items")
    product = relationship("Product")


class LayByPayment(Base, TenantMixin):
    """One instalment. Append-only: a correction is a negative payment."""
    __tablename__ = "layby_payments"
    id = Column(Integer, primary_key=True)
    layby_id = Column(Integer, ForeignKey("laybys.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    method = Column(String(20), default="cash")
    currency_code = Column(String(5), default="")
    reference = Column(String(60), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    layby = relationship("LayBy", back_populates="payments")
    user = relationship("User")




class StockTake(Base, TenantMixin):
    """A physical count of the shelves, against what the system believes.

    Shrinkage is invisible without this. A pharmacy can reconcile its till to
    the cent every day and still be losing stock, because the till only knows
    about things that were sold.

    A count is a session rather than an event: it opens, lines are counted over
    hours or days, and it is closed once — at which point the variances become
    stock movements and the shelves and the system agree again. Nothing is
    adjusted before the close, so a half-finished count leaves the system exactly
    as it was.
    """
    __tablename__ = "stock_takes"
    id = Column(Integer, primary_key=True)
    reference = Column(String(30), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    # open | closed | abandoned
    status = Column(String(12), default="open", index=True)
    # Narrows what is expected to be counted, so a pharmacy can count one aisle
    # on a Tuesday rather than the whole shop on a Sunday.
    scope_category = Column(String(40), default="")
    scope_bin = Column(String(20), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_by = relationship("User", foreign_keys=[created_by_id])
    closed_by = relationship("User", foreign_keys=[closed_by_id])
    lines = relationship("StockTakeLine", back_populates="stock_take",
                         cascade="all, delete-orphan")


class StockTakeLine(Base, TenantMixin):
    """One product counted.

    `expected` is captured when the line is counted rather than read at close,
    because a count that takes two days would otherwise compare Monday's count
    against Wednesday's system figure and call the difference shrinkage.
    """
    __tablename__ = "stock_take_lines"
    id = Column(Integer, primary_key=True)
    stock_take_id = Column(Integer, ForeignKey("stock_takes.id"),
                           nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    counted = Column(Integer, nullable=False)
    expected = Column(Integer, nullable=False)
    unit_cost = Column(Float, default=0.0)
    counted_at = Column(DateTime, default=datetime.utcnow)
    counted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    note = Column(String(240), default="")

    stock_take = relationship("StockTake", back_populates="lines")
    product = relationship("Product")
    counted_by = relationship("User")

    @property
    def variance(self) -> int:
        return (self.counted or 0) - (self.expected or 0)


class ScriptChange(Base, TenantMixin):
    """What changed on a prescription, and who changed it.

    A script is the one record in this system that carries clinical weight, and
    it is editable. Without a trail, "the dose was changed" has no answer to
    "by whom, from what, and when", and that question is asked precisely when
    something has gone wrong.

    Append-only. A correction is another row.
    """
    __tablename__ = "script_changes"
    id = Column(Integer, primary_key=True)
    prescription_id = Column(Integer, ForeignKey("prescriptions.id"),
                             nullable=False, index=True)
    prescription_item_id = Column(Integer, ForeignKey("prescription_items.id"),
                                  nullable=True, index=True)
    field = Column(String(40), nullable=False)
    old_value = Column(String(240), default="")
    new_value = Column(String(240), default="")
    reason = Column(String(240), default="")
    changed_at = Column(DateTime, default=datetime.utcnow, index=True)
    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    changed_by = relationship("User")




class DosageAbbreviation(Base):
    """A short code a dispenser types, and the words that print on the label.

    Typing "one tablet three times a day after food" forty times a day is how
    directions end up abbreviated on the label itself, which is where a patient
    reads them. So the abbreviation lives here and the full sentence prints:
    the dispenser types `1t tds pc`, the label says what the patient needs.

    Seeded with the codes in common use, and editable — every pharmacy has its
    own shorthand and one it inherited from whoever trained there.
    """
    __tablename__ = "dosage_abbreviations"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    # What prints on the label, in words a patient can follow.
    expansion = Column(String(200), nullable=False)
    # Latin or trade origin, for a dispenser who wants to know what it means.
    meaning = Column(String(120), default="")
    category = Column(String(30), default="")   # frequency | route | timing | quantity
    # Where a code is known to be read two ways. ISMP publishes a list of
    # abbreviations implicated in real dispensing errors, and several of them
    # are in daily use in Zimbabwean practice — `od` is once-daily here and the
    # right eye in the ophthalmic literature. This system never prints a code on
    # a label, which removes most of that risk, but the ambiguity is still there
    # at the moment somebody types it. So it is written down beside the code
    # rather than left to whoever trained the dispenser.
    caution = Column(String(200), default="")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MedicalAidDueDate(Base):
    """When a scheme is contracted to pay, so the pharmacy can chase on time.

    A memorandum of understanding gives a pharmacy the dates it will be paid on.
    Nothing in this system knew them, so "are we overdue or is it simply not due
    yet" was a question answered from memory, and a claim chased too early
    annoys the scheme while one chased too late is written off.
    """
    __tablename__ = "medical_aid_due_dates"
    id = Column(Integer, primary_key=True)
    medical_aid_id = Column(Integer, ForeignKey("medical_aids.id"),
                            nullable=False, index=True)
    # Day of the month a submission is due, and the day payment is expected.
    submit_by_day = Column(Integer, default=0)
    payment_day = Column(Integer, default=0)
    # Days after submission, where a scheme works to a lag rather than a date.
    payment_lag_days = Column(Integer, default=0)
    notes = Column(Text, default="")
    reminder_days_before = Column(Integer, default=3)
    active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

    medical_aid = relationship("MedicalAid")



# Fail here rather than on the first query.
#
# SQLAlchemy configures mappers lazily, so a broken relationship — two foreign
# keys to the same table and no `foreign_keys=` to say which one is meant —
# imports perfectly and then raises on whatever query happens to run first.
# That has happened twice in this file: once on Shift.user, once on
# Sale.cashier, and the second time it broke all sixty reports at once while
# `from app.main import app` still printed "ok".
#
# Configuring eagerly turns a silent import into a loud one.
from sqlalchemy.orm import configure_mappers as _configure_mappers  # noqa: E402

_configure_mappers()


class AiConversation(Base, TenantMixin):
    """One question put to the assistant, and what it answered.

    Kept because the useful ones are asked once and wanted again a week later:
    "what did it say about the slow-moving lines". Holding them only in the tab
    means the answer to a question worth twelve seconds of a model's time is
    thrown away by a page refresh.

    Stored per user rather than per pharmacy. The questions people ask an
    assistant are working notes, and a shared log of everybody's half-formed
    queries is something staff learn to avoid rather than use.

    The answer is kept verbatim, including the figures it quoted. Re-running the
    question later would answer about today, which is a different question, and
    silently substituting one for the other is how a record stops being one.
    """
    __tablename__ = "ai_conversations"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False, default="")
    # Which model wrote it. An answer from a different model a year from now is
    # not the same evidence, and the log should say so rather than imply it is.
    model = Column(String(60), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User")


class SampleReceipt(Base, TenantMixin):
    """Medicine samples received from a manufacturer's representative.

    A rep leaves a box of something on the counter. It is medicine, it is in the
    pharmacy, and it is not stock: it was not bought, it cannot be sold, and it
    does not appear on any invoice. Which is exactly why it goes missing from the
    records — every other medicine in the building arrives through a purchase
    order and leaves through a till, and a sample does neither.

    MCAZ expects a pharmacy to account for what it holds. A box of samples with
    no paper trail is the easiest thing in the shop to be wrong about, and
    "a rep left them, I think in March" is not an answer.

    Modelled as a receipt with movements against it, the same shape as the
    controlled register, because it is the same question: what came in, what went
    out, to whom, and what is left.
    """
    __tablename__ = "sample_receipts"
    id = Column(Integer, primary_key=True)
    reference = Column(String(30), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    # Who left them. A company and a person, because the company is who the
    # pharmacy deals with and the person is who actually walked in.
    supplier_name = Column(String(160), default="")
    representative = Column(String(120), default="")
    batch_number = Column(String(60), default="")
    expiry_date = Column(Date, nullable=True, index=True)
    quantity_received = Column(Integer, default=0)
    quantity_remaining = Column(Integer, default=0)
    received_at = Column(DateTime, default=datetime.utcnow, index=True)
    received_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, default="")

    product = relationship("Product")
    received_by = relationship("User")
    movements = relationship("SampleMovement", back_populates="receipt",
                             cascade="all, delete-orphan")


class SampleMovement(Base, TenantMixin):
    """One thing that happened to a sample: issued, returned, destroyed, expired.

    A sample is never sold, so there is no sale to attach it to and no till entry
    to find it in later. This is the only record that it left, and the balance it
    carries is the only figure anybody can check against the shelf.
    """
    __tablename__ = "sample_movements"
    id = Column(Integer, primary_key=True)
    receipt_id = Column(Integer, ForeignKey("sample_receipts.id"), nullable=False, index=True)
    # issued | returned | destroyed | expired | counted
    movement = Column(String(20), nullable=False)
    quantity = Column(Integer, default=0)
    balance_after = Column(Integer, default=0)
    # Who got it. A patient where there is one on file, and a name either way,
    # because a sample is often handed to somebody who is not a patient yet.
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    given_to = Column(String(120), default="")
    # Destroying medicine needs a second person watching, the same as writing off
    # a controlled item. The field exists so the requirement can be enforced.
    witness_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reason = Column(Text, default="")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    receipt = relationship("SampleReceipt", back_populates="movements")
    patient = relationship("Patient")
    user = relationship("User", foreign_keys=[user_id])
    witness = relationship("User", foreign_keys=[witness_id])


class ConsentEvent(Base, TenantMixin):
    """Permission given or withdrawn, as an event rather than a flag.

    `marketing_opt_in = True` answers "may we message them" and nothing else. It
    cannot answer when they agreed, what they were told, through which channel,
    who recorded it, or whether they have since said stop, and those are the
    questions asked when somebody complains, which is the only time the answer
    matters.

    So the boolean stays as a fast read and this is the record behind it. A
    withdrawal never deletes the grant: the fact that somebody once agreed and
    later changed their mind is two facts, and erasing the first one leaves a
    pharmacy unable to say why it ever sent anything.
    """
    __tablename__ = "consent_events"
    id = Column(Integer, primary_key=True)
    # patient | lead | contact — one table rather than three near-identical ones,
    # because the question and the evidence are the same whoever it is about.
    subject_type = Column(String(16), nullable=False, index=True)
    subject_id = Column(Integer, nullable=False, index=True)
    # sms | whatsapp | email | phone | post | all
    channel = Column(String(16), default="all", index=True)
    # granted | withdrawn
    state = Column(String(12), nullable=False)
    # How it was taken: verbal at the counter, a signed form, the patient portal,
    # a reply of STOP, or imported from whatever came before. "Imported" is not
    # consent and is recorded as what it is.
    captured_via = Column(String(24), default="counter")
    # What they were actually told. Consent to wording nobody kept is not
    # evidence of anything.
    wording = Column(Text, default="")
    note = Column(Text, default="")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User")


class ClinicalTerm(Base):
    """A word the pharmacy is allowed to record in a clinical field.

    Allergies and chronic conditions were free text, and both are read by code
    rather than only by people. An allergy raises a blocking warning at
    dispensing by matching the typed words against product names and active
    ingredients; a chronic condition decides whether a patient's repeat is
    treated as urgent. So "penicilin" with one L is not a typo that somebody
    tidies up later — it is a safety check that silently never fires, on the
    one record whose whole purpose is to fire.

    A catalogue fixes that by making the common answer a click rather than a
    spelling. It stays open, though: `POST /api/clinical-terms` adds a term at
    the moment somebody needs one, because a locked vocabulary in a pharmacy is
    a vocabulary people work around by typing into the notes field, and an
    allergy recorded in the notes warns nobody at all.

    `synonyms` exist because the patient says one word and the box says another
    — "aspirin" for acetylsalicylic acid, "sulfa" for sulphonamides. They widen
    what the dispensing check matches without asking the counter to know the
    pharmacological name.
    """
    __tablename__ = "clinical_terms"
    id = Column(Integer, primary_key=True)
    # allergy | condition
    kind = Column(String(20), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    # Comma-separated alternatives matched alongside the name.
    synonyms = Column(String(300), default="")
    # drug | food | environmental | "" — grouping for the picker, not clinical.
    category = Column(String(40), default="")
    # Seeded terms are common enough to offer first; ones added at the counter
    # are kept but not promoted until somebody uses them.
    common = Column(Boolean, default=False, index=True)
    active = Column(Boolean, default=True)
    times_used = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_by = relationship("User")

    __table_args__ = (
        UniqueConstraint("kind", "name", name="uq_clinical_term_kind_name"),
    )
