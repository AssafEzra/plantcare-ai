"""Health check routes (API_CONTRACTS §Health, FINAL §16).

    POST /v1/plants/{plant_id}/health-checks    -> 202
    GET  /v1/health-assessments/{assessment_id}
    GET  /v1/plants/{plant_id}/health-history

The Health Agent cannot change a care plan. When a finding asks for one, the
result carries `requires_care_plan_adjustment` and the client raises a proposal
through the care route — which the user then approves. That indirection is the
whole of §16's "It cannot directly modify the Care Plan".
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request, status
from pydantic import BaseModel, Field

from app.agents.health.agent import HealthAgent
from app.agents.health.contract import MAX_IMAGES, MIN_IMAGES
from app.api.dependencies import AIRateLimitDep, CurrentUserDep
from app.api.schemas.common import DataEnvelope, UniqueImageIds
from app.common.enums import ConfidenceLevel, HealthStatus, HealthTrend
from app.infrastructure.ai.gateway import AIGateway
from app.orchestration.services.agent_requests import BackgroundTasksExecutor
from app.orchestration.workflows import health as workflow
from app.repositories import plants as plants_repo

router = APIRouter(tags=["health"])


def get_health_agent() -> HealthAgent:
    """The agent, as a dependency, so a test can substitute a scripted provider."""
    return HealthAgent(AIGateway())


HealthAgentDep = Annotated[HealthAgent, Depends(get_health_agent)]


class HealthCheckRequest(BaseModel):
    model_config = {"extra": "forbid"}

    image_ids: UniqueImageIds = Field(min_length=MIN_IMAGES, max_length=MAX_IMAGES)
    user_note: str | None = Field(default=None, max_length=1000)


class HealthCheckAccepted(BaseModel):
    agent_request_id: UUID
    status: str
    replayed: bool = False


class AssessmentResponse(BaseModel):
    id: UUID
    plant_id: UUID
    overall_status: HealthStatus
    confidence_level: ConfidenceLevel | None = None
    trend: HealthTrend
    requires_attention: bool = False
    user_note: str | None = None
    insufficient_information_reason: str | None = None
    created_at: datetime
    observations: list[dict[str, Any]] = Field(default_factory=list)
    possible_issues: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)


class HistoryEntry(BaseModel):
    id: UUID
    overall_status: HealthStatus
    confidence_level: ConfidenceLevel | None = None
    trend: HealthTrend
    requires_attention: bool = False
    created_at: datetime


class IssueBrief(BaseModel):
    """A possible issue, cut to what fits on a card — never without its evidence.

    §16 forbids presenting a definitive diagnosis, and the evidence is what keeps an
    issue arguable rather than pronounced. It travels with the name even here.
    """

    issue_name: str
    severity: int | None = None
    evidence: str | None = None


class LatestAssessment(HistoryEntry):
    insufficient_information_reason: str | None = None
    issues: list[IssueBrief] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class PlantHealthOverview(BaseModel):
    plant_id: UUID
    latest: LatestAssessment
    history: list[HistoryEntry] = Field(default_factory=list)


@router.post(
    "/plants/{plant_id}/health-checks",
    response_model=DataEnvelope[HealthCheckAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_health_check(
    request: Request,
    plant_id: UUID,
    payload: HealthCheckRequest,
    user: CurrentUserDep,
    background: BackgroundTasks,
    agent: HealthAgentDep,
    _rate_limit: AIRateLimitDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DataEnvelope[HealthCheckAccepted]:
    """Start a health check. Returns 202; poll `/v1/agent-requests/{id}`."""
    agent_request = workflow.start(
        user.client,
        user_id=user.id,
        plant_id=plant_id,
        image_ids=payload.image_ids,
        user_note=payload.user_note,
        idempotency_key=idempotency_key,
    )

    if not agent_request.replayed:
        BackgroundTasksExecutor(background).submit(
            workflow.execute,
            request_id=agent_request.id,
            user_id=user.id,
            plant_id=plant_id,
            image_ids=payload.image_ids,
            user_note=payload.user_note,
            access_token=user.access_token,
            agent=agent,
        )

    return DataEnvelope(
        data=HealthCheckAccepted(
            agent_request_id=agent_request.id,
            status=agent_request.status.value,
            replayed=agent_request.replayed,
        ),
        request_id=request.state.request_id,
    )


@router.get("/health-assessments/{assessment_id}", response_model=DataEnvelope[AssessmentResponse])
async def get_assessment(
    request: Request, assessment_id: UUID, user: CurrentUserDep
) -> DataEnvelope[AssessmentResponse]:
    assessment = workflow.get_assessment(user.client, assessment_id)
    return DataEnvelope(data=AssessmentResponse(**assessment), request_id=request.state.request_id)


@router.get("/plants/{plant_id}/health-history", response_model=DataEnvelope[list[HistoryEntry]])
async def get_health_history(
    request: Request,
    plant_id: UUID,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DataEnvelope[list[HistoryEntry]]:
    """Every assessment for this plant, newest first.

    Previous assessments are never modified (FINAL §16), so this is an
    append-only record of what was thought at each point.
    """
    entries = workflow.history(user.client, plant_id=plant_id, limit=limit)
    return DataEnvelope(
        data=[HistoryEntry(**entry) for entry in entries], request_id=request.state.request_id
    )


@router.get("/health/overview", response_model=DataEnvelope[list[PlantHealthOverview]])
async def get_health_overview(
    request: Request, user: CurrentUserDep
) -> DataEnvelope[list[PlantHealthOverview]]:
    """What every assessed plant's last check found, and when the ones before it ran.

    The בריאות screen draws a card per plant with the last check's finding on it and
    the dates of the checks before it. Through the per-plant routes that is two round
    trips a card; here it is four queries for the screen. The plant's name, species and
    photograph are NOT repeated — the screen already holds the plant list, and a second
    copy of a thumbnail URL is a second thing to keep true.

    Only plants the user owns, through the repository, so this screen and My Plants
    cannot disagree about what a plant of theirs is.
    """
    plants = plants_repo.list_for_user(user.client, owner_id=user.id)
    found = workflow.overview(user.client, [str(plant["id"]) for plant in plants])
    return DataEnvelope(
        data=[
            PlantHealthOverview(plant_id=UUID(plant_id), **entry)
            for plant_id, entry in found.items()
        ],
        request_id=request.state.request_id,
    )
