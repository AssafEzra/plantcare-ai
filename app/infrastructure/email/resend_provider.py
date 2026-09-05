"""Resend, behind the `EmailProvider` protocol (FINAL §14).

Called over plain HTTP rather than through Resend's SDK. The API is one POST, the
dependency would exist solely to construct that request, and every additional
package in the deployment is one more thing to keep current — DEPLOYMENT §11
prefers the smaller surface.
"""

from __future__ import annotations

import httpx

from app.config.logging import get_logger
from app.config.settings import get_settings
from app.infrastructure.email.provider import EmailMessage, EmailSendError

log = get_logger(__name__)

_ENDPOINT = "https://api.resend.com/emails"

# A reminder is not urgent to the second, but the tick must not be held up by a
# slow provider when it has other users to serve.
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class ResendProvider:
    name = "resend"

    def __init__(self, api_key: str | None = None, from_email: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.resend_api_key
        self._from = from_email or settings.resend_from_email

        if not self._api_key or not self._from:
            # Constructed without credentials is a configuration error, not a
            # runtime one: it should fail where it is built, not on the first
            # user who happens to have reminders switched on.
            raise EmailSendError("Resend is not configured")

    def send(self, message: EmailMessage) -> str | None:
        payload = {
            "from": self._from,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text_body,
        }
        if message.html_body:
            payload["html"] = message.html_body

        try:
            response = httpx.post(
                _ENDPOINT,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise EmailSendError(f"could not reach Resend: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            # The body can name the offending field, which is worth having in the
            # delivery row; it is truncated because a provider can be verbose and
            # this ends up in a database column a human reads.
            raise EmailSendError(f"Resend returned {response.status_code}: {response.text[:200]}")

        try:
            return str(response.json().get("id") or "") or None
        except ValueError:  # pragma: no cover - Resend returns JSON on success
            return None
