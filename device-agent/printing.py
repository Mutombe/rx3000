"""ESC/POS receipt printing and cash-drawer control.

Thermal printers speak ESC/POS: a byte stream of text interleaved with control
codes. Writing those bytes straight to the device gives silent printing (no
browser dialog) and lets us send the drawer-kick pulse, which a browser cannot.

Configured with environment variables so a till can be set up without editing
code:

    PRINTER_MODE      file | windows | none      (default: auto-detect)
    PRINTER_PORT      COM3, /dev/usb/lp0, or a Windows printer share name
    PRINTER_WIDTH     characters per line (default 42, the usual 80mm width)
    DRAWER_PIN        2 or 5 (default 2) — which RJ11 pin the drawer sits on
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


class ReceiptPrinter:
    def __init__(self):
        self.port = os.getenv("PRINTER_PORT", "")
        self.width = int(os.getenv("PRINTER_WIDTH", "42"))
        self.mode = os.getenv("PRINTER_MODE", "").lower() or self._detect()

    def _detect(self) -> str:
        if not self.port:
            return "none"
        return "windows" if os.name == "nt" and not self.port.upper().startswith("COM") else "file"

    def status(self) -> dict:
        return {"mode": self.mode, "port": self.port or None, "width": self.width,
                "ready": self.mode != "none"}

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
