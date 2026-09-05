"""Health check workflow (FINAL §16).

The order of operations here is the specification's prose, and it differs from
its own diagram (A28). The diagram puts the care proposal and the user's approval
*before* the assessment is saved, which would mean a check is only recorded once
someone agrees to a care change — and never recorded when they decline one. The
prose says "Every successful Health Check updates the Plant's current health
status." The prose is implemented:

    assess -> save -> (optionally) raise a care proposal

Saving happens through one RPC. The 1-4 image constraint is deferred and checked
at commit, and PostgREST gives every call its own transaction, so the assessment
and its images cannot be written by two separate requests.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from app.agents.health.agent import HealthAgent
from app.agents.health.contract import (
    MAX_IMAGES,
    MIN_IMAGES,
    HealthContext,
    HealthRequest,
    HealthResult,
)
from app.common.enums import (
    AgentStage,
    AgentType,
    HealthStatus,
)
from app.common.errors import NotFoundError, ValidationFailedError
from app.config.logging import get_logger
from app.config.settings import get_settings
from app.domain.rules import health_trend
from app.domain.services import image_quality, knowledge_content
from app.infrastructure.ai.provider import ImageInput
from app.infrastructure.storage import plant_images as storage
from app.infrastructure.supabase.client import service_client, user_client
from app.orchestration.services import agent_requests as requests_service
from app.repositories import plants as plants_repo
from app.repositories.base import Row, first_row, require_row, rows
from supabase import Client

log = get_logger(__name__)

HISTORY_LIMIT = 5


def start(
    client: Client,
    *,
    user_id: UUID,
    plant_id: UUID,
    image_ids: list[UUID],
    user_note: str | None,
    idempotency_key: str | None,
) -> requests_service.AgentRequest:
    """Validate and queue. Does not run the agent."""
    plant = plants_repo.find(client, plant_id, owner_id=user_id)
    if plant is None:
        raise NotFoundError("הצמח לא נמצא.")

    if not MIN_IMAGES <= len(image_ids) <= MAX_IMAGES:
        raise ValidationFailedError(f"יש לצרף בין {MIN_IMAGES} ל-{MAX_IMAGES} תמונות.")

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
        agent_type=AgentType.HEALTH,
        payload={
            "image_ids": sorted(str(i) for i in image_ids),
            "user_note": (user_note or "").strip() or None,
        },
        idempotency_key=idempotency_key,
    )


def execute(
    *,
    request_id: UUID,
    user_id: UUID,
    plant_id: UUID,
    image_ids: list[UUID],
    user_note: str | None,
    access_token: str,
    agent: HealthAgent,
) -> None:
    """Run the check and save what it found.

    An `UNKNOWN` result is saved like any other (FINAL §16). It is not an
    authoritative finding — it carries no confidence and no issues, and a CHECK
    constraint enforces both — so §25 is satisfied by the shape of the row rather
    than by refusing to write one.
    """
    client = user_client(access_token)
    admin = service_client()

    try:
        requests_service.mark_stage(request_id, AgentStage.IMAGES_RECEIVED.value)
        images, warnings = _load_images(admin, plant_id, image_ids)

        requests_service.mark_stage(request_id, AgentStage.CONTEXT_LOADED.value)
        context = _build_context(client, plant_id=plant_id)

        requests_service.mark_stage(request_id, AgentStage.ANALYZING.value)
        result = agent.assess(
            HealthRequest(
                images=images,
                context=context,
                user_note=user_note,
                image_warnings=warnings,
            ),
            request_id=request_id,
        )

        requests_service.mark_stage(request_id, AgentStage.PREPARING_RESULT.value)
        assessment = save(
            client,
            plant_id=plant_id,
            image_ids=image_ids,
            result=result,
            user_note=user_note,
            agent_request_id=request_id,
        )

        requests_service.mark_succeeded(
            request_id,
            {
                "health_assessment_id": assessment["id"],
                "overall_status": assessment["overall_status"],
                "trend": assessment["trend"],
                "requires_care_plan_adjustment": result.wants_care_adjustment,
            },
        )
    except Exception:
        # FINAL §25: nothing partial survives. The RPC is one transaction, so a
        # failure before it leaves no row and a failure inside it rolls back.
        log.exception("health.execute_failed", request_id=str(request_id))
        requests_service.mark_failed(request_id, "AGENT_FAILED")
        raise


def save(
    client: Client,
    *,
    plant_id: UUID,
    image_ids: list[UUID],
    result: HealthResult,
    user_note: str | None,
    agent_request_id: UUID | None = None,
) -> Row:
    """Persist the assessment and everything it produced, in one transaction.

    The trend is computed here, from stored history (A11). It is arithmetic over
    rows the model never saw, and asking a model shown one photograph whether a
    plant is improving would get an answer about that photograph.
    """
    previous = [
        row["overall_status"]
        for row in rows(
            client.table("health_assessments")
            .select("overall_status, created_at")
            .eq("plant_id", str(plant_id))
            .order("created_at", desc=True)
            .limit(HISTORY_LIMIT)
            .execute()
        )
    ]
    trend = health_trend.trend_from([result.overall_status.value, *previous])

    return require_row(
        client.rpc(
            "save_health_assessment",
            {
                "p_plant_id": str(plant_id),
                "p_overall_status": result.overall_status.value,
                "p_trend": trend.value,
                "p_image_ids": [str(i) for i in image_ids],
                "p_agent_request_id": str(agent_request_id) if agent_request_id else None,
                "p_confidence_level": (
                    result.confidence_level.value if result.confidence_level else None
                ),
                "p_requires_attention": result.requires_attention,
                "p_user_note": user_note,
                "p_insufficient_reason": result.insufficient_information_reason,
                "p_observations": [o.model_dump(mode="json") for o in result.observations],
                "p_issues": [i.model_dump(mode="json") for i in result.possible_issues],
                "p_recommendations": [r.model_dump(mode="json") for r in result.recommendations],
                "p_sources": [],
                "p_raw_result": None,
            },
        ).execute()
    )


def _load_images(
    admin: Client, plant_id: UUID, image_ids: list[UUID]
) -> tuple[list[ImageInput], list[str]]:
    """Fetch the processed derivatives and measure their quality (A25).

    The quality gate **warns**; it never rejects. A blurred photograph of a plant
    someone is worried about should reach the agent and produce an honest
    `UNKNOWN`, not a refusal telling them to go and take a better one.
    """
    from io import BytesIO

    from PIL import Image

    records = rows(
        admin.table("plant_images")
        .select("id, storage_path_processed, storage_path_original")
        .eq("plant_id", str(plant_id))
        .in_("id", [str(i) for i in image_ids])
        .execute()
    )

    images: list[ImageInput] = []
    reports: list[image_quality.QualityReport] = []

    for record in records:
        path = record.get("storage_path_processed") or record["storage_path_original"]
        url = storage.admin_signed_url(path)
        if not url:
            continue

        response = httpx.get(url, timeout=30, follow_redirects=True)
        if response.status_code != 200:
            continue

        images.append(ImageInput(data=response.content, mime_type="image/jpeg"))
        try:
            with Image.open(BytesIO(response.content)) as decoded:
                reports.append(image_quality.assess_image_quality(decoded))
        except Exception as exc:  # pragma: no cover - the pipeline already decoded it
            log.info("health.quality_check_skipped", error_type=type(exc).__name__)

    if not images:
        raise ValidationFailedError("לא הצלחנו לטעון את התמונות.")

    return images, image_quality.summarise(reports)


def _build_context(client: Client, *, plant_id: UUID) -> HealthContext:
    """The seven inputs FINAL §16 lists, and nothing else."""
    plant = first_row(
        client.table("plants")
        .select("id, name, species_id, current_health_status")
        .eq("id", str(plant_id))
        .execute()
    )
    if plant is None:
        raise NotFoundError("הצמח לא נמצא.")

    species: Row = {}
    knowledge_sections: dict[str, str] = {}
    if plant.get("species_id"):
        species = (
            first_row(
                client.table("species")
                .select("scientific_name, common_name")
                .eq("id", plant["species_id"])
                .execute()
            )
            or {}
        )
        settings = get_settings()
        version = first_row(
            client.table("knowledge_versions")
            .select("content")
            .eq("species_id", plant["species_id"])
            .eq("language", settings.default_content_language)
            .eq("is_current", True)
            .limit(1)
            .execute()
        )
        if version:
            # Read through the shared reader: versions published before A16 store
            # sections as plain strings, and those rows are immutable.
            knowledge_sections = knowledge_content.as_sections(version.get("content"))

    environment = (
        first_row(
            client.table("plant_environments")
            .select(
                "location_type, light_level, light_direction, "
                "temperature_c, humidity_percent, room, notes"
            )
            .eq("plant_id", str(plant_id))
            .execute()
        )
        or {}
    )

    return HealthContext(
        plant_name=plant.get("name"),
        scientific_name=species.get("scientific_name") or "לא ידוע",
        common_name=species.get("common_name"),
        knowledge_sections=knowledge_sections,
        environment={k: v for k, v in environment.items() if v is not None},
        previous_assessments=_previous(client, plant_id),
        care_history=_care_history(client, plant_id),
        current_care_rules=_care_rules(client, plant_id),
    )


def _previous(client: Client, plant_id: UUID) -> list[dict[str, Any]]:
    return [
        {
            "assessed_at": row.get("created_at"),
            "status": row.get("overall_status"),
            "requires_attention": row.get("requires_attention"),
        }
        for row in rows(
            client.table("health_assessments")
            .select("created_at, overall_status, requires_attention")
            .eq("plant_id", str(plant_id))
            .order("created_at", desc=True)
            .limit(HISTORY_LIMIT)
            .execute()
        )
    ]


def _care_history(client: Client, plant_id: UUID) -> list[dict[str, Any]]:
    return [
        {"event_type": row.get("event_type"), "event_at": row.get("event_at")}
        for row in rows(
            client.table("care_events")
            .select("event_type, event_at")
            .eq("plant_id", str(plant_id))
            .order("event_at", desc=True)
            .limit(HISTORY_LIMIT)
            .execute()
        )
    ]


def _care_rules(client: Client, plant_id: UUID) -> list[dict[str, Any]]:
    plan = first_row(
        client.table("care_plans")
        .select("active_version_id")
        .eq("plant_id", str(plant_id))
        .execute()
    )
    if not plan or not plan.get("active_version_id"):
        return []

    return [
        {"action_type": rule["action_type"], "interval_days": rule["interval_days"]}
        for rule in rows(
            client.table("care_rules")
            .select("action_type, interval_days")
            .eq("care_plan_version_id", plan["active_version_id"])
            .eq("is_active", True)
            .execute()
        )
    ]


# --- reads ----------------------------------------------------------------------


def get_assessment(client: Client, assessment_id: UUID) -> dict[str, Any]:
    """One assessment with everything it produced."""
    assessment = first_row(
        client.table("health_assessments")
        .select(
            "id, plant_id, overall_status, confidence_level, trend, user_note, "
            "requires_attention, insufficient_information_reason, created_at"
        )
        .eq("id", str(assessment_id))
        .execute()
    )
    if assessment is None:
        raise NotFoundError("הבדיקה לא נמצאה.")

    return {
        **assessment,
        "observations": rows(
            client.table("health_observations")
            .select("id, observation_text, confidence_level")
            .eq("health_assessment_id", str(assessment_id))
            .execute()
        ),
        "possible_issues": rows(
            client.table("health_issues")
            .select("id, issue_name, severity, confidence_level, evidence")
            .eq("health_assessment_id", str(assessment_id))
            .order("severity", desc=True)
            .execute()
        ),
        "recommendations": rows(
            client.table("health_recommendations")
            .select("id, recommendation_text, priority, requires_care_plan_adjustment")
            .eq("health_assessment_id", str(assessment_id))
            .order("priority")
            .execute()
        ),
        "sources": rows(
            client.table("health_assessment_sources")
            .select("id, source_class, title, url, publisher")
            .eq("health_assessment_id", str(assessment_id))
            .execute()
        ),
    }


def history(client: Client, *, plant_id: UUID, limit: int = 20) -> list[Row]:
    return rows(
        client.table("health_assessments")
        .select("id, overall_status, confidence_level, trend, requires_attention, created_at")
        .eq("plant_id", str(plant_id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )


def status_of(client: Client, plant_id: UUID) -> HealthStatus:
    plant = first_row(
        client.table("plants").select("current_health_status").eq("id", str(plant_id)).execute()
    )
    return HealthStatus((plant or {}).get("current_health_status") or "UNKNOWN")
