"""The register of external integrations, and the guard that keeps simulators out of production.

RX5000 is sold to pharmacies, not installed once in-house, so two failure modes
matter more here than in a bespoke system:

* **A simulator reaching a live counter.** Every simulator in this codebase
  approves things. A pharmacy running live on one would be handing out medicine
  against fake adjudications and filing nothing with the revenue authority, and
  would not find out until a funder or ZIMRA asked. `require_live()` makes that
  impossible rather than unlikely: in production a simulator refuses to act.

* **An integration finished from guesswork.** Where a counterparty has not
  published their wire format, the adapter is declared blocked here and says
  exactly which document unblocks it. Nothing is invented to make a demo pass.

This module is the single source of truth for both. It is published at
`GET /api/integrations`, so what is real and what is pretended is visible in
the product rather than buried in comments.
"""
from dataclasses import dataclass, field

from .config import settings


class NotLiveError(RuntimeError):
    """Raised when a simulated or blocked integration is used in production."""


@dataclass(frozen=True)
class Integration:
    """One external dependency, and how far it actually is.

    The four states are deliberately not three. `unproven` is the one that is
    easy to leave out and expensive to omit: code written correctly from a
    counterparty's published specification, which has never exchanged a packet
    with them. It looks finished, it reviews as finished, and it is the state in
    which integrations most often turn out to be wrong — a field the docs did
    not mention, a sandbox that behaves differently, a credential that grants
    less than expected. Calling that `live` is how a pharmacy discovers it at a
    counter with a customer waiting.

        live       proven end to end against the real counterparty
        unproven   implemented from their specification, never actually run
        simulated  a stand-in that fabricates plausible answers
        blocked    declared but not implemented; waiting on a document
    """

    key: str
    name: str
    category: str                    # switch | fiscal | payment | device
    state: str                       # live | unproven | simulated | blocked
    module: str                      # where the remaining work is
    blocked_on: tuple = ()           # exactly what is needed to finish it
    unblocks: str = ""               # what becomes possible once it lands
    notes: str = ""

    @property
    def production_safe(self) -> bool:
        # Only a proven integration. `unproven` deliberately fails this: the
        # first real transaction should happen because someone chose to run it,
        # not because a customer was standing at the till.
        return self.state == "live"


REGISTRY: dict[str, Integration] = {}


def register(integration: Integration) -> Integration:
    REGISTRY[integration.key] = integration
    return integration


def get(key: str) -> Integration | None:
    return REGISTRY.get(key)


def require_live(key: str) -> None:
    """Refuse to use a simulated or blocked integration on a live installation.

    Called at the point of action, not at startup, so the message names the
    thing that was actually attempted and the pharmacy is told what to do about
    it — rather than the server simply failing to boot with a stack trace.
    """
    integration = REGISTRY.get(key)
    if integration is None or integration.production_safe:
        return
    if not settings.is_production:
        return
    needed = "; ".join(integration.blocked_on) or "a real driver"
    raise NotLiveError(
        f"{integration.name} is {integration.state} and this installation is "
        f"configured as production (RX5000_ENV={settings.ENVIRONMENT}). It will "
        f"not be used for live transactions. To finish it: {needed}."
    )


def unfinished() -> list[Integration]:
    """Everything that is not yet real, worst first."""
    order = {"blocked": 0, "simulated": 1, "live": 2}
    return sorted((i for i in REGISTRY.values() if not i.production_safe),
                  key=lambda i: (order.get(i.state, 9), i.name))


def production_readiness() -> dict:
    """Whether this installation could lawfully take money and dispense today."""
    blocking = unfinished()
    return {
        "environment": settings.ENVIRONMENT,
        "is_production": settings.is_production,
        "ready": not blocking,
        "live": [i.key for i in REGISTRY.values() if i.production_safe],
        "blocking": [{"key": i.key, "name": i.name, "state": i.state,
                      "blocked_on": list(i.blocked_on)} for i in blocking],
    }


# ---------------------------------------------------------------------------
# The register itself
# ---------------------------------------------------------------------------

register(Integration(
    key="switch.simulator", name="Claims switch simulator", category="switch",
    state="simulated", module="app/services/gateway.py:SimulatorSwitch",
    blocked_on=("route the funder to a real switch instead",),
    unblocks="Claims adjudicated by a funder rather than by this machine.",
    notes="Adjudicates locally. Every approval it returns is fictional.",
))

register(Integration(
    key="switch.health263", name="Health 263 claims switch", category="switch",
    state="blocked", module="app/services/gateway.py:Health263Switch",
    blocked_on=(
        "Health 263's REST integration specification: endpoint URLs, request "
        "envelope, authentication scheme and response/error codes",
    ),
    unblocks="Real-time claims, eligibility, authorisations and remittance "
             "advice for funders that sit behind Health 263.",
    notes="Onboarding runs through the pharmacy: the HSP contract obliges them "
          "to put their software provider in touch with Health 263. "
          "Authorisations and remittance advice are built and work against the "
          "simulator; advices can be imported as CSV until the adapter lands.",
))

register(Integration(
    key="era.csv", name="Remittance advice by spreadsheet", category="switch",
    state="live", module="app/services/era.py",
    notes="Funders without a switch integration send a CSV. Parsing, matching "
          "against submitted claims, and shortfall reconciliation are complete "
          "and need nothing from anyone.",
))

register(Integration(
    key="switch.mediswitch", name="Mediswitch / Altron SwitchOn", category="switch",
    state="blocked", module="app/services/gateway.py:MediswitchSwitch",
    blocked_on=("The WSDL, the SOAP envelope shape, and the fault-code vocabulary",),
    unblocks="Claims to funders that settle through Mediswitch.",
))

register(Integration(
    key="biometric.health263", name="Health 263 fingerprint reader", category="device",
    state="blocked", module="device-agent/biometric.py:Health263Reader",
    blocked_on=("The make and model of the reader they issue, and its capture SDK",
                "The template format identifier the switch expects",
                "Whether enrolment is driven from the till or from their portal"),
    unblocks="Member verification at the counter for funders that require it.",
    notes="The reader is Health 263's property, supplied free on connection.",
))

register(Integration(
    key="fiscal.simulator", name="Fiscal device simulator", category="fiscal",
    state="simulated", module="app/services/fiscal_devices.py:SimulatorFiscalDevice",
    blocked_on=("set FISCAL_DEVICE=cloudesd and supply CloudESD credentials",),
    unblocks="Receipts actually filed with ZIMRA rather than signed locally.",
    notes="Signs receipts plausibly and files nothing. The hash chain it "
          "produces is valid, but no revenue authority has seen it.",
))

# ZIMRA publishes no driver. There are three real routes to the same obligation,
# and a pharmacy picks one before RX5000 is installed, so all three are
# registered, rather than one being treated as "the" integration.
register(Integration(
    key="fiscal.external", name="Approved Supplier fiscal device", category="fiscal",
    state="live", module="app/services/fiscal_devices.py:ExternalFiscalDevice",
    notes="The device fiscalises; RX5000 files nothing and does not pretend to. "
          "Nothing to implement, but the pharmacy must procure and register the "
          "device through a ZIMRA Approved Supplier and declare it with "
          "FISCAL_SUPPLIER and FISCAL_DEVICE_SERIAL, or the record cannot say "
          "which device carries the obligation.",
))

register(Integration(
    key="fiscal.zimra_fdms", name="Virtual fiscalisation direct to ZIMRA",
    category="fiscal", state="blocked",
    module="app/services/fiscal_devices.py:ZimraFdmsDevice",
    blocked_on=("ZIMRA's Fiscal Device Gateway API Specification",
                "Device registration with ZIMRA, and the certificate it issues",
                "Server certificate retrieval and the signature scheme"),
    unblocks="A multi-till operator filing receipts itself, without a device per "
             "counter and without a hosted intermediary.",
    notes="The route for an operator large enough to own the integration. "
          "Smaller pharmacies should use fiscal.external or fiscal.cloudesd "
          "instead, both discharge the same obligation.",
))

register(Integration(
    key="fiscal.cloudesd", name="CloudESD (ZIMRA FDMS)", category="fiscal",
    state="blocked", module="app/services/fiscal_devices.py:CloudEsdDevice",
    blocked_on=("The exact receipt payload CloudESD expects at POST /api/receipt/sign",
                "A tenant id and bearer token from the CloudESD portal"),
    unblocks="Receipts signed and filed with ZIMRA, and lawful VAT invoices.",
    notes="Endpoints, auth header, device gating and QR fields are built from "
          "their published overview; only the receipt body is unknown.",
))

register(Integration(
    key="payment.paynow", name="Paynow (EcoCash / OneMoney)", category="payment",
    state="unproven", module="device-agent/drivers.py:PaynowDriver",
    blocked_on=("A Paynow merchant account, and its integration id and key",
                "PAYNOW_AUTH_EMAIL, Paynow rejects mobile transactions without one",
                "One real end-to-end transaction: push, approve on the handset, "
                "poll to paid, and confirm the money arrived"),
    unblocks="EcoCash and OneMoney taken at the till instead of by hand.",
    notes="Implemented in full from Paynow's published SDK, initiate, poll, "
          "SHA-512 hashing and reply verification. It has never made a request "
          "to paynow.co.zw. The code is finished; the integration is not.",
))

register(Integration(
    key="payment.billpay", name="Paynow BillPay (bill payments at the counter)",
    category="payment", state="blocked",
    module="device-agent/drivers.py, not started",
    blocked_on=("A BillPay vendor account, obtained through support@paynow.co.zw",
                "Their vendor API specification: base URL, endpoints, the List "
                "Billers call, and the payment request/response fields",
                "The webhook contract for biller-config changes and payment "
                "notifications, and the bearer token that authenticates it"),
    unblocks="Customers paying electricity, water, DStv or medical aid "
             "subscriptions at the pharmacy counter, with the pharmacy earning "
             "commission on each.",
    notes="A different product from the Paynow express checkout already built, "
          "not a replacement for it: express checkout takes money FOR the "
          "pharmacy's own sale; BillPay takes money for SOMEONE ELSE'S bill and "
          "pays the pharmacy a commission. A pharmacy would be a BillPay "
          "'vendor'. Neither the endpoints nor the field names are published — "
          "there is no public SDK and the developer hub refuses automated "
          "access. So nothing here is guessed at.",
))

register(Integration(
    key="payment.terminal_sim", name="Card terminal simulator", category="payment",
    state="simulated", module="device-agent/drivers.py:SimulatorTerminal",
    blocked_on=("The acquirer's semi-integration guide, then TERMINAL_DRIVER=tcp",),
    unblocks="Card payments actually taken rather than assumed approved.",
))
