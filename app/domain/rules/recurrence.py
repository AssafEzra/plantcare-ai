"""Deterministic scheduling (FINAL §1.4, §13).

    "Scheduling is deterministic Python."

That sentence is the reason this module exists and the reason it looks the way it
does. No model, no database, no clock: **time is a parameter**. A function that
called `datetime.now()` could not be tested against a DST boundary without
waiting for October, and "the scheduler is deterministic" would be a claim rather
than a property.

`tests/unit/test_architecture_boundaries.py` fails the build if anything under
`domain/rules/` imports an agent, a provider or a client.

Local time is the point
-----------------------
A user asks to be reminded at 08:00. Not 08:00 UTC, and not "whatever 08:00 was
when the rule was written" — 08:00 in their own timezone, on the day the reminder
lands. So every computation here converts to the user's zone, does the arithmetic
on calendar days there, and converts back. Adding `interval_days * 86400` seconds
to a UTC timestamp is the obvious implementation and it is wrong twice a year:
across an Israeli DST boundary it moves the reminder to 07:00 or 09:00.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.common.enums import CareEventType, CareIntensity, Weekday

# How far ahead a task may be materialised. FINAL §13: "do not pre-generate
# excessive future tasks", and the database enforces one PENDING task per rule.
HORIZON_DAYS = 14

# A9. After this long an overdue task stops being actionable and becomes a MISSED
# event, so a plant left alone for a month does not greet its owner with thirty
# outstanding waterings. Capped by the rule's own interval: a daily task that is
# a week late is far more stale than a monthly one at the same age.
MAX_OVERDUE_DAYS = 14

# The weekday enum in Python's own terms. `date.weekday()` is Monday=0.
_WEEKDAY_INDEX: dict[Weekday, int] = {
    Weekday.MONDAY: 0,
    Weekday.TUESDAY: 1,
    Weekday.WEDNESDAY: 2,
    Weekday.THURSDAY: 3,
    Weekday.FRIDAY: 4,
    Weekday.SATURDAY: 5,
    Weekday.SUNDAY: 6,
}


@dataclass(frozen=True)
class Rule:
    """A care rule, reduced to what scheduling needs.

    Not the database row: this module must be callable from a test with three
    lines of setup, and it must be impossible for it to read a column it was not
    given.
    """

    interval_days: int
    preferred_time_local: time = time(8, 0)
    preferred_weekday: Weekday | None = None


def zone(timezone_name: str) -> ZoneInfo:
    """The user's zone, falling back rather than failing.

    A stored timezone can be stale — a zone gets renamed, or a client sends
    something odd. Failing here would stop the whole tick for every user, so an
    unknown zone degrades to UTC and the reminder is merely at an unexpected hour
    for one person.
    """
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def _at_local_time(day: date, at: time, tz: ZoneInfo) -> datetime:
    """A local wall-clock time on a given day, as UTC.

    The `fold=0` default resolves the ambiguous hour when clocks go back by
    taking the *first* occurrence. Either is defensible; picking one explicitly
    means the answer is stable rather than dependent on platform behaviour.

    A time that does not exist at all (the skipped hour when clocks go forward)
    is normalised by `astimezone`, which is the standard-library behaviour and
    lands the reminder an hour later that day rather than dropping it.
    """
    return datetime.combine(day, at, tzinfo=tz).astimezone(UTC)


def next_due(
    rule: Rule,
    *,
    anchor_utc: datetime,
    timezone_name: str,
) -> datetime:
    """When this rule next falls due, given the moment it last happened.

    The interval is added in **calendar days in the user's zone**, then the
    preferred time is applied there. Adding seconds to a UTC instant would drift
    the reminder by an hour across a DST boundary; this cannot, because the local
    time is re-applied after the day arithmetic.
    """
    tz = zone(timezone_name)
    anchor_local = anchor_utc.astimezone(tz)

    target_day = anchor_local.date() + timedelta(days=rule.interval_days)

    if rule.preferred_weekday is not None and rule.interval_days % 7 == 0:
        # A7: a weekday only anchors *which* day a weekly rhythm lands on, and
        # only when the interval is a multiple of seven. The rule validation and
        # a CHECK constraint both refuse other combinations, so reaching this
        # branch with a 5-day interval is impossible — but the guard costs
        # nothing and keeps this function correct in isolation.
        wanted = _WEEKDAY_INDEX[rule.preferred_weekday]
        shift = (wanted - target_day.weekday()) % 7
        target_day += timedelta(days=shift)

    return _at_local_time(target_day, rule.preferred_time_local, tz)


def first_due(
    rule: Rule,
    *,
    activated_at_utc: datetime,
    timezone_name: str,
) -> datetime:
    """When a newly activated rule fires for the first time.

    Deliberately **not** `next_due(anchor=activation)`. A user who approves a
    watering plan at 09:00 should not wait a full interval to be told to water
    for the first time; the first occurrence is today if its time has not yet
    passed, and tomorrow otherwise. Waiting nine days to hear anything makes an
    approved plan feel broken.
    """
    tz = zone(timezone_name)
    local = activated_at_utc.astimezone(tz)

    candidate_day = local.date()
    if local.timetz().replace(tzinfo=None) >= rule.preferred_time_local:
        candidate_day += timedelta(days=1)

    if rule.preferred_weekday is not None and rule.interval_days % 7 == 0:
        wanted = _WEEKDAY_INDEX[rule.preferred_weekday]
        shift = (wanted - candidate_day.weekday()) % 7
        candidate_day += timedelta(days=shift)

    return _at_local_time(candidate_day, rule.preferred_time_local, tz)


def anchor_for(
    event_type: CareEventType, *, due_at_utc: datetime, event_at_utc: datetime
) -> datetime:
    """What the next occurrence counts from (A8).

    The spec does not say, and the two plausible answers behave differently
    enough that guessing would be a bug either way:

    * **DONE anchors on when it actually happened.** The plant was watered on
      Thursday; the next watering is seven days after Thursday, not after the
      Monday it was nominally due. Anchoring on the due date would compound
      lateness into a schedule the user never agreed to.
    * **SKIPPED anchors on the original due date.** Skipping says "not this
      time", not "restart the clock". Anchoring on the moment of skipping would
      let a user push a task indefinitely by skipping it repeatedly, and the
      rhythm the plan describes would quietly drift.
    * **MISSED anchors on when it was written off**, which is `event_at`. This
      one is not symmetry, it is a fix: anchoring a miss on its long-past due
      date puts the next occurrence in the past too, the sweep retires that one
      as expired as well, and the scheduler writes a MISSED event on every tick
      forever. A miss means the rhythm was broken; it restarts from the moment we
      gave up on it.
    """
    if event_type is CareEventType.DONE:
        return event_at_utc
    if event_type is CareEventType.MISSED:
        return event_at_utc
    return due_at_utc


def is_overdue(*, due_at_utc: datetime, now_utc: datetime) -> bool:
    return now_utc > due_at_utc


def overdue_deadline(
    rule: Rule,
    *,
    due_at_utc: datetime,
    schedule: CareSchedule | None = None,
    timezone_name: str = "UTC",
) -> datetime:
    """When an overdue task stops being actionable (A9).

    `min(interval_days, MAX_OVERDUE_DAYS)`: a daily task a fortnight late is
    meaningless, while a monthly one is still worth doing at two weeks. Bounding
    by the interval keeps the window proportional to the rhythm, and the ceiling
    stops a yearly repotting task lingering for months.

    On care days the window runs to the end of the **next care day** instead. A
    watering every two days for someone who cares on Fridays would otherwise be
    written off on Sunday, two days before they could have done it, and every week
    would add a MISSED entry for a task they were never going to see in time. Kept
    open, it waits for Friday; done then, `align_to_care_days` keeps the following
    one from coming too soon. Missed on that Friday too, it expires and the rhythm
    restarts.
    """
    if schedule is not None and schedule.groups:
        due_day = local_date(due_at_utc, timezone_name)
        care_day = _next_care_day(due_day + timedelta(days=1), schedule.care_days)
        return day_bounds_utc(care_day, timezone_name)[1]

    days = min(rule.interval_days, MAX_OVERDUE_DAYS)
    return due_at_utc + timedelta(days=days)


def has_expired(
    rule: Rule,
    *,
    due_at_utc: datetime,
    now_utc: datetime,
    schedule: CareSchedule | None = None,
    timezone_name: str = "UTC",
) -> bool:
    """Has this overdue task passed the point of being worth doing? (A9)"""
    deadline = overdue_deadline(
        rule, due_at_utc=due_at_utc, schedule=schedule, timezone_name=timezone_name
    )
    return now_utc > deadline


def catch_up(rule: Rule, due_at_utc: datetime, *, now_utc: datetime) -> datetime:
    """Advance a stale occurrence to the next one that is still worth doing.

    A safety net rather than the main path. Any occurrence computed from an old
    anchor can land in the past — a plan reactivated after months, a clock
    correction, a miss anchored badly — and materialising it produces a task the
    sweep immediately retires, which writes a MISSED event and computes the next
    stale occurrence, on every tick, indefinitely. That loop is worse than any
    scheduling error it could be covering for.

    Advancing by whole intervals rather than jumping to "now plus one interval"
    keeps the rhythm's phase: a Monday-morning watering stays on Monday morning.
    """
    if rule.interval_days <= 0:  # pragma: no cover - CHECK constraint forbids it
        return due_at_utc

    due = due_at_utc
    # Bounded: an interval of one day and an anchor a decade old would otherwise
    # spin. Anything beyond this is a data problem, not a scheduling one.
    for _ in range(1000):
        if not has_expired(rule, due_at_utc=due, now_utc=now_utc):
            return due
        due += timedelta(days=rule.interval_days)
    return due


def within_horizon(due_at_utc: datetime, *, now_utc: datetime) -> bool:
    """Should this occurrence be materialised yet?

    FINAL §13 forbids pre-generating excessive future tasks, so a task is only
    written once it is within the horizon. The database additionally allows one
    PENDING task per rule, so a scheduler bug cannot produce a backlog even if
    this returns True too eagerly.
    """
    return due_at_utc <= now_utc + timedelta(days=HORIZON_DAYS)


def local_date(moment_utc: datetime, timezone_name: str) -> date:
    """The calendar date a UTC instant falls on, for the user.

    "Today's tasks" is a question about the user's calendar, not about UTC. At
    22:00 in Jerusalem it is already tomorrow in UTC, and a dashboard that
    disagreed with the user's own date would be wrong for two hours every night.
    """
    return moment_utc.astimezone(zone(timezone_name)).date()


def day_bounds_utc(day: date, timezone_name: str) -> tuple[datetime, datetime]:
    """The UTC half-open interval `[start, end)` covering a local calendar day."""
    tz = zone(timezone_name)
    start = _at_local_time(day, time(0, 0), tz)
    end = _at_local_time(day + timedelta(days=1), time(0, 0), tz)
    return start, end


# --- care intensity: grouping care onto fixed weekdays (migration 0021) -----------

# Rule B: a task may move *earlier* onto a care day only once this share of its
# interval has passed since it was last done. Below it, the move goes forward.
EARLIEST_SHARE_OF_INTERVAL = 0.75

# A task is flagged when the user's care days leave it at most half as often as its
# plan asks: the longest gap between care days is at least this multiple of the
# task's interval. Every-3-days on Tuesday/Friday (gaps of 3 and 4) passes;
# every-2-days does not, and nor does every-3-days on a single day a week.
WARNING_GAP_RATIO = 2


@dataclass(frozen=True)
class CareSchedule:
    """Which days care is grouped onto, if any.

    HIGH, or a level with no days, groups nothing and leaves every date exactly as
    the rule produced it - the scheduler's behaviour before this existed.
    """

    intensity: CareIntensity = CareIntensity.HIGH
    care_days: tuple[Weekday, ...] = ()

    @property
    def groups(self) -> bool:
        return self.intensity is not CareIntensity.HIGH and bool(self.care_days)


def care_schedule(
    *,
    profile_intensity: CareIntensity | str | None,
    care_day_low: Weekday | str | None,
    care_days_medium: list[Weekday] | list[str] | tuple[Weekday, ...] | None,
    plant_override: CareIntensity | str | None = None,
) -> CareSchedule:
    """The schedule one plant follows: its own override, else its owner's setting.

    Care days always come from the owner. A plant pinned to MEDIUM uses the owner's
    two days, because per-plant days would scatter the tasks again and the grouping
    is the whole point.
    """
    chosen = plant_override or profile_intensity or CareIntensity.HIGH
    intensity = CareIntensity(chosen)

    if intensity is CareIntensity.LOW and care_day_low:
        return CareSchedule(intensity, (Weekday(care_day_low),))
    if intensity is CareIntensity.MEDIUM and care_days_medium:
        days = tuple(dict.fromkeys(Weekday(day) for day in care_days_medium))
        return CareSchedule(intensity, days)
    return CareSchedule(intensity)


def _is_care_day(day: date, care_days: tuple[Weekday, ...]) -> bool:
    return day.weekday() in {_WEEKDAY_INDEX[d] for d in care_days}


def _next_care_day(day: date, care_days: tuple[Weekday, ...]) -> date:
    """The first care day on or after `day`."""
    for offset in range(7):
        candidate = day + timedelta(days=offset)
        if _is_care_day(candidate, care_days):
            return candidate
    raise ValueError("a care schedule needs at least one care day")  # pragma: no cover


def _previous_care_day(day: date, care_days: tuple[Weekday, ...]) -> date:
    """The last care day on or before `day`."""
    for offset in range(7):
        candidate = day - timedelta(days=offset)
        if _is_care_day(candidate, care_days):
            return candidate
    raise ValueError("a care schedule needs at least one care day")  # pragma: no cover


def align_to_care_days(
    due_utc: datetime,
    *,
    schedule: CareSchedule,
    timezone_name: str,
    interval_days: int,
    last_done_utc: datetime | None,
    now_utc: datetime,
) -> datetime:
    """Move a due date onto the user's care days (rule B).

    The nearest care day wins, so a task lands as close to its real rhythm as the
    user's week allows. Moving *earlier* has one condition: at least
    `EARLIEST_SHARE_OF_INTERVAL` of the interval must have passed since the task was
    last done. Without it, a weekly task done late on a Tuesday would come due again
    on the Saturday before the following Tuesday - four days later, which is
    over-watering made routine. When the earlier day fails that test, the task moves
    forward instead. Ties go earlier: under-care is the failure a user notices too
    late, and the guard already stops early from becoming over-care.

    Never into the past: a care day that has already gone by is not a date anyone
    can act on, so the next one is used.

    The local wall-clock time of the original due date is kept. Only the day moves.
    """
    if not schedule.groups:
        return due_utc

    tz = zone(timezone_name)
    local = due_utc.astimezone(tz)
    day = local.date()
    at = local.time().replace(tzinfo=None)

    if _is_care_day(day, schedule.care_days):
        chosen = day
    else:
        earlier = _previous_care_day(day, schedule.care_days)
        later = _next_care_day(day, schedule.care_days)

        earliest_allowed: date | None = None
        if last_done_utc is not None:
            minimum = math.ceil(interval_days * EARLIEST_SHARE_OF_INTERVAL)
            earliest_allowed = local_date(last_done_utc, timezone_name) + timedelta(days=minimum)

        earlier_is_nearer = (day - earlier) <= (later - day)
        earlier_is_allowed = earliest_allowed is None or earlier >= earliest_allowed
        chosen = earlier if earlier_is_nearer and earlier_is_allowed else later

    moved = _at_local_time(chosen, at, tz)
    if moved >= now_utc:
        return moved

    # Gone by. The next care day whose slot is still ahead.
    today = local_date(now_utc, timezone_name)
    candidate = _next_care_day(today, schedule.care_days)
    moved = _at_local_time(candidate, at, tz)
    if moved < now_utc:
        moved = _at_local_time(
            _next_care_day(candidate + timedelta(days=1), schedule.care_days), at, tz
        )
    return moved


def max_gap_days(care_days: tuple[Weekday, ...] | list[Weekday]) -> int:
    """The longest stretch between consecutive care days, wrapping the week.

    One care day is seven. Tuesday and Friday are three and four, so four. Sunday and
    Monday are one and six, so six - uneven days count against the user, which is
    what they should do: the worst week is the one the plant has to survive.
    """
    indices = sorted({_WEEKDAY_INDEX[Weekday(day)] for day in care_days})
    if not indices:
        return 0
    if len(indices) == 1:
        return 7
    gaps = [b - a for a, b in pairwise(indices)]
    gaps.append(indices[0] + 7 - indices[-1])
    return max(gaps)


def needs_warning(interval_days: int, schedule: CareSchedule) -> bool:
    """Would this schedule leave the task at most half as often as its plan asks?

    A ratio rather than a fixed number of days: a day late is a lot for a task due
    every two days and nothing for a monthly one.
    """
    if not schedule.groups or interval_days <= 0:
        return False
    return max_gap_days(schedule.care_days) >= WARNING_GAP_RATIO * interval_days


# --- overdue summarisation (FINAL §13, PROGRESS §14) ---------------------------


@dataclass(frozen=True)
class OverdueItem:
    """One overdue task, reduced to what a summary line needs."""

    plant_id: str
    plant_name: str
    action_type: str
    due_at_utc: datetime


@dataclass(frozen=True)
class OverdueSummary:
    """Everything outstanding for one plant, as one line.

    FINAL §13: "Multiple overdue items can be summarized." A user returning from
    a fortnight away should be told "the monstera needs watering and feeding",
    not shown fourteen separate rows — the second is technically complete and
    reads as a punishment.
    """

    plant_id: str
    plant_name: str
    action_types: list[str]
    oldest_due_at_utc: datetime
    count: int


def summarize_overdue(items: list[OverdueItem]) -> list[OverdueSummary]:
    """Group overdue tasks into one summary per plant, most overdue first.

    Ordering by the oldest outstanding task rather than by count: one task three
    weeks late matters more than three tasks one day late, and the user's
    attention should land there.
    """
    grouped: dict[str, list[OverdueItem]] = {}
    for item in items:
        grouped.setdefault(item.plant_id, []).append(item)

    summaries = [
        OverdueSummary(
            plant_id=plant_id,
            plant_name=group[0].plant_name,
            # Deduplicated and ordered by urgency, so the line reads "watering
            # and feeding" rather than repeating an action a rule generated twice.
            action_types=list(
                dict.fromkeys(
                    item.action_type for item in sorted(group, key=lambda i: i.due_at_utc)
                )
            ),
            oldest_due_at_utc=min(item.due_at_utc for item in group),
            count=len(group),
        )
        for plant_id, group in grouped.items()
    ]
    return sorted(summaries, key=lambda s: s.oldest_due_at_utc)


def days_late(summary: OverdueSummary, *, now_utc: datetime) -> int:
    """Whole days since the oldest outstanding task fell due."""
    return max(0, (now_utc - summary.oldest_due_at_utc).days)
