"""Plant routes: CRUD, archive/restore, and environment.

API_CONTRACTS §Plants and §Environment. Ownership always comes from the JWT, and
every statement runs through the caller's client so RLS applies underneath.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.api.dependencies import CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.api.schemas.plants import (
    EnvironmentRequest,
    EnvironmentResponse,
    PlantCreateRequest,
    PlantResponse,
    PlantUpdateRequest,
)
from app.common.enums import CareTaskStatus, HealthStatus, PlantStatus, SystemEventType
from app.common.errors import InvalidTransitionError, PlantNotFoundError
from app.domain.rules.plant_lifecycle import (
    PlantFacts,
    ensure_transition,
    status_after_restore,
)
from app.infrastructure.storage import plant_images as storage
from app.repositories import plants as repo
from app.repositories.base import rows

router = APIRouter(prefix="/plants", tags=["plants"])


def _facts(client, plant: dict) -> PlantFacts:
    """Gather what the lifecycle rules need to decide a restore target.

    Knowledge is looked up rather than assumed: a species may have gained a
    published version while the plant sat archived, and the restored status
    should reflect the world as it is now.
    """
    species_id = plant.get("species_id")
    if not species_id:
        return PlantFacts(has_confirmed_species=False, has_published_knowledge=False)

    published = (
        client.table("knowledge_versions")
        .select("id")
        .eq("species_id", species_id)
        .eq("is_current", True)
        .limit(1)
        .execute()
    )
    return PlantFacts(
        has_confirmed_species=True,
        has_published_knowledge=bool(published.data),
    )


@router.post("", response_model=DataEnvelope[PlantResponse], status_code=status.HTTP_201_CREATED)
async def create_plant(
    request: Request, payload: PlantCreateRequest, user: CurrentUserDep
) -> DataEnvelope[PlantResponse]:
    """Create a plant in PENDING_IDENTIFICATION.

    The name is optional here on purpose: the Add Plant flow creates the plant
    before the user names it (FINAL §3 step 5 comes after confirmation).
    """
    plant = repo.create(user.client, user_id=user.id, name=payload.name, notes=payload.notes)
    repo.record_event(
        user.client,
        user_id=user.id,
        plant_id=UUID(plant["id"]),
        event_type=SystemEventType.PLANT_CREATED,
    )
    return DataEnvelope(
        data=PlantResponse.model_validate(plant), request_id=request.state.request_id
    )


def _decorate_for_grid(client, access_token: str, plants: list[dict]) -> list[dict]:
    """Add the thumbnail, species name and nearest task each card needs.

    Four queries for the whole page rather than three per plant. A listing
    endpoint that fans out per row is how a grid of twenty plants becomes sixty
    round trips, and the signing call is an HTTP request of its own - which is
    why the images are signed in one batch.

    Everything here is optional and best-effort. A plant whose species row is
    missing, or whose thumbnail cannot be signed, still renders; it simply shows
    less. The card is already written to be honest about what it does not know.
    """
    if not plants:
        return []

    image_ids = [str(p["main_image_id"]) for p in plants if p.get("main_image_id")]
    species_ids = [str(p["species_id"]) for p in plants if p.get("species_id")]
    plant_ids = [str(p["id"]) for p in plants]

    thumbnails: dict[str, str] = {}
    if image_ids:
        images = {
            row["id"]: row.get("storage_path_thumbnail") or row.get("storage_path_processed")
            for row in rows(
                client.table("plant_images")
                .select("id, storage_path_thumbnail, storage_path_processed")
                .in_("id", image_ids)
                .execute()
            )
        }
        signed = storage.signed_urls(access_token, [p for p in images.values() if p])
        thumbnails = {
            image_id: signed[path] for image_id, path in images.items() if path and path in signed
        }

    species: dict[str, str] = {}
    if species_ids:
        species = {
            row["id"]: row.get("common_name") or row["scientific_name"]
            for row in rows(
                client.table("species")
                .select("id, scientific_name, common_name")
                .in_("id", species_ids)
                .execute()
            )
        }

    # Ascending by due date, so the first row seen for a plant is its nearest.
    # OVERDUE counts: work that is late is the most relevant thing a card can
    # say, and hiding it until it is done is how a task gets forgotten.
    next_tasks: dict[str, dict] = {}
    open_tasks = rows(
        client.table("care_tasks")
        .select("id, plant_id, care_rule_id, due_at_utc, status")
        .in_("plant_id", plant_ids)
        .in_("status", [CareTaskStatus.PENDING.value, CareTaskStatus.OVERDUE.value])
        .order("due_at_utc")
        .execute()
    )
    if open_tasks:
        actions = {
            rule["id"]: rule["action_type"]
            for rule in rows(
                client.table("care_rules")
                .select("id, action_type")
                .in_("id", list({str(t["care_rule_id"]) for t in open_tasks}))
                .execute()
            )
        }
        for task in open_tasks:
            plant_id = str(task["plant_id"])
            action = actions.get(str(task["care_rule_id"]))
            if plant_id in next_tasks or not action:
                continue
            next_tasks[plant_id] = {
                "id": task["id"],
                "action_type": action,
                "due_at_utc": task["due_at_utc"],
                "status": task["status"],
            }

    return [
        {
            **plant,
            "thumbnail_url": thumbnails.get(str(plant.get("main_image_id"))),
            "species_name": species.get(str(plant.get("species_id"))),
            "next_task": next_tasks.get(str(plant["id"])),
        }
        for plant in plants
    ]


@router.get("", response_model=DataEnvelope[list[PlantResponse]])
async def list_plants(
    request: Request,
    user: CurrentUserDep,
    plant_status: Annotated[PlantStatus | None, Query(alias="status")] = None,
    health_status: Annotated[HealthStatus | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> DataEnvelope[list[PlantResponse]]:
    found = repo.list_for_user(
        user.client,
        owner_id=user.id,
        status=plant_status.value if plant_status else None,
        health_status=health_status.value if health_status else None,
        query=q,
    )
    decorated = _decorate_for_grid(user.client, user.access_token, found)
    return DataEnvelope(
        data=[PlantResponse.model_validate(row) for row in decorated],
        request_id=request.state.request_id,
    )


@router.get("/{plant_id}", response_model=DataEnvelope[PlantResponse])
async def get_plant(
    request: Request, plant_id: UUID, user: CurrentUserDep
) -> DataEnvelope[PlantResponse]:
    plant = repo.get(user.client, plant_id, owner_id=user.id)
    return DataEnvelope(
        data=PlantResponse.model_validate(plant), request_id=request.state.request_id
    )


@router.patch("/{plant_id}", response_model=DataEnvelope[PlantResponse])
async def update_plant(
    request: Request, plant_id: UUID, payload: PlantUpdateRequest, user: CurrentUserDep
) -> DataEnvelope[PlantResponse]:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return await get_plant(request, plant_id, user)

    before = repo.get(user.client, plant_id, owner_id=user.id)
    plant = repo.update(user.client, plant_id, changes)

    if "name" in changes and changes["name"] != before.get("name"):
        repo.record_event(
            user.client,
            user_id=user.id,
            plant_id=plant_id,
            event_type=SystemEventType.PLANT_RENAMED,
            payload={"from": before.get("name"), "to": changes["name"]},
        )

    return DataEnvelope(
        data=PlantResponse.model_validate(plant), request_id=request.state.request_id
    )


@router.post("/{plant_id}/archive", response_model=DataEnvelope[PlantResponse])
async def archive_plant(
    request: Request, plant_id: UUID, user: CurrentUserDep
) -> DataEnvelope[PlantResponse]:
    """Archive rather than delete (FINAL §21). History is preserved."""
    plant = repo.get(user.client, plant_id, owner_id=user.id)
    ensure_transition(PlantStatus(plant["status"]), PlantStatus.ARCHIVED)

    updated = repo.update(user.client, plant_id, {"status": "ARCHIVED", "archived_at": "now()"})
    repo.record_event(
        user.client,
        user_id=user.id,
        plant_id=plant_id,
        event_type=SystemEventType.PLANT_ARCHIVED,
        payload={"previous_status": plant["status"]},
    )
    return DataEnvelope(
        data=PlantResponse.model_validate(updated), request_id=request.state.request_id
    )


@router.post("/{plant_id}/restore", response_model=DataEnvelope[PlantResponse])
async def restore_plant(
    request: Request, plant_id: UUID, user: CurrentUserDep
) -> DataEnvelope[PlantResponse]:
    """Bring an archived plant back.

    The target status is recomputed from the plant's own data rather than
    remembered, so an unidentified plant does not come back as ACTIVE with no
    species - and a plant whose species gained published knowledge while it was
    archived comes back ACTIVE rather than waiting again.
    """
    plant = repo.get(user.client, plant_id, owner_id=user.id)
    if PlantStatus(plant["status"]) is not PlantStatus.ARCHIVED:
        raise InvalidTransitionError("הצמח אינו בארכיון.")

    target = status_after_restore(_facts(user.client, plant))
    ensure_transition(PlantStatus.ARCHIVED, target)

    updated = repo.update(user.client, plant_id, {"status": target.value, "archived_at": None})
    repo.record_event(
        user.client,
        user_id=user.id,
        plant_id=plant_id,
        event_type=SystemEventType.PLANT_RESTORED,
        payload={"restored_to": target.value},
    )
    return DataEnvelope(
        data=PlantResponse.model_validate(updated), request_id=request.state.request_id
    )


# --- environment --------------------------------------------------------------


@router.get("/{plant_id}/environment", response_model=DataEnvelope[EnvironmentResponse])
async def get_environment(
    request: Request, plant_id: UUID, user: CurrentUserDep
) -> DataEnvelope[EnvironmentResponse]:
    repo.get(user.client, plant_id, owner_id=user.id)  # 404s if it is not the caller's plant
    environment = repo.get_environment(user.client, plant_id) or {"plant_id": str(plant_id)}
    return DataEnvelope(
        data=EnvironmentResponse.model_validate(environment),
        request_id=request.state.request_id,
    )


@router.put("/{plant_id}/environment", response_model=DataEnvelope[EnvironmentResponse])
async def put_environment(
    request: Request, plant_id: UUID, payload: EnvironmentRequest, user: CurrentUserDep
) -> DataEnvelope[EnvironmentResponse]:
    """Replace the plant's current environment and record the change.

    `plant_environments` keeps only the current row, so without the accompanying
    `system_events` write there would be nothing for Plant History to render
    (FINAL §19). The two belong together, which is why one function does both.
    """
    if not repo.find(user.client, plant_id, owner_id=user.id):
        raise PlantNotFoundError()

    before = repo.get_environment(user.client, plant_id) or {}
    values = payload.model_dump(mode="json", exclude_unset=True)
    after = repo.upsert_environment(user.client, plant_id, values)

    tracked = set(EnvironmentRequest.model_fields)
    changed = {
        field: {"from": before.get(field), "to": after.get(field)}
        for field in tracked
        if before.get(field) != after.get(field)
    }
    if changed:
        repo.record_event(
            user.client,
            user_id=user.id,
            plant_id=plant_id,
            event_type=SystemEventType.ENVIRONMENT_CHANGED,
            payload={"changed": changed},
        )

    return DataEnvelope(
        data=EnvironmentResponse.model_validate(after), request_id=request.state.request_id
    )
