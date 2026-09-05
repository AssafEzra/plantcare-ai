"""The plant dashboard view model and its history (FINAL §17, §19).

    GET  /v1/plants/{plant_id}/dashboard
    GET  /v1/plants/{plant_id}/history
    POST /v1/plants/{plant_id}/history

§17 lists thirteen sections for one screen. Assembled on the server into one
response for the same reason the Home dashboard is: this is a page a user opens
often, and eight sequential round trips would be felt on every visit.

A separate route from `GET /v1/plants/{id}` rather than a fatter version of it.
That endpoint is used by the grid, the scheduler and the workflows, and none of
them want a gallery, a plan and a timeline attached — a view model is for a
view.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.common.enums import SystemEventType
from app.common.errors import ValidationFailedError
from app.infrastructure.storage import plant_images as storage
from app.orchestration.services import plant_history, scheduler
from app.orchestration.workflows import care as care_workflow
from app.repositories import plants as repo
from app.repositories.base import first_row, rows

router = APIRouter(prefix="/plants", tags=["plants"])

# How many recent assessments the trend section shows. Enough to see a direction
# without turning the dashboard into a health archive.
HEALTH_HISTORY = 5


class GalleryImage(BaseModel):
    id: UUID
    url: str | None = None
    thumbnail_url: str | None = None
    context_type: str
    is_main: bool = False
    created_at: datetime


class SpeciesSummary(BaseModel):
    id: UUID
    scientific_name: str
    common_name: str | None = None


class HealthSummary(BaseModel):
    current_status: str
    latest_assessment_id: UUID | None = None
    latest_assessed_at: datetime | None = None
    trend: str | None = None
    requires_attention: bool = False
    history: list[dict[str, Any]] = Field(default_factory=list)


class PlantDashboardResponse(BaseModel):
    """Everything FINAL §17 lists, in one payload."""

    id: UUID
    name: str | None = None
    status: str
    notes: str | None = None
    created_at: datetime
    archived_at: datetime | None = None

    species: SpeciesSummary | None = None
    main_image: GalleryImage | None = None
    gallery: list[GalleryImage] = Field(default_factory=list)
    environment: dict[str, Any] | None = None
    health: HealthSummary
    upcoming_tasks: list[dict[str, Any]] = Field(default_factory=list)
    care_plan: dict[str, Any] | None = None
    open_proposals: int = 0


class HistoryEntryResponse(BaseModel):
    kind: str
    occurred_at: datetime
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    source: str


class HistoryEventRequest(BaseModel):
    """A user logging something they did out of band (FINAL §19).

    Restricted to the four kinds §19 names as user-created. A user cannot forge a
    `PLANT_CREATED` or an `ENVIRONMENT_CHANGED`: those are written by the actions
    that actually cause them, and letting the client choose would make the
    timeline a place where anything can be claimed.
    """

    model_config = {"extra": "forbid"}

    event_type: SystemEventType
    note: str | None = Field(default=None, max_length=1000)


USER_LOGGABLE = {
    SystemEventType.REPOTTED,
    SystemEventType.MOVED,
    SystemEventType.PRUNED,
    SystemEventType.CUSTOM_NOTE,
}


def _image(row: dict[str, Any], *, main_id: str | None, access_token: str) -> GalleryImage:
    processed = row.get("storage_path_processed") or row.get("storage_path_original")
    thumbnail = row.get("storage_path_thumbnail") or processed
    return GalleryImage(
        id=row["id"],
        # Signed as the caller and short-lived: the bucket is private, storage RLS
        # decides who may sign, and a URL that outlived the page would be a link
        # anyone could pass on (FINAL §20).
        url=storage.signed_url(access_token, processed) if processed else None,
        thumbnail_url=storage.signed_url(access_token, thumbnail) if thumbnail else None,
        context_type=row.get("context_type") or "gallery",
        is_main=row["id"] == main_id,
        created_at=row["created_at"],
    )


@router.get("/{plant_id}/dashboard", response_model=DataEnvelope[PlantDashboardResponse])
async def get_plant_dashboard(
    request: Request, plant_id: UUID, user: CurrentUserDep
) -> DataEnvelope[PlantDashboardResponse]:
    plant = repo.get(user.client, plant_id, owner_id=user.id)

    species = None
    if plant.get("species_id"):
        found = first_row(
            user.client.table("species")
            .select("id, scientific_name, common_name")
            .eq("id", plant["species_id"])
            .execute()
        )
        if found:
            species = SpeciesSummary(**found)

    images = repo.list_images(user.client, plant_id)
    gallery = [
        _image(row, main_id=plant.get("main_image_id"), access_token=user.access_token)
        for row in images
    ]
    main_image = next((image for image in gallery if image.is_main), None) or (
        gallery[0] if gallery else None
    )

    assessments = rows(
        user.client.table("health_assessments")
        .select("id, overall_status, trend, requires_attention, created_at")
        .eq("plant_id", str(plant_id))
        .order("created_at", desc=True)
        .limit(HEALTH_HISTORY)
        .execute()
    )
    latest = assessments[0] if assessments else None

    open_tasks = [
        task
        for task in scheduler.tasks_for_user(user.client, user_id=user.id)
        if str(task["plant_id"]) == str(plant_id)
    ]

    plan = care_workflow.plan_for_plant(user.client, plant_id=plant_id)
    proposals = care_workflow.proposals_for_plant(user.client, plant_id=plant_id)

    return DataEnvelope(
        data=PlantDashboardResponse(
            id=plant["id"],
            name=plant.get("name"),
            status=plant["status"],
            notes=plant.get("notes"),
            created_at=plant["created_at"],
            archived_at=plant.get("archived_at"),
            species=species,
            main_image=main_image,
            gallery=gallery,
            environment=repo.get_environment(user.client, plant_id),
            health=HealthSummary(
                current_status=plant.get("current_health_status") or "UNKNOWN",
                latest_assessment_id=(latest or {}).get("id"),
                latest_assessed_at=(latest or {}).get("created_at"),
                trend=(latest or {}).get("trend"),
                requires_attention=bool((latest or {}).get("requires_attention")),
                history=assessments,
            ),
            upcoming_tasks=open_tasks,
            care_plan=plan,
            open_proposals=len(proposals),
        ),
        request_id=request.state.request_id,
    )


@router.get("/{plant_id}/history", response_model=DataEnvelope[list[HistoryEntryResponse]])
async def get_plant_history(
    request: Request,
    plant_id: UUID,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = plant_history.PAGE_SIZE,
    before: Annotated[str | None, Query()] = None,
) -> DataEnvelope[list[HistoryEntryResponse]]:
    """The merged timeline, newest first.

    `before` is a timestamp cursor rather than an offset: an append-only timeline
    grows at the head, so an offset-based page two drifts as entries arrive and
    the user sees something twice or not at all.
    """
    repo.get(user.client, plant_id, owner_id=user.id)  # 404s if it is not theirs

    entries = plant_history.timeline(user.client, plant_id=plant_id, limit=limit, before=before)
    return DataEnvelope(
        data=[HistoryEntryResponse(**entry) for entry in entries],
        request_id=request.state.request_id,
    )


@router.post(
    "/{plant_id}/history",
    response_model=DataEnvelope[dict],
    status_code=status.HTTP_201_CREATED,
)
async def log_history_event(
    request: Request, plant_id: UUID, payload: HistoryEventRequest, user: CurrentUserDep
) -> DataEnvelope[dict]:
    """Record something the user did out of band (FINAL §19).

    Repotting a plant on a whim is still part of its history, and the care plan
    should not have to have asked for it first. Restricted to the four
    user-created kinds — the rest are written by the actions that cause them.
    """
    if payload.event_type not in USER_LOGGABLE:
        raise ValidationFailedError("לא ניתן לרשום אירוע מהסוג הזה ידנית.")
    if payload.event_type is SystemEventType.CUSTOM_NOTE and not (payload.note or "").strip():
        raise ValidationFailedError("הערה ריקה אינה נשמרת.")

    repo.get(user.client, plant_id, owner_id=user.id)

    repo.record_event(
        user.client,
        user_id=user.id,
        plant_id=plant_id,
        event_type=payload.event_type,
        payload={"note": (payload.note or "").strip() or None, "logged_by_user": True},
    )

    return DataEnvelope(
        data={"event_type": payload.event_type.value},
        request_id=request.state.request_id,
    )
