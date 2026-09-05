"""Plant history: one timeline out of five tables (FINAL §19).

§19 lists eleven kinds of entry, and they do not live together. Care events,
health assessments, identifications and care plan versions each have their own
table, because each carries fields the others do not — and `system_events` holds
only the kinds with no table of their own (A22).

The alternative would be writing a `system_events` row alongside every care
action, which is how a timeline ends up disagreeing with the data it describes:
two writes, one transaction boundary, and eventually a care event with no
timeline entry or a timeline entry for a care event that was never recorded.
Merging on read costs five queries and cannot drift.

**Append-oriented.** Nothing here rewrites anything. A correction is a new entry,
which is why `care_events` has `correction_of_event_id` rather than an UPDATE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.common.enums import SystemEventType
from app.repositories.base import Row, rows
from supabase import Client

# One page of history. Enough that a plant with a few months of care reads as a
# story; small enough that the five queries stay cheap.
PAGE_SIZE = 30


@dataclass(frozen=True)
class TimelineEntry:
    """One thing that happened, from whichever table recorded it.

    `kind` is the union of `SystemEventType` and the four merged sources, as a
    plain string: it is a presentation label, and constraining it to an enum
    would mean adding a value every time the timeline learns to show something.
    """

    kind: str
    occurred_at: datetime
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)
    source: str = "system_events"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "occurred_at": self.occurred_at.isoformat(),
            "summary": self.summary,
            "detail": self.detail,
            "source": self.source,
        }


def _parse(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# Hebrew summaries. Kept here rather than in the UI because the timeline is a
# merge of five shapes and the phrasing depends on which one an entry came from;
# putting that in a page would push the merge logic into the presentation layer.
_SYSTEM_SUMMARIES: dict[str, str] = {
    SystemEventType.PLANT_CREATED.value: "הצמח נוסף",
    SystemEventType.PLANT_ARCHIVED.value: "הצמח הועבר לארכיון",
    SystemEventType.PLANT_RESTORED.value: "הצמח שוחזר מהארכיון",
    SystemEventType.PLANT_RENAMED.value: "שם הצמח שונה",
    SystemEventType.ENVIRONMENT_CHANGED.value: "תנאי הסביבה עודכנו",
    SystemEventType.MAIN_IMAGE_CHANGED.value: "התמונה הראשית הוחלפה",
    SystemEventType.REPOTTED.value: "הצמח הועבר לעציץ אחר",
    SystemEventType.MOVED.value: "הצמח הועבר למקום אחר",
    SystemEventType.PRUNED.value: "הצמח נגזם",
    SystemEventType.CUSTOM_NOTE.value: "הערה",
}

_CARE_SUMMARIES: dict[str, str] = {
    "DONE": "בוצע טיפול",
    "SKIPPED": "דילוג על טיפול",
    "MISSED": "טיפול שלא בוצע",
    "CORRECTED": "תיקון רישום",
}

_ACTION_LABELS: dict[str, str] = {
    "WATERING": "השקיה",
    "FERTILIZING": "דישון",
    "REPOTTING": "החלפת עציץ",
    "PRUNING": "גיזום",
    "MISTING": "ריסוס",
    "ROTATING": "סיבוב",
    "INSPECTION": "בדיקה",
}

_HEALTH_SUMMARIES: dict[str, str] = {
    "HEALTHY": "בדיקת בריאות: הצמח נראה תקין",
    "NEEDS_ATTENTION": "בדיקת בריאות: נדרשת תשומת לב",
    "CRITICAL": "בדיקת בריאות: מצב קריטי",
    "UNKNOWN": "בדיקת בריאות: לא ניתן לקבוע",
}

_PLAN_SUMMARIES: dict[str, str] = {
    "INITIAL_PLAN": "תוכנית טיפול ראשונה",
    "OPERATIONAL_ADJUSTMENT": "שינוי תפעולי בתוכנית",
    "ENVIRONMENT_CHANGE": "עדכון תוכנית בעקבות שינוי בסביבה",
    "HEALTH_DRIVEN": "עדכון תוכנית בעקבות בדיקת בריאות",
    "RE_IDENTIFICATION": "עדכון תוכנית בעקבות זיהוי מחדש",
}


def timeline(
    client: Client, *, plant_id: UUID, limit: int = PAGE_SIZE, before: str | None = None
) -> list[dict[str, Any]]:
    """The merged history, newest first.

    Paginated on `occurred_at` rather than by offset. An append-only timeline
    grows at the head, so an offset page-two drifts as new entries arrive and the
    user sees an entry twice or not at all; a timestamp cursor cannot.
    """
    cutoff = _parse(before) if before else None

    entries: list[TimelineEntry] = []
    entries.extend(_system_entries(client, plant_id, limit))
    entries.extend(_care_entries(client, plant_id, limit))
    entries.extend(_health_entries(client, plant_id, limit))
    entries.extend(_identification_entries(client, plant_id, limit))
    entries.extend(_plan_entries(client, plant_id, limit))

    if cutoff is not None:
        entries = [entry for entry in entries if entry.occurred_at < cutoff]

    entries.sort(key=lambda entry: entry.occurred_at, reverse=True)
    return [entry.as_dict() for entry in entries[:limit]]


def _system_entries(client: Client, plant_id: UUID, limit: int) -> list[TimelineEntry]:
    return [
        TimelineEntry(
            kind=row["event_type"],
            occurred_at=_parse(row["created_at"]),
            summary=_system_summary(row),
            detail=row.get("payload") or {},
            source="system_events",
        )
        for row in rows(
            client.table("system_events")
            .select("event_type, payload, created_at")
            .eq("plant_id", str(plant_id))
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    ]


def _system_summary(row: Row) -> str:
    payload = row.get("payload") or {}
    event_type = str(row["event_type"])
    base = _SYSTEM_SUMMARIES.get(event_type, event_type)

    # A CUSTOM_NOTE with no note is an empty line in the timeline; showing the
    # user's own words is the entire point of the entry.
    if event_type == SystemEventType.CUSTOM_NOTE.value and payload.get("note"):
        return str(payload["note"])[:200]
    if event_type == SystemEventType.PLANT_RENAMED.value and payload.get("name"):
        return f"{base}: {payload['name']}"
    return base


def _care_entries(client: Client, plant_id: UUID, limit: int) -> list[TimelineEntry]:
    events = rows(
        client.table("care_events")
        .select("id, care_task_id, event_type, event_at, note")
        .eq("plant_id", str(plant_id))
        .order("event_at", desc=True)
        .limit(limit)
        .execute()
    )
    if not events:
        return []

    actions = _actions_for_tasks(
        client, [e["care_task_id"] for e in events if e.get("care_task_id")]
    )

    entries = []
    for event in events:
        action = actions.get(str(event.get("care_task_id") or ""), "")
        event_type = str(event["event_type"])
        label = _CARE_SUMMARIES.get(event_type, event_type)
        summary = f"{label}: {_ACTION_LABELS.get(action, action)}" if action else label
        entries.append(
            TimelineEntry(
                kind=f"CARE_{event['event_type']}",
                occurred_at=_parse(event["event_at"]),
                summary=summary,
                detail={"note": event.get("note"), "action_type": action},
                source="care_events",
            )
        )
    return entries


def _actions_for_tasks(client: Client, task_ids: list[str]) -> dict[str, str]:
    """Which action each task was for.

    Two hops — task to rule to action type — because `care_tasks` deliberately
    does not duplicate the action: the rule owns it, and copying it would let the
    two disagree after an operational adjustment.
    """
    if not task_ids:
        return {}

    tasks = rows(
        client.table("care_tasks")
        .select("id, care_rule_id")
        .in_("id", list(set(task_ids)))
        .execute()
    )
    if not tasks:
        return {}

    rules = {
        rule["id"]: rule["action_type"]
        for rule in rows(
            client.table("care_rules")
            .select("id, action_type")
            .in_("id", list({t["care_rule_id"] for t in tasks}))
            .execute()
        )
    }
    return {task["id"]: rules.get(task["care_rule_id"], "") for task in tasks}


def _health_entries(client: Client, plant_id: UUID, limit: int) -> list[TimelineEntry]:
    return [
        TimelineEntry(
            kind="HEALTH_ASSESSMENT",
            occurred_at=_parse(row["created_at"]),
            summary=_HEALTH_SUMMARIES.get(row["overall_status"], "בדיקת בריאות"),
            detail={
                "assessment_id": row["id"],
                "status": row["overall_status"],
                "trend": row.get("trend"),
            },
            source="health_assessments",
        )
        for row in rows(
            client.table("health_assessments")
            .select("id, overall_status, trend, created_at")
            .eq("plant_id", str(plant_id))
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    ]


def _identification_entries(client: Client, plant_id: UUID, limit: int) -> list[TimelineEntry]:
    entries = []
    for row in rows(
        client.table("identifications")
        .select("id, status, method, primary_species_id, created_at")
        .eq("plant_id", str(plant_id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    ):
        method = row.get("method")
        if method == "USER_CONFIRMED":
            summary = "הזיהוי אושר"
        elif method == "USER_CORRECTED":
            summary = "המשתמש תיקן את הזיהוי"
        elif row.get("status") == "SUCCESS":
            summary = "זיהוי הושלם"
        else:
            summary = "ניסיון זיהוי"

        entries.append(
            TimelineEntry(
                kind="IDENTIFICATION",
                occurred_at=_parse(row["created_at"]),
                summary=summary,
                detail={"identification_id": row["id"], "status": row.get("status")},
                source="identifications",
            )
        )
    return entries


def _plan_entries(client: Client, plant_id: UUID, limit: int) -> list[TimelineEntry]:
    plan = rows(
        client.table("care_plans").select("id").eq("plant_id", str(plant_id)).limit(1).execute()
    )
    if not plan:
        return []

    entries = []
    for row in rows(
        client.table("care_plan_versions")
        .select("id, version_number, status, source_type, change_summary, created_at")
        .eq("care_plan_id", plan[0]["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    ):
        base = _PLAN_SUMMARIES.get(row["source_type"], "עדכון תוכנית טיפול")
        # A rejected proposal is history too: "we suggested this and you said no"
        # is exactly the kind of thing a user looks back for.
        if row["status"] == "REJECTED":
            base = f"{base} (נדחתה)"
        elif row["status"] == "PROPOSED":
            base = f"{base} (ממתינה לאישור)"

        entries.append(
            TimelineEntry(
                kind="CARE_PLAN_VERSION",
                occurred_at=_parse(row["created_at"]),
                summary=base,
                detail={
                    "version_number": row["version_number"],
                    "status": row["status"],
                    "change_summary": row.get("change_summary"),
                },
                source="care_plan_versions",
            )
        )
    return entries
