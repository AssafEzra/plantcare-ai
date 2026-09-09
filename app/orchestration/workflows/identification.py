"""Identification workflows.

Two flows live here, and the split between them is the product rule: the agent
proposes, the user disposes.

* :func:`run_identification` — analyse photographs and record what the agent
  proposed. Changes nothing about the plant.
* :func:`confirm_identification` — the user picks a candidate. Only now does a
  species become authoritative, a `species` row get created, and the plant move.

FINAL §9 is explicit that the Identification Agent never changes
`plants.species_id`, and keeping the two functions apart is what makes that
structural rather than a matter of care.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from app.agents.identification.agent import IdentificationAgent
from app.agents.identification.contract import IdentificationRequest, IdentificationResult
from app.common.enums import (
    AgentStage,
    AgentType,
    CarePlanVersionSourceType,
    IdentificationMethod,
    IdentificationStatus,
    KnowledgeDraftStatus,
    PlantStatus,
    SystemEventType,
)
from app.common.errors import NotFoundError, ValidationFailedError
from app.config.logging import get_logger
from app.domain.rules.knowledge_lifecycle import is_open
from app.domain.rules.plant_lifecycle import (
    PlantFacts,
    ensure_transition,
    status_after_confirmation,
)
from app.infrastructure.ai.provider import ImageInput
from app.infrastructure.storage import plant_images as storage
from app.infrastructure.supabase.client import service_client
from app.orchestration.services import agent_requests as requests_service
from app.orchestration.workflows import knowledge as knowledge_workflow
from app.repositories import plants as plants_repo
from app.repositories.base import first_row, require_row, rows
from supabase import Client

log = get_logger(__name__)

MAX_IMAGES = 4


# --- running an identification -------------------------------------------------


def start(
    client: Client,
    *,
    user_id: UUID,
    plant_id: UUID,
    image_ids: list[UUID],
    user_description: str | None,
    idempotency_key: str | None,
) -> requests_service.AgentRequest:
    """Validate the request and create the agent request. Does not run the agent."""
    plant = plants_repo.find(client, plant_id, owner_id=user_id)
    if plant is None:
        raise NotFoundError("הצמח לא נמצא.")

    if not image_ids:
        raise ValidationFailedError("יש לצרף לפחות תמונה אחת.")
    if len(image_ids) > MAX_IMAGES:
        raise ValidationFailedError(f"אפשר לצרף עד {MAX_IMAGES} תמונות.")

    # Duplicates, before ownership - the check below collapses them to a set and
    # cannot see them. Identification has no join table to refuse a repeat, so
    # this failed silently instead of loudly: `_load_images` fetches with SQL
    # `IN`, so four copies of one id had the agent identify a plant from one
    # photograph while the user believed it had used four.
    if len(set(image_ids)) != len(image_ids):
        raise ValidationFailedError("אי אפשר לצרף את אותה תמונה יותר מפעם אחת.")

    # Every image must belong to this plant and this user. Checked through the
    # caller's own client, so RLS has already excluded anyone else's images; this
    # additionally stops one plant's photographs being used to identify another.
    owned = rows(
        client.table("plant_images")
        .select("id")
        .eq("plant_id", str(plant_id))
        .in_("id", [str(i) for i in image_ids])
        .execute()
    )
    if len(owned) != len(set(image_ids)):
        raise ValidationFailedError("חלק מהתמונות אינן שייכות לצמח הזה.")

    return requests_service.create_or_replay(
        client,
        user_id=user_id,
        plant_id=plant_id,
        agent_type=AgentType.IDENTIFICATION,
        payload={
            "image_ids": sorted(str(i) for i in image_ids),
            "user_description": (user_description or "").strip() or None,
        },
        idempotency_key=idempotency_key,
    )


def execute(
    *,
    request_id: UUID,
    user_id: UUID,
    plant_id: UUID,
    image_ids: list[UUID],
    user_description: str | None,
    access_token: str,
    agent: IdentificationAgent,
) -> None:
    """Run the agent and persist what it proposed.

    Runs after the 202 has been returned, so there is no request context and no
    user JWT in scope for writes that must succeed regardless — the service role
    is used for those, which is one of the uses the plan reserves it for.
    """
    admin = service_client()

    try:
        requests_service.mark_stage(request_id, AgentStage.IMAGES_RECEIVED.value)
        images = _load_images(admin, access_token, plant_id, image_ids)

        requests_service.mark_stage(request_id, AgentStage.CONTEXT_LOADED.value)
        requests_service.mark_stage(request_id, AgentStage.ANALYZING.value)

        result = agent.identify(
            IdentificationRequest(images=images, user_description=user_description),
            request_id=request_id,
        )

        requests_service.mark_stage(request_id, AgentStage.PREPARING_RESULT.value)
        identification_id = _persist(admin, request_id, user_id, plant_id, result)

        # The images actually shown to a model are retained for audit even if the
        # user later removes them (FINAL §20).
        admin.table("plant_images").update({"ai_used": True}).in_(
            "id", [str(i) for i in image_ids]
        ).execute()

        if result.status is IdentificationStatus.FAILED:
            # The model never answered. `identify` catches `AgentError` and returns
            # a FAILED result rather than raising - deliberately, so the row below
            # can be written - which meant nothing reached the `except` and the
            # request was marked SUCCEEDED. A request whose every execution failed
            # then read as a success in ניטור סוכנים, and the one screen with an
            # honest message was unreachable for every model failure.
            #
            # `NEEDS_MORE_INFORMATION` stays SUCCEEDED, and that is the whole
            # distinction: there the model did answer, and its answer was "I need
            # more". Only this branch means "the service could not tell you
            # anything".
            requests_service.mark_failed(request_id, result.error_code or "AGENT_FAILED")
        else:
            requests_service.mark_succeeded(
                request_id,
                {
                    "identification_id": str(identification_id),
                    "status": result.status.value,
                    "candidate_count": len(result.candidates),
                },
            )

        # A run that identified nothing. `NEEDS_MORE_INFORMATION` and a FAILED
        # result never reach the `except` below, because the agent handled the
        # failure itself - so without this the commonest disappointing outcome
        # would be the one case that still left a plant behind.
        if not result.succeeded:
            _archive_abandoned(admin, user_id, plant_id)
    except Exception as exc:
        # FINAL §25: no authoritative record - nothing here writes a species, a
        # confidence or a care plan. The plant itself is archived, which is the
        # one thing about it that does change: it was created as a placeholder for
        # this run (FINAL §3 puts naming after confirmation), and a run that
        # failed leaves a placeholder nobody can ever finish.
        log.exception("identification.execute_failed", request_id=str(request_id))
        requests_service.mark_failed(request_id, "AGENT_FAILED")
        _archive_abandoned(admin, user_id, plant_id)
        raise exc from None


def _archive_abandoned(admin: Client, user_id: UUID, plant_id: UUID) -> None:
    """Retire a plant whose identification will never be finished.

    The plant row exists before identification runs, because FINAL §3 puts naming
    after confirmation. Every route out of `PENDING_IDENTIFICATION` except "the
    user confirms" therefore abandons it, and nothing ever picked those up: they
    sat in My Plants reading "ממתין לזיהוי" for identifications that had failed
    days earlier.

    Two guards, and both are load-bearing:

    * **Only a plant still PENDING_IDENTIFICATION.** Re-identification of an
      established plant runs through this same function, and `ACTIVE -> ACTIVE` is
      a supported path (A21). A failed re-identification must leave a working
      plant exactly as it was.
    * **Never one with a successful identification.** That plant is waiting on the
      *user*, not on the model; the grid lists it and offers the button that
      accepts it. Archiving it would throw away a result they can still take.

    Best-effort by construction. This runs inside a failure path, and a plant that
    could not be archived is a great deal less serious than an exception that
    replaces the error the user and `agent_requests` are waiting to see.
    """
    try:
        plant = first_row(
            admin.table("plants").select("id, status").eq("id", str(plant_id)).execute()
        )
        if plant is None or plant["status"] != PlantStatus.PENDING_IDENTIFICATION.value:
            return

        if plants_repo.confirmable_plant_ids(admin, [str(plant_id)]):
            return

        ensure_transition(PlantStatus(plant["status"]), PlantStatus.ARCHIVED)
        plants_repo.update(admin, plant_id, {"status": "ARCHIVED", "archived_at": "now()"})
        plants_repo.record_event(
            admin,
            user_id=user_id,
            plant_id=plant_id,
            event_type=SystemEventType.PLANT_ARCHIVED,
            payload={
                "previous_status": plant["status"],
                "reason": "IDENTIFICATION_FAILED",
            },
        )
        log.info("identification.plant_archived", plant_id=str(plant_id))
    except Exception:
        log.exception("identification.archive_failed", plant_id=str(plant_id))


def _load_images(
    admin: Client, access_token: str, plant_id: UUID, image_ids: list[UUID]
) -> list[ImageInput]:
    """Fetch the processed derivatives to send to the model.

    The processed version rather than the original: it is bounded to 1600px, so
    the token cost is predictable and a 10 MB photograph does not become a
    correspondingly large request.
    """
    records = rows(
        admin.table("plant_images")
        .select("id, storage_path_processed, storage_path_original")
        .eq("plant_id", str(plant_id))
        .in_("id", [str(i) for i in image_ids])
        .execute()
    )

    images: list[ImageInput] = []
    for record in records:
        path = record.get("storage_path_processed") or record["storage_path_original"]
        url = storage.admin_signed_url(path)
        if not url:
            continue

        response = httpx.get(url, timeout=30, follow_redirects=True)
        if response.status_code == 200:
            images.append(ImageInput(data=response.content, mime_type="image/jpeg"))

    if not images:
        raise ValidationFailedError("לא הצלחנו לטעון את התמונות.")
    return images


def _persist(
    admin: Client,
    request_id: UUID,
    user_id: UUID,
    plant_id: UUID,
    result: IdentificationResult,
) -> UUID:
    """Write the identification and its candidates.

    A non-SUCCESS row carries neither a species nor a confidence level. That is
    also a CHECK constraint, so FINAL §25 holds even if this function is wrong.
    """
    primary = result.primary
    # `succeeded` already requires a candidate, but stating it this way lets the
    # type checker see it too, rather than needing a cast.
    is_success = result.succeeded and primary is not None

    row = require_row(
        admin.table("identifications")
        .insert(
            {
                "user_id": str(user_id),
                "plant_id": str(plant_id),
                "agent_request_id": str(request_id),
                "status": result.status.value,
                "method": IdentificationMethod.AI.value,
                "confidence_score": (
                    round(primary.confidence_score, 3) if primary and is_success else None
                ),
                "confidence_level": (
                    primary.confidence_level.value if primary and is_success else None
                ),
                "image_quality": result.image_quality,
                "request_more_photos": result.request_more_photos,
                "raw_result": {
                    "candidates": [c.model_dump() for c in result.candidates],
                    "insufficient_reason": result.insufficient_reason,
                },
            }
        )
        .execute()
    )
    identification_id = UUID(row["id"])

    if result.candidates:
        admin.table("identification_candidates").insert(
            [
                {
                    "identification_id": str(identification_id),
                    "scientific_name": candidate.scientific_name,
                    "common_name": candidate.common_name,
                    "rank": index + 1,
                    "confidence_score": round(candidate.confidence_score, 3),
                }
                for index, candidate in enumerate(result.candidates)
            ]
        ).execute()

    return identification_id


# --- confirming ---------------------------------------------------------------


def confirm(
    client: Client,
    *,
    user_id: UUID,
    identification_id: UUID,
    candidate_id: UUID,
    name: str | None = None,
) -> dict[str, Any]:
    """The user chooses a candidate. Only here does a species become authoritative.

    Plan decision 2: the `species` row is created now, from the candidate the user
    picked, rather than when the candidates were stored. Materialising a row per
    candidate would let every low-confidence hallucinated binomial permanently
    pollute the global taxonomy table.

    This is also where the plant gets its name (A2). `plants.name` is nullable
    only until confirmation, and API_CONTRACTS says an absent name falls back to
    the candidate's common name - so a user who skips the field ends up with "כנף
    נזירים" rather than a grid of cards all reading "ללא שם".
    """
    identification = first_row(
        client.table("identifications")
        .select("id, plant_id, status")
        .eq("id", str(identification_id))
        .execute()
    )
    if identification is None:
        raise NotFoundError("הזיהוי לא נמצא.")

    if identification["status"] != IdentificationStatus.SUCCESS.value:
        # Confirming a failed identification would be exactly the authoritative
        # record FINAL §25 forbids.
        raise ValidationFailedError("לא ניתן לאשר זיהוי שלא הצליח.")

    candidate = first_row(
        client.table("identification_candidates")
        .select("id, scientific_name, common_name, confidence_score")
        .eq("id", str(candidate_id))
        .eq("identification_id", str(identification_id))
        .execute()
    )
    if candidate is None:
        raise NotFoundError("האפשרות שנבחרה לא נמצאה.")

    plant_id = UUID(identification["plant_id"])
    plant = plants_repo.get(client, plant_id, owner_id=user_id)

    species = require_row(
        client.rpc(
            "upsert_species",
            {
                "p_scientific_name": candidate["scientific_name"],
                "p_common_name": candidate.get("common_name"),
            },
        ).execute()
    )
    species_id = species["id"]

    published = rows(
        client.table("knowledge_versions")
        .select("id")
        .eq("species_id", species_id)
        .eq("is_current", True)
        .limit(1)
        .execute()
    )

    current = PlantStatus(plant["status"])
    target = _status_after_confirm(plant, has_knowledge=bool(published))

    # The plant passes *through* IDENTIFIED rather than jumping straight to its
    # destination. FINAL §7 and TESTING §3 both model IDENTIFIED as a real state,
    # and the lifecycle table refuses PENDING_IDENTIFICATION -> ACTIVE precisely
    # so a plant cannot become active without having been identified. Walking the
    # path keeps the rule and the workflow agreeing with each other.
    for step in _confirmation_path(current, target):
        ensure_transition(current, step)
        current = step

    changes: dict[str, Any] = {"species_id": species_id, "status": target.value}
    # A name the user typed always wins. Otherwise the plant is named only if it
    # has no name yet: re-identifying a plant the user named "המונסטרה בסלון"
    # must not rename it after them.
    chosen_name = name or plant.get("name") or _fallback_name(candidate)
    if chosen_name != plant.get("name"):
        changes["name"] = chosen_name
    plants_repo.update(client, plant_id, changes)

    client.table("identifications").update(
        {"primary_species_id": species_id, "method": IdentificationMethod.USER_CONFIRMED.value}
    ).eq("id", str(identification_id)).execute()

    client.table("identification_candidates").update({"species_id": species_id}).eq(
        "id", str(candidate_id)
    ).execute()

    research: dict[str, str] | None = None
    if target is PlantStatus.KNOWLEDGE_PENDING:
        research = _start_research(UUID(species_id), user_id)

    initial_plan = _start_initial_plan(client, user_id=user_id, plant_id=plant_id, target=target)

    plants_repo.record_event(
        client,
        user_id=user_id,
        plant_id=plant_id,
        event_type=SystemEventType.CUSTOM_NOTE,
        payload={
            "kind": "identification_confirmed",
            "species_id": species_id,
            "scientific_name": candidate["scientific_name"],
            "status": target.value,
        },
    )

    return {
        "plant_id": str(plant_id),
        "name": chosen_name,
        # Present when the plant landed ACTIVE and had no plan. The caller submits
        # it, for the same reason `research` is handled that way: confirmation must
        # not block on a model call that takes a minute and a half.
        "initial_plan": initial_plan,
        "species_id": species_id,
        "scientific_name": species["scientific_name"],
        "status": target.value,
        "knowledge_pending": target is PlantStatus.KNOWLEDGE_PENDING,
        # Present when research was started. The caller submits it to an executor:
        # confirmation must not block on a model call that takes a minute, and the
        # user's plant is already usable without it.
        "research": research,
    }


def _start_initial_plan(
    client: Client, *, user_id: UUID, plant_id: UUID, target: PlantStatus
) -> dict[str, str] | None:
    """A3: a plant that becomes ACTIVE gets a care plan proposal.

    The fan-out on publication has done this since PR 16 - for plants that waited
    in KNOWLEDGE_PENDING. The other route into ACTIVE is this one: confirming a
    species whose knowledge is *already* published, which is the "existing species
    reuses published Knowledge" journey and the common case once the library
    fills up. Nothing queued a proposal there, so those plants arrived ACTIVE with
    no plan, no schedule and no reminders, and the only way to a plan was for the
    user to notice an empty state and press a button.

    Found by walking the product in a browser (PR 31). Every layer below passed:
    the journey asserts the plant is ACTIVE, which it was.
    """
    if target is not PlantStatus.ACTIVE:
        return None

    from app.orchestration.workflows import care as care_workflow

    # Re-identification of a plant that already has a working plan is a different
    # flow with a different source type, and must not be given a second INITIAL_PLAN.
    if care_workflow.plan_for_plant(client, plant_id=plant_id):
        return None

    try:
        request = care_workflow.start_proposal(
            client,
            user_id=user_id,
            plant_id=plant_id,
            reason=CarePlanVersionSourceType.INITIAL_PLAN,
        )
    except ValidationFailedError:
        # A proposal is already pending, or the plant cannot take one yet. The
        # confirmation itself succeeded and must not be undone by this.
        return None

    return {"request_id": str(request.id), "plant_id": str(plant_id)}


def _fallback_name(candidate: dict[str, Any]) -> str:
    """What to call a plant whose owner did not name it.

    The common name reads like something a person would say; the binomial is the
    honest fallback when the model returned no common name. Truncated to the
    column's limit, which a long common name can exceed.
    """
    return (candidate.get("common_name") or candidate["scientific_name"])[:120]


def _confirmation_path(current: PlantStatus, target: PlantStatus) -> list[PlantStatus]:
    """The states a plant moves through when its identification is confirmed.

    Re-identifying an already-ACTIVE plant is a single self-transition (A21): it
    keeps its care plan and its live tasks while the new species is researched.
    Everything else goes through IDENTIFIED, which is the state that records "a
    species has been confirmed" independently of whether knowledge exists yet.
    """
    if current is target:
        return [target]
    if current is PlantStatus.PENDING_IDENTIFICATION and target is not PlantStatus.IDENTIFIED:
        return [PlantStatus.IDENTIFIED, target]
    return [target]


def _status_after_confirm(plant: dict[str, Any], *, has_knowledge: bool) -> PlantStatus:
    """Where the plant lands after confirmation.

    A21: re-identifying a plant that is already ACTIVE leaves it ACTIVE. Sending
    it back to KNOWLEDGE_PENDING would cancel its live care tasks and take away a
    working plan while research runs, which is a worse outcome than briefly
    holding knowledge for the previous species.
    """
    current = PlantStatus(plant["status"])
    if current is PlantStatus.ACTIVE:
        return PlantStatus.ACTIVE

    return status_after_confirmation(
        PlantFacts(has_confirmed_species=True, has_published_knowledge=has_knowledge)
    )


def _start_research(species_id: UUID, user_id: UUID) -> dict[str, str] | None:
    """Open a research draft and queue the run, unless one is already in flight.

    A partial unique index allows only one open draft per species and language, so
    a second confirmation of the same new species joins the existing research
    rather than racing it — and joining means *not* queueing a second billable
    run, which is why this returns None in that case.

    Failure here is deliberately swallowed. The user has confirmed their plant and
    it is theirs; if research could not be started, the plant sits in
    KNOWLEDGE_PENDING and an administrator can retry (A17). Turning that into a
    500 would undo a confirmation that already succeeded.
    """
    admin = service_client()
    open_draft = rows(
        admin.table("knowledge_drafts")
        .select("id, status")
        .eq("species_id", str(species_id))
        .in_("status", [s.value for s in KnowledgeDraftStatus if is_open(s)])
        .limit(1)
        .execute()
    )
    if open_draft:
        return None

    try:
        run = knowledge_workflow.start_research(species_id=species_id, initiated_by=user_id)
    except Exception as exc:
        log.error(
            "identification.research_start_failed",
            species_id=str(species_id),
            error_type=type(exc).__name__,
        )
        return None

    return run.as_summary()
