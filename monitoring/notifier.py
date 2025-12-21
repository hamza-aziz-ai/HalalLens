#!/usr/bin/env python3
"""Operations notifier for emailing or posting monitoring alerts."""

from __future__ import annotations

import logging
import os
import smtplib
import textwrap
from email.message import EmailMessage
from typing import Optional

import requests

logger = logging.getLogger("monitoring.notifier")


class OpsNotifier:
    """Dispatches monitoring alerts via email and/or Slack-compatible webhooks."""

    def __init__(self, component: str) -> None:
        self.component = component
        self.smtp_host = os.getenv("OPS_SMTP_HOST")
        self.smtp_port = int(os.getenv("OPS_SMTP_PORT", "587"))
        self.smtp_username = os.getenv("OPS_SMTP_USERNAME")
        self.smtp_password = os.getenv("OPS_SMTP_PASSWORD")
        self.email_sender = os.getenv("OPS_EMAIL_SENDER")
        self.email_recipient = os.getenv("OPS_EMAIL_RECIPIENT")
        self.slack_webhook = os.getenv("OPS_SLACK_WEBHOOK")

    def notify(self, severity: str, message: str, details: Optional[str] = None) -> None:
        """Send the alert to any configured channel."""

        severity = severity.upper()
        subject = f"[HalalLens][{self.component}] {severity}: {message}"
        body_lines = [
            f"Component: {self.component}",
            f"Severity: {severity}",
            f"Message : {message}",
        ]
        if details:
            body_lines.append("")
            body_lines.append("Details:")
            body_lines.append(textwrap.dedent(details).strip())
        body = "\n".join(body_lines)

        if self._email_enabled:
            try:
                self._send_email(subject, body)
            except Exception:
                logger.exception("Failed to send ops email alert")
        if self.slack_webhook:
            try:
                self._send_slack(subject, body)
            except Exception:
                logger.exception("Failed to send ops slack alert")

    @property
    def _email_enabled(self) -> bool:
        return all([self.smtp_host, self.email_sender, self.email_recipient])

    def _send_email(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.email_sender
        msg["To"] = self.email_recipient
        msg.set_content(body)

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
            server.starttls()
            if self.smtp_username and self.smtp_password:
                server.login(self.smtp_username, self.smtp_password)
            server.send_message(msg)

    def _send_slack(self, subject: str, body: str) -> None:
        payload = {"text": f"*{subject}*\n```\n{body}\n```"}
        response = requests.post(self.slack_webhook, json=payload, timeout=10)
        response.raise_for_status()

