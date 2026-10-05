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
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.common.enums import NotificationChannel, NotificationDeliveryStatus
from app.common.errors import ValidationFailedError
from app.notifications import service

router = APIRouter(tags=["notifications"])


class PreferencesResponse(BaseModel):
    user_id: UUID
    email_enabled: bool
    # When the morning Today and Due notifications go out. Fixed at 07:30 for now
    # and returned so the screen can say so; not accepted from clients yet.
    preferred_time_local: time
    # Retired by migration 0022 (no per-task emails); always true.
    daily_digest: bool = True
    due_reminder_days: int = 1
    evening_enabled: bool = False
    evening_time_local: time = time(19, 0)


class PreferencesRequest(BaseModel):
    """What a user may change about their reminders.

    The times are absent on purpose: they are fixed for now (07:30 and 19:00) and
    stored per user so they can become a choice later. `daily_digest` is gone
    with per-task emails. `extra="forbid"` makes a client still sending either
    get a 422 rather than a silent no-op.
    """

    model_config = {"extra": "forbid"}

    email_enabled: bool | None = None
    due_reminder_days: int | None = Field(default=None, ge=0, le=3)
    evening_enabled: bool | None = None


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
