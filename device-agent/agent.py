"""RX3000 device agent.

A browser cannot open a serial port, send an ESC/POS pulse to a cash drawer, or
hold a socket to a card terminal. This is the small local service that can. It
runs on the till PC and RX3000 talks to it over localhost.

    python agent.py                 # starts on http://127.0.0.1:9110

Endpoints
    GET  /status                    what hardware is configured and reachable
    POST /print                     raw ESC/POS receipt printing (silent)
    POST /drawer/kick               open the cash drawer
    POST /terminal/payment          take a card payment, return the slip detail
    POST /terminal/cancel           cancel an in-flight terminal request
    POST /biometric/capture         one fingerprint impression, for verification
    POST /biometric/enrol           the several impressions an enrolment needs

Nothing here talks to the RX3000 server: the browser is the only client, so the
agent never needs credentials and never leaves the till.
"""
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from biometric import MIN_QUALITY, get_biometric_driver
from drivers import get_mobile_driver, get_terminal_driver
from printing import CashDrawer, Printers, ReceiptPrinter

log = logging.getLogger("rx3000.agent")

HOST = os.getenv("AGENT_HOST", "127.0.0.1")
PORT = int(os.getenv("AGENT_PORT", "9110"))
# Only the RX3000 front end may call the agent.
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("AGENT_ORIGINS", "http://localhost:5180,http://127.0.0.1:5180").split(",")
    if o.strip()
]

printers = Printers()
# The drawer hangs off the receipt printer's RJ11 port specifically — it is a
# solenoid on the till, not on the label roll by the dispensary bench.
printer = printers.by_role["receipt"]
drawer = CashDrawer(printer)
terminal = get_terminal_driver()
mobile = get_mobile_driver()
biometric = get_biometric_driver()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    # ---- plumbing ----
    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in ALLOWED_ORIGINS

    def _cors(self):
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, status: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- routes ----
    def do_GET(self):
        if not self._origin_ok():
            return self._send(403, {"error": "origin not allowed"})
        if self.path.split("?")[0] == "/status":
            return self._send(200, {
                "agent": "rx3000-device-agent",
                "version": "1.0",
                # `printer` stays for the till already running against this
                # agent and reading one object; `printers` is the whole bench.
                "printer": printer.status(),
                "printers": printers.status(),
                "drawer": drawer.status(),
                "terminal": terminal.status(),
                "mobile_money": mobile.status(),
                "biometric": {**biometric.status(), "min_quality": MIN_QUALITY},
            })
        self._send(404, {"error": "unknown endpoint"})

    def do_POST(self):
        if not self._origin_ok():
            return self._send(403, {"error": "origin not allowed"})
        route = self.path.split("?")[0]
        body = self._read_json()

        try:
            if route == "/print":
                # Defaults to the receipt roll, so a caller that predates roles
                # keeps printing exactly where it did.
                target = printers.get(str(body.get("role", "receipt")))
                result = target.print_receipt(
                    lines=body.get("lines", []),
                    cut=body.get("cut", True),
                    open_drawer=body.get("open_drawer", False),
                )
                return self._send(200, {**result, "role": target.role,
                                        "port": target.port or None})

            if route == "/drawer/kick":
                return self._send(200, drawer.kick())

            if route == "/terminal/payment":
                amount = float(body.get("amount") or 0)
                if amount <= 0:
                    return self._send(400, {"error": "amount must be positive"})
                result = terminal.payment(amount, reference=body.get("reference", ""))
                return self._send(200 if result.get("approved") else 402, result)

            if route == "/terminal/cancel":
                return self._send(200, terminal.cancel())

            # Mobile money is push-and-poll: initiate returns immediately with a
            # token, and the till polls until the customer approves or it expires.
            if route == "/mobile/initiate":
                amount = float(body.get("amount") or 0)
                if amount <= 0:
                    return self._send(400, {"error": "amount must be positive"})
                phone = (body.get("phone") or "").strip()
                if not phone:
                    return self._send(400, {"error": "phone number is required"})
                result = mobile.initiate(amount, phone,
                                         body.get("method", "ecocash"),
                                         body.get("reference", ""))
                return self._send(200 if result.get("started") else 400, result)

            if route == "/mobile/poll":
                poll_ref = (body.get("poll_ref") or "").strip()
                if not poll_ref:
                    return self._send(400, {"error": "poll_ref is required"})
                return self._send(200, mobile.poll(poll_ref))

            # A capture is handed to the caller and forgotten. The agent keeps
            # no copy, and the template is never written to the log.
            if route == "/biometric/capture":
                result = biometric.capture(body.get("finger", "right_index"),
                                           float(body.get("timeout") or 20))
                if result.get("captured") and result.get("quality", 100) < MIN_QUALITY:
                    result["captured"] = False
                    result["retake"] = True
                    result.pop("template", None)
                return self._send(200 if result.get("captured") else 422, result)

            # Enrolment is the same capture several times over: funders register
            # a finger from multiple impressions, not one.
            if route == "/biometric/enrol":
                finger = body.get("finger", "right_index")
                needed = int(body.get("captures") or biometric.enrolment_captures)
                impressions, failure = [], None
                for _ in range(max(1, needed)):
                    shot = biometric.capture(finger, float(body.get("timeout") or 20))
                    if not shot.get("captured") or shot.get("quality", 100) < MIN_QUALITY:
                        shot.pop("template", None)
                        failure = shot
                        break
                    impressions.append(shot)
                if failure is not None:
                    return self._send(422, {
                        "enrolled": False, "captured": len(impressions),
                        "required": needed, "finger": finger,
                        "message": failure.get("message", "Enrolment could not be completed"),
                    })
                return self._send(200, {
                    "enrolled": True, "finger": finger,
                    "format": impressions[0].get("format", ""),
                    "quality": min(i.get("quality", 0) for i in impressions),
                    "templates": [i["template"] for i in impressions],
                    "message": f"{len(impressions)} impressions captured for {finger}",
                })

        except Exception as exc:  # a dead printer must not kill the agent
            log.exception("device call failed")
            return self._send(500, {"error": str(exc)})

        self._send(404, {"error": "unknown endpoint"})


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("RX3000 device agent on http://%s:%d", HOST, PORT)
    for role, state in printers.status().items():
        log.info("printer[%s]=%s", role, state)
    log.info("terminal=%s mobile=%s", terminal.status(), mobile.status())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
