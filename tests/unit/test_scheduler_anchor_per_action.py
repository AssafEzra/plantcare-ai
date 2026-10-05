"""The next occurrence counts from the same kind of care, not from the plant's
latest event of any kind.

Found while designing care intensity: `_next_occurrence` took the plant's most
recent DONE/SKIPPED/MISSED event whatever task it belonged to. A plant fed on
1 October and watered on the 12th had its monthly feeding scheduled 30 days after
the *watering* - and with weekly watering, a monthly task never came within the
14-day horizon, so it was never materialised at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from tests.unit.fake_db import FakeDB

JERUSALEM = "Asia/Jerusalem"
PLANT = "plant-1"


def at(day: int, month: int = 10) -> datetime:
    return datetime(2026, month, day, 6, 0, tzinfo=UTC)


def task(task_id: str, rule_id: str, *, due: int) -> dict[str, Any]:
    return {
        "id": task_id,
        "plant_id": PLANT,
        "care_rule_id": rule_id,
        "due_at_utc": at(due).isoformat(),
    }


def done(task_id: str, *, on: int) -> dict[str, Any]:
    return {
        "plant_id": PLANT,
        "care_task_id": task_id,
        "event_type": "DONE",
        "event_at": at(on).isoformat(),
    }


def _store(
    *, rules: list[dict[str, Any]], tasks: list[dict[str, Any]], events: list[dict[str, Any]]
) -> FakeDB:
    return FakeDB({"care_rules": rules, "care_tasks": tasks, "care_events": events})


@pytest.fixture
def scheduler(env):
    from app.orchestration.services import scheduler

    return scheduler


def _next(scheduler, db: FakeDB, *, rule: dict[str, Any], now: datetime) -> datetime:
    from app.domain.rules import recurrence

    return scheduler._next_occurrence(
        db,
        rule_row=rule,
        domain_rule=recurrence.Rule(interval_days=int(rule["interval_days"])),
        plan_version={"plant_id": PLANT, "created_at": at(1, 9).isoformat()},
        timezone_name=JERUSALEM,
        now_utc=now,
    )


FEED = {"id": "r-feed", "action_type": "FERTILIZING", "interval_days": 30}
WATER = {"id": "r-water", "action_type": "WATERING", "interval_days": 7}


def test_a_watering_does_not_re_anchor_the_feeding(scheduler):
    db = _store(
        rules=[FEED, WATER],
        tasks=[
            task("t-feed", "r-feed", due=1),
            task("t-water", "r-water", due=12),
        ],
        events=[
            done("t-feed", on=1),
            done("t-water", on=12),
        ],
    )

    due = _next(scheduler, db, rule=FEED, now=at(13))

    assert due.astimezone(UTC).date() == datetime(2026, 10, 31).date()


def test_each_kind_of_care_keeps_its_own_rhythm(scheduler):
    db = _store(
        rules=[FEED, WATER],
        tasks=[
            task("t-feed", "r-feed", due=1),
            task("t-water", "r-water", due=12),
        ],
        events=[
            done("t-feed", on=13),
            done("t-water", on=12),
        ],
    )

    # Fed more recently than watered: the watering still counts from the watering.
    due = _next(scheduler, db, rule=WATER, now=at(13))

    assert due.astimezone(UTC).date() == datetime(2026, 10, 19).date()


def test_history_carries_across_a_new_plan_version(scheduler):
    """A new version has new rule ids. Matching on the rule id would see no history
    and schedule a watering for today on a plant watered yesterday."""
    new_water = {"id": "r-water-v2", "action_type": "WATERING", "interval_days": 10}
    db = _store(
        rules=[WATER, new_water],
        tasks=[
            task("t-old", "r-water", due=12),
        ],
        events=[
            done("t-old", on=12),
        ],
    )

    due = _next(scheduler, db, rule=new_water, now=at(13))

    assert due.astimezone(UTC).date() == datetime(2026, 10, 22).date()


def test_a_kind_of_care_with_no_history_starts_from_activation(scheduler):
    db = _store(
        rules=[FEED, WATER],
        tasks=[
            task("t-water", "r-water", due=12),
        ],
        events=[
            done("t-water", on=12),
        ],
    )

    # Never fed: first_due from the plan's activation, not 30 days after a watering.
    due = _next(scheduler, db, rule=FEED, now=at(13))

    # Activated 09:00 local on 1 September, after the 08:00 slot: first due the 2nd.
    assert due.astimezone(UTC).date() == datetime(2026, 9, 2).date()
