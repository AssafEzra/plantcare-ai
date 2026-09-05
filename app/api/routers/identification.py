"""Identification routes (API_CONTRACTS §Identification).

    POST /v1/plants/{plant_id}/identification-runs   -> 202 + agent_request_id
    GET  /v1/identifications/{identification_id}
    POST /v1/identifications/{identification_id}/confirm
    POST /v1/identifications/{identification_id}/correct

The Wikipedia link is attached on read, not on write: it is verified against
Wikipedia's own API and a verification is only as good as the moment it was made
(FINAL §8 — the URL must never be invented).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, status
from pydantic import BaseModel, Field

from app.agents.identification.agent import IdentificationAgent
from app.agents.knowledge.agent import KnowledgeAgent
from app.api.dependencies import AIRateLimitDep, CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.common.enums import ConfidenceLevel, IdentificationMethod, IdentificationStatus
from app.common.errors import NotFoundError, ValidationFailedError
from app.infrastructure import wikipedia
from app.infrastructure.ai.anthropic_provider import AnthropicProvider
from app.infrastructure.ai.gateway import AIGateway
from app.orchestration.services.agent_requests import BackgroundTasksExecutor
from app.orchestration.workflows import identification as workflow
from app.orchestration.workflows import knowledge as knowledge_workflow
from app.repositories.base import first_row, rows

router = APIRouter(tags=["identification"])


def get_identification_agent() -> IdentificationAgent:
    """The agent, as a dependency.

    A dependency rather than a direct construction so a test can substitute a
    scripted provider through `app.dependency_overrides`. Without that seam, every
    integration test of this route would make a real, billable model call - and
    could not reach the failure paths at all.
    """
    return IdentificationAgent(AIGateway(AnthropicProvider()))


AgentDep = Annotated[IdentificationAgent, Depends(get_identification_agent)]


def get_knowledge_agent() -> KnowledgeAgent:
    """The Knowledge Agent, for the research run confirmation may start."""
    return KnowledgeAgent(AIGateway(AnthropicProvider()))


KnowledgeAgentDep = Annotated[KnowledgeAgent, Depends(get_knowledge_agent)]


# --- schemas ------------------------------------------------------------------


class IdentificationRunRequest(BaseModel):
    model_config = {"extra": "forbid"}

    image_ids: list[UUID] = Field(min_length=1, max_length=4)
    user_description: str | None = Field(default=None, max_length=1000)


class IdentificationRunResponse(BaseModel):
    agent_request_id: UUID
    status: str
    replayed: bool = False


class CandidateResponse(BaseModel):
    id: UUID
    scientific_name: str
    common_name: str | None = None
    rank: int
    confidence_score: float | None = None
    species_id: UUID | None = None


class IdentificationResponse(BaseModel):
    id: UUID
    plant_id: UUID
    status: IdentificationStatus
    method: IdentificationMethod
    confidence_score: float | None = None
    confidence_level: ConfidenceLevel | None = None
    image_quality: str | None = None
    request_more_photos: bool = False
    wikipedia_url: str | None = None
    created_at: datetime
    candidates: list[CandidateResponse] = Field(default_factory=list)


class ConfirmRequest(BaseModel):
    """Plan decision 2: a candidate, not a species id.

    API_CONTRACTS writes `confirmed_species_id`, but candidates deliberately have
    no species row until this moment — creating one per candidate would let every
    hallucinated binomial into the global taxonomy table.
    """

    model_config = {"extra": "forbid"}

    candidate_id: UUID


class CorrectRequest(BaseModel):
    """A13. The spec defines no body for `/correct`, so this is the recorded shape.

    Records that the user disagreed. It does **not** change the plant: FINAL §8
    says a correction creates history and still requires confirmation before the
    plant moves.
    """

    model_config = {"extra": "forbid"}

    scientific_name: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


# --- routes -------------------------------------------------------------------


@router.post(
    "/plants/{plant_id}/identification-runs",
    response_model=DataEnvelope[IdentificationRunResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_identification_run(
    request: Request,
    plant_id: UUID,
    payload: IdentificationRunRequest,
    user: CurrentUserDep,
    background: BackgroundTasks,
    agent: AgentDep,
    _rate_limit: AIRateLimitDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DataEnvelope[IdentificationRunResponse]:
    """Start an identification. Returns 202; poll `/v1/agent-requests/{id}`."""
    agent_request = workflow.start(
        user.client,
        user_id=user.id,
        plant_id=plant_id,
        image_ids=payload.image_ids,
        user_description=payload.user_description,
        idempotency_key=idempotency_key,
    )

    # A replay must not start a second analysis: the client is retrying, not
    # asking again, and the work is already done or in flight (A24).
    if not agent_request.replayed:
        BackgroundTasksExecutor(background).submit(
            workflow.execute,
            request_id=agent_request.id,
            user_id=user.id,
            plant_id=plant_id,
            image_ids=payload.image_ids,
            user_description=payload.user_description,
            access_token=user.access_token,
            agent=agent,
        )

    return DataEnvelope(
        data=IdentificationRunResponse(
            agent_request_id=agent_request.id,
            status=agent_request.status.value,
            replayed=agent_request.replayed,
        ),
        request_id=request.state.request_id,
    )


@router.get(
    "/identifications/{identification_id}",
    response_model=DataEnvelope[IdentificationResponse],
)
async def get_identification(
    request: Request, identification_id: UUID, user: CurrentUserDep
) -> DataEnvelope[IdentificationResponse]:
    record = first_row(
        user.client.table("identifications")
        .select(
            "id, plant_id, status, method, confidence_score, confidence_level, "
            "image_quality, request_more_photos, wikipedia_url, created_at"
        )
        .eq("id", str(identification_id))
        .execute()
    )
    if record is None:
        raise NotFoundError("הזיהוי לא נמצא.")

    candidates = rows(
        user.client.table("identification_candidates")
        .select("id, scientific_name, common_name, rank, confidence_score, species_id")
        .eq("identification_id", str(identification_id))
        .order("rank")
        .execute()
    )

    # Verified on read. A link is an enhancement, so a slow or unreachable
    # Wikipedia costs the link and nothing else.
    if record["status"] == IdentificationStatus.SUCCESS.value and candidates:
        page = wikipedia.verify_page(candidates[0]["scientific_name"])
        record["wikipedia_url"] = page.url if page else None

    return DataEnvelope(
        data=IdentificationResponse(
            **record, candidates=[CandidateResponse(**c) for c in candidates]
        ),
        request_id=request.state.request_id,
    )


@router.post("/identifications/{identification_id}/confirm", response_model=DataEnvelope[dict])
async def confirm_identification(
    request: Request,
    identification_id: UUID,
    payload: ConfirmRequest,
    user: CurrentUserDep,
    background: BackgroundTasks,
    knowledge_agent: KnowledgeAgentDep,
) -> DataEnvelope[dict]:
    """Confirm a candidate. The species becomes authoritative here and only here."""
    result = workflow.confirm(
        user.client,
        user_id=user.id,
        identification_id=identification_id,
        candidate_id=payload.candidate_id,
    )

    # A species with no published knowledge needs research before a care plan can
    # exist. It runs after the response: the user's plant is already added and
    # usable, and FINAL §11 says research is long-running and should feel queued.
    research = result.get("research")
    if research:
        BackgroundTasksExecutor(background).submit(
            knowledge_workflow.execute_research,
            request_id=UUID(research["request_id"]),
            draft_id=UUID(research["draft_id"]),
            species_id=UUID(research["species_id"]),
            language=research["language"],
            reason=None,
            agent=knowledge_agent,
        )

    return DataEnvelope(data=result, request_id=request.state.request_id)


@router.post("/identifications/{identification_id}/correct", response_model=DataEnvelope[dict])
async def correct_identification(
    request: Request,
    identification_id: UUID,
    payload: CorrectRequest,
    user: CurrentUserDep,
) -> DataEnvelope[dict]:
    """Record that the user disagrees with the identification.

    Creates a historical correction and nothing else. FINAL §8: the plant does not
    move until a confirmation, and a species change then triggers a new Care Plan
    proposal rather than silently replacing the existing one.
    """
    original = first_row(
        user.client.table("identifications")
        .select("id, plant_id, status")
        .eq("id", str(identification_id))
        .execute()
    )
    if original is None:
        raise NotFoundError("הזיהוי לא נמצא.")

    if not payload.scientific_name and not payload.note:
        raise ValidationFailedError("יש לציין שם מדעי או הערה.")

    correction = first_row(
        user.client.table("identifications")
        .insert(
            {
                "user_id": str(user.id),
                "plant_id": original["plant_id"],
                # A correction is a user statement, not a model result, so it is
                # NEEDS_MORE_INFORMATION rather than SUCCESS - which the CHECK
                # constraint also requires, since it carries no verified species.
                "status": IdentificationStatus.NEEDS_MORE_INFORMATION.value,
                "method": IdentificationMethod.USER_CORRECTED.value,
                "user_description": payload.note,
                "raw_result": {
                    "corrects": str(identification_id),
                    "user_scientific_name": payload.scientific_name,
                },
            }
        )
        .execute()
    )

    return DataEnvelope(
        data={
            "correction_id": correction["id"] if correction else None,
            "corrects": str(identification_id),
            "requires_confirmation": True,
        },
        request_id=request.state.request_id,
    )
