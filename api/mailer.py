"""Transactional email: account verification, password reset and alert emails.

Mail goes to the account's own address and raises on failure, so every caller
knows whether it was handed to the server (alerts/delivery.py retries on that).
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Optional

from config import ALERT_EMAIL_SENDER, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME


def mail_configured() -> bool:
    return bool(SMTP_HOST and ALERT_EMAIL_SENDER)


def send_email(to: str, subject: str, body: str, message_id: Optional[str] = None) -> None:
    """Send one plain-text email over STARTTLS with a verified certificate.

    Raises on any failure. ``to`` must already be a validated address (the
    API's email check rejects whitespace, so no header injection).
    ``message_id`` (``<local@domain>``) makes a retried send the same message.
    """

    if not mail_configured():
        raise RuntimeError("SMTP is not configured")
    message = EmailMessage()
    message["From"] = f"HalalLens <{ALERT_EMAIL_SENDER}>"
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = message_id or make_msgid(domain=ALERT_EMAIL_SENDER.rsplit("@", 1)[-1])
    message.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        server.starttls(context=ssl.create_default_context())
        if SMTP_USERNAME:
            server.login(SMTP_USERNAME, SMTP_PASSWORD or "")
        server.send_message(message)
