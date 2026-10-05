"""Care intensity, as the interface needs to see it.

The scheduling itself is in `domain/rules/recurrence.py` and `scheduler.py`. This
module answers the two questions the screens ask: which schedule a plant actually
follows, and which of its tasks that schedule would leave at most half as often as
the plan asks (`recurrence.needs_warning`).
"""

from __future__ import annotations

from typing import Any

from app.common.enums import CareIntensity, Weekday
from app.domain.rules import recurrence
from app.orchestration.services.scheduler import OwnerCareSettings
from app.orchestration.workflows import care as care_workflow
from app.repositories.base import Row, rows
from supabase import Client


def warnings_for(rules: list[Row], schedule: recurrence.CareSchedule) -> list[dict[str, Any]]:
    """The active rules this schedule would leave at most half as often."""
    gap = recurrence.max_gap_days(schedule.care_days)
    return [
        {
            "action_type": rule["action_type"],
            "interval_days": int(rule["interval_days"]),
            "max_gap_days": gap,
        }
        for rule in rules
        if rule.get("is_active", True)
        and recurrence.needs_warning(int(rule["interval_days"]), schedule)
    ]


def plant_summary(
    owner: OwnerCareSettings, *, plant_override: str | None, rules: list[Row]
) -> dict[str, Any]:
    """What the plant card shows: the override, what it resolves to, and any warning."""
    schedule = owner.schedule_for(plant_override)
    return {
        "override": plant_override,
        "owner_intensity": owner.intensity or CareIntensity.HIGH.value,
        "effective": schedule.intensity.value,
        "care_days": [day.value for day in schedule.care_days],
        "warnings": warnings_for(rules, schedule),
    }


def impact(
    client: Client,
    *,
    user_id: str,
    intensity: CareIntensity,
    care_day_low: Weekday,
    care_days_medium: list[Weekday],
) -> list[dict[str, Any]]:
    """Plants a *proposed* setting would warn about, before the user saves it.

    Plants pinned to their own level are left out: the setting does not reach them.
    """
    schedule = recurrence.care_schedule(
        profile_intensity=intensity,
        care_day_low=care_day_low,
        care_days_medium=care_days_medium,
    )
    if not schedule.groups:
        return []

    plants = rows(
        client.table("plants")
        .select("id, name, status, care_intensity")
        .eq("user_id", str(user_id))
        .eq("status", "ACTIVE")
        .execute()
    )

    affected: list[dict[str, Any]] = []
    for plant in plants:
        if plant.get("care_intensity"):
            continue
        plan = care_workflow.plan_for_plant(client, plant_id=plant["id"])
        if not plan:
            continue
        warned = warnings_for(plan.get("rules") or [], schedule)
        if warned:
            affected.append(
                {"plant_id": plant["id"], "plant_name": plant.get("name"), "tasks": warned}
            )
    return affected
