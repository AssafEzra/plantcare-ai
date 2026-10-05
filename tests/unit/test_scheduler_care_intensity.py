"""The scheduler groups tasks onto care days, against an in-memory database.

The pure rules are covered in test_care_intensity_rules.py. These run the real
scheduler functions - materialise, the overdue sweep, scheduling the next task,
rescheduling after a settings change - to show the rules are applied where tasks
are actually written.

October 2026: Friday the 9th, 16th, 23rd; Monday the 5th, 12th, 19th.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from tests.unit.fake_db import FakeDB

JERUSALEM = "Asia/Jerusalem"
TZ = ZoneInfo(JERUSALEM)
USER = "user-1"
PLANT = "plant-1"


def local(day: int, hour: int = 8, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=TZ).astimezone(UTC)


def day_of(value: Any) -> int:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return moment.astimezone(TZ).day


def world(
    *,
    intensity: str = "LOW",
    plant_override: str | None = None,
    interval: int = 7,
    tasks: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> FakeDB:
    return FakeDB(
        {
            "profiles": [
                {
                    "id": USER,
                    "timezone": JERUSALEM,
                    "care_intensity": intensity,
                    "care_day_low": "FRIDAY",
                    "care_days_medium": ["TUESDAY", "FRIDAY"],
                }
            ],
            "plants": [
                {
                    "id": PLANT,
                    "user_id": USER,
                    "status": "ACTIVE",
                    "name": "Monstera",
                    "care_intensity": plant_override,
                }
            ],
            "care_plans": [
                {"id": "plan", "plant_id": PLANT, "user_id": USER, "active_version_id": "v1"}
            ],
            "care_plan_versions": [
                {"id": "v1", "care_plan_id": "plan", "created_at": local(1, month=9).isoformat()}
            ],
            "care_rules": [
                {
                    "id": "r-water",
                    "care_plan_version_id": "v1",
                    "action_type": "WATERING",
                    "interval_days": interval,
                    "preferred_time_local": "08:00",
                    "preferred_weekday": None,
                    "is_active": True,
                }
            ],
            "care_tasks": tasks or [],
            "care_events": events or [],
        }
    )


def task(task_id: str, *, due: datetime, status: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "user_id": USER,
        "plant_id": PLANT,
        "care_rule_id": "r-water",
        "due_at_utc": due.isoformat(),
        "status": status,
        "overdue_since": None,
        "completed_at": None,
        "created_at": due.isoformat(),
    }


def done(task_id: str, *, on: datetime) -> dict[str, Any]:
    return {
        "user_id": USER,
        "plant_id": PLANT,
        "care_task_id": task_id,
        "event_type": "DONE",
        "event_at": on.isoformat(),
    }


def open_tasks(db: FakeDB) -> list[dict[str, Any]]:
    return [t for t in db.store["care_tasks"] if t["status"] in {"PENDING", "OVERDUE"}]


@pytest.fixture
def scheduler(env):
    from app.orchestration.services import scheduler

    return scheduler


# --- materialise --------------------------------------------------------------------


def watered_on_monday_the_5th(**kwargs: Any) -> FakeDB:
    return world(
        tasks=[task("t1", due=local(5), status="DONE")],
        events=[done("t1", on=local(5))],
        **kwargs,
    )


def test_a_new_task_lands_on_the_care_day(scheduler):
    """Weekly, watered Monday the 5th: naturally due Monday the 12th. Friday the 9th
    is nearer but only four days after the watering, so it goes to the 16th."""
    db = watered_on_monday_the_5th()

    assert scheduler.materialise(db, now_utc=local(6)) == 1
    assert day_of(open_tasks(db)[0]["due_at_utc"]) == 16


def test_a_plant_pinned_to_high_keeps_its_own_rhythm(scheduler):
    db = watered_on_monday_the_5th(plant_override="HIGH")

    scheduler.materialise(db, now_utc=local(6))

    assert day_of(open_tasks(db)[0]["due_at_utc"]) == 12


def test_high_for_the_user_changes_nothing(scheduler):
    db = watered_on_monday_the_5th(intensity="HIGH")

    scheduler.materialise(db, now_utc=local(6))

    assert day_of(open_tasks(db)[0]["due_at_utc"]) == 12


# --- the next task after acting on one ------------------------------------------------


def test_done_late_the_next_one_is_not_too_soon(scheduler):
    """Due Friday the 9th, done Monday the 12th. Next naturally Monday the 19th; the
    16th would be four days after watering, so it is the 23rd."""
    db = world(tasks=[task("t1", due=local(9), status="DONE")])

    upcoming = scheduler._schedule_next(
        db, task=db.store["care_tasks"][0], event_type=_done(), event_at=local(12)
    )

    assert upcoming is not None and day_of(upcoming) == 23


def _done():
    from app.common.enums import CareEventType

    return CareEventType.DONE


# --- the overdue sweep ----------------------------------------------------------------


def test_an_overdue_task_waits_for_the_next_care_day(scheduler):
    db = world(interval=2, tasks=[task("t1", due=local(9), status="PENDING")])

    result = scheduler.sweep_overdue(db, now_utc=local(13))

    assert (result.marked_overdue, result.missed) == (1, 0)
    assert db.store["care_tasks"][0]["status"] == "OVERDUE"


def test_on_high_the_same_task_is_written_off_as_before(scheduler):
    db = world(
        interval=2, plant_override="HIGH", tasks=[task("t1", due=local(9), status="PENDING")]
    )

    result = scheduler.sweep_overdue(db, now_utc=local(13))

    assert result.missed == 1


# --- changing the setting ---------------------------------------------------------------


def test_changing_the_setting_moves_pending_tasks_and_back_again(scheduler):
    db = world(
        intensity="LOW",
        tasks=[
            task("t1", due=local(5), status="DONE"),
            task("t2", due=local(12), status="PENDING"),
        ],
        events=[done("t1", on=local(5))],
    )

    assert scheduler.reschedule_pending(db, user_id=USER, now_utc=local(6)) == 1
    assert day_of(db.store["care_tasks"][1]["due_at_utc"]) == 16

    db.store["profiles"][0]["care_intensity"] = "HIGH"
    assert scheduler.reschedule_pending(db, user_id=USER, now_utc=local(6)) == 1
    assert day_of(db.store["care_tasks"][1]["due_at_utc"]) == 12


def test_overdue_tasks_are_not_moved(scheduler):
    db = world(intensity="LOW", tasks=[task("t1", due=local(5), status="OVERDUE")])

    assert scheduler.reschedule_pending(db, user_id=USER, now_utc=local(6)) == 0
    assert day_of(db.store["care_tasks"][0]["due_at_utc"]) == 5
