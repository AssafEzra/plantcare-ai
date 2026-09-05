"""Polling endpoint for asynchronous agent work (API_CONTRACTS §Identification).

The client gets 202 with an id, then polls here for status and stage. The stage
values drive the processing display in the wireframes:

    IMAGES_RECEIVED -> CONTEXT_LOADED -> ANALYZING -> PREPARING_RESULT -> COMPLETE
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.dependencies import CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.common.enums import AgentRequestStatus, AgentStage, AgentType
from app.orchestration.services import agent_requests as service

router = APIRouter(prefix="/agent-requests", tags=["agents"])


class AgentRequestResponse(BaseModel):
    id: UUID
    agent_type: AgentType
    status: AgentRequestStatus
    stage: AgentStage | None = None
    plant_id: UUID | None = None
    error_code: str | None = None
    # Where the result is. A client that polls until COMPLETE has an agent
    # request id and nothing else - there is no route from a plant to its
    # identification - so without this the confirmation screen could never be
    # reached. It shipped without it, and the Add Plant flow dead-ended at
    # "not found" for every user who got that far.
    #
    # Identifiers and statuses only: `mark_succeeded` is called with a small
    # explicit dict per workflow (identification id, version number, health
    # status). No prompt and no reasoning is written to this column by anything,
    # so exposing it to the request's owner cannot leak either - which is the
    # same argument that keeps `agent_executions` admin-only.
    output_summary: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


@router.get("/{request_id}", response_model=DataEnvelope[AgentRequestResponse])
async def get_agent_request(
    request: Request, request_id: UUID, user: CurrentUserDep
) -> DataEnvelope[AgentRequestResponse]:
    """Status for one request.

    Read through the caller's own client, so RLS restricts it to their requests -
    DATABASE_SCHEMA allows exactly this exception to the admin-only rule on AI
    monitoring: "minimal request status for the request owner". Model, cost and
    prompt version are not exposed here; those live in agent_executions, which is
    admin-only.
    """
    row = service.get_for_user(user.client, request_id)
    return DataEnvelope(
        data=AgentRequestResponse.model_validate(row),
        request_id=request.state.request_id,
    )
