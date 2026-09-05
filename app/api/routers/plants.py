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
from app.common.enums import HealthStatus, PlantStatus, SystemEventType
from app.common.errors import InvalidTransitionError, PlantNotFoundError
from app.domain.rules.plant_lifecycle import (
    PlantFacts,
    ensure_transition,
    status_after_restore,
)
from app.repositories import plants as repo

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
        status=plant_status.value if plant_status else None,
        health_status=health_status.value if health_status else None,
        query=q,
    )
    return DataEnvelope(
        data=[PlantResponse.model_validate(row) for row in found],
        request_id=request.state.request_id,
    )


@router.get("/{plant_id}", response_model=DataEnvelope[PlantResponse])
async def get_plant(
    request: Request, plant_id: UUID, user: CurrentUserDep
) -> DataEnvelope[PlantResponse]:
    plant = repo.get(user.client, plant_id)
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

    before = repo.get(user.client, plant_id)
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
    plant = repo.get(user.client, plant_id)
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
    plant = repo.get(user.client, plant_id)
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
    repo.get(user.client, plant_id)  # 404s if it is not the caller's plant
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
    if not repo.find(user.client, plant_id):
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
