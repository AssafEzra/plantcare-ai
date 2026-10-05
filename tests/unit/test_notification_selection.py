"""What goes into Today and Due, and how a push reads. Pure functions."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.notifications import selection

TZ = "Asia/Jerusalem"
MONDAY = date(2026, 10, 12)


def at_local(day: int, hour: int, minute: int = 0) -> str:
    return datetime(2026, 10, day, hour, minute, tzinfo=ZoneInfo(TZ)).astimezone(UTC).isoformat()


def task(due: str, *, status: str = "PENDING", plant: str = "מונסטרה", action: str = "WATERING"):
    return {
        "due_at_utc": due,
        "status": status,
        "plant_name": plant,
        "plant_id": plant,
        "action_type": action,
    }


def test_today_is_the_users_calendar_day_not_utcs():
    """23:30 on Monday in Jerusalem is already Tuesday in UTC; it is still Monday's work."""
    late_evening = task(at_local(12, 23, 30))
    assert selection.today_tasks([late_evening], today=MONDAY, timezone_name=TZ) == [late_evening]


def test_done_tasks_are_never_mentioned():
    done = task(at_local(12, 8), status="DONE")
    assert selection.today_tasks([done], today=MONDAY, timezone_name=TZ) == []


def test_due_covers_exactly_the_chosen_number_of_days():
    one_ago = task(at_local(11, 8), status="OVERDUE")
    three_ago = task(at_local(9, 8), status="OVERDUE")
    four_ago = task(at_local(8, 8), status="OVERDUE")
    tasks = [one_ago, three_ago, four_ago]

    assert selection.due_tasks(tasks, today=MONDAY, timezone_name=TZ, days=0) == []
    assert selection.due_tasks(tasks, today=MONDAY, timezone_name=TZ, days=1) == [one_ago]
    assert selection.due_tasks(tasks, today=MONDAY, timezone_name=TZ, days=3) == [
        one_ago,
        three_ago,
    ]


def test_a_late_task_still_labelled_pending_counts_as_late():
    """The overdue sweep may not have run yet; the due date is what decides."""
    stale = task(at_local(11, 8), status="PENDING")
    assert selection.due_tasks([stale], today=MONDAY, timezone_name=TZ, days=1) == [stale]


def test_todays_task_is_not_in_due():
    assert (
        selection.due_tasks([task(at_local(12, 8))], today=MONDAY, timezone_name=TZ, days=3) == []
    )


def test_a_plant_with_two_tasks_is_one_entry():
    message = selection.today_push(
        [task(at_local(12, 8)), task(at_local(12, 8), action="FERTILIZING")], day=MONDAY
    )
    assert message.body == "מונסטרה (השקיה, דישון)"
    assert message.title == "🟢 צמח אחד צריך טיפול היום"


def test_a_long_list_is_cut_short():
    plants = [task(at_local(12, 8), plant=f"צמח {i}") for i in range(6)]
    message = selection.today_push(plants, day=MONDAY)
    assert message.title.startswith("🟢 6 צמחים")
    assert message.body.endswith("ועוד 2")


def test_each_kind_has_its_colour_marker_and_icon_kind():
    today = selection.today_push([task(at_local(12, 8))], day=MONDAY)
    late = selection.due_push([task(at_local(11, 8))], day=MONDAY)
    assert (today.kind, today.title[0]) == ("today", "🟢")
    assert (late.kind, late.title[0]) == ("late", "🔴")
    assert today.payload()["tag"] != late.payload()["tag"]
