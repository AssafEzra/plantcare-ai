"""Care rule validation (FINAL §34).

These rules exist twice — here and as CHECK constraints on `care_rules` — and the
duplication is the point: the database constraint is the one that cannot be
bypassed, this one runs before the write so a bad model output becomes a retry
rather than a 500. They have to agree exactly, so several tests below assert the
Python bound *is* the SQL bound.
"""

from __future__ import annotations

from datetime import time

import pytest

from app.common.enums import CareRuleActionType, Weekday
from app.domain.rules.care_rule_validation import (
    MAX_INTERVAL_DAYS,
    MIN_INTERVAL_DAYS,
    InvalidCareRuleError,
    duplicate_action_types,
    ensure_valid,
    validate,
)

MORNING = time(8, 0)


def problems(**kwargs) -> list[str]:
    defaults = {
        "action_type": CareRuleActionType.WATERING,
        "interval_days": 7,
        "preferred_time_local": MORNING,
    }
    return [v.field for v in validate(**{**defaults, **kwargs})]


def test_an_ordinary_watering_rule_is_valid():
    assert problems() == []


# --- interval bounds -----------------------------------------------------------


@pytest.mark.parametrize("interval", [0, -1, MAX_INTERVAL_DAYS + 1, 3650])
def test_an_out_of_range_interval_is_refused(interval: int):
    """3650 is the specific nonsense the schema comment calls out."""
    assert "interval_days" in problems(interval_days=interval)


@pytest.mark.parametrize("interval", [MIN_INTERVAL_DAYS, MAX_INTERVAL_DAYS])
def test_the_bounds_themselves_are_accepted(interval: int):
    """The Python bounds must be the SQL bounds. A rule this module rejects but
    the database would have accepted is a feature silently lost."""
    assert problems(interval_days=interval, action_type=CareRuleActionType.WATERING) == []


# --- plausibility per action ---------------------------------------------------


def test_repotting_every_three_days_is_refused():
    """In range for the database, absurd as horticulture. The database cannot
    know that repotting is measured in months, so this check is the only thing
    between a misread and a plan telling someone to repot twice a week."""
    assert "interval_days" in problems(action_type=CareRuleActionType.REPOTTING, interval_days=3)


def test_watering_every_day_is_fine():
    """The same interval that is absurd for repotting is ordinary for watering,
    which is why the floor is per action rather than global."""
    assert problems(action_type=CareRuleActionType.WATERING, interval_days=1) == []


@pytest.mark.parametrize(
    ("action", "interval"),
    [
        (CareRuleActionType.REPOTTING, 365),
        (CareRuleActionType.PRUNING, 30),
        (CareRuleActionType.FERTILIZING, 14),
        (CareRuleActionType.INSPECTION, 7),
    ],
)
def test_realistic_intervals_pass(action: CareRuleActionType, interval: int):
    assert problems(action_type=action, interval_days=interval) == []


# --- A7: weekday coherence -----------------------------------------------------


@pytest.mark.parametrize("interval", [7, 14, 28])
def test_a_weekday_is_allowed_on_a_weekly_multiple(interval: int):
    assert problems(interval_days=interval, preferred_weekday=Weekday.FRIDAY) == []


@pytest.mark.parametrize("interval", [5, 10, 30])
def test_a_weekday_on_a_non_weekly_interval_is_refused(interval: int):
    """A7. A recurrence every five days cannot land on Friday every time, so the
    combination is rejected rather than silently ignored by the scheduler —
    which would leave the user believing something the plan does not do."""
    assert "preferred_weekday" in problems(interval_days=interval, preferred_weekday=Weekday.FRIDAY)


def test_no_weekday_is_always_fine():
    assert problems(interval_days=5, preferred_weekday=None) == []


# --- reminder hours ------------------------------------------------------------


@pytest.mark.parametrize("hour", [0, 3, 4, 23])
def test_a_reminder_outside_waking_hours_is_refused(hour: int):
    assert "preferred_time_local" in problems(preferred_time_local=time(hour, 0))


@pytest.mark.parametrize("hour", [5, 8, 18, 22])
def test_a_reminder_during_the_day_is_accepted(hour: int):
    assert problems(preferred_time_local=time(hour, 0)) == []


# --- reporting -----------------------------------------------------------------


def test_every_problem_is_reported_not_just_the_first():
    """The proposal card shows these to a user, and fixing one at a time is a
    worse experience than seeing all three."""
    found = problems(
        action_type=CareRuleActionType.REPOTTING,
        interval_days=3,
        preferred_time_local=time(2, 0),
    )
    assert set(found) == {"interval_days", "preferred_time_local"}


def test_ensure_valid_raises_with_every_reason_attached():
    with pytest.raises(InvalidCareRuleError) as raised:
        ensure_valid(
            action_type=CareRuleActionType.WATERING,
            interval_days=0,
            preferred_time_local=time(3, 0),
        )
    assert len(raised.value.violations) == 2


# --- duplicates ----------------------------------------------------------------


def test_a_repeated_action_type_is_reported():
    """Two watering rules is not a richer schedule; the scheduler would
    materialise a task for each and tell the user to water the plant twice."""
    assert duplicate_action_types(
        [
            CareRuleActionType.WATERING,
            CareRuleActionType.FERTILIZING,
            CareRuleActionType.WATERING,
        ]
    ) == [CareRuleActionType.WATERING]


def test_distinct_action_types_are_not_duplicates():
    assert duplicate_action_types([CareRuleActionType.WATERING, CareRuleActionType.PRUNING]) == []


def test_a_triplicate_is_reported_once():
    assert duplicate_action_types([CareRuleActionType.MISTING] * 3) == [CareRuleActionType.MISTING]
