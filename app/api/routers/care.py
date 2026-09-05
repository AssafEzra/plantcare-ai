"""Care plan routes (API_CONTRACTS §Care Plans).

    GET  /v1/plants/{plant_id}/care-plan
    POST /v1/plants/{plant_id}/care-plan/proposals              -> 202
    GET  /v1/plants/{plant_id}/care-plan/proposals
    POST /v1/plants/{plant_id}/care-plan/adjustment-proposals   -> 202
    POST /v1/care-plan-proposals/{version_id}/approve
    POST /v1/care-plan-proposals/{version_id}/reject
    POST /v1/care-plan-versions/{version_id}/operational-adjustment

Only two of these change what a plant is actually scheduled to do, and both
require the user: `approve`, and `operational-adjustment`. Every other route
either reads, or produces a proposal that sits there until somebody looks at it —
which is FINAL §12's rule expressed as a route table.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, status
from pydantic import BaseModel, Field

from app.agents.care.agent import CareAgent
from app.api.dependencies import AIRateLimitDep, CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.common.enums import (
    CarePlanVersionSourceType,
    CarePlanVersionStatus,
    CareRuleActionType,
    Weekday,
)
from app.common.errors import NotFoundError, ValidationFailedError
from app.infrastructure.ai.anthropic_provider import AnthropicProvider
from app.infrastructure.ai.gateway import AIGateway
from app.orchestration.services.agent_requests import BackgroundTasksExecutor
from app.orchestration.workflows import care as workflow

router = APIRouter(tags=["care"])


def get_care_agent() -> CareAgent:
    """The agent, as a dependency, so a test can substitute a scripted provider."""
    return CareAgent(AIGateway(AnthropicProvider()))


CareAgentDep = Annotated[CareAgent, Depends(get_care_agent)]


# --- schemas ------------------------------------------------------------------


class RuleResponse(BaseModel):
    id: UUID
    action_type: CareRuleActionType
    interval_days: int
    preferred_time_local: time
    preferred_weekday: Weekday | None = None
    instructions: str | None = None
    is_active: bool = True


class VersionResponse(BaseModel):
    id: UUID
    care_plan_id: UUID
    version_number: int
    knowledge_version_id: UUID | None = None
    status: CarePlanVersionStatus
    professional_recommendations: dict[str, Any]
    operational_preferences: dict[str, Any] | None = None
    change_summary: str | None = None
    source_type: CarePlanVersionSourceType
    created_at: datetime
    rules: list[RuleResponse] = Field(default_factory=list)


class ProposalRequest(BaseModel):
    model_config = {"extra": "forbid"}

    reason: CarePlanVersionSourceType = CarePlanVersionSourceType.INITIAL_PLAN
    note: str | None = Field(default=None, max_length=1000)


class AdjustmentProposalRequest(BaseModel):
    """A health finding asking for the plan to be revisited (FINAL §12).

    The Health Agent cannot touch the plan, so it comes through here — the same
    proposal machinery, with a `source_type` that records why.
    """

    model_config = {"extra": "forbid"}

    health_assessment_id: UUID | None = None
    reason: str = Field(min_length=3, max_length=1000)


class ProposalAcceptedResponse(BaseModel):
    agent_request_id: UUID
    status: str
    replayed: bool = False


class RejectRequest(BaseModel):
    model_config = {"extra": "forbid"}

    note: str | None = Field(default=None, max_length=500)


class OperationalAdjustmentRequest(BaseModel):
    """API_CONTRACTS gives the payload; the constraint is what it may not carry.

    `professional_recommendations` is deliberately absent and `extra: forbid`
    rejects it, so the endpoint cannot be used to edit advice even by a client
    that tries. FINAL §12 makes that a product rule; this makes it a 422.
    """

    model_config = {"extra": "forbid"}

    operational_preferences: dict[str, Any]
    change_summary: str = Field(min_length=3, max_length=500)


# --- reads --------------------------------------------------------------------


@router.get("/plants/{plant_id}/care-plan", response_model=DataEnvelope[VersionResponse])
async def get_care_plan(
    request: Request, plant_id: UUID, user: CurrentUserDep
) -> DataEnvelope[VersionResponse]:
    """The active plan. A plant with only an open proposal has no plan yet."""
    plan = workflow.plan_for_plant(user.client, plant_id=plant_id)
    if plan is None:
        raise NotFoundError("אין עדיין תוכנית טיפול פעילה לצמח הזה.")
    return DataEnvelope(data=VersionResponse(**plan), request_id=request.state.request_id)


@router.get(
    "/plants/{plant_id}/care-plan/proposals",
    response_model=DataEnvelope[list[VersionResponse]],
)
async def list_proposals(
    request: Request, plant_id: UUID, user: CurrentUserDep
) -> DataEnvelope[list[VersionResponse]]:
    proposals = workflow.proposals_for_plant(user.client, plant_id=plant_id)
    return DataEnvelope(
        data=[VersionResponse(**p) for p in proposals], request_id=request.state.request_id
    )


# --- proposing ----------------------------------------------------------------


@router.post(
    "/plants/{plant_id}/care-plan/proposals",
    response_model=DataEnvelope[ProposalAcceptedResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_proposal(
    request: Request,
    plant_id: UUID,
    payload: ProposalRequest,
    user: CurrentUserDep,
    background: BackgroundTasks,
    agent: CareAgentDep,
    _rate_limit: AIRateLimitDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DataEnvelope[ProposalAcceptedResponse]:
    agent_request = workflow.start_proposal(
        user.client,
        user_id=user.id,
        plant_id=plant_id,
        reason=payload.reason,
        note=payload.note,
        idempotency_key=idempotency_key,
    )

    if not agent_request.replayed:
        BackgroundTasksExecutor(background).submit(
            workflow.execute_proposal,
            request_id=agent_request.id,
            user_id=user.id,
            plant_id=plant_id,
            reason=payload.reason,
            note=payload.note,
            access_token=user.access_token,
            agent=agent,
        )

    return DataEnvelope(
        data=ProposalAcceptedResponse(
            agent_request_id=agent_request.id,
            status=agent_request.status.value,
            replayed=agent_request.replayed,
        ),
        request_id=request.state.request_id,
    )


@router.post(
    "/plants/{plant_id}/care-plan/adjustment-proposals",
    response_model=DataEnvelope[ProposalAcceptedResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_adjustment_proposal(
    request: Request,
    plant_id: UUID,
    payload: AdjustmentProposalRequest,
    user: CurrentUserDep,
    background: BackgroundTasks,
    agent: CareAgentDep,
    _rate_limit: AIRateLimitDep,
) -> DataEnvelope[ProposalAcceptedResponse]:
    """A health finding proposes a plan change. It cannot make one."""
    note = payload.reason
    if payload.health_assessment_id:
        note = f"{note}\n(health_assessment_id: {payload.health_assessment_id})"

    agent_request = workflow.start_proposal(
        user.client,
        user_id=user.id,
        plant_id=plant_id,
        reason=CarePlanVersionSourceType.HEALTH_DRIVEN,
        note=note,
        idempotency_key=None,
    )

    BackgroundTasksExecutor(background).submit(
        workflow.execute_proposal,
        request_id=agent_request.id,
        user_id=user.id,
        plant_id=plant_id,
        reason=CarePlanVersionSourceType.HEALTH_DRIVEN,
        note=note,
        access_token=user.access_token,
        agent=agent,
    )

    return DataEnvelope(
        data=ProposalAcceptedResponse(
            agent_request_id=agent_request.id, status=agent_request.status.value
        ),
        request_id=request.state.request_id,
    )


# --- deciding -----------------------------------------------------------------


@router.post("/care-plan-proposals/{version_id}/approve", response_model=DataEnvelope[dict])
async def approve_proposal(
    request: Request, version_id: UUID, user: CurrentUserDep
) -> DataEnvelope[dict]:
    """Approve a proposal: it becomes the active plan (FINAL §12)."""
    result = workflow.approve(user.client, version_id=version_id)
    return DataEnvelope(data=result, request_id=request.state.request_id)


@router.post("/care-plan-proposals/{version_id}/reject", response_model=DataEnvelope[dict])
async def reject_proposal(
    request: Request, version_id: UUID, payload: RejectRequest, user: CurrentUserDep
) -> DataEnvelope[dict]:
    """Decline a proposal. Whatever plan is active stays active."""
    version = workflow.reject(user.client, version_id=version_id, note=payload.note)
    return DataEnvelope(
        data={"version_id": version["id"], "status": version["status"]},
        request_id=request.state.request_id,
    )


@router.post(
    "/care-plan-versions/{version_id}/operational-adjustment",
    response_model=DataEnvelope[dict],
)
async def adjust_operational_preferences(
    request: Request,
    version_id: UUID,
    payload: OperationalAdjustmentRequest,
    user: CurrentUserDep,
) -> DataEnvelope[dict]:
    """Change frequency, time or reminders. No model call, no advice rewritten.

    Produces a new PROPOSED version carrying the professional recommendations
    byte-identical from the source. The user still approves it — the version chain
    is the audit trail, and skipping approval here would make an operational tweak
    the one way to change the active plan without saying yes to it.
    """
    if not payload.operational_preferences:
        raise ValidationFailedError("לא נשלחה העדפה לעדכון.")

    result = workflow.operational_adjustment(
        user.client,
        user_id=user.id,
        version_id=version_id,
        operational_preferences=payload.operational_preferences,
        change_summary=payload.change_summary,
    )
    return DataEnvelope(data=result, request_id=request.state.request_id)
