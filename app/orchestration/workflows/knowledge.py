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
from app.common.enums import AgentStage, AgentType, KnowledgeDraftStatus, PlantStatus
from app.common.errors import NotFoundError, ValidationFailedError
from app.config.logging import get_logger
from app.config.settings import get_settings
from app.domain.rules.knowledge_lifecycle import ensure_transition, is_publishable
from app.domain.services import source_verification as verification
from app.infrastructure.supabase.client import service_client
from app.orchestration.services import agent_requests as requests_service
from app.repositories.base import Row, first_row, require_row, rows
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


#: The statuses that mean "research is already under way, or its result is still
#: waiting to be read". A draft in any of them is the one `_open_or_reuse_draft`
#: would take over, so they are also the statuses that must block a second run
#: being started from somewhere else.
OPEN_DRAFT_STATUSES = (
    KnowledgeDraftStatus.DRAFT,
    KnowledgeDraftStatus.RESEARCHING,
    KnowledgeDraftStatus.READY_FOR_REVIEW,
)


def open_draft(client: Client, *, species_id: UUID, language: str) -> Row | None:
    """The species' draft that is still in play, if it has one.

    Exists so a caller can find out *before* acting that research would take over
    an existing draft rather than open a new one. `_open_or_reuse_draft` reuses
    such a draft by design - that is what the retry control in the drafts tab
    needs - but a caller starting research from the published catalogue is making
    a different request, and reusing a `READY_FOR_REVIEW` draft there would
    overwrite content nobody has read yet.

    Matches the partial unique index in migration 0006, which is defined over
    these same three statuses: at most one row can satisfy this query.

    Deliberately not `DRAFT_COLUMNS`: the answer is "which draft, and in what
    state", and selecting the whole row would fetch a fourteen-section article to
    decide whether to refuse a request.
    """
    return first_row(
        client.table("knowledge_drafts")
        .select("id, status")
        .eq("species_id", str(species_id))
        .eq("language", language)
        .in_("status", [s.value for s in OPEN_DRAFT_STATUSES])
        .limit(1)
        .execute()
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

        # PR 33: finished research releases the plants waiting on it, without
        # waiting for review. They go ACTIVE with knowledge marked "ממתין
        # לאישור מומחה" and a care plan built from the draft; the review gate
        # itself is unchanged, since nothing here writes a `knowledge_versions`
        # row. Before this, a plant sat in KNOWLEDGE_PENDING with no knowledge,
        # no plan and no schedule until an administrator happened to look.
        released = release_pending_plants(admin, species_id=species_id)

        requests_service.mark_succeeded(
            request_id,
            {
                "draft_id": str(draft_id),
                "species_id": str(species_id),
                "released_plants": released,
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


# --- admin review and publication ----------------------------------------------


def list_drafts(client: Client, *, status: str | None = None, limit: int = 50) -> list[Row]:
    """Drafts awaiting attention, newest activity first.

    Ordered by `updated_at` rather than `created_at`: a draft that has just
    finished researching is the one an administrator wants to see, and it may have
    been created days earlier by whoever first confirmed that species.
    """
    query = client.table("knowledge_drafts").select(DRAFT_COLUMNS)
    if status:
        query = query.eq("status", status)
    return rows(query.order("updated_at", desc=True).limit(limit).execute())


def publish(client: Client, *, draft_id: UUID, admin_note: str | None = None) -> dict[str, Any]:
    """Approve a reviewed draft and release the plants waiting on it.

    One RPC, one transaction. The demote-then-insert ordering the partial unique
    index forces, the source rows, the draft status, the fan-out and the audit
    entry either all happen or none do — from Python they would be six round trips
    with a window in the middle where a species has no current version at all.

    The lifecycle rule is asserted here as well as in SQL. The database check is
    the one that cannot be bypassed; this one produces a Hebrew error the user
    interface can show, instead of a Postgres exception.
    """
    draft = get_draft(client, draft_id)
    status = KnowledgeDraftStatus(draft["status"])
    if not is_publishable(status):
        raise ValidationFailedError("רק טיוטה שנבדקה ומוכנה לאישור ניתנת לפרסום.")

    version = require_row(
        client.rpc(
            "publish_knowledge_draft",
            {"p_draft_id": str(draft_id), "p_admin_note": admin_note},
        ).execute()
    )

    released = rows(
        client.table("plants")
        .select("id", count=None)
        .eq("species_id", version["species_id"])
        .eq("status", PlantStatus.ACTIVE.value)
        .execute()
    )

    log.info(
        "knowledge.published",
        draft_id=str(draft_id),
        version_id=version["id"],
        version_number=version["version_number"],
    )

    return {
        "version_id": version["id"],
        "species_id": version["species_id"],
        "language": version["language"],
        "version_number": version["version_number"],
        "source_summary": version.get("source_summary") or {},
        # Informational: how many plants of this species are now active. Read
        # after the fact through the caller's own client, so it reflects what RLS
        # lets an administrator see rather than what the transaction did.
        "active_plants": len(released),
    }


def is_newest_draft(client: Client, *, draft_id: UUID) -> bool:
    """Is this the most recent draft for its species and language?

    Guards the automatic re-research on rejection against becoming a loop: only
    the newest draft triggers one, so rejecting the *replacement* does not start a
    third attempt. An administrator who wants another after that presses Retry,
    which is a deliberate act.
    """
    draft = first_row(
        client.table("knowledge_drafts")
        .select("id, species_id, language, created_at")
        .eq("id", str(draft_id))
        .execute()
    )
    if draft is None:  # pragma: no cover - the caller just updated it
        return False

    newest = first_row(
        client.table("knowledge_drafts")
        .select("id")
        .eq("species_id", draft["species_id"])
        .eq("language", draft["language"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return newest is not None and str(newest["id"]) == str(draft_id)


def pending_draft(client: Client, *, species_id: UUID, language: str | None = None) -> Row | None:
    """Finished research a user may read while it waits for review (PR 33).

    Shaped like a published version so one response model serves both: the screen
    should differ in what it *says* about the content, not in how it reads it.
    `version_number` is 0 - there is no published version yet, and inventing a 1
    would collide with the real first version the moment it publishes.

    Returns nothing unless RLS lets the caller see it: the draft policy admits
    `READY_FOR_REVIEW` only, and only for a species they own a plant of.
    """
    settings = get_settings()
    draft = first_row(
        client.table("knowledge_drafts")
        .select("id, species_id, language, content, updated_at")
        .eq("species_id", str(species_id))
        .eq("language", language or settings.default_content_language)
        .eq("status", KnowledgeDraftStatus.READY_FOR_REVIEW.value)
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    if draft is None:
        return None

    return {
        "id": draft["id"],
        "species_id": draft["species_id"],
        "language": draft["language"],
        "version_number": 0,
        "review": "pending",
        "content": draft.get("content"),
        "source_summary": {},
        "published_at": draft["updated_at"],
    }


def release_pending_plants(admin: Client, *, species_id: UUID) -> int:
    """Move this species' waiting plants to ACTIVE (PR 33).

    Runs under the service role: the plants belong to other users and the trigger
    is a background research run, so there is no user JWT in scope. Each plant's
    own rows still carry their `user_id`, so RLS shows the result to them and
    nobody else.

    Deliberately *not* queueing the care proposals here. Publication has a
    dedicated fan-out (`care.queue_initial_plans`) that already knows how to skip
    a plant with a pending proposal or a working plan, and duplicating that
    judgement in a second place is how the two roads into ACTIVE came to disagree
    in the first place (A3, PR 31). The caller queues.
    """
    waiting = rows(
        admin.table("plants")
        .select("id, user_id")
        .eq("species_id", str(species_id))
        .eq("status", PlantStatus.KNOWLEDGE_PENDING.value)
        .execute()
    )
    if not waiting:
        return 0

    # No system event, deliberately. `publish_knowledge_draft` performs the same
    # KNOWLEDGE_PENDING -> ACTIVE transition and writes none either, and A22 keeps
    # the event vocabulary to things with no table of their own. What the user
    # sees on the timeline is the care plan version this releases, which is the
    # thing that actually happened.
    admin.table("plants").update({"status": PlantStatus.ACTIVE.value}).in_(
        "id", [p["id"] for p in waiting]
    ).execute()

    log.info(
        "knowledge.plants_released_on_draft",
        species_id=str(species_id),
        plants=len(waiting),
    )
    return len(waiting)


def reject(client: Client, *, draft_id: UUID, admin_note: str) -> Row:
    """Reject a draft, leaving the species retriable (A17).

    A rejection is a verdict on the draft, not on the plants — stranding them is
    the failure A17 exists to prevent, and the lifecycle table keeps
    `REJECTED → RESEARCHING` open so the next attempt can still release them.

    Since PR 33 a rejected draft may already be carrying care plans, because
    plants no longer wait for review. Those plans are **not** cancelled: the plant
    would be left with no schedule at all, which is worse than a schedule built on
    advice an administrator disliked. Instead the plant page says so — read from
    the join between `care_plan_versions.knowledge_draft_id` and this status, so
    there is no second copy of the fact to drift — and the caller queues one fresh
    research run.
    """
    if not admin_note.strip():
        raise ValidationFailedError("יש לציין סיבה לדחייה.")

    draft = get_draft(client, draft_id)
    ensure_transition(KnowledgeDraftStatus(draft["status"]), KnowledgeDraftStatus.REJECTED)

    return require_row(
        client.rpc(
            "reject_knowledge_draft",
            {"p_draft_id": str(draft_id), "p_admin_note": admin_note.strip()},
        ).execute()
    )


def published_version(
    client: Client, *, species_id: UUID, language: str | None = None
) -> Row | None:
    """The current published version of a species' knowledge, or None.

    RLS gives regular users `where is_current`, so this is the same query for
    everyone — an administrator simply also has a policy that lets them read the
    history through :func:`version_history`.
    """
    settings = get_settings()
    return first_row(
        client.table("knowledge_versions")
        .select("id, species_id, language, version_number, content, source_summary, published_at")
        .eq("species_id", str(species_id))
        .eq("language", language or settings.default_content_language)
        .eq("is_current", True)
        .limit(1)
        .execute()
    )


def version_history(client: Client, *, species_id: UUID) -> list[Row]:
    """Every version of a species' knowledge, newest first. Admin-only by RLS."""
    return rows(
        client.table("knowledge_versions")
        .select("id, species_id, language, version_number, is_current, published_by, published_at")
        .eq("species_id", str(species_id))
        .order("version_number", desc=True)
        .execute()
    )


def published_catalogue(client: Client, *, query: str | None = None) -> list[Row]:
    """Every species with published knowledge, with its name and its numbers.

    The admin screen offered a box asking for a species UUID and nothing else, so
    on a database with 857 species and fifty published articles there was no way
    to reach any of them except by already knowing the id. The endpoint had
    existed since PR 15; nothing could list it.

    Three reads rather than a join: PostgREST embedding across knowledge, species
    and plants is hard to follow and this runs once, for an administrator, over a
    set the size of the published catalogue.
    """
    current = rows(
        client.table("knowledge_versions")
        .select("id, species_id, language, version_number, published_at")
        .eq("is_current", True)
        .order("published_at", desc=True)
        .execute()
    )
    if not current:
        return []

    species_ids = list({str(v["species_id"]) for v in current})
    species = {
        row["id"]: row
        for row in rows(
            client.table("species")
            .select("id, scientific_name, common_name")
            .in_("id", species_ids)
            .execute()
        )
    }

    # How many plants each article is actually serving. It is the one number that
    # says which entries matter, and it is why an admin opens this screen.
    counts: dict[str, int] = {}
    for plant in rows(
        client.table("plants").select("species_id").in_("species_id", species_ids).execute()
    ):
        key = str(plant["species_id"])
        counts[key] = counts.get(key, 0) + 1

    # Which of these species already have research in play, keyed by species and
    # language because a draft in Hebrew says nothing about an English article.
    # The published screen offers a "research again" control per card, and without
    # this it would offer it for a species whose draft is already open - which
    # `_open_or_reuse_draft` would take over rather than duplicate, overwriting a
    # draft awaiting review. See `open_draft`.
    open_drafts = {
        (str(draft["species_id"]), str(draft["language"])): str(draft["status"])
        for draft in rows(
            client.table("knowledge_drafts")
            .select("species_id, language, status")
            .in_("species_id", species_ids)
            .in_("status", [s.value for s in OPEN_DRAFT_STATUSES])
            .execute()
        )
    }

    catalogue = []
    for version in current:
        found = species.get(str(version["species_id"])) or {}
        catalogue.append(
            {
                **version,
                "scientific_name": found.get("scientific_name") or "",
                "common_name": found.get("common_name"),
                "plant_count": counts.get(str(version["species_id"]), 0),
                "open_draft_status": open_drafts.get(
                    (str(version["species_id"]), str(version["language"]))
                ),
            }
        )

    if query:
        needle = query.strip().lower()
        catalogue = [
            entry
            for entry in catalogue
            if needle in entry["scientific_name"].lower()
            or needle in (entry["common_name"] or "").lower()
        ]

    return sorted(catalogue, key=lambda e: e["scientific_name"].lower())


def version_detail(client: Client, *, version_id: UUID) -> Row:
    """One published version in full, for the admin reader.

    `GET /v1/species/{id}/knowledge` returns only the *current* version, which is
    the right answer for a user and the wrong one for an administrator reviewing
    what changed between two of them.
    """
    return require_row(
        client.table("knowledge_versions")
        .select(
            "id, species_id, language, version_number, is_current, content, "
            "source_summary, published_by, published_at"
        )
        .eq("id", str(version_id))
        .execute(),
        NotFoundError("הגרסה לא נמצאה."),
    )


def version_sources(client: Client, *, version_id: UUID) -> list[Row]:
    return rows(
        client.table("knowledge_sources")
        .select("id, source_class, title, url, publisher, retrieved_at, notes, approved_source_id")
        .eq("knowledge_version_id", str(version_id))
        .order("source_class")
        .execute()
    )
