"""How this till satisfies its revenue authority.

"Driver" here means a class in this file, not something downloadable. ZIMRA in
particular publishes no driver and no installable component: compliance is
reached by one of three routes, and which one a pharmacy is on is a business
decision it has already made before RX3000 is installed.

    FISCAL_DEVICE   none | external | cloudesd | zimra_fdms | simulator

  * **external** - a hardware fiscal device procured, configured and registered
    through a ZIMRA Approved Supplier. The device fiscalises; RX3000 does not
    and must not pretend to. This is the common case for a small pharmacy.
  * **cloudesd** - a hosted service that signs and files on the taxpayer's
    behalf. Virtual fiscalisation with somebody else operating it.
  * **zimra_fdms** - the pharmacy interfaces its own software directly with the
    ZIMRA server, per the Fiscal Device Gateway API Specification. Suits an
    operator with many tills; it means owning device registration, certificate
    handling and signature generation.
  * **simulator** - development only; refuses to act in production.
  * **none** - the jurisdiction imposes no fiscal obligation at all.

The distinction that matters is between `none` and `external`. Both mean this
software files nothing, but they are opposite claims: `none` says there is no
obligation, `external` says there is one and something else discharges it.
Reporting the first when the second is true would tell a Zimbabwean pharmacy it
had no fiscal duty. So `external` is a distinct route, not an absence.

What is *not* authority-specific - fiscal days, hash-chained receipt counters,
the offline queue, credit notes - lives in `fiscal.py` and is shared by all of
them. A new country implements one class here.
"""
import base64
import json
import logging
import os
import random
import string
import urllib.error
import urllib.request

from .. import integrations

log = logging.getLogger("rx3000.fiscal.device")


class FiscalDevice:
    """Interface a fiscal device driver must satisfy.

    `submit_receipt` returns:
        accepted    bool
        reference   the authority's receipt reference
        signature   device signature over the receipt (printed on the slip)
        qr_data     payload encoded into the verification QR code
        url         public verification URL, if the authority publishes one
        code        response code
        message     human-readable outcome
    """

    name = "base"
    requires_network = True

    def status(self) -> dict:
        raise NotImplementedError

    def submit_receipt(self, payload: dict) -> dict:
        raise NotImplementedError

    def close_day(self, payload: dict) -> dict:
        raise NotImplementedError


class NoFiscalDevice(FiscalDevice):
    """Jurisdiction does not require fiscalisation — receipts are never queued."""

    name = "none"
    requires_network = False

    def status(self) -> dict:
        # Only honest where the pack imposes no obligation. Where one exists and
        # a device discharges it elsewhere, the route is `external`, not this.
        return {"driver": self.name, "ready": True, "required": False,
                "fiscalises_here": False,
                "message": "Fiscalisation is not required in this jurisdiction"}

    def submit_receipt(self, payload: dict) -> dict:
        return {"accepted": True, "reference": "", "signature": "", "qr_data": "",
                "url": "", "code": "NOT_REQUIRED", "message": "Fiscalisation not required"}

    def close_day(self, payload: dict) -> dict:
        return {"accepted": True, "reference": "", "code": "NOT_REQUIRED", "message": ""}


class ExternalFiscalDevice(FiscalDevice):
    """A hardware fiscal device from a ZIMRA Approved Supplier.

    The supplier procures, configures, registers and tests the device against
    the live platform. Receipts are fiscalised on the device, not here, so this
    class deliberately does almost nothing - and that restraint is the point.

    Two things it will not do:

    * **It will not sign.** A signature invented here would be worthless and
      would make the audit trail look complete when nothing had been filed.
    * **It will not block the sale.** The device is the compliance boundary; a
      till that refused to trade because RX3000 could not see it would be
      inventing an outage.

    What it does do is record which device carries the obligation, so that when
    ZIMRA asks, the answer names a supplier, a serial and a registration rather
    than a shrug. RX3000's own hash chain still runs underneath, which gives the
    pharmacy an internal record that its device output can be reconciled against.

        FISCAL_SUPPLIER / FISCAL_DEVICE_SERIAL / FISCAL_REGISTRATION_REF
    """

    name = "external"
    requires_network = False

    def __init__(self):
        self.supplier = os.getenv("FISCAL_SUPPLIER", "")
        self.serial = os.getenv("FISCAL_DEVICE_SERIAL", "")
        self.registration = os.getenv("FISCAL_REGISTRATION_REF", "")

    def _declared(self) -> bool:
        return bool(self.supplier and self.serial)

    def status(self) -> dict:
        info = {
            "driver": self.name,
            "required": True,
            "ready": self._declared(),
            "fiscalises_here": False,
            "route": "Approved Supplier hardware fiscal device",
            "supplier": self.supplier or None,
            "device_serial": self.serial or None,
            "registration_ref": self.registration or None,
        }
        if not self._declared():
            info["message"] = (
                "Fiscalisation IS required here, and this till is configured to "
                "rely on an external fiscal device - but no device is declared. "
                "Set FISCAL_SUPPLIER and FISCAL_DEVICE_SERIAL so the record shows "
                "which device carries the obligation."
            )
        else:
            info["message"] = (
                f"Receipts are fiscalised on {self.serial} supplied by "
                f"{self.supplier}. RX3000 keeps its own hash chain for "
                "reconciliation and files nothing itself."
            )
        return info

    def submit_receipt(self, payload: dict) -> dict:
        # Accepted so the sale completes and the local chain stays unbroken, but
        # the code says plainly that nothing was filed from here.
        return {
            "accepted": True,
            "reference": "",
            "signature": "",
            "qr_data": "",
            "url": "",
            "code": "FILED_EXTERNALLY",
            "message": (f"Fiscalised on external device {self.serial or '(undeclared)'}"
                        if self._declared() else
                        "Relying on an external fiscal device, but none is declared"),
        }

    def close_day(self, payload: dict) -> dict:
        return {"accepted": True, "reference": "", "code": "FILED_EXTERNALLY",
                "message": "The Z-report is produced by the external fiscal device."}


class SimulatorFiscalDevice(FiscalDevice):
    """Accepts everything and signs it plausibly.

    Lets the whole fiscal flow — day open, hash chain, queue, credit notes,
    Z-report — be built and tested before a real device is provisioned. Set
    FISCAL_SIM_FAIL=1 to make submissions fail so the offline queue and retry
    path can be exercised deliberately.
    """

    name = "simulator"

    def __init__(self):
        self.device_id = os.getenv("FISCAL_DEVICE_ID", "SIM-FD-0001")

    def _fail(self) -> bool:
        return os.getenv("FISCAL_SIM_FAIL", "") == "1"

    def status(self) -> dict:
        return {"driver": self.name, "ready": not self._fail(), "required": True,
                "device_id": self.device_id,
                "message": "Simulated fiscal device — set FISCAL_SIM_FAIL=1 to force failures"}

    def submit_receipt(self, payload: dict) -> dict:
        # A simulated signature is not a fiscal signature. On a live till this
        # would leave receipts looking filed while nothing had been filed.
        try:
            integrations.require_live("fiscal.simulator")
        except integrations.NotLiveError as exc:
            return {"accepted": False, "code": "NOT_LIVE", "message": str(exc)}
        if self._fail():
            return {"accepted": False, "code": "NETWORK", "message": "Simulated submission failure"}
        ref = "".join(random.choices(string.digits, k=10))
        return {
            "accepted": True,
            "reference": ref,
            "signature": "".join(random.choices(string.ascii_uppercase + string.digits, k=32)),
            "qr_data": f"{self.device_id}|{payload.get('global_counter')}|{payload.get('receipt_hash', '')[:16]}",
            "url": f"https://example-revenue-authority.invalid/verify/{ref}",
            "code": "ACCEPTED",
            "message": "Receipt accepted",
        }

    def close_day(self, payload: dict) -> dict:
        if self._fail():
            return {"accepted": False, "code": "NETWORK", "message": "Simulated close failure"}
        return {"accepted": True, "reference": "".join(random.choices(string.digits, k=8)),
                "code": "DAY_CLOSED",
                "message": f"Fiscal day {payload.get('day_number')} closed"}


class CloudEsdDevice(FiscalDevice):
    """CloudESD - signs receipts and files them with ZIMRA FDMS for the taxpayer.

    A hosted signing service rather than a physical fiscal device, which is why
    it fits this interface at all: RX3000 keeps its own fiscal days, counters and
    hash chain, and CloudESD supplies the signature and the ZIMRA submission.

    Built from CloudESD's published overview:

        base URL   https://zw.cloudesd.africa
        auth       bearer token + tenant id, base64 in the header
        GET  /api/device/{zimraDeviceId}   confirm active, read tax types, read
                                           FiscalDayStatus (FiscalDayOpened)
        POST /api/receipt/sign             sign and file
        GET  /api/receipt/{reference}      retrieve a submitted receipt

    Two of their rules are enforced rather than assumed:

    * **Their fiscal day must be open.** Submitting into a closed day fails, so
      the day is checked first and the receipt queues locally instead of being
      lost.
    * **A credit or debit note must carry the original invoice Reference as
      OriginalReference.** RX3000 already refuses to void a filed sale and
      issues a credit note instead, so the original reference is threaded here.

    `ZIG` is accepted and converted to `ZWG` on their side, but it is normalised
    here too so that what is filed matches what is recorded locally.

    NOT KNOWN: the field names of the receipt body at POST /api/receipt/sign.
    Their overview documents the response fields but not the request schema, so
    `_receipt_body()` is the one method left to complete - and it raises rather
    than guessing, because a compliance integration that silently files the
    wrong shape is worse than one that has not started.

        CLOUDESD_URL / CLOUDESD_TOKEN / CLOUDESD_TENANT_ID / CLOUDESD_DEVICE_ID
    """

    name = "cloudesd"
    BASE_URL = "https://zw.cloudesd.africa"
    TIMEOUT = 30

    def __init__(self):
        self.api_url = os.getenv("CLOUDESD_URL", self.BASE_URL).rstrip("/")
        self.token = os.getenv("CLOUDESD_TOKEN", "")
        self.tenant_id = os.getenv("CLOUDESD_TENANT_ID", "")
        self.device_id = os.getenv("CLOUDESD_DEVICE_ID", "")

    # ---- transport ----
    def _auth_header(self) -> str:
        """Bearer token and tenant id, base64-encoded, per their authentication note."""
        return "Basic " + base64.b64encode(
            f"{self.token}:{self.tenant_id}".encode()).decode()

    def _call(self, method: str, path: str, body: dict | None = None):
        request = urllib.request.Request(f"{self.api_url}{path}", method=method)
        request.add_header("Authorization", self._auth_header())
        request.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urllib.request.urlopen(request, data=data, timeout=self.TIMEOUT) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"message": raw[:300]}
        except OSError as exc:
            # Unreachable is not rejected: the receipt queues and is retried.
            return 0, {"message": str(exc)}

    def _configured(self) -> bool:
        return bool(self.token and self.tenant_id and self.device_id)

    @staticmethod
    def _currency(code: str) -> str:
        """CloudESD accepts ZIG and stores ZWG. Normalise so both ends agree."""
        return "ZWG" if (code or "").upper() == "ZIG" else (code or "").upper()

    # ---- interface ----
    def status(self) -> dict:
        info = {"driver": self.name, "required": True, "ready": False,
                "device_id": self.device_id or None,
                "configured": self._configured()}
        if not self._configured():
            info["message"] = ("Set CLOUDESD_TOKEN, CLOUDESD_TENANT_ID and "
                               "CLOUDESD_DEVICE_ID from the CloudESD portal")
            return info
        code, device = self._call("GET", f"/api/device/{self.device_id}")
        if code != 200:
            info["message"] = ("CloudESD did not confirm the device: "
                               f"{device.get('message', code)}")
            return info
        day_status = device.get("FiscalDayStatus") or device.get("fiscalDayStatus") or ""
        info["fiscal_day_status"] = day_status
        info["tax_types"] = device.get("TaxTypes") or device.get("taxTypes") or []
        info["ready"] = day_status == "FiscalDayOpened"
        if not info["ready"]:
            info["message"] = (f"The device fiscal day is {day_status or 'unknown'}; "
                               "receipts queue until it is FiscalDayOpened")
        return info

    def _receipt_body(self, payload: dict) -> dict:
        raise NotImplementedError(
            "The CloudESD receipt schema for POST /api/receipt/sign is not in "
            "their published overview. Map RX3000's receipt payload to their "
            "field names here - it is the only unknown. Authentication, device "
            "and fiscal-day gating, currency normalisation, the credit-note "
            "OriginalReference, response handling and the QR fields are built."
        )

    def submit_receipt(self, payload: dict) -> dict:
        if not self._configured():
            return {"accepted": False, "code": "NOT_CONFIGURED",
                    "message": "CloudESD credentials are not set on this till"}

        state = self.status()
        if not state.get("ready"):
            # Queue rather than reject: the receipt keeps its place in the local
            # chain and is re-filed once the day is open.
            return {"accepted": False, "code": "DAY_NOT_OPEN",
                    "message": state.get("message", "The CloudESD fiscal day is not open")}

        body = self._receipt_body({
            **payload,
            "currency_code": self._currency(payload.get("currency_code", "")),
        })
        code, response = self._call("POST", "/api/receipt/sign", body)
        if code != 200:
            return {"accepted": False,
                    "code": "REJECTED" if code >= 400 else "NETWORK",
                    "message": str(response.get("message") or response)[:300]}

        # Their documented response fields. All three are needed to print the QR
        # code on the slip, so they are carried back rather than summarised away.
        verification = response.get("VerificationCode") or response.get("verificationCode", "")
        zimra_device = (response.get("ZimraDeviceId")
                        or response.get("zimraDeviceId") or self.device_id)
        counter = response.get("GlobalCounter") or response.get("globalCounter", "")
        return {
            "accepted": True,
            "reference": str(response.get("Reference")
                             or response.get("reference") or verification),
            "signature": verification,
            "qr_data": f"{zimra_device}|{counter}|{verification}",
            "url": response.get("QrUrl") or response.get("qrUrl", ""),
            "code": "ACCEPTED",
            "message": "Receipt signed and filed",
            "verification_code": verification,
            "zimra_device_id": zimra_device,
            "global_counter": counter,
        }

    def receipt(self, reference: str) -> dict:
        """Retrieve a previously submitted receipt - the reconciliation path."""
        code, response = self._call("GET", f"/api/receipt/{reference}")
        return {"found": code == 200, "http_status": code, "receipt": response}

    def close_day(self, payload: dict) -> dict:
        # CloudESD holds the fiscal day at their end; the local Z-report still
        # closes so the hash chain is complete either way.
        state = self.status()
        return {"accepted": True, "reference": "", "code": "DELEGATED",
                "message": ("CloudESD holds the fiscal day (status "
                            f"{state.get('fiscal_day_status', 'unknown')})")}


class ZimraFdmsDevice(FiscalDevice):
    """Virtual fiscalisation: this software interfaces ZIMRA directly.

    The route for an operator with enough tills to justify owning the
    integration rather than buying a device per counter. ZIMRA publishes no
    driver and no component to install - it publishes the **Fiscal Device
    Gateway API Specification**, and everything below comes from that document.

    NOT IMPLEMENTED, deliberately. A compliance integration that silently files
    the wrong shape is worse than one that has not started, so nothing here is
    guessed. What the specification supplies and this class needs:

      * device registration, and the certificate ZIMRA issues to the device
      * server certificate retrieval, and how it is refreshed
      * the signature scheme - each receipt payload is signed by the device
      * endpoint URLs and the receipt payload schema
      * the fiscal-day open and close calls
      * the QR-code payload format for the printed slip

    Everything around it is built and proven against the simulator: fiscal days,
    hash-chained counters, the offline queue with retry, credit notes, the
    Z-report, and the rule that a filed receipt is credit-noted rather than
    voided. Implementing this class is the remaining work.

    A pharmacy that does not want to own this should be on `cloudesd` or
    `external` instead - both are legitimate routes to the same obligation.

        FISCAL_API_URL / FISCAL_DEVICE_ID / FISCAL_CERT_PATH / FISCAL_KEY_PATH
    """

    name = "zimra_fdms"

    def __init__(self):
        self.api_url = os.getenv("FISCAL_API_URL", "")
        self.device_id = os.getenv("FISCAL_DEVICE_ID", "")
        self.cert_path = os.getenv("FISCAL_CERT_PATH", "")
        self.key_path = os.getenv("FISCAL_KEY_PATH", "")

    def status(self) -> dict:
        return {
            "driver": self.name, "ready": False, "required": True,
            "device_id": self.device_id or None,
            "configured": bool(self.api_url and self.device_id and self.cert_path),
            "message": "ZIMRA FDMS driver is not implemented — supply the FDMS "
                       "specification and this is the only class that changes.",
        }

    def submit_receipt(self, payload: dict) -> dict:
        raise NotImplementedError(
            "ZIMRA FDMS submission is not implemented. Receipts continue to queue "
            "locally with a valid hash chain, so nothing is lost — but they are "
            "not being filed with ZIMRA and the till is not compliant."
        )

    def close_day(self, payload: dict) -> dict:
        raise NotImplementedError("ZIMRA FDMS day-close is not implemented.")


DRIVERS = {
    "none": NoFiscalDevice,
    "external": ExternalFiscalDevice,
    "simulator": SimulatorFiscalDevice,
    "cloudesd": CloudEsdDevice,
    "zimra_fdms": ZimraFdmsDevice,
}


# The three routes to compliance, published so an installation can be asked
# which one it is on rather than having it inferred from a driver name.
ROUTES = {
    "external": {
        "route": "Approved Supplier hardware fiscal device",
        "who_files": "The fiscal device supplied and registered by an Approved Supplier",
        "suits": "A pharmacy with one or a few tills.",
        "setup": "Procure and register the device through a ZIMRA Approved "
                 "Supplier, then declare it with FISCAL_SUPPLIER and "
                 "FISCAL_DEVICE_SERIAL.",
    },
    "cloudesd": {
        "route": "Virtual fiscalisation through a hosted service",
        "who_files": "CloudESD, on the taxpayer's behalf",
        "suits": "A pharmacy that wants virtual fiscalisation without operating "
                 "the ZIMRA integration itself.",
        "setup": "Obtain a tenant id and bearer token from the CloudESD portal.",
    },
    "zimra_fdms": {
        "route": "Virtual fiscalisation direct to ZIMRA",
        "who_files": "RX3000, against the Fiscal Device Gateway API",
        "suits": "A multi-till operator prepared to own device registration, "
                 "certificates and signature generation.",
        "setup": "Obtain the Fiscal Device Gateway API Specification and register "
                 "the device with ZIMRA.",
    },
    "simulator": {
        "route": "Simulated — development only",
        "who_files": "Nobody. Receipts are signed plausibly and filed nowhere.",
        "suits": "Building and demonstrating the system.",
        "setup": "Refuses to act when RX3000_ENV=production.",
    },
    "none": {
        "route": "No fiscal obligation",
        "who_files": "Not applicable.",
        "suits": "A jurisdiction that does not fiscalise.",
        "setup": "Nothing to do.",
    },
}


def route_for(name: str) -> dict:
    return ROUTES.get(name, ROUTES["none"])


def get_device(required_by_jurisdiction: str | None) -> FiscalDevice:
    """Resolve the route: explicit setting wins, else the jurisdiction's default.

    Where a jurisdiction fiscalises and nothing has been chosen, the simulator is
    the default so a fresh install runs — and it refuses to act in production, so
    the choice cannot be left unmade on a live till.
    """
    choice = os.getenv("FISCAL_DEVICE", "").lower()
    if not choice:
        choice = "simulator" if required_by_jurisdiction else "none"
    driver = DRIVERS.get(choice, NoFiscalDevice)
    return driver()
