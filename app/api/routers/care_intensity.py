"""Care intensity: what a proposed setting would mean, before it is saved.

    GET /v1/care-intensity/impact  -> plants whose tasks it would leave at most
                                      half as often as their plan asks

Saving the setting itself is PATCH /v1/me; a plant's own override is
PATCH /v1/plants/{id}. Both re-date pending tasks at once.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.dependencies import CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.common.enums import CareIntensity, Weekday
from app.common.errors import ValidationFailedError
from app.orchestration.services import care_intensity

router = APIRouter(prefix="/care-intensity", tags=["care-intensity"])


@router.get("/impact", response_model=DataEnvelope[list[dict[str, Any]]])
async def get_impact(
    request: Request,
    user: CurrentUserDep,
    intensity: CareIntensity,
    care_day_low: Weekday = Weekday.FRIDAY,
    care_days_medium: str = "TUESDAY,FRIDAY",
) -> DataEnvelope[list[dict[str, Any]]]:
    """`care_days_medium` is comma-separated ("TUESDAY,FRIDAY"): one value in the
    query string, which is what the client's request helper sends."""
    try:
        medium = [Weekday(day.strip()) for day in care_days_medium.split(",") if day.strip()]
    except ValueError as exc:
        raise ValidationFailedError("יום לא מוכר.") from exc
    if len(medium) != 2 or medium[0] == medium[1]:
        raise ValidationFailedError("לרמה בינונית יש לבחור שני ימים שונים.")

    affected = care_intensity.impact(
        user.client,
        user_id=str(user.id),
        intensity=intensity,
        care_day_low=care_day_low,
        care_days_medium=medium,
    )
    return DataEnvelope(data=affected, request_id=request.state.request_id)
