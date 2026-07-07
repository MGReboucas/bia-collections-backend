from dataclasses import dataclass

from app.core import email as email_core


@dataclass(frozen=True)
class EmailSendResult:
    provider: str
    provider_message_id: str | None = None


class EmailProvider:
    """Small adapter over the configured email provider in app.core.email."""

    def send(self, to: str, subject: str, html: str | None = None, text: str | None = None) -> EmailSendResult:
        provider = email_core._provider()  # Centralized provider selection.
        email_core._send_email(to, subject, text=text, html=html)
        return EmailSendResult(provider=provider)
