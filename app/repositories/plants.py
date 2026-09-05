"""Persistence for plants, their environment and their images.

PROJECT_STRUCTURE §8: persistence only. Nothing here decides whether a
transition is legal or what a restored plant's status should be — those live in
`app/domain/rules/plant_lifecycle.py`.

Every function takes the caller's client, so RLS applies to each statement. The
`.eq("user_id", ...)` filters are redundant with the policies by design: belt and
braces, and they keep the queries honest to read.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from postgrest.types import CountMethod

from app.common.enums import ImageContextType, SystemEventType
from app.common.errors import PlantNotFoundError
from app.repositories.base import Row, first_row, require_row, rows
from supabase import Client

PLANT_COLUMNS = (
    "id, user_id, name, species_id, status, current_health_status, "
    "main_image_id, notes, archived_at, created_at, updated_at"
)

IMAGE_COLUMNS = (
    "id, plant_id, storage_path_original, storage_path_processed, storage_path_thumbnail, "
    "mime_type, size_bytes, width, height, context_type, user_visible, ai_used, created_at"
)


# --- plants -------------------------------------------------------------------


def create(client: Client, *, user_id: UUID, name: str | None, notes: str | None) -> Row:
    result = (
        client.table("plants")
        .insert({"user_id": str(user_id), "name": name, "notes": notes})
        .execute()
    )
    return require_row(result)


def get(client: Client, plant_id: UUID) -> Row:
    result = client.table("plants").select(PLANT_COLUMNS).eq("id", str(plant_id)).execute()
    return require_row(result, PlantNotFoundError())


def find(client: Client, plant_id: UUID) -> Row | None:
    result = client.table("plants").select(PLANT_COLUMNS).eq("id", str(plant_id)).execute()
    return first_row(result)


def list_for_user(
    client: Client,
    *,
    status: str | None = None,
    health_status: str | None = None,
    query: str | None = None,
    include_archived: bool = False,
) -> list[Row]:
    builder = client.table("plants").select(PLANT_COLUMNS)

    if status:
        builder = builder.eq("status", status)
    elif not include_archived:
        # FINAL §21: archived plants are hidden from active views unless asked for.
        builder = builder.neq("status", "ARCHIVED")

    if health_status:
        builder = builder.eq("current_health_status", health_status)

    if query and query.strip():
        safe = _search_term(query)
        if not safe:
            # The term consisted entirely of pattern syntax. The user did search
            # for something, so returning every plant would be misleading - and
            # it is exactly what made searching "*" list everything.
            return []
        builder = builder.ilike("name", f"%{safe}%")

    return rows(builder.order("created_at", desc=True).execute())


def _search_term(query: str) -> str:
    """Neutralise pattern syntax in a user's search box.

    Three characters are special on the way to Postgres and none of them mean
    anything in a plant's name:

    * ``%`` and ``_`` are SQL LIKE wildcards - "any run" and "any single
      character";
    * ``*`` is PostgREST's own shorthand, which it rewrites to ``%`` before the
      query is built. Escaping it is not enough, because the rewrite happens to
      the pattern we send, so it is replaced outright.

    Without this, searching for ``*`` returns every plant the user owns, which
    looks like the filter is broken. ``,`` is dropped for the same family of
    reasons: it separates values inside a PostgREST filter expression.
    """
    cleaned = query.replace("*", " ").replace(",", " ")
    escaped = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped.strip()


def update(client: Client, plant_id: UUID, changes: dict[str, Any]) -> Row:
    result = client.table("plants").update(changes).eq("id", str(plant_id)).execute()
    return require_row(result, PlantNotFoundError())


# --- environment --------------------------------------------------------------

ENVIRONMENT_COLUMNS = (
    "id, plant_id, location_type, light_level, light_direction, "
    "temperature_c, humidity_percent, room, notes, created_at, updated_at"
)


def get_environment(client: Client, plant_id: UUID) -> Row | None:
    result = (
        client.table("plant_environments")
        .select(ENVIRONMENT_COLUMNS)
        .eq("plant_id", str(plant_id))
        .execute()
    )
    return first_row(result)


def upsert_environment(client: Client, plant_id: UUID, values: dict[str, Any]) -> Row:
    """Write the single current environment row for a plant.

    `plant_environments` holds one row per plant by design; history lives in
    `system_events` (DATABASE_SCHEMA, "System history"), which the caller writes.
    """
    payload = {"plant_id": str(plant_id), **values}
    result = client.table("plant_environments").upsert(payload, on_conflict="plant_id").execute()
    return require_row(result)


# --- images -------------------------------------------------------------------


def list_images(
    client: Client, plant_id: UUID, *, context: ImageContextType | None = None
) -> list[Row]:
    builder = (
        client.table("plant_images")
        .select(IMAGE_COLUMNS)
        .eq("plant_id", str(plant_id))
        .eq("user_visible", True)
    )
    if context:
        builder = builder.eq("context_type", context.value)
    return rows(builder.order("created_at", desc=True).execute())


def get_image(client: Client, image_id: UUID) -> Row | None:
    result = client.table("plant_images").select(IMAGE_COLUMNS).eq("id", str(image_id)).execute()
    return first_row(result)


def create_image(client: Client, values: dict[str, Any]) -> Row:
    return require_row(client.table("plant_images").insert(values).execute())


def hide_image(client: Client, image_id: UUID, reason: str) -> Row:
    """Hide an AI-used image instead of deleting it.

    FINAL §20: images used by AI are not physically deleted when the user asks
    for removal; they remain for history and audit and are hidden from the user.
    """
    result = (
        client.table("plant_images")
        .update({"user_visible": False, "retention_reason": reason})
        .eq("id", str(image_id))
        .execute()
    )
    return require_row(result)


def delete_image(client: Client, image_id: UUID) -> None:
    client.table("plant_images").delete().eq("id", str(image_id)).execute()


def count_images(client: Client, plant_id: UUID, context: ImageContextType) -> int:
    result = (
        client.table("plant_images")
        .select("id", count=CountMethod.exact)
        .eq("plant_id", str(plant_id))
        .eq("context_type", context.value)
        .eq("user_visible", True)
        .execute()
    )
    return result.count or 0


# --- history ------------------------------------------------------------------


def record_event(
    client: Client,
    *,
    user_id: UUID,
    plant_id: UUID | None,
    event_type: SystemEventType,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append to the plant's timeline.

    `system_events` is immutable, so this is the only way an entry ever appears —
    there is no update path to fall back on.
    """
    client.table("system_events").insert(
        {
            "user_id": str(user_id),
            "plant_id": str(plant_id) if plant_id else None,
            "event_type": event_type.value,
            "payload": payload or {},
        }
    ).execute()
