"""Profile request/response schemas for /v1/me."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import BaseModel, Field, field_validator

from app.common.enums import CareIntensity, UserRole, Weekday

_VALID_TIMEZONES = available_timezones()


class ProfileResponse(BaseModel):
    id: UUID
    email: str | None = None
    display_name: str | None = None
    role: UserRole
    timezone: str
    locale: str
    is_active: bool
    created_at: datetime
    care_intensity: CareIntensity = CareIntensity.HIGH
    care_day_low: Weekday = Weekday.FRIDAY
    care_days_medium: list[Weekday] = Field(
        default_factory=lambda: [Weekday.TUESDAY, Weekday.FRIDAY]
    )


class ProfileUpdateRequest(BaseModel):
    """Only fields a user may change about themselves.

    `role`, `is_active` and `anonymized_at` are absent by design: they are
    administrative, and a database trigger rejects them even if a caller finds
    another route to them (TESTING §7). `care_level` (the user's expertise, FINAL
    §2) is likewise absent. `care_intensity` is a different thing: how tightly
    care is grouped onto weekdays, which only the scheduler reads.
    """

    model_config = {"extra": "forbid"}

    display_name: str | None = Field(default=None, max_length=120)
    timezone: str | None = None
    care_intensity: CareIntensity | None = None
    care_day_low: Weekday | None = None
    care_days_medium: list[Weekday] | None = None

    @field_validator("care_days_medium")
    @classmethod
    def _two_different_days(cls, v: list[Weekday] | None) -> list[Weekday] | None:
        """Mirrors the CHECK on profiles: MEDIUM is exactly two different days."""
        if v is None:
            return None
        if len(v) != 2 or v[0] == v[1]:
            raise ValueError("Medium care needs exactly two different days.")
        return v

    @field_validator("display_name")
    @classmethod
    def _not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, v: str | None) -> str | None:
        """Reject anything zoneinfo cannot resolve.

        The scheduler converts every due time through this value, so an unknown
        zone would not fail here - it would fail later, inside the tick, for one
        user only.
        """
        if v is None:
            return None
        if v not in _VALID_TIMEZONES:
            raise ValueError(f"Unknown timezone: {v}")
        return v
