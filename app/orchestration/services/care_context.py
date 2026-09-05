"""Assembling the Care Agent's context (FINAL §12).

§12 lists seven inputs: the Knowledge version, the plant, its environment, its
health state, health history, care history and user preferences. This module is
that list, and it is the only place those queries live.

The reason it is a separate module rather than a method on the agent is the
architectural rule it enforces: **the agent never queries the database.** It
receives a `CareContext` and can see nothing else. That is checked by an import
test, but the point of the rule is not the test — it is that an agent which
cannot read also cannot write, which is what makes "AI failure never creates an
authoritative record" (FINAL §25) structural rather than a promise.

Everything is read through the **caller's** client, so RLS applies. A plan is
assembled for the user asking for it, out of rows they can already see.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.agents.care.contract import CareContext
from app.common.errors import NotFoundError, ValidationFailedError
from app.config.logging import get_logger
from app.config.settings import get_settings
from app.repositories.base import Row, first_row, rows
from supabase import Client

log = get_logger(__name__)

# Enough history for a pattern to be visible without the context becoming a log.
HISTORY_LIMIT = 10

# The knowledge sections a care plan is actually built from. Toxicity and
# propagation are excellent reading and irrelevant to a watering schedule; sending
# all thirteen costs tokens and dilutes what matters.
PLAN_RELEVANT_SECTIONS = (
    "light",
    "watering",
    "soil",
    "temperature",
    "humidity",
    "fertilization",
    "repotting",
    "pruning",
    "common_problems",
)


def build(client: Client, *, plant_id: UUID) -> tuple[CareContext, str | None]:
    """Assemble the context, and the knowledge version it was built from.

    The version id is returned alongside because `care_plan_versions` records it:
    a plan has to be traceable to the exact knowledge it was derived from, or
    "why does my plan say this?" has no answer after the knowledge is revised.
    """
    plant = first_row(
        client.table("plants")
        .select("id, user_id, name, species_id, status, current_health_status, notes")
        .eq("id", str(plant_id))
        .execute()
    )
    if plant is None:
        raise NotFoundError("הצמח לא נמצא.")

    if not plant.get("species_id"):
        # Not an error the user can fix by retrying: a plan needs a species, and
        # a species arrives by confirming an identification.
        raise ValidationFailedError("לא ניתן לבנות תוכנית טיפול לפני שהצמח זוהה.")

    species = first_row(
        client.table("species")
        .select("id, scientific_name, common_name")
        .eq("id", plant["species_id"])
        .execute()
    )
    if species is None:  # pragma: no cover - FK guarantees this
        raise NotFoundError("המין לא נמצא.")

    knowledge = _current_knowledge(client, plant["species_id"])
    if knowledge is None:
        # The plant should not have reached ACTIVE without published knowledge,
        # so this is a real inconsistency rather than a user-facing state.
        raise ValidationFailedError("אין עדיין מידע מקצועי מאושר עבור המין הזה.")

    profile = first_row(
        client.table("profiles").select("timezone").eq("id", plant["user_id"]).execute()
    )

    context = CareContext(
        plant_name=plant.get("name"),
        scientific_name=species["scientific_name"],
        common_name=species.get("common_name"),
        knowledge_sections=_sections(knowledge),
        environment=_environment(client, plant_id),
        current_health_status=plant.get("current_health_status"),
        health_history=_health_history(client, plant_id),
        care_history=_care_history(client, plant_id),
        user_preferences=_preferences(client),
        timezone=(profile or {}).get("timezone") or get_settings().default_timezone,
    )
    return context, knowledge["id"]


def _current_knowledge(client: Client, species_id: str) -> Row | None:
    settings = get_settings()
    return first_row(
        client.table("knowledge_versions")
        .select("id, content, version_number")
        .eq("species_id", species_id)
        .eq("language", settings.default_content_language)
        .eq("is_current", True)
        .limit(1)
        .execute()
    )


def _sections(knowledge: Row) -> dict[str, str]:
    """The plan-relevant sections, as plain text.

    The per-section confidence is deliberately dropped. It is an admin review
    signal (PR 14), and feeding it to the Care Agent would invite it to hedge a
    watering interval because a reviewer was unsure about propagation.
    """
    content = knowledge.get("content") or {}
    extracted: dict[str, str] = {}
    for name in PLAN_RELEVANT_SECTIONS:
        section = content.get(name)
        if isinstance(section, dict) and section.get("text"):
            extracted[name] = str(section["text"])
    return extracted


def _environment(client: Client, plant_id: UUID) -> dict[str, Any]:
    row = first_row(
        client.table("plant_environments")
        # Exactly the columns `plant_environments` has. Pot size, drainage and
        # soil type are *not* among them, and that is not an oversight to work
        # around here — it is precisely what A20's `missing_context` exists to
        # surface on the proposal card.
        .select(
            "location_type, light_level, light_direction, "
            "temperature_c, humidity_percent, room, notes"
        )
        .eq("plant_id", str(plant_id))
        .execute()
    )
    return {key: value for key, value in (row or {}).items() if value is not None}


def _health_history(client: Client, plant_id: UUID) -> list[dict[str, Any]]:
    return [
        {
            "assessed_at": row.get("created_at"),
            "status": row.get("overall_status"),
            "trend": row.get("trend"),
            "requires_attention": row.get("requires_attention"),
        }
        for row in rows(
            client.table("health_assessments")
            .select("created_at, overall_status, trend, requires_attention")
            .eq("plant_id", str(plant_id))
            .order("created_at", desc=True)
            .limit(HISTORY_LIMIT)
            .execute()
        )
    ]


def _care_history(client: Client, plant_id: UUID) -> list[dict[str, Any]]:
    """What the user actually did.

    The most useful input in the list and the easiest to omit: the plan says what
    should happen, and this says what does. A user watering five days late every
    time is telling us the interval is wrong for their home.
    """
    return [
        {
            "event_type": row.get("event_type"),
            "event_at": row.get("event_at"),
            "note": row.get("note"),
        }
        for row in rows(
            client.table("care_events")
            .select("event_type, event_at, note")
            .eq("plant_id", str(plant_id))
            .order("event_at", desc=True)
            .limit(HISTORY_LIMIT)
            .execute()
        )
    ]


def _preferences(client: Client) -> dict[str, Any]:
    row = first_row(
        client.table("notification_preferences")
        .select("email_enabled, preferred_time_local, daily_digest")
        .limit(1)
        .execute()
    )
    return {key: value for key, value in (row or {}).items() if value is not None}
