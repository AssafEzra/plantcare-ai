"""The scheduler: turning care rules into dated tasks, and tasks into events.

`domain/rules/recurrence.py` answers *when*; this module does the reading and
writing around those answers. Keeping the arithmetic pure and the I/O here is
what lets the DST and anchoring cases be tested without a database, and it is the
shape FINAL §1.4 asks for — "deterministic software where AI adds no value".

Three operations, and the invariants each protects:

* :func:`materialise` — create the near-term tasks. At most one PENDING task per
  rule, which the database also enforces, so a buggy run cannot build a backlog.
* :func:`sweep_overdue` — move past-due tasks to OVERDUE, and retire ones nobody
  is going to do (A9), writing a MISSED event and scheduling the next occurrence.
* :func:`complete` / :func:`skip` — record what happened as an immutable event
  and advance the schedule (A8).

`now_utc` is a parameter everywhere. The tick passes the real clock; a test
passes whatever moment it wants to examine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.common.enums import CareEventType, CareTaskStatus
from app.common.errors import DuplicateActionError, NotFoundError, ValidationFailedError
from app.config.logging import get_logger
from app.config.settings import get_settings
from app.domain.rules import recurrence
from app.repositories.base import Row, first_row, require_row, rows
from supabase import Client

log = get_logger(__name__)

TASK_COLUMNS = (
    "id, user_id, plant_id, care_rule_id, due_at_utc, status, "
    "overdue_since, completed_at, created_at"
)


@dataclass(frozen=True)
class TickResult:
    """What one scheduler run did. Returned so the tick endpoint can report it."""

    materialised: int = 0
    marked_overdue: int = 0
    missed: int = 0

    def merged(self, other: TickResult) -> TickResult:
        return TickResult(
            materialised=self.materialised + other.materialised,
            marked_overdue=self.marked_overdue + other.marked_overdue,
            missed=self.missed + other.missed,
        )


def _rule_of(row: Row) -> recurrence.Rule:
    """A database row as the pure rule the domain understands."""
    from datetime import time

    from app.common.enums import Weekday

    raw_time = str(row.get("preferred_time_local") or "08:00")
    parsed = time.fromisoformat(raw_time if len(raw_time) > 5 else f"{raw_time}:00")
    weekday = row.get("preferred_weekday")

    return recurrence.Rule(
        interval_days=int(row["interval_days"]),
        preferred_time_local=parsed,
        preferred_weekday=Weekday(weekday) if weekday else None,
    )


def timezone_of(client: Client, user_id: str) -> str:
    profile = first_row(client.table("profiles").select("timezone").eq("id", user_id).execute())
    return (profile or {}).get("timezone") or get_settings().default_timezone


# --- materialisation ------------------------------------------------------------


def materialise(client: Client, *, now_utc: datetime, user_id: str | None = None) -> int:
    """Create near-term tasks for every active rule that has none pending.

    Idempotent by construction: a rule with a PENDING task is skipped, and the
    partial unique index refuses a second one even if two runs raced. That is why
    running the tick twice produces one task rather than two — a property the
    integration tests assert directly, because it is the difference between a
    reminder and a duplicate reminder.
    """
    created = 0

    for rule, plan_version, plant in _active_rules(client, user_id=user_id):
        if _pending_task_for(client, rule["id"]):
            continue

        timezone_name = timezone_of(client, plant["user_id"])
        domain_rule = _rule_of(rule)
        due = _next_occurrence(
            client,
            rule_row=rule,
            domain_rule=domain_rule,
            plan_version=plan_version,
            timezone_name=timezone_name,
            now_utc=now_utc,
        )

        if not recurrence.within_horizon(due, now_utc=now_utc):
            continue

        try:
            client.table("care_tasks").insert(
                {
                    "user_id": plant["user_id"],
                    "plant_id": plant["id"],
                    "care_rule_id": rule["id"],
                    "due_at_utc": due.isoformat(),
                    "status": CareTaskStatus.PENDING.value,
                }
            ).execute()
            created += 1
        except Exception as exc:
            # Almost certainly the one-PENDING-per-rule index, which means another
            # run got there first. That is the index doing its job, not an error.
            log.info(
                "scheduler.materialise_skipped",
                care_rule_id=rule["id"],
                error_type=type(exc).__name__,
            )

    return created


def _next_occurrence(
    client: Client,
    *,
    rule_row: Row,
    domain_rule: recurrence.Rule,
    plan_version: Row,
    timezone_name: str,
    now_utc: datetime,
) -> datetime:
    """When this rule is next due, from whatever happened last.

    A rule that has never produced an event uses :func:`recurrence.first_due`
    from the plan's activation, so an approved plan starts reminding today or
    tomorrow rather than after a full interval.
    """
    last = first_row(
        client.table("care_events")
        .select("event_type, event_at, care_task_id")
        .eq("plant_id", plan_version["plant_id"])
        .in_(
            "event_type",
            [CareEventType.DONE.value, CareEventType.SKIPPED.value, CareEventType.MISSED.value],
        )
        .order("event_at", desc=True)
        .limit(1)
        .execute()
    )

    if last is None:
        activated = parse_timestamp(plan_version.get("created_at")) or now_utc
        return recurrence.first_due(
            domain_rule, activated_at_utc=activated, timezone_name=timezone_name
        )

    event_at = parse_timestamp(last["event_at"]) or now_utc
    due_at = event_at
    if last.get("care_task_id"):
        task = first_row(
            client.table("care_tasks").select("due_at_utc").eq("id", last["care_task_id"]).execute()
        )
        due_at = parse_timestamp((task or {}).get("due_at_utc")) or event_at

    anchor = recurrence.anchor_for(
        CareEventType(last["event_type"]), due_at_utc=due_at, event_at_utc=event_at
    )
    due = recurrence.next_due(domain_rule, anchor_utc=anchor, timezone_name=timezone_name)

    # Never materialise an occurrence the sweep would retire on sight: that pair
    # of behaviours is a loop that writes a MISSED event on every tick.
    return recurrence.catch_up(domain_rule, due, now_utc=now_utc)


def _active_rules(client: Client, *, user_id: str | None = None) -> list[tuple[Row, Row, Row]]:
    """Every active rule of every active plan, with its version and plant.

    Read as three queries rather than one join because PostgREST embedding across
    four tables is hard to read and harder to change; the volumes here are one
    plan per plant and a handful of rules per plan.
    """
    plans_query = client.table("care_plans").select("id, plant_id, user_id, active_version_id")
    if user_id:
        plans_query = plans_query.eq("user_id", user_id)
    plans = [p for p in rows(plans_query.execute()) if p.get("active_version_id")]
    if not plans:
        return []

    plants = {
        plant["id"]: plant
        for plant in rows(
            client.table("plants")
            .select("id, user_id, status, name")
            .in_("id", [p["plant_id"] for p in plans])
            .execute()
        )
    }

    versions = {
        version["id"]: version
        for version in rows(
            client.table("care_plan_versions")
            .select("id, care_plan_id, created_at")
            .in_("id", [p["active_version_id"] for p in plans])
            .execute()
        )
    }

    found: list[tuple[Row, Row, Row]] = []
    for plan in plans:
        plant = plants.get(plan["plant_id"])
        version = versions.get(plan["active_version_id"])
        if plant is None or version is None:
            continue
        # An archived plant keeps its plan and its history but stops being
        # scheduled: reminding someone to water a plant they have put away is the
        # clearest possible sign the app is not paying attention.
        if plant.get("status") != "ACTIVE":
            continue

        version = {**version, "plant_id": plant["id"]}
        for rule in rows(
            client.table("care_rules")
            .select(
                "id, care_plan_version_id, action_type, interval_days, "
                "preferred_time_local, preferred_weekday, is_active"
            )
            .eq("care_plan_version_id", version["id"])
            .eq("is_active", True)
            .execute()
        ):
            found.append((rule, version, plant))

    return found


def _pending_task_for(client: Client, rule_id: str) -> Row | None:
    return first_row(
        client.table("care_tasks")
        .select("id")
        .eq("care_rule_id", rule_id)
        .eq("status", CareTaskStatus.PENDING.value)
        .limit(1)
        .execute()
    )


# --- the overdue sweep (A9) -----------------------------------------------------


def sweep_overdue(client: Client, *, now_utc: datetime, user_id: str | None = None) -> TickResult:
    """Move past-due tasks to OVERDUE, and retire the ones that have expired.

    The second half is A9: a plant left for a month must not greet its owner with
    thirty outstanding waterings. An expired task becomes a MISSED event — which
    is history, and belongs in the timeline — and the task is CANCELLED so the
    next recurrence can be scheduled. FINAL §13 is explicit that the next
    occurrence remains scheduled; missing one does not end the plan.
    """
    marked = 0
    missed = 0

    open_query = (
        client.table("care_tasks")
        .select(TASK_COLUMNS)
        .in_("status", [CareTaskStatus.PENDING.value, CareTaskStatus.OVERDUE.value])
    )
    if user_id:
        open_query = open_query.eq("user_id", user_id)

    for task in rows(open_query.execute()):
        due = parse_timestamp(task["due_at_utc"])
        if due is None or not recurrence.is_overdue(due_at_utc=due, now_utc=now_utc):
            continue

        rule_row = first_row(
            client.table("care_rules")
            .select("id, interval_days, preferred_time_local, preferred_weekday")
            .eq("id", task["care_rule_id"])
            .execute()
        )
        if rule_row is None:  # pragma: no cover - FK guarantees this
            continue
        domain_rule = _rule_of(rule_row)

        if recurrence.has_expired(domain_rule, due_at_utc=due, now_utc=now_utc):
            _record_missed(client, task, now_utc=now_utc)
            missed += 1
            continue

        if task["status"] == CareTaskStatus.PENDING.value:
            client.table("care_tasks").update(
                {
                    "status": CareTaskStatus.OVERDUE.value,
                    "overdue_since": now_utc.isoformat(),
                }
            ).eq("id", task["id"]).execute()
            marked += 1

    return TickResult(marked_overdue=marked, missed=missed)


def _record_missed(client: Client, task: Row, *, now_utc: datetime) -> None:
    """Retire an expired task: a MISSED event, then CANCELLED.

    The event is written first. If the update failed afterwards the task would be
    swept again and the event written twice, which is untidy; if the order were
    reversed a crash would lose the history entirely, and the timeline would show
    a task that simply vanished.

    `MISSED` is deliberately outside the one-action-per-task unique index (see
    migration 0007): it is written by this sweep rather than by the user, and must
    not consume the slot a later corrective DONE would need.
    """
    client.table("care_events").insert(
        {
            "user_id": task["user_id"],
            "plant_id": task["plant_id"],
            "care_task_id": task["id"],
            "event_type": CareEventType.MISSED.value,
            "event_at": now_utc.isoformat(),
        }
    ).execute()

    client.table("care_tasks").update({"status": CareTaskStatus.CANCELLED.value}).eq(
        "id", task["id"]
    ).execute()


# --- acting on a task -----------------------------------------------------------


def complete(
    client: Client, *, task_id: UUID, user_id: UUID, note: str | None = None
) -> dict[str, Any]:
    return _act(client, task_id=task_id, user_id=user_id, event_type=CareEventType.DONE, note=note)


def skip(
    client: Client, *, task_id: UUID, user_id: UUID, note: str | None = None
) -> dict[str, Any]:
    return _act(
        client, task_id=task_id, user_id=user_id, event_type=CareEventType.SKIPPED, note=note
    )


def _act(
    client: Client,
    *,
    task_id: UUID,
    user_id: UUID,
    event_type: CareEventType,
    note: str | None,
) -> dict[str, Any]:
    """Record what happened and advance the schedule.

    The immutable event comes first and is the authoritative record; the task
    status and the next occurrence follow from it. A duplicate is refused by a
    unique index rather than by a read-then-check, so two taps on a slow
    connection cannot both succeed.
    """
    task = first_row(
        client.table("care_tasks").select(TASK_COLUMNS).eq("id", str(task_id)).execute()
    )
    if task is None:
        raise NotFoundError("המשימה לא נמצאה.")

    if task["status"] in {CareTaskStatus.DONE.value, CareTaskStatus.SKIPPED.value}:
        raise DuplicateActionError()
    if task["status"] == CareTaskStatus.CANCELLED.value:
        raise ValidationFailedError("המשימה כבר אינה פעילה.")

    now = datetime.now(UTC)

    try:
        client.table("care_events").insert(
            {
                "user_id": str(user_id),
                "plant_id": task["plant_id"],
                "care_task_id": task["id"],
                "event_type": event_type.value,
                "event_at": now.isoformat(),
                "note": note,
            }
        ).execute()
    except Exception as exc:
        # The one-action-per-task index. API_CONTRACTS asks for a 409 on a
        # duplicate, and this is where it actually comes from.
        if "care_events_one_action_per_task" in str(exc):
            raise DuplicateActionError() from exc
        raise

    status = (
        CareTaskStatus.DONE.value
        if event_type is CareEventType.DONE
        else CareTaskStatus.SKIPPED.value
    )
    client.table("care_tasks").update(
        {
            "status": status,
            # A CHECK requires completed_at if and only if the status is DONE.
            "completed_at": now.isoformat() if event_type is CareEventType.DONE else None,
        }
    ).eq("id", task["id"]).execute()

    next_due = _schedule_next(client, task=task, event_type=event_type, event_at=now)

    return {
        "task_id": task["id"],
        "status": status,
        "next_due_at_utc": next_due.isoformat() if next_due else None,
    }


def _schedule_next(
    client: Client, *, task: Row, event_type: CareEventType, event_at: datetime
) -> datetime | None:
    """Create the following occurrence, if it is near enough to materialise.

    Written here rather than left to the next tick so that completing a task
    immediately shows the user when it comes round again. If it is beyond the
    horizon nothing is created and the tick will pick it up later — the horizon
    exists precisely so a yearly repotting task does not sit in the list for
    eleven months.
    """
    rule_row = first_row(
        client.table("care_rules")
        .select("id, interval_days, preferred_time_local, preferred_weekday, is_active")
        .eq("id", task["care_rule_id"])
        .execute()
    )
    if rule_row is None or not rule_row.get("is_active", True):
        return None

    due = parse_timestamp(task["due_at_utc"]) or event_at
    anchor = recurrence.anchor_for(event_type, due_at_utc=due, event_at_utc=event_at)
    upcoming = recurrence.next_due(
        _rule_of(rule_row),
        anchor_utc=anchor,
        timezone_name=timezone_of(client, task["user_id"]),
    )

    if not recurrence.within_horizon(upcoming, now_utc=event_at):
        return upcoming

    try:
        client.table("care_tasks").insert(
            {
                "user_id": task["user_id"],
                "plant_id": task["plant_id"],
                "care_rule_id": task["care_rule_id"],
                "due_at_utc": upcoming.isoformat(),
                "status": CareTaskStatus.PENDING.value,
            }
        ).execute()
    except Exception as exc:  # pragma: no cover - the index doing its job
        log.info("scheduler.next_task_exists", error_type=type(exc).__name__)

    return upcoming


# --- reads ----------------------------------------------------------------------


def tasks_for_user(
    client: Client,
    *,
    user_id: UUID,
    on_date: str | None = None,
    status: str | None = None,
    timezone_name: str | None = None,
) -> list[Row]:
    """Open tasks, optionally limited to one of the user's calendar days.

    "Today" is the *user's* today. Filtering on the UTC date would show the wrong
    day's work for the first three hours of every morning in Jerusalem.
    """
    query = (
        client.table("care_tasks")
        .select(TASK_COLUMNS)
        .eq("user_id", str(user_id))
        .order("due_at_utc")
    )

    if status:
        query = query.eq("status", status)
    else:
        query = query.in_("status", [CareTaskStatus.PENDING.value, CareTaskStatus.OVERDUE.value])

    if on_date:
        tz = timezone_name or timezone_of(client, str(user_id))
        day = (
            recurrence.local_date(datetime.now(UTC), tz)
            if on_date == "today"
            else datetime.fromisoformat(on_date).date()
        )
        start, end = recurrence.day_bounds_utc(day, tz)
        # Overdue work from previous days belongs on today's list: it is what the
        # user still has to do, and hiding it behind a date filter is how a task
        # gets forgotten.
        query = query.lt("due_at_utc", end.isoformat())
        if status == CareTaskStatus.PENDING.value:
            query = query.gte("due_at_utc", start.isoformat())

    return rows(query.execute())


def decorate_tasks(client: Client, tasks: list[Row]) -> list[Row]:
    """Attach the plant name and action type a task is meaningless without.

    Lives here rather than in a router because both the care-task list and the
    plant dashboard need it — and the dashboard shipped without it, rendering
    "**** · my plant" where a reminder should have been. A task row on its own is
    two foreign keys and a timestamp.
    """
    if not tasks:
        return []

    plants = {
        plant["id"]: plant
        for plant in rows(
            client.table("plants")
            .select("id, name")
            .in_("id", list({str(t["plant_id"]) for t in tasks}))
            .execute()
        )
    }
    care_rules = {
        rule["id"]: rule
        for rule in rows(
            client.table("care_rules")
            .select("id, action_type")
            .in_("id", list({str(t["care_rule_id"]) for t in tasks}))
            .execute()
        )
    }

    return [
        {
            **task,
            "plant_name": plants.get(str(task["plant_id"]), {}).get("name"),
            "action_type": care_rules.get(str(task["care_rule_id"]), {}).get("action_type"),
        }
        for task in tasks
    ]


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:  # pragma: no cover - PostgREST returns ISO-8601
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def require_task(client: Client, task_id: UUID) -> Row:
    return require_row(
        client.table("care_tasks").select(TASK_COLUMNS).eq("id", str(task_id)).execute(),
        NotFoundError("המשימה לא נמצאה."),
    )
