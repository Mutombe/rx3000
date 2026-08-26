"""Outbound messaging: email via SMTP, SMS via configurable HTTP gateway.

When no provider is configured, messages are logged to the console and marked
sent with a note — so the full reminder pipeline works out of the box in dev.
"""
import logging
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText

from ..config import settings
from ..models import Message

log = logging.getLogger("rx5000.messaging")


def _send_email(to_addr: str, subject: str, body: str) -> tuple[bool, str]:
    if not settings.SMTP_HOST:
        log.info("EMAIL (console) to=%s subject=%s body=%s", to_addr, subject, body)
        return True, "console (SMTP not configured)"
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to_addr
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)
        return True, "smtp"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:190]


def _send_sms(phone: str, body: str) -> tuple[bool, str]:
    if not settings.SMS_GATEWAY_URL:
        log.info("SMS (console) to=%s body=%s", phone, body)
        return True, "console (SMS gateway not configured)"
    try:
        url = settings.SMS_GATEWAY_URL.format(
            phone=urllib.parse.quote(phone), message=urllib.parse.quote(body)
        )
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.status < 300, f"gateway HTTP {resp.status}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:190]


def deliver(message: Message) -> None:
    """Attempt delivery of a Message row and update its status in place."""
    patient = message.patient
    if message.channel == "email":
        if not patient.email:
            message.status, message.detail = "failed", "patient has no email address"
            return
        ok, detail = _send_email(patient.email, message.subject or "Message from your pharmacy", message.body)
    else:
        if not patient.phone:
            message.status, message.detail = "failed", "patient has no phone number"
            return
        ok, detail = _send_sms(patient.phone, message.body)

    message.status = "sent" if ok else "failed"
    message.detail = detail
    message.sent_at = datetime.utcnow() if ok else None
