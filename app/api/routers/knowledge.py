"""Knowledge routes (API_CONTRACTS §Knowledge).

Two audiences with almost no overlap, which is why they share a file but not a
prefix:

* users read the current published version of a species and may report an error
  in it. They cannot see drafts, cannot see history, and cannot write a word of
  knowledge (FINAL §10);
* administrators review drafts, approve or reject them, retry research, read
  version history, and manage the approved-source list.

Every admin route depends on `AdminDep`, and every admin table also has an
`is_admin()` RLS policy. The dependency produces a clean 403; the policy is what
makes a forgotten dependency a non-event rather than a breach.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from pydantic import BaseModel, Field

from app.agents.knowledge.agent import KnowledgeAgent
from app.api.dependencies import AdminDep, CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.common.enums import KnowledgeDraftStatus, KnowledgeSourceClass
from app.common.errors import NotFoundError, ValidationFailedError
from app.infrastructure.ai.anthropic_provider import AnthropicProvider
from app.infrastructure.ai.gateway import AIGateway
from app.orchestration.services.agent_requests import BackgroundTasksExecutor
from app.orchestration.workflows import knowledge as workflow
from app.repositories.base import first_row, rows

router = APIRouter(tags=["knowledge"])


def get_knowledge_agent() -> KnowledgeAgent:
    """The agent, as a dependency, so a test can substitute a scripted provider."""
    return KnowledgeAgent(AIGateway(AnthropicProvider()))


KnowledgeAgentDep = Annotated[KnowledgeAgent, Depends(get_knowledge_agent)]


# --- schemas ------------------------------------------------------------------


class SourceResponse(BaseModel):
    id: UUID
    source_class: KnowledgeSourceClass
    title: str | None = None
    url: str | None = None
    publisher: str | None = None
    retrieved_at: datetime | None = None
    notes: str | None = None


class KnowledgeResponse(BaseModel):
    """What a user sees: the current version and where it came from."""

    id: UUID
    species_id: UUID
    language: str
    version_number: int
    content: dict[str, Any]
    source_summary: dict[str, Any] = Field(default_factory=dict)
    published_at: datetime
    sources: list[SourceResponse] = Field(default_factory=list)


class DraftResponse(BaseModel):
    id: UUID
    species_id: UUID
    language: str
    status: KnowledgeDraftStatus
    research_request_id: UUID | None = None
    content: dict[str, Any] | None = None
    research_notes: str | None = None
    admin_note: str | None = None
    created_at: datetime
    updated_at: datetime


class VersionSummary(BaseModel):
    id: UUID
    species_id: UUID
    language: str
    version_number: int
    is_current: bool
    published_by: UUID | None = None
    published_at: datetime


class ApproveRequest(BaseModel):
    model_config = {"extra": "forbid"}

    admin_note: str | None = Field(default=None, max_length=2000)


class RejectRequest(BaseModel):
    """A rejection must say why.

    Without a reason the retry has nothing to address and the audit entry records
    only that somebody said no — which is what makes A17's "stays retriable"
    useful rather than merely possible.
    """

    model_config = {"extra": "forbid"}

    admin_note: str = Field(min_length=3, max_length=2000)


class RetryRequest(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str | None = Field(default=None, max_length=1000)


class ReportRequest(BaseModel):
    model_config = {"extra": "forbid"}

    plant_id: UUID | None = None
    report_text: str = Field(min_length=3, max_length=2000)


class ApprovedSourceRequest(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=200)
    # Stored bare and lowercase ("rhs.org.uk"), because classification is a
    # label-boundary suffix match against a retrieved URL's host. A CHECK
    # constraint enforces the shape; this catches the common paste of a full URL
    # before it becomes a database error.
    domain: str = Field(min_length=3, max_length=200)
    source_type: str | None = Field(default=None, max_length=100)
    reliability_level: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=1000)


class ApprovedSourceUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1, max_length=200)
    source_type: str | None = Field(default=None, max_length=100)
    reliability_level: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=1000)
    is_enabled: bool | None = None


class ApprovedSourceResponse(BaseModel):
    id: UUID
    name: str
    domain: str
    source_type: str | None = None
    reliability_level: int | None = None
    notes: str | None = None
    is_enabled: bool


def _normalise_domain(value: str) -> str:
    """Accept what an administrator is likely to paste, store what matching needs."""
    cleaned = value.strip().lower()
    for prefix in ("https://", "http://"):
        cleaned = cleaned.removeprefix(prefix)
    cleaned = cleaned.split("/")[0].split(":")[0].removeprefix("www.")
    if not cleaned or "." not in cleaned:
        raise ValidationFailedError("יש להזין דומיין תקין, למשל rhs.org.uk.")
    return cleaned


# --- user-facing --------------------------------------------------------------


@router.get("/species/{species_id}/knowledge", response_model=DataEnvelope[KnowledgeResponse])
async def get_species_knowledge(
    request: Request,
    species_id: UUID,
    user: CurrentUserDep,
    language: str | None = Query(default=None, max_length=2),
) -> DataEnvelope[KnowledgeResponse]:
    """The current published version. Drafts are never visible here."""
    version = workflow.published_version(user.client, species_id=species_id, language=language)
    if version is None:
        # KNOWLEDGE_PENDING is not an error state for the plant, but there is
        # genuinely nothing to return yet, and an empty 200 would render as an
        # article with no text.
        raise NotFoundError("עדיין אין מידע מקצועי מאושר עבור המין הזה.")

    sources = workflow.version_sources(user.client, version_id=UUID(version["id"]))

    return DataEnvelope(
        data=KnowledgeResponse(**version, sources=[SourceResponse(**s) for s in sources]),
        request_id=request.state.request_id,
    )


@router.post(
    "/species/{species_id}/knowledge-reports",
    response_model=DataEnvelope[dict],
    status_code=status.HTTP_201_CREATED,
)
async def report_knowledge_error(
    request: Request,
    species_id: UUID,
    payload: ReportRequest,
    user: CurrentUserDep,
) -> DataEnvelope[dict]:
    """A user reports a suspected error (FINAL §10: report, never edit).

    The current version is recorded alongside the species, so a report filed
    against version 3 is still legible after version 4 publishes — otherwise an
    administrator reading the queue a week later cannot tell which text the
    complaint was about.
    """
    current = workflow.published_version(user.client, species_id=species_id)

    report = first_row(
        user.client.table("knowledge_reports")
        .insert(
            {
                "user_id": str(user.id),
                "plant_id": str(payload.plant_id) if payload.plant_id else None,
                "species_id": str(species_id),
                "knowledge_version_id": current["id"] if current else None,
                "report_text": payload.report_text.strip(),
            }
        )
        .execute()
    )

    return DataEnvelope(
        data={"report_id": report["id"] if report else None, "status": "OPEN"},
        request_id=request.state.request_id,
    )


# --- admin: drafts ------------------------------------------------------------


@router.get("/admin/knowledge-drafts", response_model=DataEnvelope[list[DraftResponse]])
async def list_knowledge_drafts(
    request: Request,
    admin: AdminDep,
    status_filter: Annotated[KnowledgeDraftStatus | None, Query(alias="status")] = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> DataEnvelope[list[DraftResponse]]:
    drafts = workflow.list_drafts(
        admin.client, status=status_filter.value if status_filter else None, limit=limit
    )
    return DataEnvelope(
        data=[DraftResponse(**draft) for draft in drafts], request_id=request.state.request_id
    )


@router.get("/admin/knowledge-drafts/{draft_id}", response_model=DataEnvelope[DraftResponse])
async def get_knowledge_draft(
    request: Request, draft_id: UUID, admin: AdminDep
) -> DataEnvelope[DraftResponse]:
    draft = workflow.get_draft(admin.client, draft_id)
    return DataEnvelope(data=DraftResponse(**draft), request_id=request.state.request_id)


@router.post("/admin/knowledge-drafts/{draft_id}/approve", response_model=DataEnvelope[dict])
async def approve_knowledge_draft(
    request: Request, draft_id: UUID, payload: ApproveRequest, admin: AdminDep
) -> DataEnvelope[dict]:
    """Publish a reviewed draft and release the plants waiting on it (A4).

    Everything happens in one database transaction, because the ordering the
    unique index forces — demote, then insert — leaves a species with no current
    version in between.
    """
    result = workflow.publish(admin.client, draft_id=draft_id, admin_note=payload.admin_note)
    return DataEnvelope(data=result, request_id=request.state.request_id)


@router.post(
    "/admin/knowledge-drafts/{draft_id}/reject", response_model=DataEnvelope[DraftResponse]
)
async def reject_knowledge_draft(
    request: Request, draft_id: UUID, payload: RejectRequest, admin: AdminDep
) -> DataEnvelope[DraftResponse]:
    """Reject a draft. Plants stay pending and the species stays retriable (A17)."""
    draft = workflow.reject(admin.client, draft_id=draft_id, admin_note=payload.admin_note)
    return DataEnvelope(data=DraftResponse(**draft), request_id=request.state.request_id)


@router.post(
    "/admin/knowledge-drafts/{draft_id}/retry",
    response_model=DataEnvelope[dict],
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_knowledge_research(
    request: Request,
    draft_id: UUID,
    payload: RetryRequest,
    admin: AdminDep,
    background: BackgroundTasks,
    agent: KnowledgeAgentDep,
) -> DataEnvelope[dict]:
    """Research this species again.

    The path out of a rejected or failed draft, and therefore the path out of
    KNOWLEDGE_PENDING for every plant waiting on it. The administrator's reason is
    passed to the agent, so a retry after a rejection can address the objection
    rather than reproduce it.
    """
    draft = workflow.get_draft(admin.client, draft_id)

    run = workflow.start_research(
        species_id=UUID(draft["species_id"]),
        initiated_by=admin.id,
        reason=payload.reason,
        language=draft["language"],
    )

    BackgroundTasksExecutor(background).submit(
        workflow.execute_research,
        request_id=run.request_id,
        draft_id=run.draft_id,
        species_id=run.species_id,
        language=run.language,
        reason=payload.reason,
        agent=agent,
    )

    return DataEnvelope(
        data={"draft_id": str(run.draft_id), "agent_request_id": str(run.request_id)},
        request_id=request.state.request_id,
    )


# --- admin: versions ----------------------------------------------------------


@router.get(
    "/admin/knowledge-versions/{species_id}", response_model=DataEnvelope[list[VersionSummary]]
)
async def list_knowledge_versions(
    request: Request, species_id: UUID, admin: AdminDep
) -> DataEnvelope[list[VersionSummary]]:
    """Version history, newest first.

    Reachable only because migration 0006 gives administrators a read-all policy
    alongside the users' `where is_current` one. Without it an admin client would
    see exactly one row here.
    """
    versions = workflow.version_history(admin.client, species_id=species_id)
    return DataEnvelope(
        data=[VersionSummary(**v) for v in versions], request_id=request.state.request_id
    )


# --- admin: approved sources ---------------------------------------------------


@router.get("/admin/approved-sources", response_model=DataEnvelope[list[ApprovedSourceResponse]])
async def list_approved_sources(
    request: Request, admin: AdminDep
) -> DataEnvelope[list[ApprovedSourceResponse]]:
    records = rows(
        admin.client.table("approved_sources")
        .select("id, name, domain, source_type, reliability_level, notes, is_enabled")
        .order("domain")
        .execute()
    )
    return DataEnvelope(
        data=[ApprovedSourceResponse(**r) for r in records], request_id=request.state.request_id
    )


@router.post(
    "/admin/approved-sources",
    response_model=DataEnvelope[ApprovedSourceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_approved_source(
    request: Request, payload: ApprovedSourceRequest, admin: AdminDep
) -> DataEnvelope[ApprovedSourceResponse]:
    domain = _normalise_domain(payload.domain)

    if first_row(
        admin.client.table("approved_sources").select("id").eq("domain", domain).execute()
    ):
        raise ValidationFailedError("הדומיין כבר קיים ברשימה.")

    created = first_row(
        admin.client.table("approved_sources")
        .insert(
            {
                "name": payload.name.strip(),
                "domain": domain,
                "source_type": payload.source_type,
                "reliability_level": payload.reliability_level,
                "notes": payload.notes,
                "created_by": str(admin.id),
            }
        )
        .execute()
    )
    if created is None:  # pragma: no cover - insert returns the row or raises
        raise ValidationFailedError("לא ניתן היה להוסיף את המקור.")

    _audit(admin, "approved_source.create", created["id"], {"domain": domain})

    return DataEnvelope(data=ApprovedSourceResponse(**created), request_id=request.state.request_id)


@router.patch(
    "/admin/approved-sources/{source_id}", response_model=DataEnvelope[ApprovedSourceResponse]
)
async def update_approved_source(
    request: Request, source_id: UUID, payload: ApprovedSourceUpdate, admin: AdminDep
) -> DataEnvelope[ApprovedSourceResponse]:
    """Update a source. The domain is deliberately not editable.

    Changing it would silently reclassify every existing `knowledge_sources` row
    that points at this record — rows that are immutable precisely so that a
    published version's provenance cannot be rewritten. A different domain is a
    different source; add it and disable this one.
    """
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise ValidationFailedError("לא נשלח שדה לעדכון.")

    updated = first_row(
        admin.client.table("approved_sources").update(changes).eq("id", str(source_id)).execute()
    )
    if updated is None:
        raise NotFoundError("המקור לא נמצא.")

    _audit(admin, "approved_source.update", str(source_id), changes)

    return DataEnvelope(data=ApprovedSourceResponse(**updated), request_id=request.state.request_id)


@router.post(
    "/admin/approved-sources/{source_id}/disable",
    response_model=DataEnvelope[ApprovedSourceResponse],
)
async def disable_approved_source(
    request: Request, source_id: UUID, admin: AdminDep
) -> DataEnvelope[ApprovedSourceResponse]:
    """Retire a domain without deleting it.

    Disabling stops it conferring `APPROVED` on future research. It deliberately
    does **not** touch existing `knowledge_sources` rows: those record what was
    true when a version was published, and rewriting history to match a later
    policy change is exactly what an immutable provenance record is for.
    """
    updated = first_row(
        admin.client.table("approved_sources")
        .update({"is_enabled": False})
        .eq("id", str(source_id))
        .execute()
    )
    if updated is None:
        raise NotFoundError("המקור לא נמצא.")

    _audit(admin, "approved_source.disable", str(source_id), {"domain": updated["domain"]})

    return DataEnvelope(data=ApprovedSourceResponse(**updated), request_id=request.state.request_id)


def _audit(admin: AdminDep, action: str, target_id: str, payload: dict[str, Any]) -> None:
    """Record a consequential admin action (FINAL §29).

    Written through the administrator's own client, which is why migration 0012
    had to add an INSERT policy: the table was created read-only for admins on the
    assumption that only the service role would ever write it.

    Publication and rejection do not come through here — they write their own
    entry inside the same transaction as the change, which is stronger: an audit
    entry that can be lost separately from the action it describes is not much of
    a record.
    """
    admin.client.table("admin_audit_log").insert(
        {
            "admin_user_id": str(admin.id),
            "action": action,
            "target_table": "approved_sources",
            "target_id": target_id,
            "payload": payload,
        }
    ).execute()
