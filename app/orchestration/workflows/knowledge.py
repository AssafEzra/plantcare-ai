"""Knowledge research workflow.

The Knowledge Agent researches; this module decides what is written down. The
split is FINAL §11's — the agent "never publishes" — and keeping persistence out
here is what makes that true rather than promised.

What a research run produces is a draft in `READY_FOR_REVIEW`, and nothing else.
No `knowledge_versions` row, no plant leaves `KNOWLEDGE_PENDING`, no user sees a
word of it. Publication is an administrator's decision and lives in PR 15.

Everything here runs under the service role. Drafts and approved sources are
admin-only tables by RLS, and a research run is started by the *system* on behalf
of a user who confirmed an identification — there is no admin JWT in scope, and
inventing one would defeat the policy rather than satisfy it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.agents.knowledge.agent import KnowledgeAgent
from app.agents.knowledge.contract import KnowledgeContent, KnowledgeRequest, ProposedSource
from app.common.enums import (
    AgentStage,
    AgentType,
    KnowledgeDraftStatus,
)
from app.common.errors import NotFoundError
from app.config.logging import get_logger
from app.config.settings import get_settings
from app.domain.rules.knowledge_lifecycle import ensure_transition
from app.domain.services import source_verification as verification
from app.infrastructure.supabase.client import service_client
from app.orchestration.services import agent_requests as requests_service
from app.repositories.base import Row, first_row, rows
from supabase import Client

log = get_logger(__name__)

DRAFT_COLUMNS = (
    "id, species_id, language, status, initiated_by, research_request_id, "
    "content, research_notes, admin_note, created_at, updated_at"
)


@dataclass(frozen=True)
class ResearchRun:
    """A queued research run: what the caller needs to execute it.

    Carries the language rather than letting the caller re-derive it. Two places
    resolving the default independently is how a draft ends up written in one
    language and looked up in another.
    """

    draft_id: UUID
    request_id: UUID
    species_id: UUID
    language: str

    def as_summary(self) -> dict[str, str]:
        return {
            "draft_id": str(self.draft_id),
            "request_id": str(self.request_id),
            "species_id": str(self.species_id),
            "language": self.language,
        }


# --- starting a research run ---------------------------------------------------


def start_research(
    *,
    species_id: UUID,
    initiated_by: UUID,
    reason: str | None = None,
    language: str | None = None,
) -> ResearchRun:
    """Open (or reuse) a draft and create the agent request for it.

    Does not run the agent — the caller submits :func:`execute_research` to an
    executor, so the 202-and-poll contract is identical to identification's.
    """
    admin = service_client()
    settings = get_settings()
    lang = language or settings.default_content_language

    species = first_row(
        admin.table("species")
        .select("id, scientific_name, common_name")
        .eq("id", str(species_id))
        .execute()
    )
    if species is None:
        raise NotFoundError("המין לא נמצא.")

    draft = _open_or_reuse_draft(admin, species_id, lang, initiated_by)
    status = KnowledgeDraftStatus(draft["status"])

    if status is KnowledgeDraftStatus.RESEARCHING and draft.get("research_request_id"):
        # Already running. Joining it is the whole point of reusing the draft:
        # starting a second request here would bill for a duplicate run whose
        # result would then race the first one into the same row.
        return ResearchRun(
            draft_id=UUID(draft["id"]),
            request_id=UUID(draft["research_request_id"]),
            species_id=species_id,
            language=lang,
        )

    # Before the write, not after. DRAFT, REJECTED, FAILED and READY_FOR_REVIEW
    # may all be researched (A17); anything else is a bug the table catches here
    # rather than after a row has already moved.
    ensure_transition(status, KnowledgeDraftStatus.RESEARCHING)

    request = requests_service.create_or_replay(
        admin,
        user_id=initiated_by,
        plant_id=None,
        agent_type=AgentType.KNOWLEDGE,
        payload={
            "species_id": str(species_id),
            "draft_id": draft["id"],
            "language": lang,
            "reason": (reason or "").strip() or None,
        },
        idempotency_key=None,
    )

    admin.table("knowledge_drafts").update(
        {"research_request_id": str(request.id), "status": KnowledgeDraftStatus.RESEARCHING.value}
    ).eq("id", draft["id"]).execute()

    return ResearchRun(
        draft_id=UUID(draft["id"]),
        request_id=request.id,
        species_id=species_id,
        language=lang,
    )


def _open_or_reuse_draft(admin: Client, species_id: UUID, language: str, initiated_by: UUID) -> Row:
    """The draft to research into.

    A draft already open for this species and language is reused rather than
    duplicated — the partial unique index in migration 0006 would refuse a second
    one anyway, and racing two research runs would end with two versions of the
    same knowledge competing to publish.
    """
    existing = first_row(
        admin.table("knowledge_drafts")
        .select(DRAFT_COLUMNS)
        .eq("species_id", str(species_id))
        .eq("language", language)
        .in_("status", [s.value for s in KnowledgeDraftStatus])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if existing is not None and KnowledgeDraftStatus(existing["status"]) != (
        KnowledgeDraftStatus.APPROVED
    ):
        return existing

    created = first_row(
        admin.table("knowledge_drafts")
        .insert(
            {
                "species_id": str(species_id),
                "language": language,
                "status": KnowledgeDraftStatus.DRAFT.value,
                "initiated_by": str(initiated_by),
            }
        )
        .execute()
    )
    if created is None:  # pragma: no cover - insert returns the row or raises
        raise NotFoundError("could not create the knowledge draft")
    return created


# --- running it ----------------------------------------------------------------


def execute_research(
    *,
    request_id: UUID,
    draft_id: UUID,
    species_id: UUID,
    language: str,
    reason: str | None,
    agent: KnowledgeAgent,
) -> None:
    """Research a species and store the result as a draft awaiting review."""
    admin = service_client()

    try:
        requests_service.mark_stage(request_id, AgentStage.CONTEXT_LOADED.value)
        species = first_row(
            admin.table("species")
            .select("id, scientific_name, common_name")
            .eq("id", str(species_id))
            .execute()
        )
        if species is None:
            raise NotFoundError("המין לא נמצא.")

        domains = _approved_domains(admin)

        requests_service.mark_stage(request_id, AgentStage.ANALYZING.value)
        result = agent.generate(
            KnowledgeRequest(
                scientific_name=species["scientific_name"],
                common_name=species.get("common_name"),
                language=language,
                approved_domains=[domain.domain for domain in domains],
                reason=reason,
            ),
            request_id=request_id,
        )

        requests_service.mark_stage(request_id, AgentStage.PREPARING_RESULT.value)
        verified = verification.verify_all(
            [
                verification.SourceClaim(
                    url=source.url, title=source.title, publisher=source.publisher
                )
                for source in result.proposed_sources
            ],
            scientific_name=species["scientific_name"],
            common_name=species.get("common_name"),
            approved_domains=domains,
        )

        admin.table("knowledge_drafts").update(
            {
                "status": KnowledgeDraftStatus.READY_FOR_REVIEW.value,
                "content": _draft_payload(result.content, result.proposed_sources, verified),
                "research_notes": result.research_notes,
            }
        ).eq("id", str(draft_id)).execute()

        requests_service.mark_succeeded(
            request_id,
            {
                "draft_id": str(draft_id),
                "species_id": str(species_id),
                "verified_sources": sum(1 for s in verified if s.url is not None),
                "unverified_sources": sum(1 for s in verified if s.url is None),
                "weak_sections": result.content.weakest_sections,
            },
        )

    except Exception:
        # FINAL §25 with a twist: the draft is not an authoritative record, so it
        # survives - marked FAILED, which A17 keeps retriable. What must not
        # happen is a published version, and nothing on this path writes one.
        log.exception("knowledge.research_failed", request_id=str(request_id))
        _mark_draft_failed(admin, draft_id)
        requests_service.mark_failed(request_id, "AGENT_FAILED")
        raise


def _mark_draft_failed(admin: Client, draft_id: UUID) -> None:
    """Record the failure without losing the draft.

    Swallows its own errors: the agent failure is what matters, and a
    bookkeeping error on top of it must not replace the original traceback.
    """
    try:
        admin.table("knowledge_drafts").update({"status": KnowledgeDraftStatus.FAILED.value}).eq(
            "id", str(draft_id)
        ).execute()
    except Exception as exc:  # pragma: no cover - defensive
        log.error("knowledge.draft_status_write_failed", error_type=type(exc).__name__)


def _approved_domains(admin: Client) -> list[verification.ApprovedDomain]:
    """The enabled allow-list.

    Disabled rows are excluded here rather than filtered later, so a domain an
    administrator has disabled cannot classify a source as APPROVED - which is the
    only thing disabling it is for.
    """
    records = rows(
        admin.table("approved_sources")
        .select("id, name, domain")
        .eq("is_enabled", True)
        .order("domain")
        .execute()
    )
    return [
        verification.ApprovedDomain(id=r["id"], domain=r["domain"], name=r.get("name"))
        for r in records
    ]


def _draft_payload(
    content: KnowledgeContent,
    proposed: list[ProposedSource],
    verified: list[verification.VerifiedSource],
) -> dict[str, Any]:
    """What goes into `knowledge_drafts.content`.

    The fourteen sections, plus the verification outcome for each proposed
    source. The sources live inside the draft blob rather than in
    `knowledge_sources`, because that table's rows belong to a *published
    version* and are immutable — writing them before publication would make a
    draft's provenance unrevisable while the draft itself is still being edited.
    They become rows at approval (PR 15).
    """
    return {
        "sections": content.model_dump(),
        "sources": [
            {
                "source_class": source.source_class.value,
                "url": source.url,
                "title": source.title,
                "publisher": source.publisher,
                "approved_source_id": source.approved_domain,
                "notes": source.notes,
                "supports_sections": claim.supports_sections,
            }
            for source, claim in zip(verified, proposed, strict=True)
        ],
    }


def get_draft(client: Client, draft_id: UUID) -> Row:
    """Read a draft. RLS admits administrators only."""
    found = first_row(
        client.table("knowledge_drafts").select(DRAFT_COLUMNS).eq("id", str(draft_id)).execute()
    )
    if found is None:
        raise NotFoundError("הטיוטה לא נמצאה.")
    return found
