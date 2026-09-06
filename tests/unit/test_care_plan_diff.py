"""What actually changes when a proposal is approved (PR 33, FINAL §12).

The proposal showed the agent's one-sentence summary and the new plan in full.
Both true, and neither answered the question the user is really asking, which is
*what is different* — leaving them to read two schedules side by side and notice
that watering moved from seven days to five.

The comparison is pure on purpose. A user leans on it to make a decision, so it
must not be something a model rephrases differently each run; and being pure it
can be tested exhaustively without a database, a clock or a screen.
"""

from __future__ import annotations

import pytest

from app.domain.services.care_plan_diff import diff_rules, has_changes


def rule(action: str, days: int, time: str = "08:00:00", **extra):
    return {
        "action_type": action,
        "interval_days": days,
        "preferred_time_local": time,
        "preferred_weekday": None,
        "is_active": True,
        **extra,
    }


def by_action(changes):
    return {c.action_type: c for c in changes}


def test_a_first_plan_is_all_additions():
    """Every rule is new because there is nothing to compare against. The caller
    decides whether to draw that as a diff or simply as the plan."""
    changes = diff_rules([], [rule("WATERING", 7), rule("FERTILIZING", 30)])

    assert {c.kind for c in changes} == {"added"}
    assert len(changes) == 2


def test_a_changed_interval_names_the_field():
    changes = by_action(diff_rules([rule("WATERING", 7)], [rule("WATERING", 5)]))

    watering = changes["WATERING"]
    assert watering.kind == "changed"
    assert watering.fields == ("interval_days",)
    assert watering.before["interval_days"] == 7
    assert watering.after["interval_days"] == 5


def test_a_rule_the_proposal_drops_is_reported_as_removed():
    """The easiest change to miss reading two lists, and the one most worth
    knowing: a reminder is about to stop arriving."""
    changes = by_action(
        diff_rules([rule("WATERING", 7), rule("ROTATING", 7)], [rule("WATERING", 7)])
    )

    assert changes["ROTATING"].kind == "removed"
    assert changes["WATERING"].kind == "unchanged"


def test_an_identical_plan_reports_no_changes():
    changes = diff_rules([rule("WATERING", 7)], [rule("WATERING", 7)])

    assert not has_changes(changes)


@pytest.mark.parametrize("stored,proposed", [("08:00:00", "08:00"), ("08:00", "08:00:00")])
def test_the_same_time_in_two_notations_is_not_a_change(stored, proposed):
    """Postgres returns `time` as HH:MM:SS and the agent's contract accepts HH:MM.
    Without normalising, every proposal would report a time change on every rule —
    and a diff that cries wolf on everything is worth nothing on anything."""
    changes = diff_rules([rule("WATERING", 7, time=stored)], [rule("WATERING", 7, time=proposed)])

    assert not has_changes(changes)


def test_reworded_instructions_are_not_a_schedule_change():
    """The agent rewords the same advice run to run. Reporting that as a change to
    the schedule would bury the ones that matter."""
    changes = diff_rules(
        [rule("WATERING", 7, instructions="להשקות עד ניקוז")],
        [rule("WATERING", 7, instructions="יש להשקות עד שהמים מנקזים")],
    )

    assert not has_changes(changes)


def test_a_deactivated_rule_counts_as_removed():
    changes = by_action(diff_rules([rule("MISTING", 3)], [rule("MISTING", 3, is_active=False)]))

    assert changes["MISTING"].kind == "removed"


def test_changes_come_before_things_that_stayed_the_same():
    """A user scanning this is looking for the difference. Six unchanged rules
    above the one that moved is the same failure as hiding it."""
    changes = diff_rules(
        [rule("WATERING", 7), rule("FERTILIZING", 30), rule("PRUNING", 60)],
        [rule("WATERING", 7), rule("FERTILIZING", 14), rule("PRUNING", 60)],
    )

    assert changes[0].action_type == "FERTILIZING"
    assert changes[0].kind == "changed"
    assert {c.kind for c in changes[1:]} == {"unchanged"}


def test_nothing_at_all_is_not_an_error():
    assert diff_rules(None, None) == []
