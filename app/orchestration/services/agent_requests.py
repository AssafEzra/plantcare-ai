"""Agent request lifecycle: the 202-and-poll pattern.

FINAL §24 rules out a queue or worker service for MVP, so long-running agent work
runs in-process behind the same contract a worker would satisfy: the caller gets
`202` with an `agent_request_id`, and polls
`GET /v1/agent-requests/{id}` for status and stage.

`AgentExecutor` is the seam. Replacing `BackgroundTasksExecutor` with something
that enqueues to a real worker changes this file and nothing else - no agent
contract, no route, no client.

Idempotency (A24)
-----------------
API_CONTRACTS says AI-triggering POSTs accept `Idempotency-Key` but does not say
what a repeat does. Resolved here: the same key with the same payload replays the
original `202` and its request id, so a client retrying after a dropped
connection does not start a second, billable analysis. The same key with a
*different* payload is a client bug and answers `409` rather than silently
serving the wrong result.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.common.enums import AgentRequestStatus, AgentType
from app.common.errors import IdempotencyConflictError, NotFoundError
from app.config.logging import get_logger
from app.infrastructure.supabase.client import service_client
from app.repositories.base import Row, first_row
from supabase import Client

log = get_logger(__name__)

REQUEST_COLUMNS = (
    "id, user_id, plant_id, agent_type, status, stage, error_code, "
    "input_summary, output_summary, created_at, updated_at"
)


def fingerprint(payload: dict[str, Any]) -> str:
    """A stable hash of a request body.

    Sorted keys so two equivalent bodies that differ only in field order are
    recognised as the same request rather than as a conflict.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AgentRequest:
    id: UUID
    status: AgentRequestStatus
    stage: str | None
    replayed: bool = False


class AgentExecutor(Protocol):
    """Runs agent work outside the request/response cycle."""

    def submit(self, fn, /, *args: Any, **kwargs: Any) -> None: ...


class InlineExecutor:
    """Runs the work immediately. For tests, where determinism beats concurrency."""

    def submit(self, fn, /, *args: Any, **kwargs: Any) -> None:
        fn(*args, **kwargs)


class BackgroundTasksExecutor:
    """Runs the work on FastAPI's background tasks, after the 202 is returned."""

    def __init__(self, background_tasks) -> None:
        self._tasks = background_tasks

    def submit(self, fn, /, *args: Any, **kwargs: Any) -> None:
        self._tasks.add_task(fn, *args, **kwargs)


def create_or_replay(
    client: Client,
    *,
    user_id: UUID,
    plant_id: UUID | None,
    agent_type: AgentType,
    payload: dict[str, Any],
    idempotency_key: str | None,
) -> AgentRequest:
    """Start a request, or replay one the client already started."""
    digest = fingerprint(payload)

    if idempotency_key:
        existing = first_row(
            client.table("agent_requests")
            .select(REQUEST_COLUMNS + ", request_fingerprint")
            .eq("idempotency_key", idempotency_key)
            .execute()
        )
        if existing:
            if existing.get("request_fingerprint") != digest:
                raise IdempotencyConflictError()
            return AgentRequest(
                id=UUID(existing["id"]),
                status=AgentRequestStatus(existing["status"]),
                stage=existing.get("stage"),
                replayed=True,
            )

    row = (
        client.table("agent_requests")
        .insert(
            {
                "user_id": str(user_id),
                "plant_id": str(plant_id) if plant_id else None,
                "agent_type": agent_type.value,
                "status": AgentRequestStatus.QUEUED.value,
                "idempotency_key": idempotency_key,
                "request_fingerprint": digest,
                "input_summary": payload,
            }
        )
        .execute()
    )

    created = first_row(row)
    if created is None:  # pragma: no cover - insert returns the row or raises
        raise NotFoundError("could not create the agent request")

    return AgentRequest(
        id=UUID(created["id"]),
        status=AgentRequestStatus.QUEUED,
        stage=None,
    )


def get_for_user(client: Client, request_id: UUID) -> Row:
    """Read a request as its owner. RLS limits this to their own."""
    found = first_row(
        client.table("agent_requests").select(REQUEST_COLUMNS).eq("id", str(request_id)).execute()
    )
    if found is None:
        raise NotFoundError("הבקשה לא נמצאה.")
    return found


# --- background-side updates --------------------------------------------------
#
# These run after the response has been sent, so there is no user JWT in scope.
# They use the service role, which is one of the uses the plan reserves it for.


def mark_stage(request_id: UUID, stage: str) -> None:
    _update(request_id, {"stage": stage, "status": AgentRequestStatus.PROCESSING.value})


def mark_succeeded(request_id: UUID, output_summary: dict[str, Any] | None = None) -> None:
    _update(
        request_id,
        {
            "status": AgentRequestStatus.SUCCEEDED.value,
            "stage": "COMPLETE",
            "output_summary": output_summary or {},
        },
    )


def mark_failed(request_id: UUID, error_code: str) -> None:
    """Record a failure.

    The request is marked FAILED and nothing else is written. FINAL §25: a failed
    AI operation must not leave an authoritative record behind, so the caller's
    orchestration deliberately has nothing to roll back.
    """
    _update(
        request_id,
        {"status": AgentRequestStatus.FAILED.value, "error_code": error_code},
    )


def _update(request_id: UUID, changes: dict[str, Any]) -> None:
    try:
        service_client().table("agent_requests").update(changes).eq("id", str(request_id)).execute()
    except Exception as exc:
        # Losing a status update must not crash the background task and leave the
        # request stuck mid-flight; the poll endpoint will simply show stale state.
        log.error(
            "agent_request.update_failed",
            request_id=str(request_id),
            error_type=type(exc).__name__,
        )
