"""Request and response schemas for plants, environment and images."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.common.enums import (
    HealthStatus,
    ImageContextType,
    LightDirection,
    LightLevel,
    LocationType,
    PlantStatus,
)


def _clean(value: str | None) -> str | None:
    """Trim, and treat an all-whitespace string as absent.

    The database rejects a blank name outright, so normalising here turns a
    fumbled form submission into "not named yet" rather than a 422.
    """
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


# --- plants -------------------------------------------------------------------


class PlantCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)

    _normalise = field_validator("name", "notes")(_clean)


class PlantUpdateRequest(BaseModel):
    """Only the personal fields (API_CONTRACTS: "personal fields such as name, notes").

    `status`, `species_id` and `current_health_status` are absent by design: each
    changes only through its own workflow - confirmation, admin publication, or a
    health check - never by a client PATCHing the plant.
    """

    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)

    _normalise = field_validator("name", "notes")(_clean)


class PlantResponse(BaseModel):
    id: UUID
    name: str | None = None
    species_id: UUID | None = None
    status: PlantStatus
    current_health_status: HealthStatus
    main_image_id: UUID | None = None
    notes: str | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# --- environment --------------------------------------------------------------


class EnvironmentRequest(BaseModel):
    """Every field optional: FINAL §18 says the Care Agent works with partial data."""

    model_config = {"extra": "forbid"}

    location_type: LocationType | None = None
    light_level: LightLevel | None = None
    light_direction: LightDirection | None = None
    temperature_c: float | None = Field(default=None, ge=-50, le=60)
    humidity_percent: float | None = Field(default=None, ge=0, le=100)
    room: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)

    _normalise = field_validator("room", "notes")(_clean)


class EnvironmentResponse(BaseModel):
    plant_id: UUID
    location_type: LocationType | None = None
    light_level: LightLevel | None = None
    light_direction: LightDirection | None = None
    temperature_c: float | None = None
    humidity_percent: float | None = None
    room: str | None = None
    notes: str | None = None
    updated_at: datetime | None = None


# --- images -------------------------------------------------------------------


class PlantImageResponse(BaseModel):
    id: UUID
    plant_id: UUID
    context_type: ImageContextType
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    created_at: datetime
    # Short-lived signed URLs; the bucket is private, so there is no durable
    # address for a plant photograph.
    thumbnail_url: str | None = None
    processed_url: str | None = None
