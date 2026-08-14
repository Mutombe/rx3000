"""Jurisdiction packs.

RX3000 is sold into more than one country, and almost everything that differs
between them is regulatory rather than functional: which schedules a medicine
falls into, what a drug code is called, which privacy statute governs marketing
consent, when the tax year starts, which currency the till trades in, and
whether receipts must be fiscalised.

Rather than hard-code one country, each is a pack selected with the
`JURISDICTION` setting. Dispensing, stock, FEFO, CRM and the till are
jurisdiction-neutral and never need to change.

    JURISDICTION=ZA     South Africa
    JURISDICTION=ZW     Zimbabwe

Adding a country means adding a pack below. Nothing else moves.
"""
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class SchedulePolicy:
    """How one class of medicine must be dispensed.

    `schedule` is an ordinal, not a name. South Africa numbers its schedules and
    the ordinal *is* the number; Zimbabwe does not number anything - MCAZ
    classifies by letter (N, PP10, PP, PIM, P, HR, SR) - so there the ordinal is
    purely an internal ranking, ordered by how tightly controlled the class is.

    `code` is what a human sees and what goes on a label. Callers must display
    `code`, never `schedule`, or a Zimbabwean pharmacy will be shown a South
    African schedule number that does not exist in its law.

    Ranking still matters even where the numbers do not: a compound inherits the
    strictest class among its ingredients, and `max()` over the ordinal is what
    computes that.
    """
    schedule: int
    code: str
    label: str
    route: str                    # otc | prescription | controlled | prohibited
    requires_prescription: bool
    requires_pharmacist: bool
    register_entry: bool          # electronic controlled-substances register
    max_repeats: int              # -1 = governed by the script itself
    max_repeat_months: int
    requires_id_verification: bool
    requires_script_sighted: bool
    requires_prescriber_verification: bool
    requires_witness: bool
    counselling_required: bool
    notes: str


@dataclass(frozen=True)
class Currency:
    code: str
    symbol: str
    decimals: int = 2


@dataclass(frozen=True)
class Jurisdiction:
    code: str
    name: str
    regulator: str                # medicines regulator
    privacy_act: str              # governs marketing consent wording
    product_code_label: str       # NAPPI, MCAZ registration number, …
    id_number_label: str          # what the controlled register records
    locale: str                   # number and date formatting
    currencies: list[Currency]    # first entry is the base currency
    vat_rate: float
    tax_year_start_month: int
    tax_year_start_day: int
    medical_schemes: list[str]
    schedules: dict[int, SchedulePolicy]
    fiscalisation: str | None = None   # e.g. ZIMRA_FDMS — None means not required
    verified: bool = False             # has the regulatory detail been confirmed?
    caveat: str = ""

    @property
    def base_currency(self) -> Currency:
        return self.currencies[0]

    def policy_for(self, schedule: int | None) -> SchedulePolicy:
        return self.schedules.get(schedule or 0, self.schedules[0])


def _sched(n, label, route, *, code="", script=False, pharmacist=False, register=False,
           max_repeats=-1, months=0, verify_id=False, sight_script=False,
           verify_prescriber=False, witness=False, counsel=False, notes=""):
    return SchedulePolicy(
        n, code or f"S{n}", label, route,
        requires_prescription=script, requires_pharmacist=pharmacist,
        register_entry=register, max_repeats=max_repeats, max_repeat_months=months,
        requires_id_verification=verify_id, requires_script_sighted=sight_script,
        requires_prescriber_verification=verify_prescriber, requires_witness=witness,
        counselling_required=counsel, notes=notes,
    )


# --------------------------------------------------------------------------
# South Africa — Medicines and Related Substances Act
# --------------------------------------------------------------------------
ZA_SCHEDULES = {
    0: _sched(0, "Schedule 0 — general sale", "otc",
              notes="May be sold without pharmacist involvement."),
    1: _sched(1, "Schedule 1 — pharmacy medicine", "otc", pharmacist=True, counsel=True,
              notes="Sold under pharmacist supervision. Record the sale and counsel the patient."),
    2: _sched(2, "Schedule 2 — pharmacy medicine", "otc", pharmacist=True, counsel=True,
              notes="Pharmacist must personally hand over and counsel. Record every sale."),
    3: _sched(3, "Schedule 3 — prescription medicine", "prescription",
              script=True, pharmacist=True, months=6, sight_script=True, counsel=True,
              notes="Valid prescription required. Repeats permitted for up to 6 months."),
    4: _sched(4, "Schedule 4 — prescription medicine", "prescription",
              script=True, pharmacist=True, months=6, sight_script=True, counsel=True,
              notes="Valid prescription required. Repeats permitted for up to 6 months."),
    5: _sched(5, "Schedule 5 — controlled substance", "controlled",
              script=True, pharmacist=True, register=True, max_repeats=5, months=6,
              verify_id=True, sight_script=True, verify_prescriber=True, counsel=True,
              notes="Dangerous drug. Register entry mandatory, patient identity must be "
                    "verified, and the original script must be sighted and retained."),
    6: _sched(6, "Schedule 6 — controlled substance", "controlled",
              script=True, pharmacist=True, register=True, max_repeats=0,
              verify_id=True, sight_script=True, verify_prescriber=True, witness=True,
              counsel=True,
              notes="Dangerous drug. No repeats — a fresh prescription is required each "
                    "time. Requires an independent witness to co-sign the dispensing."),
    7: _sched(7, "Schedule 7 — restricted", "prohibited",
              script=True, pharmacist=True, register=True, max_repeats=0,
              verify_id=True, sight_script=True, verify_prescriber=True, witness=True,
              counsel=True,
              notes="Not dispensable in a retail pharmacy — requires a departmental permit."),
    8: _sched(8, "Schedule 8 — restricted", "prohibited",
              script=True, pharmacist=True, register=True, max_repeats=0,
              verify_id=True, sight_script=True, verify_prescriber=True, witness=True,
              counsel=True,
              notes="Not dispensable in a retail pharmacy — requires a departmental permit."),
}

SOUTH_AFRICA = Jurisdiction(
    code="ZA",
    name="South Africa",
    regulator="SAHPRA",
    privacy_act="POPIA",
    product_code_label="NAPPI",
    id_number_label="SA ID number",
    locale="en-ZA",
    currencies=[Currency("ZAR", "R")],
    vat_rate=0.15,
    tax_year_start_month=3,
    tax_year_start_day=1,
    medical_schemes=["Discovery Health", "Bonitas", "Momentum Health", "Medihelp", "GEMS"],
    schedules=ZA_SCHEDULES,
    fiscalisation=None,
    verified=True,
)


# --------------------------------------------------------------------------
# Zimbabwe — Medicines and Allied Substances Control Act, administered by MCAZ
#
# DRAFT. The schedule structure below is a working model, not a confirmed
# reading of the Act. It must be checked against MCAZ's current classification
# before this pack is used in a live pharmacy — the controlled-substance rules
# in particular carry legal weight. `verified=False` makes the app surface that
# warning rather than let it pass silently.
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Zimbabwe - MCAZ distribution categories
#
# Zimbabwe does not use numbered schedules. MCAZ classifies human medicines into
# lettered distribution categories printed on the product label, and those
# letters - not numbers - are what a Zimbabwean pharmacist reads and dispenses
# against. An earlier version of this pack inferred numbered schedules 0-7 from
# the incumbent system's "Schedule X Register" report; that inference was wrong
# in structure, not merely in its boundaries, and is replaced here.
#
# The integer keys are the value stored on a product record, and they map onto
# categories **many-to-one**: there are nine possible stored values and seven
# categories, so more than one value can resolve to the same category. That is
# expected, not a defect - the stored number is an ordinal for ranking
# strictness (a compound inherits the strictest category among its ingredients),
# while the category is the legal classification.
#
#   0     HR    Household remedies - general sale
#   1     P     Pharmacy medicines - pharmacy only
#   2     PIM   Pharmacist-initiated - no script, pharmacist assesses
#   3, 4  PP    Prescription preparations
#   5     PP10  Prescription preparation, Tenth Schedule - statutory records
#   6     N     Narcotics / dangerous drugs
#   7, 8  SR    Specially restricted - state and central hospital pharmacies
# --------------------------------------------------------------------------

def _pp(n):
    return _sched(n, "Prescription preparation", "prescription", code="PP",
                  script=True, pharmacist=True, months=6, sight_script=True,
                  counsel=True,
                  notes="Valid prescription required. CONFIRM the repeat period "
                        "with MCAZ.")


def _sr(n):
    # Not "banned" - restricted to a setting a community pharmacy is not. Routed
    # as prohibited because the question this answers is "may this counter
    # dispense it", and there the answer is no.
    return _sched(n, "Specially restricted preparation", "prohibited", code="SR",
                  script=True, pharmacist=True, register=True, max_repeats=0, months=0,
                  verify_id=True, sight_script=True, verify_prescriber=True,
                  witness=True, counsel=True,
                  notes="Designated for state and central hospital pharmacy "
                        "handling. A community pharmacy may not dispense it - "
                        "refer the patient.")


ZW_SCHEDULES = {
    0: _sched(0, "Household remedy", "otc", code="HR",
              notes="General sale. Safe for household use without pharmacist "
                    "involvement."),
    1: _sched(1, "Pharmacy medicine", "otc", code="P", pharmacist=True, counsel=True,
              notes="Sold only through a licensed pharmacy, under pharmacist "
                    "supervision. Counsel the patient."),
    # PIM is the category with no South African equivalent and the one most
    # easily mis-modelled: no prescription is required, but a pharmacist must
    # assess the patient before supplying. It is neither ordinary OTC nor
    # prescription-only, so it routes as OTC with the pharmacist made mandatory.
    2: _sched(2, "Pharmacist-initiated medicine", "otc", code="PIM",
              pharmacist=True, counsel=True,
              notes="No prescription required, but a pharmacist must assess the "
                    "patient personally before supplying and record the assessment."),
    3: _pp(3),
    4: _pp(4),
    5: _sched(5, "Prescription preparation - Tenth Schedule", "controlled", code="PP10",
              script=True, pharmacist=True, register=True, max_repeats=0, months=0,
              verify_id=True, sight_script=True, verify_prescriber=True, counsel=True,
              notes="Tight statutory record-keeping. Register entry, identity "
                    "verification and script sighting enforced. CONFIRM the "
                    "register format and repeat limits with MCAZ."),
    6: _sched(6, "Narcotic / dangerous drug", "controlled", code="N",
              script=True, pharmacist=True, register=True, max_repeats=0, months=0,
              verify_id=True, sight_script=True, verify_prescriber=True, witness=True,
              counsel=True,
              notes="Subject to international narcotics board oversight. No "
                    "repeats; an independent witness must co-sign the hand-over. "
                    "CONFIRM with MCAZ."),
    7: _sr(7),
    8: _sr(8),
}

ZIMBABWE = Jurisdiction(
    code="ZW",
    name="Zimbabwe",
    regulator="MCAZ",
    privacy_act="Cyber and Data Protection Act",
    product_code_label="NAPPI",   # in use locally, per the incumbent's stock records
    id_number_label="National ID number",
    locale="en-ZW",
    # Multi-currency: USD is the base of account, ZiG trades alongside it.
    currencies=[Currency("USD", "$"), Currency("ZWG", "ZiG")],
    vat_rate=0.15,
    tax_year_start_month=1,
    tax_year_start_day=1,
    medical_schemes=["CIMAS", "PSMAS", "First Mutual Health", "Alliance Health", "Fidelity Life"],
    schedules=ZW_SCHEDULES,
    fiscalisation="ZIMRA_FDMS",
    verified=False,
    caveat=(
        "Medicines are classified by MCAZ distribution category (HR, P, PIM, PP, "
        "PP10, N, SR), not by numbered schedule - the numbers shown anywhere in "
        "this system are internal ranking only. The categories and their "
        "dispensing consequences still need confirming against MCAZ's own "
        "guidance: specifically the permitted repeat period for PP, the "
        "prescribed register format for PP10 and N, and whether PIM supply must "
        "be recorded in a particular form. The demonstration product catalogue "
        "carries South African schedule numbers and would be re-coded to MCAZ "
        "categories before a Zimbabwean pharmacy used it. ZIMRA fiscalisation is "
        "required for VAT-registered pharmacies and is not yet proven."
    ),
)


REGISTRY: dict[str, Jurisdiction] = {j.code: j for j in (SOUTH_AFRICA, ZIMBABWE)}


def get(code: str) -> Jurisdiction:
    """Zimbabwe unless told otherwise.

    This defaulted to South Africa, which put Rand on every price, receipt and
    report in a product sold to Zimbabwean pharmacies — and did it silently,
    because a default never announces itself. Zimbabwe trades in USD and ZWG;
    the South African pack stays in the registry for a deployment that sets
    JURISDICTION=ZA deliberately.
    """
    return REGISTRY.get((code or "ZW").strip().upper(), ZIMBABWE)


def as_dict(j: Jurisdiction) -> dict:
    data = asdict(j)
    data["schedules"] = [asdict(p) for p in j.schedules.values()]
    data["base_currency"] = asdict(j.base_currency)
    return data
