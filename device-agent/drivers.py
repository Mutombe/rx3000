"""Card terminal drivers.

Every acquirer speaks its own protocol, so the agent talks to an interface and
the acquirer-specific part is a swappable driver. Adding a real terminal means
writing one class here — nothing in RX3000 itself changes.

    TERMINAL_DRIVER   simulator | tcp | none      (default: simulator)

The simulator lets the whole card flow — tender, approval, slip capture and
reconciliation — be built and tested before any hardware or merchant agreement
exists. It is deliberately not the default in production: set TERMINAL_DRIVER
explicitly once a real driver is in place.
"""
import hashlib
import logging
import os
import random
import socket
import string
import time
import urllib.parse
import urllib.request

log = logging.getLogger("rx3000.agent.terminal")


# ---------------------------------------------------------------------------
# Production guard
#
# Every simulator in this file approves things. On a real counter that would
# mean handing over goods against a card payment nobody took, so a till marked
# as production refuses to use one rather than quietly pretending.
#
#     AGENT_ENV=production
# ---------------------------------------------------------------------------

def is_production() -> bool:
    return os.getenv("AGENT_ENV", "development").strip().lower() in ("production", "prod", "live")


def simulator_refusal(what: str, setting: str, real: str) -> str:
    return (f"The {what} simulator will not run on a till marked as production "
            f"(AGENT_ENV={os.getenv('AGENT_ENV', '')}). Set {setting}={real} and "
            f"configure the real device, or unset AGENT_ENV while testing.")



class TerminalDriver:
    """Interface a card terminal driver must satisfy.

    `payment` blocks until the customer has tapped/inserted and the terminal has
    an answer, then returns the fields RX3000 stores against the sale:

        approved      bool
        auth_code     the acquirer's approval code
        reference     the acquirer's own transaction reference (RRN)
        last4         last four digits of the PAN
        scheme        visa | mastercard | amex …
        terminal_id   which terminal took it
        batch         settlement batch the transaction landed in
        message       human-readable outcome, shown to the cashier on decline
    """

    name = "base"

    def status(self) -> dict:
        raise NotImplementedError

    def payment(self, amount: float, reference: str = "") -> dict:
        raise NotImplementedError

    def cancel(self) -> dict:
        return {"cancelled": False, "message": "This driver cannot cancel a request"}


class NoTerminal(TerminalDriver):
    """No terminal wired up — the cashier keys the amount on a standalone machine."""

    name = "none"

    def status(self) -> dict:
        return {"driver": self.name, "ready": False,
                "message": "No terminal configured — capture the slip detail by hand"}

    def payment(self, amount: float, reference: str = "") -> dict:
        return {"approved": False, "message": "No card terminal is connected to this till"}


class SimulatorTerminal(TerminalDriver):
    """Approves almost everything after a realistic pause.

    Amounts ending in .13 decline, so the decline path can be exercised
    deliberately rather than by waiting for a random failure.
    """

    name = "simulator"

    def __init__(self):
        self.terminal_id = os.getenv("TERMINAL_ID", "SIM0001")
        self.delay = float(os.getenv("TERMINAL_SIM_DELAY", "1.5"))
        self.batch = time.strftime("%Y%m%d")

    def status(self) -> dict:
        live = is_production()
        return {"driver": self.name, "ready": not live, "terminal_id": self.terminal_id,
                "simulated": True,
                "message": (simulator_refusal("card terminal", "TERMINAL_DRIVER", "tcp") if live
                            else "Simulated terminal — amounts ending .13 decline")}

    def payment(self, amount: float, reference: str = "") -> dict:
        if is_production():
            return {"approved": False, "terminal_id": self.terminal_id,
                    "message": simulator_refusal("card terminal", "TERMINAL_DRIVER", "tcp")}
        time.sleep(self.delay)
        cents = round(amount - int(amount), 2)
        if abs(cents - 0.13) < 0.001:
            log.info("simulated decline for %.2f", amount)
            return {"approved": False, "message": "DECLINED — insufficient funds",
                    "terminal_id": self.terminal_id}
        scheme = random.choice(["visa", "mastercard"])
        result = {
            "approved": True,
            "auth_code": "".join(random.choices(string.ascii_uppercase + string.digits, k=6)),
            "reference": "".join(random.choices(string.digits, k=12)),
            "last4": "".join(random.choices(string.digits, k=4)),
            "scheme": scheme,
            "terminal_id": self.terminal_id,
            "batch": self.batch,
            "message": "APPROVED",
        }
        log.info("simulated approval %s for %.2f", result["auth_code"], amount)
        return result


class TcpTerminal(TerminalDriver):
    """Semi-integrated terminal reachable over the LAN.

    This is the shape most acquirers' semi-integrated modes take: open a socket
    to the terminal, send a request, block for the response. The framing below
    is a placeholder — the real message format comes from the acquirer's
    integration guide, and that is the one method to rewrite.

        TERMINAL_HOST / TERMINAL_PORT / TERMINAL_TIMEOUT
    """

    name = "tcp"

    def __init__(self):
        self.host = os.getenv("TERMINAL_HOST", "")
        self.port = int(os.getenv("TERMINAL_PORT", "0") or 0)
        self.timeout = float(os.getenv("TERMINAL_TIMEOUT", "120"))
        self.terminal_id = os.getenv("TERMINAL_ID", "")

    def status(self) -> dict:
        ready = bool(self.host and self.port)
        info = {"driver": self.name, "ready": ready, "host": self.host or None,
                "port": self.port or None, "terminal_id": self.terminal_id or None}
        if not ready:
            info["message"] = "Set TERMINAL_HOST and TERMINAL_PORT"
            return info
        try:
            with socket.create_connection((self.host, self.port), timeout=2):
                info["reachable"] = True
        except OSError as exc:
            info["reachable"] = False
            info["message"] = f"Cannot reach terminal: {exc}"
        return info

    def payment(self, amount: float, reference: str = "") -> dict:
        if not (self.host and self.port):
            return {"approved": False, "message": "Terminal address not configured"}
        raise NotImplementedError(
            "Fill in the acquirer's request/response framing here — see their "
            "semi-integration guide. Everything else (tender flow, slip capture, "
            "reconciliation) is already wired and works against the simulator."
        )


# ---------------------------------------------------------------------------
# Mobile money
#
# Mobile money is not a card terminal with a different logo. A card payment is
# synchronous: you send an amount and block until the terminal answers. A mobile
# money payment is a *push* — the customer gets a prompt on their handset, walks
# to a corner of the shop, finds their PIN, and may never complete it. So the
# driver is two calls, not one: initiate, then poll until it resolves or times
# out. Modelling it as a blocking call would freeze the till.
# ---------------------------------------------------------------------------

class MobileMoneyDriver:
    """Interface a mobile money provider must satisfy.

    `initiate` returns immediately with a poll reference:
        started     bool
        poll_ref    opaque token passed back to poll()
        reference   the provider's transaction reference, if known this early
        message     what to tell the cashier ("Ask the customer to approve…")

    `poll` returns:
        state       pending | paid | cancelled | failed
        reference   provider reference once known
        message     human-readable status
    """

    name = "base"
    # Most providers expire an unapproved push after a few minutes.
    timeout_seconds = 180

    def status(self) -> dict:
        raise NotImplementedError

    def initiate(self, amount: float, phone: str, method: str, reference: str = "") -> dict:
        raise NotImplementedError

    def poll(self, poll_ref: str) -> dict:
        raise NotImplementedError


class NoMobileMoney(MobileMoneyDriver):
    name = "none"

    def status(self) -> dict:
        return {"driver": self.name, "ready": False,
                "message": "No mobile money provider configured"}

    def initiate(self, amount: float, phone: str, method: str, reference: str = "") -> dict:
        return {"started": False, "message": "No mobile money provider is configured on this till"}

    def poll(self, poll_ref: str) -> dict:
        return {"state": "failed", "message": "No mobile money provider configured"}


class SimulatorMobileMoney(MobileMoneyDriver):
    """Models the real push-and-poll rhythm without a provider account.

    Resolves a few seconds after initiation so the polling UI can be built and
    watched. Phone numbers ending 00 are cancelled by the "customer" and ending
    99 fail outright, so both unhappy paths can be exercised on demand.
    """

    name = "simulator"

    def __init__(self):
        self.settle_after = float(os.getenv("MOBILE_SIM_SECONDS", "6"))
        self._requests: dict[str, dict] = {}

    def status(self) -> dict:
        live = is_production()
        return {"driver": self.name, "ready": not live, "simulated": True,
                "timeout_seconds": self.timeout_seconds,
                "message": (simulator_refusal("mobile money", "MOBILE_MONEY_DRIVER", "paynow") if live
                            else "Simulated mobile money — phone ending 00 cancels, 99 fails")}

    def initiate(self, amount: float, phone: str, method: str, reference: str = "") -> dict:
        if is_production():
            return {"started": False,
                    "message": simulator_refusal("mobile money", "MOBILE_MONEY_DRIVER", "paynow")}
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) < 9:
            return {"started": False, "message": "That does not look like a valid mobile number"}
        poll_ref = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
        outcome = "paid"
        if digits.endswith("00"):
            outcome = "cancelled"
        elif digits.endswith("99"):
            outcome = "failed"
        self._requests[poll_ref] = {
            "resolves_at": time.monotonic() + self.settle_after,
            "outcome": outcome,
            "amount": amount,
            "reference": "".join(random.choices(string.digits, k=12)),
            "method": method,
        }
        log.info("mobile money push %s to %s for %.2f", poll_ref, phone, amount)
        return {
            "started": True, "poll_ref": poll_ref, "reference": "",
            "message": f"Push sent to {phone}. Ask the customer to approve it on their handset.",
        }

    def poll(self, poll_ref: str) -> dict:
        request = self._requests.get(poll_ref)
        if not request:
            return {"state": "failed", "message": "Unknown payment request"}
        if time.monotonic() < request["resolves_at"]:
            return {"state": "pending", "message": "Waiting for the customer to approve"}
        state = request["outcome"]
        messages = {
            "paid": "Payment received",
            "cancelled": "Customer cancelled the request",
            "failed": "Payment failed — insufficient balance",
        }
        return {
            "state": state,
            "reference": request["reference"] if state == "paid" else "",
            "message": messages[state],
        }


class PaynowDriver(MobileMoneyDriver):
    """Paynow (Zimbabwe) - EcoCash and OneMoney behind one interface.

    The wire format below is taken from Paynow's own published SDK, not guessed:

        initiate   POST https://www.paynow.co.zw/interface/remotetransaction
        poll       GET  the `pollurl` returned by initiate

    Both sides are form-urlencoded, and both are urlencoded key=value on the way
    back too - not JSON. Three details are easy to get wrong and are handled
    explicitly here:

    * **The hash covers values, in order, with no separators.** Every value in
      the request is concatenated in insertion order, the integration key is
      appended, and the result is SHA-512 in upper-case hex. Order therefore
      matters, so the payload is built as an ordered dict and never re-sorted.

    * **The mobile endpoint lowercases the integration key before hashing.**
      The redirect endpoint does not. This asymmetry is in their SDK and there
      is no note explaining it; getting it wrong produces a hash mismatch that
      reads as an authentication failure.

    * **Replies are hash-verified.** A reply whose hash does not check out is
      discarded rather than trusted, because a spoofed "paid" is the one lie
      that costs stock.

        PAYNOW_INTEGRATION_ID / PAYNOW_INTEGRATION_KEY
        PAYNOW_AUTH_EMAIL   - required by Paynow on mobile transactions
        PAYNOW_RESULT_URL / PAYNOW_RETURN_URL   - optional callbacks
    """

    name = "paynow"
    INITIATE_MOBILE_URL = "https://www.paynow.co.zw/interface/remotetransaction"
    INITIATE_URL = "https://www.paynow.co.zw/interface/initiatetransaction"
    TIMEOUT = 30

    # Paynow's status vocabulary, mapped onto the three outcomes a till cares
    # about. Anything unrecognised stays pending rather than being called paid.
    PAID = {"paid", "awaiting delivery", "delivered"}
    CANCELLED = {"cancelled"}
    FAILED = {"failed", "disputed", "refunded"}

    def __init__(self):
        self.integration_id = os.getenv("PAYNOW_INTEGRATION_ID", "")
        self.integration_key = os.getenv("PAYNOW_INTEGRATION_KEY", "")
        self.auth_email = os.getenv("PAYNOW_AUTH_EMAIL", "")
        self.result_url = os.getenv("PAYNOW_RESULT_URL", "")
        self.return_url = os.getenv("PAYNOW_RETURN_URL", "")
        self._polls: dict[str, str] = {}

    # ---- hashing ----
    @staticmethod
    def _hash(values: dict, key: str) -> str:
        """Concatenate every value except `hash`, append the key, SHA-512, upper hex."""
        joined = "".join(str(v) for k, v in values.items() if k.lower() != "hash")
        return hashlib.sha512((joined + key).encode()).hexdigest().upper()

    def _verify(self, reply: dict, key: str) -> bool:
        """A reply without a hash is untrusted; a reply with a wrong one is rejected."""
        given = reply.get("hash")
        if not given:
            return False
        return self._hash(reply, key) == given.upper()

    # ---- transport ----
    def _post(self, url: str, payload: dict) -> dict:
        body = urllib.parse.urlencode(payload).encode()
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(request, timeout=self.TIMEOUT) as response:
            return self._parse(response.read().decode(errors="replace"))

    def _get(self, url: str) -> dict:
        with urllib.request.urlopen(url, timeout=self.TIMEOUT) as response:
            return self._parse(response.read().decode(errors="replace"))

    @staticmethod
    def _parse(raw: str) -> dict:
        """Replies are urlencoded key=value, not JSON."""
        return {k: v[0] if v else "" for k, v in urllib.parse.parse_qs(raw).items()}

    def _configured(self) -> bool:
        return bool(self.integration_id and self.integration_key)

    # ---- interface ----
    def status(self) -> dict:
        ready = self._configured() and bool(self.auth_email)
        info = {"driver": self.name, "ready": ready,
                "configured": self._configured(),
                "timeout_seconds": self.timeout_seconds,
                "methods": ["ecocash", "onemoney"]}
        if not self._configured():
            info["message"] = "Set PAYNOW_INTEGRATION_ID and PAYNOW_INTEGRATION_KEY"
        elif not self.auth_email:
            info["message"] = ("Set PAYNOW_AUTH_EMAIL - Paynow requires an auth "
                               "email on mobile transactions")
        else:
            info["message"] = "Paynow ready"
        return info

    def initiate(self, amount: float, phone: str, method: str, reference: str = "") -> dict:
        if not self._configured():
            return {"started": False, "message": "Paynow is not configured on this till"}
        if not self.auth_email:
            return {"started": False,
                    "message": "Paynow requires an auth email for mobile payments "
                               "- set PAYNOW_AUTH_EMAIL"}
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) < 9:
            return {"started": False, "message": "That does not look like a valid mobile number"}

        method = (method or "ecocash").lower()
        reference = reference or "RX3000"
        # Insertion order is part of the hash. Do not reorder these.
        payload = {
            "resulturl": self.result_url,
            "returnurl": self.return_url,
            "reference": reference,
            "amount": f"{amount:.2f}",
            "id": self.integration_id,
            "additionalinfo": f"RX3000 {reference}",
            "authemail": self.auth_email,
            "status": "Message",
            "phone": digits,
            "method": method,
        }
        # Their SDK trims every value before hashing, so a reference that
        # arrives with stray whitespace hashes the same on both sides.
        payload = {k: str(v).strip() for k, v in payload.items()}
        # The mobile endpoint hashes against the lowercased key. Their SDK does
        # this; the redirect endpoint does not.
        payload["hash"] = self._hash(payload, self.integration_key.lower())

        try:
            reply = self._post(self.INITIATE_MOBILE_URL, payload)
        except OSError as exc:
            log.warning("paynow unreachable: %s", exc)
            return {"started": False, "message": f"Could not reach Paynow: {exc}"}

        if (reply.get("status", "").lower() != "ok"):
            return {"started": False,
                    "message": reply.get("error") or "Paynow rejected the request"}
        # Note the asymmetry: the outbound mobile request is hashed with the
        # lowercased key, but every inbound reply — initiate and poll alike — is
        # verified with the key as issued. Their SDK does exactly this.
        if not self._verify(reply, self.integration_key):
            # A reply we cannot authenticate is not a reply we act on.
            return {"started": False,
                    "message": "Paynow's reply failed hash verification and was discarded"}

        poll_url = reply.get("pollurl", "")
        if not poll_url:
            return {"started": False, "message": "Paynow did not return a poll url"}
        poll_ref = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
        self._polls[poll_ref] = poll_url
        log.info("paynow push %s to %s for %.2f via %s", poll_ref, digits, amount, method)
        return {
            "started": True,
            "poll_ref": poll_ref,
            "reference": reference,
            "message": reply.get("instructions")
                       or f"Push sent to {phone}. Ask the customer to approve it on their handset.",
        }

    def poll(self, poll_ref: str) -> dict:
        url = self._polls.get(poll_ref)
        if not url:
            return {"state": "failed", "message": "Unknown payment request"}
        try:
            reply = self._get(url)
        except OSError as exc:
            # A network blip is not a failed payment - keep waiting.
            return {"state": "pending", "message": f"Could not reach Paynow: {exc}"}

        if not self._verify(reply, self.integration_key):
            return {"state": "pending",
                    "message": "Paynow's reply failed hash verification"}

        status = (reply.get("status") or "").lower()
        reference = reply.get("paynowreference") or reply.get("reference") or ""
        if status in self.PAID:
            self._polls.pop(poll_ref, None)
            return {"state": "paid", "reference": reference, "message": "Payment received"}
        if status in self.CANCELLED:
            self._polls.pop(poll_ref, None)
            return {"state": "cancelled", "reference": "",
                    "message": "Customer cancelled the request"}
        if status in self.FAILED:
            self._polls.pop(poll_ref, None)
            return {"state": "failed", "reference": "",
                    "message": f"Payment {status}"}
        # created / sent / pending, and anything new they add.
        return {"state": "pending", "reference": "",
                "message": "Waiting for the customer to approve"}


MOBILE_DRIVERS = {
    "none": NoMobileMoney,
    "simulator": SimulatorMobileMoney,
    "paynow": PaynowDriver,
}


def get_mobile_driver() -> MobileMoneyDriver:
    choice = os.getenv("MOBILE_MONEY_DRIVER", "none").lower()
    driver = MOBILE_DRIVERS.get(choice, NoMobileMoney)
    log.info("mobile money driver: %s", choice)
    return driver()


DRIVERS = {"simulator": SimulatorTerminal, "tcp": TcpTerminal, "none": NoTerminal}


def get_terminal_driver() -> TerminalDriver:
    choice = os.getenv("TERMINAL_DRIVER", "simulator").lower()
    driver = DRIVERS.get(choice, NoTerminal)
    log.info("terminal driver: %s", choice)
    return driver()
