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

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.common.enums import CareEventType, Weekday

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


def overdue_deadline(rule: Rule, *, due_at_utc: datetime) -> datetime:
    """When an overdue task stops being actionable (A9).

    `min(interval_days, MAX_OVERDUE_DAYS)`: a daily task a fortnight late is
    meaningless, while a monthly one is still worth doing at two weeks. Bounding
    by the interval keeps the window proportional to the rhythm, and the ceiling
    stops a yearly repotting task lingering for months.
    """
    days = min(rule.interval_days, MAX_OVERDUE_DAYS)
    return due_at_utc + timedelta(days=days)


def has_expired(rule: Rule, *, due_at_utc: datetime, now_utc: datetime) -> bool:
    """Has this overdue task passed the point of being worth doing? (A9)"""
    return now_utc > overdue_deadline(rule, due_at_utc=due_at_utc)


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
