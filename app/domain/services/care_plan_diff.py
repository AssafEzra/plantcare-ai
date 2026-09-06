"""What actually changes if the user approves a proposal (FINAL §12).

A proposal card showed the agent's one-sentence `change_summary` and the new plan
in full. Both are true and neither answers the question the user is actually
asking, which is *what is different*. Reading two schedules side by side and
spotting that watering moved from seven days to five is work the software should
have done.

Pure and deterministic. No clock, no database, no model — the same reason
`recurrence.py` is pure: this is arithmetic on two lists, and a comparison a user
relies on to make a decision must not be something an LLM improvises differently
each time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# What counts as a difference. `instructions` deliberately does not: the agent
# rewords the same advice run to run, and reporting "the wording changed" as a
# change to the schedule would bury the ones that matter.
COMPARED = ("interval_days", "preferred_time_local", "preferred_weekday")


@dataclass(frozen=True)
class RuleChange:
    """One rule, and how it differs."""

    action_type: str
    kind: str  # "added" | "removed" | "changed" | "unchanged"
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    fields: tuple[str, ...] = ()


def _key(rule: dict[str, Any]) -> str:
    return str(rule.get("action_type") or "")


def _active(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Rules keyed by action, ignoring deactivated ones.

    One rule per action is the shape the Care Agent produces and the shape the
    schedule assumes — two watering rules on one plant would materialise two tasks
    and tell the user to water twice, which `care_rule_validation` rejects at
    ingest. Keyed on action here for the same reason.
    """
    return {_key(r): r for r in rules if r.get("is_active", True) and _key(r)}


def diff_rules(
    current: list[dict[str, Any]] | None,
    proposed: list[dict[str, Any]] | None,
) -> list[RuleChange]:
    """Compare two sets of care rules, newest change first.

    An empty `current` yields every proposed rule as `added`, which is the honest
    description of a first plan — the caller decides whether to render that as a
    diff or simply as the plan.

    Ordered so what changed comes before what did not: a user scanning this is
    looking for the difference, and putting six unchanged rules above the one that
    moved is the same failure as hiding it in an expander.
    """
    before = _active(current or [])
    after = _active(proposed or [])

    changes: list[RuleChange] = []

    for action in sorted(after.keys() | before.keys()):
        old = before.get(action)
        new = after.get(action)

        if old is None and new is not None:
            changes.append(RuleChange(action, "added", after=new))
        elif new is None and old is not None:
            changes.append(RuleChange(action, "removed", before=old))
        elif old is not None and new is not None:
            differing = tuple(
                field
                for field in COMPARED
                if _normalise(old.get(field)) != _normalise(new.get(field))
            )
            changes.append(
                RuleChange(
                    action,
                    "changed" if differing else "unchanged",
                    before=old,
                    after=new,
                    fields=differing,
                )
            )

    order = {"changed": 0, "added": 1, "removed": 2, "unchanged": 3}
    return sorted(changes, key=lambda c: (order[c.kind], c.action_type))


def _normalise(value: Any) -> Any:
    """Compare `08:00` and `08:00:00` as equal.

    Postgres returns `time` as `HH:MM:SS`; the agent's contract accepts `HH:MM`.
    Without this every proposal would report a time change on every rule, which
    would make the whole diff worthless by crying wolf on all of it.
    """
    if value is None:
        return None
    text = str(value)
    if len(text) == 5 and text[2] == ":":
        return f"{text}:00"
    return text


def has_changes(changes: list[RuleChange]) -> bool:
    return any(change.kind != "unchanged" for change in changes)
