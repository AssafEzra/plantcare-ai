"""Care task routes and the dashboard aggregate (API_CONTRACTS §Care Tasks, §Dashboard).

    GET  /v1/care-tasks?date=today&status=pending
    POST /v1/care-tasks/{task_id}/done
    POST /v1/care-tasks/{task_id}/skip
    GET  /v1/dashboard
    POST /v1/internal/tick

`/v1/dashboard` exists because Home would otherwise be five sequential calls on a
page a user opens every day; API_CONTRACTS asks for it explicitly.

`/v1/internal/tick` is the one route with no user behind it. It runs the
materialisation and the overdue sweep on a schedule, authenticated by a shared
secret rather than a JWT, because a cron job has no session.
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.common.enums import CareTaskStatus, PlantStatus
from app.common.errors import ForbiddenError
from app.config.logging import get_logger
from app.config.settings import get_settings
from app.domain.rules import recurrence
from app.infrastructure.supabase.client import service_client
from app.orchestration.services import scheduler
from app.repositories.base import rows

log = get_logger(__name__)

router = APIRouter(tags=["care-tasks"])


# --- schemas ------------------------------------------------------------------


class TaskResponse(BaseModel):
    id: UUID
    plant_id: UUID
    care_rule_id: UUID
    due_at_utc: datetime
    status: CareTaskStatus
    overdue_since: datetime | None = None
    completed_at: datetime | None = None
    plant_name: str | None = None
    action_type: str | None = None


class ActionRequest(BaseModel):
    model_config = {"extra": "forbid"}

    note: str | None = Field(default=None, max_length=500)


class OverdueSummaryResponse(BaseModel):
    plant_id: UUID
    plant_name: str
    action_types: list[str]
    count: int
    days_late: int


class DashboardCounts(BaseModel):
    today_tasks: int
    attention: int
    active_plants: int
    overdue: int


class DashboardResponse(BaseModel):
    """The Home payload of API_CONTRACTS §Dashboard, plus the overdue summary
    FINAL §13 asks for."""

    today_care: list[TaskResponse] = Field(default_factory=list)
    upcoming_care: list[TaskResponse] = Field(default_factory=list)
    overdue_summary: list[OverdueSummaryResponse] = Field(default_factory=list)
    plants_needing_attention: list[dict[str, Any]] = Field(default_factory=list)
    my_plants: list[dict[str, Any]] = Field(default_factory=list)
    counts: DashboardCounts


class TickResponse(BaseModel):
    materialised: int
    marked_overdue: int
    missed: int


# --- helpers ------------------------------------------------------------------


def _decorate(client, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the plant name and action type a task is meaningless without.

    "Water the monstera" is a reminder; "task 4f2a due at 08:00" is a database
    row. Two lookups rather than a join, for the same reason as the scheduler.
    """
    if not tasks:
        return []

    plants = {
        plant["id"]: plant
        for plant in rows(
            client.table("plants")
            .select("id, name")
            .in_("id", list({t["plant_id"] for t in tasks}))
            .execute()
        )
    }
    care_rules = {
        rule["id"]: rule
        for rule in rows(
            client.table("care_rules")
            .select("id, action_type")
            .in_("id", list({t["care_rule_id"] for t in tasks}))
            .execute()
        )
    }

    return [
        {
            **task,
            "plant_name": plants.get(task["plant_id"], {}).get("name"),
            "action_type": care_rules.get(task["care_rule_id"], {}).get("action_type"),
        }
        for task in tasks
    ]


# --- routes -------------------------------------------------------------------


@router.get("/care-tasks", response_model=DataEnvelope[list[TaskResponse]])
async def list_care_tasks(
    request: Request,
    user: CurrentUserDep,
    date: Annotated[str | None, Query(max_length=10)] = None,
    status: Annotated[CareTaskStatus | None, Query()] = None,
) -> DataEnvelope[list[TaskResponse]]:
    """Open tasks, optionally for one of the user's calendar days.

    `date=today` means the user's today. Overdue work from earlier days stays on
    the list: it is what they still have to do, and filtering it out by date is
    how a task gets quietly forgotten.
    """
    found = scheduler.tasks_for_user(
        user.client,
        user_id=user.id,
        on_date=date,
        status=status.value if status else None,
    )
    return DataEnvelope(
        data=[TaskResponse(**task) for task in _decorate(user.client, found)],
        request_id=request.state.request_id,
    )


@router.post("/care-tasks/{task_id}/done", response_model=DataEnvelope[dict])
async def complete_task(
    request: Request, task_id: UUID, payload: ActionRequest, user: CurrentUserDep
) -> DataEnvelope[dict]:
    """Record a completed task and schedule the next one (A8: anchored on now)."""
    result = scheduler.complete(user.client, task_id=task_id, user_id=user.id, note=payload.note)
    return DataEnvelope(data=result, request_id=request.state.request_id)


@router.post("/care-tasks/{task_id}/skip", response_model=DataEnvelope[dict])
async def skip_task(
    request: Request, task_id: UUID, payload: ActionRequest, user: CurrentUserDep
) -> DataEnvelope[dict]:
    """Skip a task. The next occurrence is anchored on the original due date, so
    skipping repeatedly cannot push the schedule out (A8)."""
    result = scheduler.skip(user.client, task_id=task_id, user_id=user.id, note=payload.note)
    return DataEnvelope(data=result, request_id=request.state.request_id)


@router.get("/dashboard", response_model=DataEnvelope[DashboardResponse])
async def get_dashboard(request: Request, user: CurrentUserDep) -> DataEnvelope[DashboardResponse]:
    """Everything Home needs, in one call."""
    timezone_name = scheduler.timezone_of(user.client, str(user.id))
    now = datetime.now(UTC)
    today = recurrence.local_date(now, timezone_name)
    _, today_end = recurrence.day_bounds_utc(today, timezone_name)

    open_tasks = scheduler.tasks_for_user(user.client, user_id=user.id)
    decorated = _decorate(user.client, open_tasks)

    today_care = [t for t in decorated if _due(t) < today_end]
    upcoming = [t for t in decorated if _due(t) >= today_end][:10]

    overdue_items = [
        recurrence.OverdueItem(
            plant_id=str(task["plant_id"]),
            plant_name=task.get("plant_name") or "",
            action_type=task.get("action_type") or "",
            due_at_utc=_due(task),
        )
        for task in decorated
        if task["status"] == CareTaskStatus.OVERDUE.value
    ]
    summaries = recurrence.summarize_overdue(overdue_items)

    plants = rows(
        user.client.table("plants")
        .select("id, name, status, current_health_status, main_image_id")
        .eq("user_id", str(user.id))
        .neq("status", PlantStatus.ARCHIVED.value)
        .order("created_at", desc=True)
        .execute()
    )
    attention = [
        plant
        for plant in plants
        if plant.get("current_health_status") in {"NEEDS_ATTENTION", "CRITICAL"}
    ]

    return DataEnvelope(
        data=DashboardResponse(
            today_care=[TaskResponse(**t) for t in today_care],
            upcoming_care=[TaskResponse(**t) for t in upcoming],
            overdue_summary=[
                OverdueSummaryResponse(
                    plant_id=UUID(s.plant_id),
                    plant_name=s.plant_name,
                    action_types=s.action_types,
                    count=s.count,
                    days_late=recurrence.days_late(s, now_utc=now),
                )
                for s in summaries
            ],
            plants_needing_attention=attention,
            my_plants=plants[:6],
            counts=DashboardCounts(
                today_tasks=len(today_care),
                attention=len(attention),
                active_plants=sum(1 for p in plants if p["status"] == PlantStatus.ACTIVE.value),
                overdue=len(overdue_items),
            ),
        ),
        request_id=request.state.request_id,
    )


def _due(task: dict[str, Any]) -> datetime:
    parsed = scheduler.parse_timestamp(task["due_at_utc"])
    return parsed or datetime.now(UTC)


@router.post("/internal/tick", response_model=DataEnvelope[TickResponse])
async def internal_tick(
    request: Request,
    secret: Annotated[str | None, Header(alias="X-Internal-Secret")] = None,
) -> DataEnvelope[TickResponse]:
    """Materialise near-term tasks and sweep overdue ones.

    No user, so no JWT: a cron job authenticates with a shared secret, compared
    with `hmac.compare_digest` so a wrong guess takes the same time as a right
    one. It runs under the service role because it works across every user's
    plants, which is one of the uses the plan reserves that role for.

    Idempotent: running it twice in a minute produces the same state as running
    it once, because materialisation skips rules that already have a pending task
    and the database refuses a second one regardless.
    """
    settings = get_settings()
    if not secret or not hmac.compare_digest(secret, settings.internal_tick_secret):
        # Deliberately the same error as any other forbidden request: an endpoint
        # that says "wrong secret" tells a prober it found the right endpoint.
        raise ForbiddenError()

    admin = service_client()
    now = datetime.now(UTC)

    created = scheduler.materialise(admin, now_utc=now)
    swept = scheduler.sweep_overdue(admin, now_utc=now)

    log.info(
        "scheduler.tick",
        materialised=created,
        marked_overdue=swept.marked_overdue,
        missed=swept.missed,
    )

    return DataEnvelope(
        data=TickResponse(
            materialised=created,
            marked_overdue=swept.marked_overdue,
            missed=swept.missed,
        ),
        request_id=request.state.request_id,
    )
