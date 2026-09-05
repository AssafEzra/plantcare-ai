"""Notification routes (API_CONTRACTS §Notifications).

    GET /v1/notification-preferences
    PUT /v1/notification-preferences
    GET /v1/notification-deliveries

The delivery log is user-visible on purpose. FINAL §14 says all sends are logged
to prevent duplicates; showing the user that log is how "we did email you" stops
being something they have to take on trust.
"""

from __future__ import annotations

from datetime import datetime, time
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.api.dependencies import CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.common.enums import NotificationChannel, NotificationDeliveryStatus
from app.common.errors import ValidationFailedError
from app.notifications import service

router = APIRouter(tags=["notifications"])


class PreferencesResponse(BaseModel):
    user_id: UUID
    email_enabled: bool
    preferred_time_local: time
    daily_digest: bool


class PreferencesRequest(BaseModel):
    """A10: this is the time we may *write*, not the time a task is due.

    A user who waters in the evening still wants their reminder in the morning,
    so the two are separate settings that answer different questions.
    """

    model_config = {"extra": "forbid"}

    email_enabled: bool | None = None
    preferred_time_local: time | None = None
    daily_digest: bool | None = None


class DeliveryResponse(BaseModel):
    id: UUID
    care_task_id: UUID | None = None
    channel: NotificationChannel
    status: NotificationDeliveryStatus
    scheduled_at: datetime
    sent_at: datetime | None = None
    error_message: str | None = None


@router.get("/notification-preferences", response_model=DataEnvelope[PreferencesResponse])
async def get_preferences(
    request: Request, user: CurrentUserDep
) -> DataEnvelope[PreferencesResponse]:
    found = service.preferences_for(user.client, str(user.id))
    return DataEnvelope(data=PreferencesResponse(**found), request_id=request.state.request_id)


@router.put("/notification-preferences", response_model=DataEnvelope[PreferencesResponse])
async def put_preferences(
    request: Request, payload: PreferencesRequest, user: CurrentUserDep
) -> DataEnvelope[PreferencesResponse]:
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise ValidationFailedError("לא נשלחה העדפה לעדכון.")

    if "preferred_time_local" in changes:
        changes["preferred_time_local"] = changes["preferred_time_local"].isoformat()

    updated = service.update_preferences(user.client, str(user.id), changes)
    return DataEnvelope(data=PreferencesResponse(**updated), request_id=request.state.request_id)


@router.get("/notification-deliveries", response_model=DataEnvelope[list[DeliveryResponse]])
async def list_deliveries(
    request: Request,
    user: CurrentUserDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> DataEnvelope[list[DeliveryResponse]]:
    found = service.deliveries_for(user.client, str(user.id), limit=limit)
    return DataEnvelope(
        data=[DeliveryResponse(**row) for row in found], request_id=request.state.request_id
    )
