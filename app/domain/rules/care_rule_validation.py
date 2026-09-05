"""Care rule validation (FINAL §34 names it as a test target).

Separate from the recurrence maths on purpose. `recurrence.py` (PR 17) answers
"when does this rule next fire?" and may assume its input is sane; this module is
what makes that assumption true.

Two of these checks also exist as CHECK constraints on `care_rules`, and that
duplication is deliberate. The database constraint is the one that cannot be
bypassed; this one runs *before* the write, so a model proposing an impossible
rule produces a schema failure the gateway can retry rather than a 500 from
Postgres. They must agree exactly — a rule this module accepts and the database
rejects is the worst of both.

Pure: no I/O, no clock, no model. `tests/unit/test_architecture_boundaries.py`
enforces that for everything under `domain/rules/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from app.common.enums import CareRuleActionType, Weekday

# Mirrors `care_rules_interval_sane`.
MIN_INTERVAL_DAYS = 1
MAX_INTERVAL_DAYS = 365

# Below this, a recurring action is almost certainly a misread rather than a
# genuine instruction. Repotting every three days is not a care plan.
_MIN_SENSIBLE_INTERVAL: dict[CareRuleActionType, int] = {
    CareRuleActionType.REPOTTING: 90,
    CareRuleActionType.PRUNING: 14,
    CareRuleActionType.FERTILIZING: 7,
    CareRuleActionType.WATERING: 1,
    CareRuleActionType.MISTING: 1,
    CareRuleActionType.ROTATING: 3,
    CareRuleActionType.INSPECTION: 3,
}

# A reminder at 03:00 is one the user will never act on, and a plan full of them
# reads as broken rather than thorough.
EARLIEST_HOUR = 5
LATEST_HOUR = 22


@dataclass(frozen=True)
class RuleViolation:
    """One reason a rule is unusable, in a form the proposal card can show."""

    field: str
    reason: str


class InvalidCareRuleError(ValueError):
    def __init__(self, violations: list[RuleViolation]) -> None:
        self.violations = violations
        super().__init__("; ".join(f"{v.field}: {v.reason}" for v in violations))


def validate(
    *,
    action_type: CareRuleActionType,
    interval_days: int,
    preferred_time_local: time,
    preferred_weekday: Weekday | None = None,
) -> list[RuleViolation]:
    """Every problem with this rule. Empty means schedulable."""
    violations: list[RuleViolation] = []

    if not MIN_INTERVAL_DAYS <= interval_days <= MAX_INTERVAL_DAYS:
        violations.append(
            RuleViolation(
                "interval_days",
                f"must be between {MIN_INTERVAL_DAYS} and {MAX_INTERVAL_DAYS} days",
            )
        )
    else:
        floor = _MIN_SENSIBLE_INTERVAL.get(action_type, 1)
        if interval_days < floor:
            violations.append(
                RuleViolation(
                    "interval_days",
                    f"{action_type.value} every {interval_days} days is implausible; "
                    f"the minimum is {floor}",
                )
            )

    # A7. The database says the same thing; saying it here first means a model
    # that proposes it gets a retry instead of a Postgres error.
    if preferred_weekday is not None and interval_days % 7 != 0:
        violations.append(
            RuleViolation(
                "preferred_weekday",
                "a weekday can only anchor a recurrence whose interval is a multiple of 7",
            )
        )

    if not EARLIEST_HOUR <= preferred_time_local.hour <= LATEST_HOUR:
        violations.append(
            RuleViolation(
                "preferred_time_local",
                f"reminders are scheduled between {EARLIEST_HOUR}:00 and {LATEST_HOUR}:00",
            )
        )

    return violations


def ensure_valid(
    *,
    action_type: CareRuleActionType,
    interval_days: int,
    preferred_time_local: time,
    preferred_weekday: Weekday | None = None,
) -> None:
    violations = validate(
        action_type=action_type,
        interval_days=interval_days,
        preferred_time_local=preferred_time_local,
        preferred_weekday=preferred_weekday,
    )
    if violations:
        raise InvalidCareRuleError(violations)


def duplicate_action_types(action_types: list[CareRuleActionType]) -> list[CareRuleActionType]:
    """Action types proposed more than once.

    Two watering rules on one plan is not a richer schedule, it is two competing
    ones — and the scheduler would materialise a task for each, so the user gets
    told to water the same plant twice.
    """
    seen: set[CareRuleActionType] = set()
    duplicates: list[CareRuleActionType] = []
    for action in action_types:
        if action in seen and action not in duplicates:
            duplicates.append(action)
        seen.add(action)
    return duplicates
