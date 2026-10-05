"""Profile routes: GET and PATCH /v1/me."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.api.dependencies import CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.api.schemas.profile import ProfileResponse, ProfileUpdateRequest
from app.common.errors import NotFoundError
from app.orchestration.services import scheduler
from app.repositories.base import require_row

router = APIRouter(tags=["profile"])

_COLUMNS = (
    "id, email, display_name, role, timezone, locale, is_active, created_at, "
    "care_intensity, care_day_low, care_days_medium"
)

# A change to any of these re-dates the user's pending tasks. Timezone included:
# a care day is a local calendar day, so moving zones can move it.
_SCHEDULING_FIELDS = {"care_intensity", "care_day_low", "care_days_medium", "timezone"}


@router.get("/me", response_model=DataEnvelope[ProfileResponse])
async def get_me(request: Request, user: CurrentUserDep) -> DataEnvelope[ProfileResponse]:
    result = user.client.table("profiles").select(_COLUMNS).eq("id", str(user.id)).execute()
    row = require_row(result, NotFoundError("Profile was not found."))

    return DataEnvelope(
        data=ProfileResponse.model_validate(row),
        request_id=request.state.request_id,
    )


@router.patch("/me", response_model=DataEnvelope[ProfileResponse])
async def update_me(
    request: Request,
    payload: ProfileUpdateRequest,
    user: CurrentUserDep,
) -> DataEnvelope[ProfileResponse]:
    changes = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)

    if not changes:
        # Nothing to write; return current state rather than a pointless round trip.
        return await get_me(request, user)

    # The filter is redundant with RLS by design: the policy already restricts the
    # row set to the caller. Belt and braces, and it keeps the statement honest to
    # read (FINAL §26 - Python checks are not sufficient, but they are not harmful).
    result = user.client.table("profiles").update(changes).eq("id", str(user.id)).execute()
    require_row(result, NotFoundError("Profile was not found."))

    if _SCHEDULING_FIELDS & changes.keys():
        # Immediate, and through the user's own client: no proposal, no model call.
        scheduler.reschedule_pending(user.client, user_id=str(user.id), now_utc=datetime.now(UTC))

    fresh = user.client.table("profiles").select(_COLUMNS).eq("id", str(user.id)).execute()
    return DataEnvelope(
        data=ProfileResponse.model_validate(require_row(fresh)),
        request_id=request.state.request_id,
    )
