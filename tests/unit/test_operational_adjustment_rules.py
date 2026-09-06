"""Adjusting a rule that is anchored to a weekday (PR 33 fix).

Reported: *"after i hit save it doesnt say what we discussed but gives an
error"*. It was a 500.

A weekday anchor only means something on an interval that is a multiple of seven
(A7), and `care_rules` has a CHECK saying so. The adjustment copied the weekday
verbatim while applying the new interval, so "every 7 days on Sunday" changed to
five days produced a row Postgres refused. Every one of a real user's plants had
at least one weekly rule anchored to a day, so the control was unusable on all of
them.

`care_rule_validation` has encoded the same rule since PR 16. This path never
consulted it - the seam again, between a rule that exists and a writer that does
not ask.
"""

from __future__ import annotations

import pytest

from app.orchestration.workflows.care import _apply_override


def rule(action="ROTATING", days=7, weekday="SUNDAY", time="09:00:00"):
    return {
        "action_type": action,
        "interval_days": days,
        "preferred_time_local": time,
        "preferred_weekday": weekday,
        "instructions": "לסובב רבע סיבוב.",
        "is_active": True,
    }


def test_a_weekday_survives_an_interval_that_still_divides_by_seven():
    """Every 7 days on Sunday becomes every 14 days on Sunday. The anchor is
    still coherent, so it stays."""
    adjusted = _apply_override(rule(), {"interval_days": 14})

    assert adjusted["interval_days"] == 14
    assert adjusted["preferred_weekday"] == "SUNDAY"


@pytest.mark.parametrize("days", [1, 3, 5, 8, 10])
def test_a_weekday_is_dropped_when_it_no_longer_fits(days):
    """Not refused - dropped. The user is choosing a frequency, and the scheduler
    already ignores a weekday that does not divide into the interval, so keeping
    it would store something with no effect while rejecting the change would
    claim they cannot pick five days when they can."""
    adjusted = _apply_override(rule(), {"interval_days": days})

    assert adjusted["interval_days"] == days
    assert adjusted["preferred_weekday"] is None


def test_a_rule_with_no_weekday_is_unaffected():
    adjusted = _apply_override(rule(weekday=None), {"interval_days": 5})

    assert adjusted["preferred_weekday"] is None
    assert adjusted["interval_days"] == 5


def test_a_rule_nobody_overrode_is_carried_across_unchanged():
    """Changing watering must not disturb fertilising - that is the whole reason
    overrides are keyed by action type."""
    original = rule(action="FERTILIZING", days=21, weekday=None, time="08:30:00")
    adjusted = _apply_override(original, {})

    assert adjusted["interval_days"] == 21
    assert adjusted["preferred_time_local"] == "08:30:00"
    assert adjusted["instructions"] == original["instructions"]


def test_an_incoherent_weekday_already_stored_is_not_carried_forward():
    """Defensive: rows predating the CHECK, or written by a future path that
    forgets it, must not be copied into a version that cannot be inserted."""
    adjusted = _apply_override(rule(days=5, weekday="SUNDAY"), {})

    assert adjusted["preferred_weekday"] is None


def test_a_time_change_leaves_the_weekday_alone():
    adjusted = _apply_override(rule(), {"preferred_time_local": "07:00:00"})

    assert adjusted["preferred_time_local"] == "07:00:00"
    assert adjusted["preferred_weekday"] == "SUNDAY"
