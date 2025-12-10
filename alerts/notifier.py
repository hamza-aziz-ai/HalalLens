#!/usr/bin/env python3
"""Email notifier for alert events."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

from alerts.engine import AlertEvent

logger = logging.getLogger("alerts.notifier")


class EmailNotifier:
    """Sends alert events via SMTP email."""

    def __init__(
        self,
        host: Optional[str],
        port: int,
        username: Optional[str],
        password: Optional[str],
        sender: Optional[str],
        recipient: Optional[str],
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.recipient = recipient

    @property
    def enabled(self) -> bool:
        return all([self.host, self.sender, self.recipient])

    def send(self, event: AlertEvent) -> None:
        if not self.enabled:
            return
        msg = EmailMessage()
        msg["Subject"] = f"[HalalLens] Alert for {event.symbol}"
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg.set_content(
            f"Trigger: {event.trigger}\nSymbol: {event.symbol}\nMessage: {event.message}"
        )

        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                server.starttls()
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.send_message(msg)
        except Exception:
            logger.exception("Failed to send alert email for %s", event.symbol)
