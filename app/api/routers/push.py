"""Phone and tablet push: registering devices, and pausing or removing them.

    GET    /v1/push/config                    -> the public VAPID key
    GET    /v1/push/subscriptions             -> this user's devices
    POST   /v1/push/subscriptions             -> register this device (upsert)
    PATCH  /v1/push/subscriptions/{id}        -> pause / resume, from any device
    DELETE /v1/push/subscriptions/{id}        -> remove, from any device
    POST   /v1/push/subscriptions/unsubscribe -> remove this device by its endpoint

Registering has to happen on the device: only the phone's browser can ask for
permission and create the subscription. After that the server holds the address,
so Settings on any device can pause or remove it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.common.errors import NotFoundError
from app.config.settings import get_settings
from app.infrastructure.push.provider import build_push_provider
from app.notifications import service
from app.repositories.base import Row, first_row, require_row, rows

router = APIRouter(prefix="/push", tags=["push"])

# Never the keys: a device's p256dh/auth are what lets anyone encrypt a message to
# it, and nothing in the interface needs them back.
DEVICE_COLUMNS = "id, device_label, platform, enabled, created_at, last_sent_at, endpoint"


class PushConfigResponse(BaseModel):
    configured: bool
    public_key: str | None = None


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class SubscribeRequest(BaseModel):
    """The browser's `PushSubscription.toJSON()`, plus how to name the device."""

    model_config = {"extra": "ignore"}  # toJSON also carries expirationTime

    endpoint: str = Field(pattern=r"^https://", max_length=1000)
    keys: SubscriptionKeys
    device_label: str | None = Field(default=None, max_length=80)
    platform: Literal["ios", "android", "other"] = "other"


class ToggleRequest(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool


class UnsubscribeRequest(BaseModel):
    endpoint: str = Field(max_length=1000)


class DeviceResponse(BaseModel):
    id: UUID
    device_label: str | None = None
    platform: str
    enabled: bool
    created_at: datetime
    last_sent_at: datetime | None = None
    # The device's own address, so the page can tell which row is "this device".
    endpoint: str


@router.get("/config", response_model=DataEnvelope[PushConfigResponse])
async def get_config(request: Request, user: CurrentUserDep) -> DataEnvelope[PushConfigResponse]:
    settings = get_settings()
    return DataEnvelope(
        data=PushConfigResponse(
            configured=settings.push_configured,
            public_key=settings.vapid_public_key if settings.push_configured else None,
        ),
        request_id=request.state.request_id,
    )


@router.get("/subscriptions", response_model=DataEnvelope[list[DeviceResponse]])
async def list_devices(
    request: Request, user: CurrentUserDep
) -> DataEnvelope[list[DeviceResponse]]:
    found = rows(
        user.client.table("push_subscriptions")
        .select(DEVICE_COLUMNS)
        .eq("user_id", str(user.id))
        .order("created_at")
        .execute()
    )
    return DataEnvelope(
        data=[DeviceResponse(**row) for row in found], request_id=request.state.request_id
    )


@router.post(
    "/subscriptions",
    response_model=DataEnvelope[DeviceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def subscribe(
    request: Request, payload: SubscribeRequest, user: CurrentUserDep
) -> DataEnvelope[DeviceResponse]:
    """Register this device, or refresh its row if it is already registered.

    Keyed on the endpoint, so the app can safely re-send its subscription every
    time it opens - which is how a subscription the browser quietly renewed gets
    its new keys to the server. A brand-new device, or one coming back from
    paused, gets one confirmation push so the user sees reminders work.
    """
    values = {
        "user_id": str(user.id),
        "endpoint": payload.endpoint,
        "p256dh": payload.keys.p256dh,
        "auth": payload.keys.auth,
        "device_label": payload.device_label,
        "platform": payload.platform,
        "enabled": True,
    }
    existing = first_row(
        user.client.table("push_subscriptions")
        .select("id, enabled")
        .eq("endpoint", payload.endpoint)
        .eq("user_id", str(user.id))
        .execute()
    )

    if existing:
        row = require_row(
            user.client.table("push_subscriptions")
            .update(values)
            .eq("id", existing["id"])
            .execute()
        )
        is_new = not existing.get("enabled", True)
    else:
        row = require_row(user.client.table("push_subscriptions").insert(values).execute())
        is_new = True

    if is_new:
        service.send_confirmation(build_push_provider(), {**row, **values})

    return DataEnvelope(data=_device(user, row["id"]), request_id=request.state.request_id)


@router.patch("/subscriptions/{subscription_id}", response_model=DataEnvelope[DeviceResponse])
async def toggle(
    request: Request, subscription_id: UUID, payload: ToggleRequest, user: CurrentUserDep
) -> DataEnvelope[DeviceResponse]:
    """Pause or resume a device. The registration is kept, so resuming needs no
    new permission on the phone."""
    _require_own(user, subscription_id)
    user.client.table("push_subscriptions").update({"enabled": payload.enabled}).eq(
        "id", str(subscription_id)
    ).execute()
    return DataEnvelope(data=_device(user, subscription_id), request_id=request.state.request_id)


@router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(subscription_id: UUID, user: CurrentUserDep) -> None:
    _require_own(user, subscription_id)
    user.client.table("push_subscriptions").delete().eq("id", str(subscription_id)).execute()


@router.post("/subscriptions/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(payload: UnsubscribeRequest, user: CurrentUserDep) -> None:
    """Remove this device by its endpoint - what signing out calls, so a shared
    phone does not keep receiving the previous user's reminders."""
    user.client.table("push_subscriptions").delete().eq("endpoint", payload.endpoint).eq(
        "user_id", str(user.id)
    ).execute()


def _require_own(user: CurrentUserDep, subscription_id: UUID) -> Row:
    found = first_row(
        user.client.table("push_subscriptions")
        .select("id")
        .eq("id", str(subscription_id))
        .eq("user_id", str(user.id))
        .execute()
    )
    if found is None:
        raise NotFoundError("המכשיר לא נמצא.")
    return found


def _device(user: CurrentUserDep, subscription_id: UUID | str) -> DeviceResponse:
    row = require_row(
        user.client.table("push_subscriptions")
        .select(DEVICE_COLUMNS)
        .eq("id", str(subscription_id))
        .execute()
    )
    return DeviceResponse(**row)
