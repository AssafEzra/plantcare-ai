"""Admin panel routes (FINAL §29, §21; API_CONTRACTS §Admin monitoring).

    GET  /v1/admin/overview
    GET  /v1/admin/agent-executions
    GET  /v1/admin/agent-requests
    GET  /v1/admin/knowledge-reports
    POST /v1/admin/knowledge-reports/{report_id}/review
    GET  /v1/admin/notification-deliveries
    GET  /v1/admin/audit-log
    GET  /v1/admin/accounts
    POST /v1/admin/accounts/{user_id}/anonymize

The knowledge-draft and approved-source routes live in `knowledge.py`, with the
workflow they belong to.

Two rules hold across every route here. Each depends on `AdminDep`, which reads
the role from the database rather than the token; and every admin table also
carries an `is_admin()` RLS policy, so a forgotten dependency is a bug rather
than a breach.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.api.dependencies import AdminDep
from app.api.schemas.common import DataEnvelope
from app.common.enums import AgentRequestStatus, AgentType
from app.common.errors import NotFoundError, ValidationFailedError
from app.config.logging import get_logger
from app.infrastructure.supabase.client import service_client
from app.repositories.base import first_row, require_row, rows

log = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# The monitoring window. Long enough to see a pattern, short enough that the
# overview stays a page rather than a report.
DEFAULT_WINDOW_DAYS = 7


class ExecutionResponse(BaseModel):
    """One agent attempt.

    The field list is the allow-list from `agent_executions`, and there is
    deliberately nowhere here for a prompt, a response or reasoning — FINAL §23
    forbids storing chain-of-thought, and a monitoring view that exposed it would
    be the obvious place for it to leak.
    """

    id: UUID
    agent_request_id: UUID
    agent_type: AgentType
    model: str
    prompt_version: str
    status: AgentRequestStatus
    attempt: int
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    latency_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime


class AgentRequestSummary(BaseModel):
    id: UUID
    user_id: UUID
    plant_id: UUID | None = None
    agent_type: AgentType
    status: AgentRequestStatus
    stage: str | None = None
    error_code: str | None = None
    created_at: datetime


class AgentStats(BaseModel):
    agent_type: str
    total: int
    failed: int
    estimated_cost: float
    average_latency_ms: int


class OverviewResponse(BaseModel):
    """What an administrator needs to see first.

    Ordered by what would make someone act: failures, then things waiting on a
    person, then volume.
    """

    window_days: int
    drafts_awaiting_review: int
    open_knowledge_reports: int
    failed_agent_requests: int
    failed_notifications: int
    agent_stats: list[AgentStats] = Field(default_factory=list)
    total_estimated_cost: float = 0.0


class KnowledgeReportResponse(BaseModel):
    id: UUID
    user_id: UUID
    plant_id: UUID | None = None
    species_id: UUID | None = None
    knowledge_version_id: UUID | None = None
    report_text: str
    status: str
    admin_note: str | None = None
    created_at: datetime


class ReviewReportRequest(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = Field(pattern="^(REVIEWING|ACTIONED|DISMISSED)$")
    admin_note: str | None = Field(default=None, max_length=2000)


class DeliveryResponse(BaseModel):
    id: UUID
    user_id: UUID
    status: str
    dedupe_key: str
    scheduled_at: datetime
    sent_at: datetime | None = None
    error_message: str | None = None


class AuditEntryResponse(BaseModel):
    id: UUID
    admin_user_id: UUID | None = None
    action: str
    target_table: str | None = None
    target_id: UUID | None = None
    payload: dict[str, Any] | None = None
    created_at: datetime


class AccountResponse(BaseModel):
    """An account as an administrator sees it.

    No email once anonymised, because there is none — that is the point of the
    operation rather than a redaction here.
    """

    id: UUID
    email: str | None = None
    display_name: str | None = None
    role: str
    is_active: bool
    anonymized_at: datetime | None = None
    created_at: datetime


class AnonymizeRequest(BaseModel):
    """A26: there is no self-service deletion control in the MVP.

    Deletion is an out-of-band request an administrator carries out, so the
    reason is required — it is the only record of why an account was closed, and
    an audit entry saying nothing is barely an audit entry.
    """

    model_config = {"extra": "forbid"}

    reason: str = Field(min_length=3, max_length=500)


def _since(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


@router.get("/overview", response_model=DataEnvelope[OverviewResponse])
async def get_overview(
    request: Request,
    admin: AdminDep,
    window_days: Annotated[int, Query(ge=1, le=90)] = DEFAULT_WINDOW_DAYS,
) -> DataEnvelope[OverviewResponse]:
    since = _since(window_days)

    drafts = rows(
        admin.client.table("knowledge_drafts")
        .select("id")
        .eq("status", "READY_FOR_REVIEW")
        .execute()
    )
    reports = rows(
        admin.client.table("knowledge_reports").select("id").eq("status", "OPEN").execute()
    )
    failed_requests = rows(
        admin.client.table("agent_requests")
        .select("id")
        .eq("status", AgentRequestStatus.FAILED.value)
        .gte("created_at", since)
        .execute()
    )
    failed_sends = rows(
        admin.client.table("notification_deliveries")
        .select("id")
        .eq("status", "FAILED")
        .gte("created_at", since)
        .execute()
    )

    executions = rows(
        admin.client.table("agent_executions")
        .select("agent_type, status, estimated_cost, latency_ms")
        .gte("created_at", since)
        .execute()
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for execution in executions:
        grouped.setdefault(str(execution["agent_type"]), []).append(execution)

    stats = [
        AgentStats(
            agent_type=agent_type,
            total=len(group),
            failed=sum(1 for e in group if e["status"] == AgentRequestStatus.FAILED.value),
            estimated_cost=round(sum(float(e.get("estimated_cost") or 0) for e in group), 4),
            average_latency_ms=int(sum(int(e.get("latency_ms") or 0) for e in group) / len(group))
            if group
            else 0,
        )
        for agent_type, group in sorted(grouped.items())
    ]

    return DataEnvelope(
        data=OverviewResponse(
            window_days=window_days,
            drafts_awaiting_review=len(drafts),
            open_knowledge_reports=len(reports),
            failed_agent_requests=len(failed_requests),
            failed_notifications=len(failed_sends),
            agent_stats=stats,
            total_estimated_cost=round(sum(s.estimated_cost for s in stats), 4),
        ),
        request_id=request.state.request_id,
    )


@router.get("/agent-executions", response_model=DataEnvelope[list[ExecutionResponse]])
async def list_agent_executions(
    request: Request,
    admin: AdminDep,
    agent_type: Annotated[AgentType | None, Query()] = None,
    status: Annotated[AgentRequestStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DataEnvelope[list[ExecutionResponse]]:
    """Model, prompt version, duration and cost (FINAL §29).

    Never chain-of-thought: `agent_executions` has no column for it, so this
    route cannot expose it however it is queried.
    """
    query = admin.client.table("agent_executions").select(
        "id, agent_request_id, agent_type, model, prompt_version, status, attempt, "
        "input_tokens, output_tokens, estimated_cost, latency_ms, error_code, "
        "error_message, created_at"
    )
    if agent_type:
        query = query.eq("agent_type", agent_type.value)
    if status:
        query = query.eq("status", status.value)

    found = rows(query.order("created_at", desc=True).limit(limit).execute())
    return DataEnvelope(
        data=[ExecutionResponse(**row) for row in found], request_id=request.state.request_id
    )


@router.get("/agent-requests", response_model=DataEnvelope[list[AgentRequestSummary]])
async def list_agent_requests(
    request: Request,
    admin: AdminDep,
    status: Annotated[AgentRequestStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DataEnvelope[list[AgentRequestSummary]]:
    query = admin.client.table("agent_requests").select(
        "id, user_id, plant_id, agent_type, status, stage, error_code, created_at"
    )
    if status:
        query = query.eq("status", status.value)

    found = rows(query.order("created_at", desc=True).limit(limit).execute())
    return DataEnvelope(
        data=[AgentRequestSummary(**row) for row in found], request_id=request.state.request_id
    )


@router.get("/knowledge-reports", response_model=DataEnvelope[list[KnowledgeReportResponse]])
async def list_knowledge_reports(
    request: Request,
    admin: AdminDep,
    status: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DataEnvelope[list[KnowledgeReportResponse]]:
    query = admin.client.table("knowledge_reports").select(
        "id, user_id, plant_id, species_id, knowledge_version_id, report_text, "
        "status, admin_note, created_at"
    )
    if status:
        query = query.eq("status", status)

    found = rows(query.order("created_at", desc=True).limit(limit).execute())
    return DataEnvelope(
        data=[KnowledgeReportResponse(**row) for row in found],
        request_id=request.state.request_id,
    )


@router.post(
    "/knowledge-reports/{report_id}/review",
    response_model=DataEnvelope[KnowledgeReportResponse],
)
async def review_knowledge_report(
    request: Request, report_id: UUID, payload: ReviewReportRequest, admin: AdminDep
) -> DataEnvelope[KnowledgeReportResponse]:
    """Triage a user's report (FINAL §29).

    Acting on it means researching the species again, which is the retry route in
    `knowledge.py` — this records the decision. Keeping the two apart means an
    administrator can mark a report actioned after a draft is already in flight,
    rather than the status silently implying a research run happened.
    """
    report = first_row(
        admin.client.table("knowledge_reports")
        .select(
            "id, user_id, plant_id, species_id, knowledge_version_id, report_text, "
            "status, admin_note, created_at"
        )
        .eq("id", str(report_id))
        .execute()
    )
    if report is None:
        raise NotFoundError("הדיווח לא נמצא.")

    changes: dict[str, Any] = {"status": payload.status}
    if payload.admin_note:
        changes["admin_note"] = payload.admin_note.strip()

    updated = require_row(
        admin.client.table("knowledge_reports").update(changes).eq("id", str(report_id)).execute()
    )

    admin.client.table("admin_audit_log").insert(
        {
            "admin_user_id": str(admin.id),
            "action": f"knowledge_report.{payload.status.lower()}",
            "target_table": "knowledge_reports",
            "target_id": str(report_id),
            "payload": {"species_id": report.get("species_id"), "note": payload.admin_note},
        }
    ).execute()

    return DataEnvelope(
        data=KnowledgeReportResponse(**updated), request_id=request.state.request_id
    )


@router.get("/notification-deliveries", response_model=DataEnvelope[list[DeliveryResponse]])
async def list_notification_deliveries(
    request: Request,
    admin: AdminDep,
    status: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DataEnvelope[list[DeliveryResponse]]:
    query = admin.client.table("notification_deliveries").select(
        "id, user_id, status, dedupe_key, scheduled_at, sent_at, error_message"
    )
    if status:
        query = query.eq("status", status)

    found = rows(query.order("created_at", desc=True).limit(limit).execute())
    return DataEnvelope(
        data=[DeliveryResponse(**row) for row in found], request_id=request.state.request_id
    )


@router.get("/audit-log", response_model=DataEnvelope[list[AuditEntryResponse]])
async def list_audit_log(
    request: Request,
    admin: AdminDep,
    action: Annotated[str | None, Query(max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DataEnvelope[list[AuditEntryResponse]]:
    """Every consequential admin action (FINAL §29).

    Append-only: the table refuses UPDATE and DELETE by trigger, for everyone.
    An audit trail an administrator can edit is not an audit trail.
    """
    query = admin.client.table("admin_audit_log").select(
        "id, admin_user_id, action, target_table, target_id, payload, created_at"
    )
    if action:
        query = query.eq("action", action)

    found = rows(query.order("created_at", desc=True).limit(limit).execute())
    return DataEnvelope(
        data=[AuditEntryResponse(**row) for row in found], request_id=request.state.request_id
    )


@router.get("/accounts", response_model=DataEnvelope[list[AccountResponse]])
async def list_accounts(
    request: Request,
    admin: AdminDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DataEnvelope[list[AccountResponse]]:
    query = admin.client.table("profiles").select(
        "id, email, display_name, role, is_active, anonymized_at, created_at"
    )
    if q and q.strip():
        # Escaped, so a search term cannot become pattern syntax and widen its own
        # match — the same lesson `plants` search learned in PR 11.
        safe = q.strip().replace("%", "").replace("*", "").replace(",", "")
        if safe:
            query = query.ilike("email", f"%{safe}%")

    found = rows(query.order("created_at", desc=True).limit(limit).execute())
    return DataEnvelope(
        data=[AccountResponse(**row) for row in found], request_id=request.state.request_id
    )


@router.post("/accounts/{user_id}/anonymize", response_model=DataEnvelope[AccountResponse])
async def anonymize_account(
    request: Request, user_id: UUID, payload: AnonymizeRequest, admin: AdminDep
) -> DataEnvelope[AccountResponse]:
    """Close an account without deleting it (FINAL §21, A26).

    One transaction: identifying fields cleared, access disabled, history kept,
    action audited. Half of that is worse than none — an account with its email
    cleared but access still enabled is a user locked out of a login they can
    still perform.

    The `auth.users` credential is revoked separately, through Supabase's admin
    API, because that is where it lives.
    """
    if user_id == admin.id:
        raise ValidationFailedError("לא ניתן לבצע אנונימיזציה לחשבון שלך.")

    profile = require_row(
        admin.client.rpc(
            "anonymize_account",
            {"p_user_id": str(user_id), "p_reason": payload.reason.strip()},
        ).execute()
    )

    # Revoking the credential is best-effort and deliberately not fatal: the
    # profile is already anonymised and access already disabled, so a failure
    # here leaves the account closed rather than half-closed.
    try:
        service_client().auth.admin.update_user_by_id(str(user_id), {"ban_duration": "876000h"})
    except Exception as exc:
        log.warning("admin.credential_revoke_failed", error_type=type(exc).__name__)

    log.info("admin.account_anonymized", target=str(user_id))

    return DataEnvelope(data=AccountResponse(**profile), request_id=request.state.request_id)
