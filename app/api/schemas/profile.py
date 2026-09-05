"""Profile request/response schemas for /v1/me."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import BaseModel, Field, field_validator

from app.common.enums import UserRole

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


class ProfileUpdateRequest(BaseModel):
    """Only fields a user may change about themselves.

    `role`, `is_active` and `anonymized_at` are absent by design: they are
    administrative, and a database trigger rejects them even if a caller finds
    another route to them (TESTING §7). `care_level` is likewise absent - it is
    out of MVP scope per FINAL §2 and §36, and API_CONTRACTS says it is not
    accepted here.
    """

    model_config = {"extra": "forbid"}

    display_name: str | None = Field(default=None, max_length=120)
    timezone: str | None = None

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
