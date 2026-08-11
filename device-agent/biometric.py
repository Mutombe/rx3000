"""Fingerprint reader drivers.

Health 263 supplies the fingerprint reader as physical hardware at the till and
retains ownership of it, so it sits here alongside the printer and the cash
drawer rather than anywhere in RX3000 itself.

    BIOMETRIC_DRIVER    simulator | health263 | none      (default: none)

**The template never rests here.** A fingerprint is biometric personal data
under the Cyber and Data Protection Act, and the matching happens at the switch
against the funder's own enrolment — not on the till. So a capture is read from
the sensor, handed straight to the caller, and forgotten. Nothing on this
machine writes a template to disk, and the gateway redacts it from the audit
trail. The only lasting record of a verification is that one happened, when, and
whether it matched.
"""
import base64
import hashlib
import logging
import os
import random
import time

from drivers import is_production, simulator_refusal

log = logging.getLogger("rx3000.agent.biometric")


class BiometricDriver:
    """Interface a fingerprint reader must satisfy.

    `capture` blocks until a finger is presented and the sensor has an image,
    then returns:

        captured    bool
        template    base64 of the vendor's template — passed straight through
        format      the vendor's template format, so the switch knows how to read it
        quality     0-100; a poor image is worth retaking before it is sent
        finger      which finger was asked for
        message     human-readable outcome, shown to the cashier

    `enrol` is the same capture repeated: funders want several impressions of
    the same finger before they will register it.
    """

    name = "base"
    # How many impressions an enrolment takes. Verification always takes one.
    enrolment_captures = 3

    def status(self) -> dict:
        raise NotImplementedError

    def capture(self, finger: str = "right_index", timeout: float = 20.0) -> dict:
        raise NotImplementedError

    def cancel(self) -> dict:
        return {"cancelled": False, "message": "This driver cannot cancel a capture"}


class NoBiometric(BiometricDriver):
    """No reader wired up — the member is identified by card and ID instead."""

    name = "none"

    def status(self) -> dict:
        return {"driver": self.name, "ready": False,
                "message": "No fingerprint reader configured — verify the member by card and ID"}

    def capture(self, finger: str = "right_index", timeout: float = 20.0) -> dict:
        return {"captured": False,
                "message": "No fingerprint reader is connected to this till"}


class SimulatorBiometric(BiometricDriver):
    """Produces a deterministic template so the whole flow is exercisable.

    The template is derived from the finger name, so the same finger always
    yields the same bytes and a match can be asserted rather than hoped for.
    Deliberate triggers instead of random failure:

        finger name containing "wet"    a poor-quality image, worth retaking
        finger name containing "none"   no finger presented before the timeout
    """

    name = "simulator"

    def __init__(self):
        self.delay = float(os.getenv("BIOMETRIC_SIM_DELAY", "1.2"))
        self.device_id = os.getenv("BIOMETRIC_DEVICE_ID", "SIMFP001")

    def status(self) -> dict:
        live = is_production()
        return {"driver": self.name, "ready": not live, "device_id": self.device_id,
                "simulated": True,
                "format": "SIM-TEMPLATE-1", "enrolment_captures": self.enrolment_captures,
                "message": (simulator_refusal("fingerprint reader", "BIOMETRIC_DRIVER", "health263")
                            if live else
                            'Simulated reader — a finger named "wet" scans poorly, "none" times out')}

    def capture(self, finger: str = "right_index", timeout: float = 20.0) -> dict:
        # A simulated match is an identity claim nobody made. Never in production.
        if is_production():
            return {"captured": False, "finger": finger,
                    "message": simulator_refusal("fingerprint reader", "BIOMETRIC_DRIVER",
                                                 "health263")}
        time.sleep(self.delay)
        finger = (finger or "right_index").lower()

        if "none" in finger:
            return {"captured": False, "finger": finger,
                    "message": "No finger was presented before the reader timed out"}

        quality = random.randint(30, 45) if "wet" in finger else random.randint(78, 99)
        digest = hashlib.sha256(f"rx3000:{finger}".encode()).digest()
        result = {
            "captured": True,
            "template": base64.b64encode(digest).decode(),
            "format": "SIM-TEMPLATE-1",
            "quality": quality,
            "finger": finger,
            "device_id": self.device_id,
            "message": "Fingerprint captured",
        }
        if quality < 60:
            result["message"] = (f"Image quality is {quality}% — wipe the sensor "
                                 "and the finger, then scan again")
        # The template is logged nowhere. Quality and finger are all that is safe.
        log.info("captured %s at quality %d", finger, quality)
        return result


class Health263Reader(BiometricDriver):
    """The reader Health 263 supplies under the HSP contract.

    NOT IMPLEMENTED. The contract establishes the commercial position — the
    device is theirs, provided free on connection, returned on termination, and
    charged at USD 150 if lost or damaged — but it is not a technical document
    and names neither the sensor model nor its SDK. What is needed:

      * the make and model of the reader they issue
      * its capture SDK or driver, and the call that returns a template
      * the template format identifier the switch expects
      * whether enrolment is driven from the till or from their own portal

    Everything around this class is finished: capture, quality gating,
    enrolment's repeated impressions, the transport into eligibility and
    claims, the redaction that keeps templates out of the audit trail, and the
    refusal to claim against a biometric funder without one.

        BIOMETRIC_DEVICE_ID / BIOMETRIC_SDK_PATH
    """

    name = "health263"

    def __init__(self):
        self.device_id = os.getenv("BIOMETRIC_DEVICE_ID", "")
        self.sdk_path = os.getenv("BIOMETRIC_SDK_PATH", "")

    def status(self) -> dict:
        return {
            "driver": self.name, "ready": False,
            "device_id": self.device_id or None,
            "configured": bool(self.sdk_path),
            "message": "The Health 263 reader driver is not implemented — supply the "
                       "device model and its capture SDK, and this is the only class "
                       "that changes.",
        }

    def capture(self, finger: str = "right_index", timeout: float = 20.0) -> dict:
        raise NotImplementedError(
            "Health 263 fingerprint capture is not implemented. The flow around it "
            "— quality gating, enrolment, transport to the switch and template "
            "redaction — is already wired and works against the simulator."
        )


DRIVERS = {
    "none": NoBiometric,
    "simulator": SimulatorBiometric,
    "health263": Health263Reader,
}

# A poor image sent to a switch comes back as a failed match, which reads to the
# cashier as "the member is a fraud" rather than "wipe the sensor". Gate it here.
MIN_QUALITY = int(os.getenv("BIOMETRIC_MIN_QUALITY", "60"))


def get_biometric_driver() -> BiometricDriver:
    choice = os.getenv("BIOMETRIC_DRIVER", "none").lower()
    driver = DRIVERS.get(choice, NoBiometric)
    log.info("biometric driver: %s", choice)
    return driver()
