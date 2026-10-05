"""Python mirror of every database enum.

This module is the single source of truth shared by Pydantic schemas, domain rules
and the migration tests. DATABASE_SCHEMA "Lifecycle enums" is the contract; the
three enums marked NEW were added by this plan and are written back to the spec.

Postgres ``ALTER TYPE ... ADD VALUE`` is cheap; removing or renaming a value is not.
Every enum here is deliberately minimal — grow it later rather than guess wide now.
"""

from __future__ import annotations

from enum import StrEnum


class PlantStatus(StrEnum):
    PENDING_IDENTIFICATION = "PENDING_IDENTIFICATION"
    IDENTIFIED = "IDENTIFIED"
    KNOWLEDGE_PENDING = "KNOWLEDGE_PENDING"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class IdentificationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    NEEDS_MORE_INFORMATION = "NEEDS_MORE_INFORMATION"
    FAILED = "FAILED"


class IdentificationMethod(StrEnum):
    AI = "AI"
    USER_CONFIRMED = "USER_CONFIRMED"
    USER_CORRECTED = "USER_CORRECTED"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class KnowledgeDraftStatus(StrEnum):
    DRAFT = "DRAFT"
    RESEARCHING = "RESEARCHING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    APPROVED = "APPROVED"


class KnowledgeSourceClass(StrEnum):
    APPROVED = "APPROVED"
    EXTERNAL_UNAPPROVED = "EXTERNAL_UNAPPROVED"
    AI_GENERATED_REQUIRES_VERIFICATION = "AI_GENERATED_REQUIRES_VERIFICATION"


class CarePlanVersionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class CarePlanVersionSourceType(StrEnum):
    INITIAL_PLAN = "INITIAL_PLAN"
    OPERATIONAL_ADJUSTMENT = "OPERATIONAL_ADJUSTMENT"
    ENVIRONMENT_CHANGE = "ENVIRONMENT_CHANGE"
    HEALTH_DRIVEN = "HEALTH_DRIVEN"
    RE_IDENTIFICATION = "RE_IDENTIFICATION"
    # Added to the SQL enum by the provisional-knowledge migration; the mirror was
    # never updated because the parity test only read `create type`.
    KNOWLEDGE_REVISED = "KNOWLEDGE_REVISED"


class CareRuleActionType(StrEnum):
    """NEW (A19). Recurring care actions a Care Rule may schedule.

    Derived from the FINAL_SPECIFICATION §10 Knowledge sections and the
    UI_DESIGN_TOKENS care-plan wireframe. MISTING and ROTATING follow from the
    ``humidity_percent`` and ``light_direction`` environment fields; INSPECTION is
    what a Health finding schedules.
    """

    WATERING = "WATERING"
    FERTILIZING = "FERTILIZING"
    REPOTTING = "REPOTTING"
    PRUNING = "PRUNING"
    MISTING = "MISTING"
    ROTATING = "ROTATING"
    INSPECTION = "INSPECTION"


class CareTaskStatus(StrEnum):
    PENDING = "PENDING"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class CareEventType(StrEnum):
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    MISSED = "MISSED"
    CORRECTED = "CORRECTED"


class HealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class HealthTrend(StrEnum):
    IMPROVING = "IMPROVING"
    WORSENING = "WORSENING"
    STABLE = "STABLE"
    UNABLE_TO_DETERMINE = "UNABLE_TO_DETERMINE"


class AgentType(StrEnum):
    IDENTIFICATION = "IDENTIFICATION"
    KNOWLEDGE = "KNOWLEDGE"
    CARE = "CARE"
    HEALTH = "HEALTH"


class AgentRequestStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentStage(StrEnum):
    """UI progress stages for async agent work (API_CONTRACTS, Identification)."""

    IMAGES_RECEIVED = "IMAGES_RECEIVED"
    CONTEXT_LOADED = "CONTEXT_LOADED"
    ANALYZING = "ANALYZING"
    PREPARING_RESULT = "PREPARING_RESULT"
    COMPLETE = "COMPLETE"


class NotificationChannel(StrEnum):
    EMAIL = "EMAIL"
    PUSH = "PUSH"


class NotificationDeliveryStatus(StrEnum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class UserRole(StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"


class SystemEventType(StrEnum):
    """NEW (A22). Timeline entries that have no dedicated table of their own.

    Deliberately excludes care events, health checks, identifications and care plan
    versions: those live in their own tables and the Plant History timeline merges
    them. Putting them here as well would double-write every care action.

    REPOTTED / MOVED / PRUNED / CUSTOM_NOTE are user-logged out-of-band actions,
    distinct from the same action arriving through a scheduled care task.
    """

    PLANT_CREATED = "PLANT_CREATED"
    PLANT_ARCHIVED = "PLANT_ARCHIVED"
    PLANT_RESTORED = "PLANT_RESTORED"
    PLANT_RENAMED = "PLANT_RENAMED"
    ENVIRONMENT_CHANGED = "ENVIRONMENT_CHANGED"
    MAIN_IMAGE_CHANGED = "MAIN_IMAGE_CHANGED"
    REPOTTED = "REPOTTED"
    MOVED = "MOVED"
    PRUNED = "PRUNED"
    CUSTOM_NOTE = "CUSTOM_NOTE"


class ImageContextType(StrEnum):
    """Storage path segment: plant-images/{user_id}/{plant_id}/{context}/"""

    GALLERY = "gallery"
    IDENTIFICATION = "identification"
    HEALTH = "health"


#: The contexts whose images are portraits of the plant, as opposed to evidence
#: gathered for one run.
#:
#: `upload_image` has drawn this line since PR 27 - the first photograph of either
#: kind becomes the plant's main image, and a health close-up of a damaged leaf does
#: not - but it drew it inline, so the rules added later for the gallery said
#: `gallery` alone and applied to nothing. No code path anywhere uploads with the
#: `gallery` context: Add Plant sends `identification`, the health check sends
#: `health`, and `gallery` is only the endpoint's default. DEV bore that out exactly
#: - 44 identification images, 3 health, no gallery at all - so ordering, "set as
#: main" and the last-image rule were each written against an empty set.
#:
#: Naming it once means the gallery a user sees, the set they can reorder, and the
#: set the last-image rule protects cannot drift apart again.
PORTRAIT_CONTEXTS: tuple[ImageContextType, ...] = (
    ImageContextType.GALLERY,
    ImageContextType.IDENTIFICATION,
)


# --- Plant environment vocabularies (FINAL_SPECIFICATION §18) ----------------
class LocationType(StrEnum):
    INDOOR = "INDOOR"
    OUTDOOR = "OUTDOOR"
    BALCONY = "BALCONY"
    GREENHOUSE = "GREENHOUSE"


class LightLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    BRIGHT = "BRIGHT"
    DIRECT_SUN = "DIRECT_SUN"


class LightDirection(StrEnum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"
    UNKNOWN = "UNKNOWN"


class CareIntensity(StrEnum):
    """How tightly care is grouped (migration 0021).

    HIGH schedules every task at its own optimal time. MEDIUM and LOW move each due
    date onto the user's two or one weekly care days. A scheduling preference only:
    plans and their rules are never rewritten for it.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Weekday(StrEnum):
    """Anchors which weekday a recurrence lands on; only honoured when
    ``interval_days % 7 == 0`` (A7)."""

    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"
