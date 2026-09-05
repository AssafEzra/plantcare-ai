"""Care plan workflows (FINAL §12).

The shape of this module is the product rule it implements: **the agent proposes,
the user disposes.** Nothing here activates a plan except :func:`approve`, and
that only ever runs because a user pressed a button.

    propose  ->  a PROPOSED version, scheduling nothing
    approve  ->  ACTIVE, previous SUPERSEDED, its pending tasks cancelled (A5)
    reject   ->  REJECTED, the existing plan untouched

An environment change or a health finding calls :func:`propose` with a different
`source_type`. Neither can activate anything — that is the whole content of §12's
"Environment change → Care Agent review → Adjustment Proposal → User approval",
and it is why there is no code path from those events to an ACTIVE version.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.agents.care.agent import CareAgent
from app.agents.care.contract import CarePlanProposal, CarePlanRequest
from app.common.enums import (
    AgentStage,
    AgentType,
    CarePlanVersionSourceType,
    CarePlanVersionStatus,
)
from app.common.errors import NotFoundError, ValidationFailedError
from app.config.logging import get_logger
from app.infrastructure.supabase.client import service_client
from app.orchestration.services import agent_requests as requests_service
from app.orchestration.services import care_context
from app.repositories.base import Row, first_row, require_row, rows
from supabase import Client

log = get_logger(__name__)

VERSION_COLUMNS = (
    "id, care_plan_id, version_number, knowledge_version_id, status, "
    "professional_recommendations, operational_preferences, change_summary, "
    "source_type, created_by_user_id, created_at"
)

RULE_COLUMNS = (
    "id, care_plan_version_id, action_type, interval_days, "
    "preferred_time_local, preferred_weekday, instructions, is_active"
)


# --- starting a proposal --------------------------------------------------------


def start_proposal(
    client: Client,
    *,
    user_id: UUID,
    plant_id: UUID,
    reason: CarePlanVersionSourceType,
    note: str | None = None,
    idempotency_key: str | None = None,
) -> requests_service.AgentRequest:
    """Validate and queue. Does not run the agent."""
    plan = ensure_plan(client, user_id=user_id, plant_id=plant_id)

    if reason is CarePlanVersionSourceType.OPERATIONAL_ADJUSTMENT:
        # An operational adjustment is a user edit, not a research question. It
        # has its own endpoint, is deterministic, and must not spend a model call
        # - routing it through the agent would also let the model rewrite the
        # professional recommendations, which FINAL §12 forbids.
        raise ValidationFailedError("שינוי תפעולי אינו נוצר על ידי הסוכן.")

    if _pending_proposal(client, plan["id"]):
        # Two open proposals for one plant is a choice the user did not ask to
        # make, and approving one would silently orphan the other.
        raise ValidationFailedError("כבר קיימת הצעה שממתינה לאישור עבור הצמח הזה.")

    return requests_service.create_or_replay(
        client,
        user_id=user_id,
        plant_id=plant_id,
        agent_type=AgentType.CARE,
        payload={"plant_id": str(plant_id), "reason": reason.value, "note": note},
        idempotency_key=idempotency_key,
    )


def execute_proposal(
    *,
    request_id: UUID,
    user_id: UUID,
    plant_id: UUID,
    reason: CarePlanVersionSourceType,
    note: str | None,
    access_token: str,
    agent: CareAgent,
) -> None:
    """Build the context, ask the agent, store a PROPOSED version.

    The context is assembled through the **user's** client so RLS applies; the
    version is written through it too. Only `agent_requests` bookkeeping uses the
    service role, and that is admin-only telemetry.
    """
    from app.infrastructure.supabase.client import user_client

    client = user_client(access_token)

    try:
        requests_service.mark_stage(request_id, AgentStage.CONTEXT_LOADED.value)
        context, knowledge_version_id = care_context.build(client, plant_id=plant_id)
        plan = ensure_plan(client, user_id=user_id, plant_id=plant_id)
        current = active_version(client, plan["id"])

        requests_service.mark_stage(request_id, AgentStage.ANALYZING.value)
        proposal = agent.generate_plan(
            CarePlanRequest(
                context=context,
                reason=reason,
                note=note,
                current_rules=_rule_payloads(client, current["id"]) if current else [],
            ),
            request_id=request_id,
        )

        requests_service.mark_stage(request_id, AgentStage.PREPARING_RESULT.value)
        version = _store_proposal(
            client,
            user_id=user_id,
            plan_id=plan["id"],
            knowledge_version_id=knowledge_version_id,
            reason=reason,
            proposal=proposal,
        )

        requests_service.mark_succeeded(
            request_id,
            {
                "care_plan_version_id": version["id"],
                "version_number": version["version_number"],
                "rules": len(proposal.rules),
                "missing_context": proposal.missing_context,
            },
        )
    except Exception:
        # FINAL §25. Nothing partial survives: the version and its rules are
        # written in one call each, after the agent has already succeeded, so a
        # failure before that point leaves no row at all.
        log.exception("care.proposal_failed", request_id=str(request_id))
        requests_service.mark_failed(request_id, "AGENT_FAILED")
        raise


def _store_proposal(
    client: Client,
    *,
    user_id: UUID,
    plan_id: str,
    knowledge_version_id: str | None,
    reason: CarePlanVersionSourceType,
    proposal: CarePlanProposal,
) -> Row:
    next_number = _next_version_number(client, plan_id)

    version = require_row(
        client.table("care_plan_versions")
        .insert(
            {
                "care_plan_id": plan_id,
                "version_number": next_number,
                "knowledge_version_id": knowledge_version_id,
                "status": CarePlanVersionStatus.PROPOSED.value,
                "professional_recommendations": proposal.recommendations.model_dump(),
                # A20: recorded with the proposal so the card can show what would
                # have made the plan better. The MVP asks no questions.
                "operational_preferences": {"missing_context": proposal.missing_context},
                # A CHECK requires a change_summary on any version after the
                # first, so a model that omitted one gets a factual fallback
                # rather than failing the insert.
                "change_summary": (
                    proposal.change_summary
                    or (None if next_number == 1 else f"עודכן עקב {reason.value}.")
                ),
                "source_type": reason.value,
                "created_by_user_id": str(user_id),
            }
        )
        .execute()
    )

    if proposal.rules:
        client.table("care_rules").insert(
            [
                {
                    "care_plan_version_id": version["id"],
                    "action_type": rule.action_type.value,
                    "interval_days": rule.interval_days,
                    "preferred_time_local": rule.preferred_time_local.isoformat(),
                    "preferred_weekday": (
                        rule.preferred_weekday.value if rule.preferred_weekday else None
                    ),
                    "instructions": rule.instructions,
                }
                for rule in proposal.rules
            ]
        ).execute()

    return version


# --- approving and rejecting ----------------------------------------------------


def approve(client: Client, *, version_id: UUID) -> dict[str, Any]:
    """The user approves a proposal. One transaction (migration 0013).

    Supersede, activate, repoint, cancel the old version's pending tasks. Done
    from Python these would be four round trips, and the unique index on the
    ACTIVE status makes the ordering load-bearing: a failure between supersede
    and activate leaves a plant with no active plan, which stops it being cared
    for silently.
    """
    version = get_version(client, version_id)
    if version["status"] != CarePlanVersionStatus.PROPOSED.value:
        raise ValidationFailedError("רק הצעה שממתינה לאישור ניתנת לאישור.")

    activated = require_row(
        client.rpc("activate_care_plan_version", {"p_version_id": str(version_id)}).execute()
    )

    log.info(
        "care.plan_activated",
        version_id=str(version_id),
        version_number=activated["version_number"],
    )

    return {
        "version_id": activated["id"],
        "version_number": activated["version_number"],
        "status": activated["status"],
        "source_type": activated["source_type"],
    }


def reject(client: Client, *, version_id: UUID, note: str | None = None) -> Row:
    """Decline a proposal. The existing plan is untouched.

    Rejecting is not a failure state and produces no retry: the user looked at a
    proposal and said no, and the plan they already have keeps running.
    """
    version = get_version(client, version_id)
    if version["status"] != CarePlanVersionStatus.PROPOSED.value:
        raise ValidationFailedError("רק הצעה שממתינה לאישור ניתנת לדחייה.")

    changes: dict[str, Any] = {"status": CarePlanVersionStatus.REJECTED.value}
    if note:
        changes["change_summary"] = note.strip()[:500]

    return require_row(
        client.table("care_plan_versions").update(changes).eq("id", str(version_id)).execute()
    )


# --- operational adjustment -----------------------------------------------------


def operational_adjustment(
    client: Client,
    *,
    user_id: UUID,
    version_id: UUID,
    operational_preferences: dict[str, Any],
    change_summary: str,
) -> dict[str, Any]:
    """The user changes frequency, time or reminder preference (FINAL §12).

    No model call. This is a deterministic edit of operational parameters, and
    routing it through the agent would both cost money and give the model an
    opportunity to rewrite advice the user is not allowed to edit.

    The professional recommendations are copied **byte-identical** from the source
    version. That is the whole guarantee of §12's "professional recommendation
    content is not directly editable", and it is asserted by a test that compares
    the two blobs rather than trusting this line.
    """
    source = get_version(client, version_id)
    if source["status"] not in {
        CarePlanVersionStatus.ACTIVE.value,
        CarePlanVersionStatus.PROPOSED.value,
    }:
        raise ValidationFailedError("ניתן להתאים רק תוכנית פעילה או הצעה פתוחה.")

    if not change_summary.strip():
        raise ValidationFailedError("יש לתאר את השינוי.")

    plan_id = source["care_plan_id"]
    new_version = require_row(
        client.table("care_plan_versions")
        .insert(
            {
                "care_plan_id": plan_id,
                "version_number": _next_version_number(client, plan_id),
                "knowledge_version_id": source.get("knowledge_version_id"),
                "status": CarePlanVersionStatus.PROPOSED.value,
                # Verbatim. Not regenerated, not re-serialised through a model.
                "professional_recommendations": source["professional_recommendations"],
                "operational_preferences": operational_preferences,
                "change_summary": change_summary.strip()[:500],
                "source_type": CarePlanVersionSourceType.OPERATIONAL_ADJUSTMENT.value,
                "created_by_user_id": str(user_id),
            }
        )
        .execute()
    )

    _copy_rules(
        client,
        source_version_id=source["id"],
        target_version_id=new_version["id"],
        overrides=operational_preferences,
    )

    return {
        "version_id": new_version["id"],
        "version_number": new_version["version_number"],
        "status": new_version["status"],
    }


def _copy_rules(
    client: Client,
    *,
    source_version_id: str,
    target_version_id: str,
    overrides: dict[str, Any],
) -> None:
    """Carry the rules across, applying the user's operational overrides.

    Overrides are keyed by action type — `{"WATERING": {"interval_days": 10}}` —
    so a user changing their watering frequency does not disturb the fertilising
    rule. An override naming an unknown action type is ignored rather than
    creating a rule the plan never had; adding an action is a plan change, which
    is a proposal, not an adjustment.
    """
    for rule in rows(
        client.table("care_rules")
        .select(RULE_COLUMNS)
        .eq("care_plan_version_id", source_version_id)
        .execute()
    ):
        override = overrides.get(rule["action_type"]) or {}
        client.table("care_rules").insert(
            {
                "care_plan_version_id": target_version_id,
                "action_type": rule["action_type"],
                "interval_days": override.get("interval_days", rule["interval_days"]),
                "preferred_time_local": override.get(
                    "preferred_time_local", rule["preferred_time_local"]
                ),
                "preferred_weekday": override.get(
                    "preferred_weekday", rule.get("preferred_weekday")
                ),
                "instructions": rule.get("instructions"),
                "is_active": override.get("is_active", rule.get("is_active", True)),
            }
        ).execute()


# --- reads ----------------------------------------------------------------------


def ensure_plan(client: Client, *, user_id: UUID, plant_id: UUID) -> Row:
    """The plant's care plan, created on first use.

    `care_plans` is one row per plant and holds no content of its own — it exists
    to give the versions something to hang off and to carry `active_version_id`.
    Creating it lazily keeps plant creation free of it.
    """
    existing = first_row(
        client.table("care_plans")
        .select("id, plant_id, active_version_id")
        .eq("plant_id", str(plant_id))
        .execute()
    )
    if existing:
        return existing

    return require_row(
        client.table("care_plans")
        .insert({"user_id": str(user_id), "plant_id": str(plant_id)})
        .execute()
    )


def get_version(client: Client, version_id: UUID) -> Row:
    found = first_row(
        client.table("care_plan_versions")
        .select(VERSION_COLUMNS)
        .eq("id", str(version_id))
        .execute()
    )
    if found is None:
        raise NotFoundError("גרסת התוכנית לא נמצאה.")
    return found


def active_version(client: Client, plan_id: str) -> Row | None:
    return first_row(
        client.table("care_plan_versions")
        .select(VERSION_COLUMNS)
        .eq("care_plan_id", plan_id)
        .eq("status", CarePlanVersionStatus.ACTIVE.value)
        .limit(1)
        .execute()
    )


def plan_for_plant(client: Client, *, plant_id: UUID) -> dict[str, Any] | None:
    """The plant's active plan with its rules, or None if nothing is active yet."""
    plan = first_row(
        client.table("care_plans")
        .select("id, plant_id, active_version_id")
        .eq("plant_id", str(plant_id))
        .execute()
    )
    if plan is None:
        return None

    version = active_version(client, plan["id"])
    if version is None:
        return None

    return {
        **version,
        "rules": rows(
            client.table("care_rules")
            .select(RULE_COLUMNS)
            .eq("care_plan_version_id", version["id"])
            .order("action_type")
            .execute()
        ),
    }


def proposals_for_plant(client: Client, *, plant_id: UUID) -> list[Row]:
    """Open proposals, newest first, each with the rules it would install."""
    plan = first_row(
        client.table("care_plans").select("id").eq("plant_id", str(plant_id)).execute()
    )
    if plan is None:
        return []

    proposals = rows(
        client.table("care_plan_versions")
        .select(VERSION_COLUMNS)
        .eq("care_plan_id", plan["id"])
        .eq("status", CarePlanVersionStatus.PROPOSED.value)
        .order("version_number", desc=True)
        .execute()
    )

    for proposal in proposals:
        proposal["rules"] = rows(
            client.table("care_rules")
            .select(RULE_COLUMNS)
            .eq("care_plan_version_id", proposal["id"])
            .order("action_type")
            .execute()
        )
    return proposals


def _pending_proposal(client: Client, plan_id: str) -> Row | None:
    return first_row(
        client.table("care_plan_versions")
        .select("id")
        .eq("care_plan_id", plan_id)
        .eq("status", CarePlanVersionStatus.PROPOSED.value)
        .limit(1)
        .execute()
    )


def _next_version_number(client: Client, plan_id: str) -> int:
    latest = first_row(
        client.table("care_plan_versions")
        .select("version_number")
        .eq("care_plan_id", plan_id)
        .order("version_number", desc=True)
        .limit(1)
        .execute()
    )
    return (latest["version_number"] + 1) if latest else 1


def _rule_payloads(client: Client, version_id: str) -> list[dict[str, Any]]:
    return [
        {
            "action_type": rule["action_type"],
            "interval_days": rule["interval_days"],
            "preferred_time_local": rule["preferred_time_local"],
            "preferred_weekday": rule.get("preferred_weekday"),
        }
        for rule in rows(
            client.table("care_rules")
            .select(RULE_COLUMNS)
            .eq("care_plan_version_id", version_id)
            .execute()
        )
    ]


# --- the deferred fan-out hook (PR 15) ------------------------------------------


def queue_initial_plans(species_id: UUID, *, executor, agent: CareAgent) -> int:
    """Queue an INITIAL_PLAN proposal for every plant released by a publication.

    A3 and A4 together: publishing knowledge moves a plant to ACTIVE, and an
    ACTIVE plant with no care plan has nothing to schedule. PR 15 deliberately
    stopped at the status change, because a QUEUED agent request that nothing
    could execute would have sat in the admin monitoring view looking like a stuck
    job. Now that the Care Agent exists, this closes the gap.

    Runs under the service role: the plants belong to other users and the trigger
    is an administrator's action, so there is no user JWT in scope. Each plant's
    own access token is unavailable here, which is why the proposal is created
    with the service client rather than the owner's - the row still carries their
    `user_id`, so RLS shows it to them and nobody else.
    """
    admin = service_client()
    released = rows(
        admin.table("plants")
        .select("id, user_id")
        .eq("species_id", str(species_id))
        .eq("status", "ACTIVE")
        .execute()
    )

    queued = 0
    for plant in released:
        plan = first_row(
            admin.table("care_plans").select("id").eq("plant_id", plant["id"]).execute()
        )
        if plan and _pending_proposal(admin, plan["id"]):
            continue
        if plan and active_version(admin, plan["id"]):
            # Already has a working plan - a re-identification proposal is a
            # different flow with a different source_type.
            continue

        try:
            request = start_proposal(
                admin,
                user_id=UUID(plant["user_id"]),
                plant_id=UUID(plant["id"]),
                reason=CarePlanVersionSourceType.INITIAL_PLAN,
            )
        except ValidationFailedError:
            continue

        executor.submit(
            execute_proposal_as_service,
            request_id=request.id,
            user_id=UUID(plant["user_id"]),
            plant_id=UUID(plant["id"]),
            reason=CarePlanVersionSourceType.INITIAL_PLAN,
            note=None,
            agent=agent,
        )
        queued += 1

    log.info("care.initial_plans_queued", species_id=str(species_id), queued=queued)
    return queued


def execute_proposal_as_service(
    *,
    request_id: UUID,
    user_id: UUID,
    plant_id: UUID,
    reason: CarePlanVersionSourceType,
    note: str | None,
    agent: CareAgent,
) -> None:
    """`execute_proposal` for work nobody is logged in for.

    The fan-out runs on an administrator's publish, minutes or days after the
    owner last had a session, so there is no access token to act as them. The rows
    still carry the owner's `user_id` and RLS still shows the proposal only to
    them; what changes is who writes it, not who owns it.
    """
    admin = service_client()

    try:
        requests_service.mark_stage(request_id, AgentStage.CONTEXT_LOADED.value)
        context, knowledge_version_id = care_context.build(admin, plant_id=plant_id)
        plan = ensure_plan(admin, user_id=user_id, plant_id=plant_id)

        requests_service.mark_stage(request_id, AgentStage.ANALYZING.value)
        proposal = agent.generate_plan(
            CarePlanRequest(context=context, reason=reason, note=note),
            request_id=request_id,
        )

        requests_service.mark_stage(request_id, AgentStage.PREPARING_RESULT.value)
        version = _store_proposal(
            admin,
            user_id=user_id,
            plan_id=plan["id"],
            knowledge_version_id=knowledge_version_id,
            reason=reason,
            proposal=proposal,
        )
        requests_service.mark_succeeded(
            request_id,
            {"care_plan_version_id": version["id"], "rules": len(proposal.rules)},
        )
    except Exception:
        log.exception("care.initial_plan_failed", request_id=str(request_id))
        requests_service.mark_failed(request_id, "AGENT_FAILED")
