"""What each notification contains, and when it may go out. No I/O.

Three notifications a day at most, each at most once:

* **Today**   - open tasks whose due date, on the user's calendar, is today;
* **Due**     - open tasks whose due date is one to `due_reminder_days` days ago
  (none when that is 0), so an overdue task is mentioned for a few mornings and
  then left to the task list rather than nagged about forever;
* **Evening** - today's tasks still open in the evening. Push only.

Dates are the user's local dates. A task due at 23:30 in Jerusalem is due "today"
there even though it is already tomorrow in UTC, and a reminder that disagreed
with the user's own calendar would be wrong for part of every day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from app.domain.rules import recurrence

OPEN_STATUSES = frozenset({"PENDING", "OVERDUE"})

MORNING_DEFAULT = time(7, 30)
EVENING_DEFAULT = time(19, 0)

# A push is a glance, not a list: past this many plants the body says "+N".
MAX_LISTED = 4

ACTION_LABELS: dict[str, str] = {
    "WATERING": "השקיה",
    "FERTILIZING": "דישון",
    "REPOTTING": "החלפת עציץ",
    "PRUNING": "גיזום",
    "MISTING": "ריסוס",
    "ROTATING": "סיבוב",
    "INSPECTION": "בדיקה",
}


def parse_time(value: Any, default: time) -> time:
    """A Postgres `time` as the API returns it ("07:30:00"), or the default."""
    raw = str(value or "")
    if not raw:
        return default
    try:
        return time.fromisoformat(raw if len(raw) > 5 else f"{raw}:00")
    except ValueError:
        return default


def window_open(local_now: datetime, at: time) -> bool:
    """Has this notification's time arrived today?

    Open from `at` until local midnight rather than at an instant: the scheduler
    can be late, and a run at 08:00 must still send the 07:30 notification. The
    dedupe key is what stops an open window sending twice.
    """
    return local_now.timetz().replace(tzinfo=None) >= at


def _due_day(task: dict[str, Any], timezone_name: str) -> date | None:
    raw = task.get("due_at_utc")
    if not raw:
        return None
    moment = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    return recurrence.local_date(moment, timezone_name)


def _is_open(task: dict[str, Any]) -> bool:
    return str(task.get("status")) in OPEN_STATUSES


def today_tasks(
    tasks: list[dict[str, Any]], *, today: date, timezone_name: str
) -> list[dict[str, Any]]:
    return [t for t in tasks if _is_open(t) and _due_day(t, timezone_name) == today]


def due_tasks(
    tasks: list[dict[str, Any]], *, today: date, timezone_name: str, days: int
) -> list[dict[str, Any]]:
    """Open tasks due 1..`days` days before today. Older ones are left out on purpose."""
    if days <= 0:
        return []
    earliest = today - timedelta(days=days)
    found = []
    for task in tasks:
        day = _due_day(task, timezone_name)
        if _is_open(task) and day is not None and earliest <= day < today:
            found.append(task)
    return found


def action_label(action_type: Any) -> str:
    return ACTION_LABELS.get(str(action_type), str(action_type or "טיפול"))


def _plants_line(tasks: list[dict[str, Any]]) -> str:
    """ "מונסטרה (השקיה), פיקוס (דישון)" - one entry per plant, its actions joined."""
    by_plant: dict[str, list[str]] = {}
    for task in tasks:
        plant = str(task.get("plant_name") or "צמח")
        actions = by_plant.setdefault(plant, [])
        label = action_label(task.get("action_type"))
        if label not in actions:
            actions.append(label)

    entries = [f"{plant} ({', '.join(actions)})" for plant, actions in by_plant.items()]
    shown = entries[:MAX_LISTED]
    line = ", ".join(shown)
    if len(entries) > MAX_LISTED:
        line += f" ועוד {len(entries) - MAX_LISTED}"
    return line


def _plant_count(tasks: list[dict[str, Any]]) -> int:
    return len({str(t.get("plant_id") or t.get("plant_name")) for t in tasks})


@dataclass(frozen=True)
class PushMessage:
    """What the service worker shows. `kind` picks the coloured icon."""

    kind: str
    title: str
    body: str
    url: str = "/tasks"
    tag: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "tag": self.tag or self.kind,
        }


def _plants_phrase(count: int) -> str:
    return "צמח אחד" if count == 1 else f"{count} צמחים"


def today_push(tasks: list[dict[str, Any]], *, day: date) -> PushMessage:
    count = _plant_count(tasks)
    verb = "צריך" if count == 1 else "צריכים"
    return PushMessage(
        kind="today",
        title=f"🟢 {_plants_phrase(count)} {verb} טיפול היום",
        body=_plants_line(tasks),
        tag=f"today-{day.isoformat()}",
    )


def due_push(tasks: list[dict[str, Any]], *, day: date) -> PushMessage:
    count = _plant_count(tasks)
    return PushMessage(
        kind="late",
        title=f"🔴 {_plants_phrase(count)} באיחור",
        body=_plants_line(tasks),
        tag=f"late-{day.isoformat()}",
    )


def evening_push(tasks: list[dict[str, Any]], *, day: date) -> PushMessage:
    open_count = len(tasks)
    what = "משימה אחת" if open_count == 1 else f"{open_count} משימות"
    return PushMessage(
        kind="today",
        title=f"🌙 עדיין פתוחות {what} מהיום",
        body=_plants_line(tasks),
        tag=f"evening-{day.isoformat()}",
    )


def confirmation_push() -> PushMessage:
    """Sent once when a device is registered, so the user sees reminders work."""
    return PushMessage(
        kind="today", title="🌱 התזכורות פעילות", body="כך ייראו התזכורות שלך.", tag="test"
    )
