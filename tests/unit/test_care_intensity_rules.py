"""Grouping care onto the user's care days (migration 0021).

October 2026 for every case: Friday the 2nd, 9th, 16th, 23rd, 30th; Tuesday the
6th, 13th, 20th, 27th. Israel leaves summer time on Sunday the 25th, which is what
the DST case uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.common.enums import CareIntensity, Weekday
from app.domain.rules.recurrence import (
    CareSchedule,
    Rule,
    align_to_care_days,
    care_schedule,
    has_expired,
    max_gap_days,
    needs_warning,
    overdue_deadline,
)

JERUSALEM = "Asia/Jerusalem"
TZ = ZoneInfo(JERUSALEM)

HIGH = CareSchedule()
LOW_FRIDAY = CareSchedule(CareIntensity.LOW, (Weekday.FRIDAY,))
MEDIUM_TUE_FRI = CareSchedule(CareIntensity.MEDIUM, (Weekday.TUESDAY, Weekday.FRIDAY))


def local(day: int, hour: int = 8, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=TZ).astimezone(UTC)


def align(due: datetime, schedule: CareSchedule, *, interval: int = 7, last_done=None, now=None):
    return align_to_care_days(
        due,
        schedule=schedule,
        timezone_name=JERUSALEM,
        interval_days=interval,
        last_done_utc=last_done,
        now_utc=now or local(1, 0),
    )


def day_of(moment: datetime) -> int:
    return moment.astimezone(TZ).day


# --- moving a date onto a care day --------------------------------------------------


def test_high_leaves_every_date_alone():
    due = local(7)
    assert align(due, HIGH) == due


def test_a_date_already_on_a_care_day_stays():
    assert align(local(9), LOW_FRIDAY) == local(9)


def test_the_nearer_care_day_wins_when_it_is_later():
    # Wednesday the 7th: Friday the 2nd is five days back, Friday the 9th two ahead.
    assert day_of(align(local(7), LOW_FRIDAY)) == 9


def test_the_nearer_care_day_wins_when_it_is_earlier():
    # Wednesday the 7th: Tuesday the 6th is one back, Friday the 9th two ahead.
    # Last done on 30 September, so the 6th is six days on - past 75% of seven.
    moved = align(local(7), MEDIUM_TUE_FRI, last_done=local(30, month=9))
    assert day_of(moved) == 6


def test_an_earlier_care_day_too_soon_after_the_last_time_is_skipped():
    # Same Wednesday, but done on Friday the 2nd: Tuesday the 6th is four days on,
    # under 75% of seven, so the task goes forward to Friday the 9th instead.
    moved = align(local(7), MEDIUM_TUE_FRI, last_done=local(2))
    assert day_of(moved) == 9


def test_a_late_completion_does_not_bring_the_next_one_back_early():
    """The case rule B exists for. A weekly task done late on Monday the 12th falls
    due Monday the 19th; the nearest Friday is the 16th, four days after it was
    done. That is over-care, so it waits for the 23rd."""
    moved = align(local(19), LOW_FRIDAY, last_done=local(12), now=local(12, 12))
    assert day_of(moved) == 23


def test_a_tie_goes_to_the_earlier_day():
    # Sunday the 11th: Friday the 9th and Tuesday the 13th are both two days away.
    assert day_of(align(local(11), MEDIUM_TUE_FRI)) == 9


def test_a_care_day_that_has_gone_by_is_never_used():
    # Saturday the 10th is nearest to Friday the 9th - but it is already the 10th.
    moved = align(local(10), LOW_FRIDAY, now=local(10, 7))
    assert day_of(moved) == 16


def test_the_time_of_day_is_kept():
    moved = align(local(7, 19, 30), LOW_FRIDAY).astimezone(TZ)
    assert (moved.day, moved.time()) == (9, time(19, 30))


def test_moving_back_across_the_dst_change_keeps_the_local_hour():
    # Monday the 26th (winter time) moves back to Friday the 23rd (summer time).
    moved = align(local(26), LOW_FRIDAY, now=local(20)).astimezone(TZ)
    assert (moved.day, moved.hour) == (23, 8)


# --- overdue tasks wait for the next care day ---------------------------------------


EVERY_TWO_DAYS = Rule(interval_days=2)


def test_an_overdue_task_stays_open_until_the_next_care_day():
    due = local(9)  # a Friday, not done
    assert not has_expired(
        EVERY_TWO_DAYS,
        due_at_utc=due,
        now_utc=local(16, 20),
        schedule=LOW_FRIDAY,
        timezone_name=JERUSALEM,
    )


def test_it_expires_once_that_care_day_has_passed_too():
    due = local(9)
    assert has_expired(
        EVERY_TWO_DAYS,
        due_at_utc=due,
        now_utc=local(17, 0, 1),
        schedule=LOW_FRIDAY,
        timezone_name=JERUSALEM,
    )


def test_high_keeps_the_interval_window():
    """No care days, so the window is the rhythm's own: `interval_days` after the
    due day. It runs to the end of that day rather than to the due *moment* plus
    two, because that moment stopped meaning anything once lateness became a
    question about the calendar day."""
    deadline = overdue_deadline(
        EVERY_TWO_DAYS, due_at_utc=local(9), schedule=HIGH, timezone_name=JERUSALEM
    )

    assert deadline == datetime(2026, 10, 12, 0, 0, tzinfo=TZ).astimezone(UTC)


# --- warnings -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "gap"),
    [
        ((Weekday.FRIDAY,), 7),
        ((Weekday.TUESDAY, Weekday.FRIDAY), 4),
        ((Weekday.SUNDAY, Weekday.MONDAY), 6),
    ],
)
def test_the_longest_gap_wraps_the_week(days, gap):
    assert max_gap_days(days) == gap


@pytest.mark.parametrize(
    ("interval", "schedule", "warned"),
    [
        (2, MEDIUM_TUE_FRI, True),  # gap 4 >= 2 x 2
        (3, MEDIUM_TUE_FRI, False),  # gap 4 <  2 x 3: a day's difference, not a problem
        (3, LOW_FRIDAY, True),  # gap 7 >= 2 x 3
        (4, LOW_FRIDAY, False),  # gap 7 <  2 x 4
        (2, HIGH, False),
    ],
)
def test_a_warning_only_when_care_would_halve(interval, schedule, warned):
    assert needs_warning(interval, schedule) is warned


# --- which schedule a plant follows -------------------------------------------------


def settings(**override):
    return care_schedule(
        profile_intensity=CareIntensity.LOW,
        care_day_low=Weekday.FRIDAY,
        care_days_medium=[Weekday.TUESDAY, Weekday.FRIDAY],
        **override,
    )


def test_a_plant_with_no_override_follows_its_owner():
    assert settings() == LOW_FRIDAY


def test_a_plant_override_wins_and_uses_the_owners_days():
    assert settings(plant_override=CareIntensity.MEDIUM) == MEDIUM_TUE_FRI


def test_a_plant_pinned_to_high_groups_nothing():
    assert not settings(plant_override=CareIntensity.HIGH).groups
