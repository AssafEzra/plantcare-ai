"""Deterministic scheduling (FINAL §1.4, §13; TESTING_STRATEGY §4).

Time is a parameter to every function here, which is what makes these tests
possible at all: the DST cases below run in March and in October without waiting
for either.

Asia/Jerusalem is the MVP default and moves its clocks, so the two boundary tests
use real 2026 transition dates. They are the reason the module does day
arithmetic in local time instead of adding seconds to a UTC instant — the naive
implementation passes every test except those two, and then quietly moves every
reminder by an hour twice a year.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.common.enums import CareEventType, Weekday
from app.domain.rules.recurrence import (
    HORIZON_DAYS,
    MAX_OVERDUE_DAYS,
    OverdueItem,
    Rule,
    anchor_for,
    catch_up,
    day_bounds_utc,
    days_late,
    first_due,
    has_expired,
    is_overdue,
    local_date,
    next_due,
    overdue_deadline,
    summarize_overdue,
    within_horizon,
    zone,
)

JERUSALEM = "Asia/Jerusalem"
TZ = ZoneInfo(JERUSALEM)


def local(year, month, day, hour=8, minute=0, tz=TZ) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=tz)


def local_hour_of(moment: datetime, tz=TZ) -> int:
    return moment.astimezone(tz).hour


# --- the basic rhythm ----------------------------------------------------------


def test_a_weekly_rule_lands_a_week_later_at_the_same_local_time():
    rule = Rule(interval_days=7, preferred_time_local=time(8, 0))
    due = next_due(rule, anchor_utc=local(2026, 6, 1).astimezone(UTC), timezone_name=JERUSALEM)

    assert due.astimezone(TZ).date() == local(2026, 6, 8).date()
    assert local_hour_of(due) == 8


def test_the_preferred_time_is_applied_not_the_anchors_time():
    """The rule says 08:00. Watering at 23:00 must not move every future
    reminder to 23:00 — the anchor supplies the day, the rule supplies the hour."""
    rule = Rule(interval_days=7, preferred_time_local=time(8, 0))
    due = next_due(
        rule, anchor_utc=local(2026, 6, 1, 23, 30).astimezone(UTC), timezone_name=JERUSALEM
    )

    assert local_hour_of(due) == 8


@pytest.mark.parametrize("interval", [1, 3, 9, 30, 365])
def test_any_interval_advances_by_exactly_that_many_local_days(interval: int):
    rule = Rule(interval_days=interval)
    anchor = local(2026, 6, 1).astimezone(UTC)
    due = next_due(rule, anchor_utc=anchor, timezone_name=JERUSALEM)

    assert (due.astimezone(TZ).date() - anchor.astimezone(TZ).date()).days == interval


# --- DST, in both directions ---------------------------------------------------


def test_the_local_hour_survives_clocks_going_forward():
    """Israel moves to IDT on 27 March 2026. A schedule that added seconds to a
    UTC instant would deliver this reminder at 07:00."""
    rule = Rule(interval_days=7, preferred_time_local=time(8, 0))
    due = next_due(rule, anchor_utc=local(2026, 3, 24).astimezone(UTC), timezone_name=JERUSALEM)

    assert due.astimezone(TZ).date() == local(2026, 3, 31).date()
    assert local_hour_of(due) == 8


def test_the_local_hour_survives_clocks_going_back():
    """Israel returns to IST on 25 October 2026 — the same bug, other direction,
    delivering at 09:00."""
    rule = Rule(interval_days=7, preferred_time_local=time(8, 0))
    due = next_due(rule, anchor_utc=local(2026, 10, 20).astimezone(UTC), timezone_name=JERUSALEM)

    assert due.astimezone(TZ).date() == local(2026, 10, 27).date()
    assert local_hour_of(due) == 8


def test_the_utc_offset_actually_differs_across_the_boundary():
    """Guards the two tests above from passing vacuously.

    If Israel ever stopped observing DST they would still pass while testing
    nothing, so this asserts the boundary is real in the tz database being used.
    """
    before = local(2026, 3, 24).utcoffset()
    after = local(2026, 3, 31).utcoffset()
    assert before != after


def test_a_daily_rule_crossing_the_spring_boundary_keeps_its_hour():
    rule = Rule(interval_days=1, preferred_time_local=time(8, 0))
    due = next_due(rule, anchor_utc=local(2026, 3, 26).astimezone(UTC), timezone_name=JERUSALEM)

    assert local_hour_of(due) == 8


# --- A7: weekday anchoring -----------------------------------------------------


def test_a_weekday_anchors_a_weekly_rule():
    rule = Rule(interval_days=7, preferred_weekday=Weekday.FRIDAY)
    due = next_due(rule, anchor_utc=local(2026, 6, 1).astimezone(UTC), timezone_name=JERUSALEM)

    assert due.astimezone(TZ).weekday() == 4  # Friday


def test_a_weekday_is_ignored_when_the_interval_is_not_weekly():
    """A7. Validation and a CHECK constraint both refuse this combination, so it
    cannot arrive from the database — but the function stays correct alone, and
    silently drifting the day would be worse than ignoring the field."""
    rule = Rule(interval_days=5, preferred_weekday=Weekday.FRIDAY)
    anchor = local(2026, 6, 1).astimezone(UTC)
    due = next_due(rule, anchor_utc=anchor, timezone_name=JERUSALEM)

    assert (due.astimezone(TZ).date() - anchor.astimezone(TZ).date()).days == 5


def test_a_fortnightly_rule_can_still_anchor_a_weekday():
    rule = Rule(interval_days=14, preferred_weekday=Weekday.SUNDAY)
    due = next_due(rule, anchor_utc=local(2026, 6, 1).astimezone(UTC), timezone_name=JERUSALEM)

    assert due.astimezone(TZ).weekday() == 6
    assert (due.astimezone(TZ).date() - local(2026, 6, 1).date()).days >= 14


# --- A8: what the next occurrence counts from ----------------------------------


def test_done_anchors_on_when_it_actually_happened():
    """Watered on Thursday, next watering seven days from Thursday.

    Anchoring on the due date would compound lateness into a schedule the user
    never agreed to.
    """
    due = local(2026, 6, 1).astimezone(UTC)
    actually = local(2026, 6, 4).astimezone(UTC)

    assert anchor_for(CareEventType.DONE, due_at_utc=due, event_at_utc=actually) == actually


def test_skipped_anchors_on_the_original_due_date():
    """Skipping says "not this time", not "restart the clock".

    Anchoring on the moment of skipping would let a user postpone indefinitely by
    skipping repeatedly, and the rhythm would drift away from the plan.
    """
    due = local(2026, 6, 1).astimezone(UTC)
    skipped_at = local(2026, 6, 4).astimezone(UTC)

    assert anchor_for(CareEventType.SKIPPED, due_at_utc=due, event_at_utc=skipped_at) == due


def test_repeated_skipping_does_not_push_the_schedule_out():
    """The property the anchoring rule exists to protect."""
    rule = Rule(interval_days=7)
    due = local(2026, 6, 1).astimezone(UTC)

    for _ in range(4):
        anchor = anchor_for(
            CareEventType.SKIPPED,
            due_at_utc=due,
            event_at_utc=due + timedelta(days=6),  # skipped just before the next one
        )
        due = next_due(rule, anchor_utc=anchor, timezone_name=JERUSALEM)

    # Four intervals from the original date, not four-plus-six-days each time.
    assert due.astimezone(TZ).date() == local(2026, 6, 29).date()


def test_a_late_completion_shifts_the_rhythm_forward():
    rule = Rule(interval_days=7)
    due = local(2026, 6, 1).astimezone(UTC)
    done_at = local(2026, 6, 4).astimezone(UTC)

    anchor = anchor_for(CareEventType.DONE, due_at_utc=due, event_at_utc=done_at)
    assert (
        next_due(rule, anchor_utc=anchor, timezone_name=JERUSALEM).astimezone(TZ).date()
        == local(2026, 6, 11).date()
    )


# --- the first occurrence ------------------------------------------------------


def test_a_new_rule_fires_today_when_its_time_has_not_passed():
    """Approving a plan at 06:00 should not mean waiting until tomorrow."""
    rule = Rule(interval_days=7, preferred_time_local=time(8, 0))
    due = first_due(
        rule, activated_at_utc=local(2026, 6, 1, 6, 0).astimezone(UTC), timezone_name=JERUSALEM
    )

    assert due.astimezone(TZ).date() == local(2026, 6, 1).date()


def test_a_new_rule_fires_tomorrow_when_its_time_has_passed():
    rule = Rule(interval_days=7, preferred_time_local=time(8, 0))
    due = first_due(
        rule, activated_at_utc=local(2026, 6, 1, 9, 0).astimezone(UTC), timezone_name=JERUSALEM
    )

    assert due.astimezone(TZ).date() == local(2026, 6, 2).date()


def test_a_new_rule_does_not_wait_a_whole_interval():
    """The distinction from `next_due`: a nine-day watering plan approved today
    should not stay silent for nine days, which reads as the plan not working."""
    rule = Rule(interval_days=9, preferred_time_local=time(8, 0))
    activated = local(2026, 6, 1, 6, 0).astimezone(UTC)

    assert first_due(rule, activated_at_utc=activated, timezone_name=JERUSALEM) < next_due(
        rule, anchor_utc=activated, timezone_name=JERUSALEM
    )


# --- A9: overdue, and when it stops mattering ----------------------------------


def test_a_task_is_overdue_once_its_moment_has_passed():
    due = local(2026, 6, 1).astimezone(UTC)
    assert not is_overdue(due_at_utc=due, now_utc=due - timedelta(minutes=1))
    assert is_overdue(due_at_utc=due, now_utc=due + timedelta(minutes=1))


def test_a_daily_task_expires_after_its_own_interval():
    """A9. A daily task a fortnight late is meaningless; the window is bounded by
    the rhythm so it does not outlive its usefulness."""
    rule = Rule(interval_days=1)
    due = local(2026, 6, 1).astimezone(UTC)

    assert not has_expired(rule, due_at_utc=due, now_utc=due + timedelta(hours=12))
    assert has_expired(rule, due_at_utc=due, now_utc=due + timedelta(days=2))


def test_a_yearly_task_expires_at_the_ceiling_not_a_year_later():
    rule = Rule(interval_days=365)
    due = local(2026, 6, 1).astimezone(UTC)

    assert overdue_deadline(rule, due_at_utc=due) == due + timedelta(days=MAX_OVERDUE_DAYS)
    assert has_expired(rule, due_at_utc=due, now_utc=due + timedelta(days=MAX_OVERDUE_DAYS + 1))


def test_a_monthly_task_is_still_worth_doing_a_week_late():
    rule = Rule(interval_days=30)
    due = local(2026, 6, 1).astimezone(UTC)

    assert not has_expired(rule, due_at_utc=due, now_utc=due + timedelta(days=7))


# --- the horizon ---------------------------------------------------------------


def test_only_near_term_occurrences_are_materialised():
    """FINAL §13: do not pre-generate excessive future tasks."""
    now = local(2026, 6, 1).astimezone(UTC)

    assert within_horizon(now + timedelta(days=HORIZON_DAYS - 1), now_utc=now)
    assert not within_horizon(now + timedelta(days=HORIZON_DAYS + 1), now_utc=now)


def test_an_overdue_occurrence_is_within_the_horizon():
    """Something already due must still be materialisable, or a task that slipped
    past the last tick would never be created at all."""
    now = local(2026, 6, 1).astimezone(UTC)
    assert within_horizon(now - timedelta(days=3), now_utc=now)


# --- the user's calendar day ---------------------------------------------------


def test_todays_date_follows_the_user_not_utc():
    """Jerusalem is ahead of UTC, so early morning there is still yesterday in
    UTC. A dashboard reading the UTC date would show yesterday's tasks for the
    first three hours of every day.
    """
    early_morning = local(2026, 6, 2, 1, 30).astimezone(UTC)

    assert early_morning.date() == local(2026, 6, 1).date()  # UTC has not rolled over
    assert local_date(early_morning, JERUSALEM) == local(2026, 6, 2).date()


def test_a_day_boundary_is_the_users_midnight_not_utc_midnight():
    """The window "today" must start when the user's day does."""
    start, end = day_bounds_utc(local(2026, 6, 2).date(), JERUSALEM)

    assert start.astimezone(TZ).hour == 0
    assert local_date(start, JERUSALEM) == local(2026, 6, 2).date()
    # Half-open: the last instant of the day is inside, the first of the next is not.
    assert local_date(end - timedelta(seconds=1), JERUSALEM) == local(2026, 6, 2).date()
    assert local_date(end, JERUSALEM) == local(2026, 6, 3).date()


def test_a_local_day_covers_exactly_twenty_four_hours_normally():
    start, end = day_bounds_utc(local(2026, 6, 1).date(), JERUSALEM)
    assert end - start == timedelta(hours=24)


def test_a_local_day_is_twenty_three_hours_when_clocks_go_forward():
    """The bounds are computed from local midnights, so a short day is short —
    which is correct, and is not what fixed 24-hour arithmetic would produce."""
    start, end = day_bounds_utc(local(2026, 3, 27).date(), JERUSALEM)
    assert end - start == timedelta(hours=23)


def test_an_unknown_timezone_falls_back_rather_than_failing():
    """A stale or malformed zone must not stop the tick for every other user."""
    assert zone("Mars/Olympus_Mons").key == "UTC"
    assert next_due(
        Rule(interval_days=7),
        anchor_utc=local(2026, 6, 1).astimezone(UTC),
        timezone_name="nonsense",
    )


# --- overdue summarisation -----------------------------------------------------


def item(plant: str, action: str, day: int) -> OverdueItem:
    return OverdueItem(
        plant_id=plant,
        plant_name=f"plant-{plant}",
        action_type=action,
        due_at_utc=local(2026, 6, day).astimezone(UTC),
    )


def test_several_overdue_tasks_for_one_plant_become_one_line():
    """FINAL §13. Fourteen rows for someone back from holiday is technically
    complete and reads as a punishment."""
    summaries = summarize_overdue(
        [item("a", "WATERING", 1), item("a", "FERTILIZING", 3), item("a", "WATERING", 5)]
    )

    assert len(summaries) == 1
    assert summaries[0].count == 3
    assert summaries[0].action_types == ["WATERING", "FERTILIZING"]


def test_plants_are_ordered_by_the_oldest_outstanding_task():
    """One task three weeks late matters more than three one day late."""
    summaries = summarize_overdue(
        [
            item("recent", "WATERING", 10),
            item("stale", "WATERING", 1),
            item("recent", "MISTING", 11),
        ]
    )

    assert [s.plant_id for s in summaries] == ["stale", "recent"]


def test_nothing_overdue_summarises_to_nothing():
    assert summarize_overdue([]) == []


def test_days_late_counts_from_the_oldest():
    summary = summarize_overdue([item("a", "WATERING", 1), item("a", "MISTING", 5)])[0]
    assert days_late(summary, now_utc=local(2026, 6, 8).astimezone(UTC)) == 7


def test_days_late_is_never_negative():
    summary = summarize_overdue([item("a", "WATERING", 10)])[0]
    assert days_late(summary, now_utc=local(2026, 6, 1).astimezone(UTC)) == 0


# --- after a miss ---------------------------------------------------------------


def test_a_miss_anchors_on_when_it_was_written_off():
    """Not on its long-past due date.

    Anchoring a miss on the date it was due puts the next occurrence in the past
    too; the sweep retires that one as expired as well, and the scheduler writes
    a MISSED event on every tick forever. Found by an integration test asserting
    FINAL §13's "the next recurrence remains scheduled" — which it was not.
    """
    due = local(2026, 6, 1).astimezone(UTC)
    noticed = local(2026, 7, 1).astimezone(UTC)

    assert anchor_for(CareEventType.MISSED, due_at_utc=due, event_at_utc=noticed) == noticed


def test_the_occurrence_after_a_miss_is_in_the_future():
    rule = Rule(interval_days=7)
    noticed = local(2026, 7, 1).astimezone(UTC)

    anchor = anchor_for(
        CareEventType.MISSED,
        due_at_utc=local(2026, 6, 1).astimezone(UTC),
        event_at_utc=noticed,
    )
    assert next_due(rule, anchor_utc=anchor, timezone_name=JERUSALEM) > noticed


# --- catch_up: the safety net ---------------------------------------------------


def test_catch_up_leaves_a_current_occurrence_alone():
    rule = Rule(interval_days=7)
    now = local(2026, 6, 1).astimezone(UTC)
    due = now + timedelta(days=3)

    assert catch_up(rule, due, now_utc=now) == due


def test_catch_up_advances_a_stale_occurrence_past_the_present():
    """The loop this exists to prevent: materialising something the sweep retires
    on sight, forever."""
    rule = Rule(interval_days=7)
    now = local(2026, 7, 1).astimezone(UTC)
    stale = local(2026, 5, 1).astimezone(UTC)

    caught = catch_up(rule, stale, now_utc=now)
    assert not has_expired(rule, due_at_utc=caught, now_utc=now)


def test_catch_up_keeps_the_rhythms_phase():
    """Advancing by whole intervals rather than jumping to "now plus one" keeps a
    Monday-morning watering on Monday morning."""
    rule = Rule(interval_days=7)
    now = local(2026, 7, 1).astimezone(UTC)
    stale = local(2026, 5, 4).astimezone(UTC)  # a Monday

    caught = catch_up(rule, stale, now_utc=now)
    assert (caught - stale).days % 7 == 0


def test_catch_up_does_not_advance_a_task_still_within_its_window():
    """A monthly task a week late is still worth doing, so it must not be
    silently pushed to next month."""
    rule = Rule(interval_days=30)
    due = local(2026, 6, 1).astimezone(UTC)

    assert catch_up(rule, due, now_utc=due + timedelta(days=7)) == due
