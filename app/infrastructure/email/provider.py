"""The email provider abstraction (FINAL §14).

§14 names "email provider abstraction" and "Resend implementation" as two
separate MVP items, which is the right reading: the application should not know
who sends its mail. Everything above this module deals in `EmailMessage` and a
`send()` that either returns a provider id or raises.

`NullProvider` is the default in CI and in any environment without Resend
credentials. That is not a convenience for tests — it is what stops a
misconfigured deployment sending real mail to real people, and what lets the
notification tests run without a network or an API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    """One message, already rendered.

    Both a plain-text and an HTML body: a mail client that cannot render HTML
    should still show something a person can read, and some spam filters treat a
    missing text part as a signal.
    """

    to: str
    subject: str
    text_body: str
    html_body: str | None = None


class EmailSendError(RuntimeError):
    """The provider refused or could not be reached."""


class EmailProvider(Protocol):
    """What the notification service may ask of a mail provider."""

    name: str

    def send(self, message: EmailMessage) -> str | None:
        """Send, returning the provider's message id when it gives one.

        Raises :class:`EmailSendError` on failure. The caller records that
        against the delivery row rather than losing the task it was reminding
        about.
        """
        ...


class NullProvider:
    """Logs instead of sending.

    The default whenever Resend is not configured. A deployment that forgot its
    credentials therefore sends nothing rather than crashing on every tick, and
    the log line makes the omission visible.
    """

    name = "null"

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> str | None:
        self.sent.append(message)
        log.info(
            "email.suppressed",
            provider=self.name,
            subject=message.subject,
            # Deliberately no recipient and no body: DEPLOYMENT §9's redaction
            # rules apply to logs, and an address is personal data.
            body_length=len(message.text_body),
        )
        return None
