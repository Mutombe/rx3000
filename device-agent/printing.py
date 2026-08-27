"""ESC/POS receipt printing and cash-drawer control.

Thermal printers speak ESC/POS: a byte stream of text interleaved with control
codes. Writing those bytes straight to the device gives silent printing (no
browser dialog) and lets us send the drawer-kick pulse, which a browser cannot.

A counter has more than one printer. The receipt roll is 80mm and lives under
the till; the dispensing labels come off a 58mm roll beside the dispensary
bench. Sending both to one device means somebody peels a receipt off a label
roll, so printers are addressed by **role** rather than by there being only one.

    receipt   the 80mm till roll: sales, refunds, the drawer kick
    label     the 58mm label roll: dispensing labels
    report    anything long, usually an ordinary office printer

Configured with environment variables so a till can be set up without editing
code. The unprefixed names still work and still mean the receipt printer, so a
counter already running this does not have to be reconfigured:

    PRINTER_MODE            file | windows | none    (default: auto-detect)
    PRINTER_PORT            COM3, /dev/usb/lp0, or a Windows printer share name
    PRINTER_WIDTH           characters per line (default 42, the usual 80mm)

    LABEL_PRINTER_PORT      the label roll, if it is a different device
    LABEL_PRINTER_MODE      as above
    LABEL_PRINTER_WIDTH     characters per line (default 32, the usual 58mm)

    REPORT_PRINTER_PORT     an office printer, if raw printing suits it
    REPORT_PRINTER_MODE
    REPORT_PRINTER_WIDTH

    DRAWER_PIN              2 or 5 (default 2) — which RJ11 pin the drawer is on

A role with no port configured reports `ready: false` and falls back to the
role below it rather than failing: a pharmacy with one printer should get its
labels on that printer, not an error. Only `receipt` has no fallback, because
there is nothing under it.
"""
import logging
import os

log = logging.getLogger("rx3000.agent.print")

ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
ALIGN_LEFT = ESC + b"a\x00"
ALIGN_CENTRE = ESC + b"a\x01"
DOUBLE_ON = GS + b"!\x11"
DOUBLE_OFF = GS + b"!\x00"
CUT = GS + b"V\x42\x00"


def drawer_pulse(pin: int = 2) -> bytes:
    """ESC p m t1 t2 — fire the solenoid on pin 2 or 5."""
    m = 0 if pin == 2 else 1
    return ESC + b"p" + bytes([m, 25, 250])


#: Role -> (env prefix, default characters per line). Ordered widest first so
#: `fallback` below can walk down to something that exists.
ROLES = {
    "receipt": ("PRINTER", 42),
    "label": ("LABEL_PRINTER", 32),
    "report": ("REPORT_PRINTER", 80),
}


class ReceiptPrinter:
    """One physical printer, addressed by the role it serves.

    Still called ReceiptPrinter because that is what every caller imports and a
    rename buys nothing; it has simply stopped being the only one.
    """

    def __init__(self, role: str = "receipt"):
        prefix, default_width = ROLES.get(role, ROLES["receipt"])
        self.role = role
        self.port = os.getenv(f"{prefix}_PORT", "")
        self.width = int(os.getenv(f"{prefix}_WIDTH", str(default_width)))
        self.mode = os.getenv(f"{prefix}_MODE", "").lower() or self._detect()

    def _detect(self) -> str:
        if not self.port:
            return "none"
        return "windows" if os.name == "nt" and not self.port.upper().startswith("COM") else "file"

    def status(self) -> dict:
        return {"role": self.role, "mode": self.mode, "port": self.port or None,
                "width": self.width, "ready": self.mode != "none"}

    # ---- rendering ----
    def _render(self, lines: list[dict]) -> bytes:
        """Turn a simple line description into an ESC/POS byte stream.

        Each line is {"text": str, "align": left|centre|right, "bold": bool,
        "double": bool, "feed": int} — enough for a receipt without making the
        caller build byte sequences.
        """
        out = bytearray(INIT)
        for line in lines:
            text = str(line.get("text", ""))
            align = line.get("align", "left")
            if align == "centre" or align == "center":
                out += ALIGN_CENTRE
            else:
                out += ALIGN_LEFT
                if align == "right":
                    text = text.rjust(self.width)
            if line.get("double"):
                out += DOUBLE_ON
            if line.get("bold"):
                out += BOLD_ON
            out += text.encode("cp437", errors="replace") + b"\n"
            if line.get("bold"):
                out += BOLD_OFF
            if line.get("double"):
                out += DOUBLE_OFF
            for _ in range(int(line.get("feed", 0) or 0)):
                out += b"\n"
        return bytes(out)

    # ---- transport ----
    def _write(self, payload: bytes) -> None:
        if self.mode == "none":
            raise RuntimeError("No printer configured — set PRINTER_PORT")
        if self.mode == "windows":
            self._write_windows(payload)
        else:
            with open(self.port, "wb") as fh:
                fh.write(payload)

    def _write_windows(self, payload: bytes) -> None:
        """Send raw bytes to a Windows printer queue, bypassing the driver."""
        try:
            import win32print  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on host
            raise RuntimeError(
                "Windows raw printing needs pywin32 (pip install pywin32), "
                "or point PRINTER_PORT at a COM port instead"
            ) from exc
        handle = win32print.OpenPrinter(self.port)
        try:
            win32print.StartDocPrinter(handle, 1, ("RX3000 receipt", None, "RAW"))
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, payload)
            win32print.EndPagePrinter(handle)
            win32print.EndDocPrinter(handle)
        finally:
            win32print.ClosePrinter(handle)

    def print_receipt(self, lines: list[dict], cut: bool = True, open_drawer: bool = False) -> dict:
        payload = self._render(lines)
        if open_drawer:
            payload += drawer_pulse(int(os.getenv("DRAWER_PIN", "2")))
        if cut:
            payload += b"\n\n\n" + CUT
        self._write(payload)
        log.info("printed %d line(s), %d bytes", len(lines), len(payload))
        return {"printed": True, "bytes": len(payload), "lines": len(lines)}


class Printers:
    """Every printer this till has, and which one a job should go to.

    The fallback is the point. A single-printer pharmacy configures
    `PRINTER_PORT` and nothing else, and its labels come off that printer
    rather than raising "no label printer configured" — which is true, and
    unhelpful, and would send somebody to a settings screen to describe a
    counter that has one printer on it.
    """

    def __init__(self):
        self.by_role = {role: ReceiptPrinter(role) for role in ROLES}

    def status(self) -> dict:
        return {role: printer.status() for role, printer in self.by_role.items()}

    def get(self, role: str) -> ReceiptPrinter:
        """The printer for this role, or the nearest one that exists."""
        wanted = self.by_role.get(role) or self.by_role["receipt"]
        if wanted.mode != "none":
            return wanted
        # Walk down to anything configured. `receipt` is last because it is the
        # one a counter is most likely to have.
        for name in ("label", "report", "receipt"):
            candidate = self.by_role.get(name)
            if candidate is not None and candidate.mode != "none":
                return candidate
        return wanted        # nothing configured; let it raise its own message


class CashDrawer:
    """The drawer hangs off the printer's RJ11 port, so it kicks through it."""

    def __init__(self, printer: ReceiptPrinter):
        self.printer = printer
        self.pin = int(os.getenv("DRAWER_PIN", "2"))

    def status(self) -> dict:
        return {"pin": self.pin, "ready": self.printer.mode != "none",
                "via": "printer" if self.printer.mode != "none" else None}

    def kick(self) -> dict:
        self.printer._write(drawer_pulse(self.pin))
        log.info("drawer kicked on pin %d", self.pin)
        return {"opened": True, "pin": self.pin}
