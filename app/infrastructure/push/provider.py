"""The push provider abstraction, mirroring `infrastructure/email/provider.py`.

Standard Web Push: the server encrypts a small JSON payload for one device and
posts it to that device's push service (Google for Android, Apple for iPhone),
signed with this server's VAPID key. No third party holds the subscriptions.

`NullPushProvider` is the default whenever the key pair is not configured - CI,
local development, a deployment that has not set it up - so nothing tries to
push and nothing fails on every tick.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from app.config.logging import get_logger

log = get_logger(__name__)

# How long a push service may hold a message for a phone that is offline. Long
# enough to survive a night in airplane mode, short enough that the morning's
# reminder is not delivered the next evening.
TTL_SECONDS = 12 * 60 * 60


class PushResult(StrEnum):
    OK = "ok"
    #: The push service says this subscription no longer exists (404 / 410): the
    #: user blocked notifications, cleared the browser, or removed the app. The
    #: caller deletes the row - retrying a dead address forever helps nobody.
    GONE = "gone"
    FAILED = "failed"


@dataclass(frozen=True)
class PushTarget:
    """One device, as stored in `push_subscriptions`."""

    endpoint: str
    p256dh: str
    auth: str


class PushProvider(Protocol):
    name: str
    #: Does `send()` deliberately not deliver? Same contract as the email side.
    suppresses: bool

    def send(self, target: PushTarget, payload: dict[str, Any]) -> PushResult: ...


class NullPushProvider:
    """Logs instead of pushing."""

    name = "null"
    suppresses = True

    def __init__(self) -> None:
        self.sent: list[tuple[PushTarget, dict[str, Any]]] = []

    def send(self, target: PushTarget, payload: dict[str, Any]) -> PushResult:
        self.sent.append((target, payload))
        log.info("push.suppressed", title=payload.get("title"))
        return PushResult.OK


class WebPushProvider:
    """Sends with `pywebpush`, signing each request with the VAPID private key."""

    name = "webpush"
    suppresses = False

    def __init__(self, *, private_key: str, subject: str) -> None:
        self._private_key = private_key
        self._claims = {"sub": subject}

    def send(self, target: PushTarget, payload: dict[str, Any]) -> PushResult:
        from pywebpush import WebPushException, webpush

        try:
            webpush(
                subscription_info={
                    "endpoint": target.endpoint,
                    "keys": {"p256dh": target.p256dh, "auth": target.auth},
                },
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=self._private_key,
                vapid_claims=dict(self._claims),
                ttl=TTL_SECONDS,
                # `high`, not `normal`, and the difference is whether the message
                # arrives at all. The push services map this header onto their own
                # priority: a `normal` message is held while the device is dozing and
                # may be dropped outright. Measured on 2026-10-06 - the daily summary
                # arrived at 07:33 because the phone was in use, and the due-task
                # reminder sent minutes later never did; re-firing both at an awake
                # phone delivered both. Every push this application sends is a
                # reminder about a specific plant at a specific time, which is the
                # case `high` exists for. It costs battery, deliberately.
                headers={"Urgency": "high"},
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                return PushResult.GONE
            log.warning("push.send_failed", status=status, error=str(exc)[:200])
            return PushResult.FAILED
        except Exception as exc:  # network, malformed keys
            log.warning("push.send_failed", error_type=type(exc).__name__)
            return PushResult.FAILED
        return PushResult.OK


def build_push_provider() -> PushProvider:
    from app.config.settings import get_settings

    settings = get_settings()
    if settings.push_configured and settings.vapid_private_key:
        return WebPushProvider(
            private_key=settings.vapid_private_key, subject=settings.vapid_subject
        )
    return NullPushProvider()
