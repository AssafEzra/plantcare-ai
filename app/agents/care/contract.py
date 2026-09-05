"""The Care Agent's contract.

FINAL §12:

    CareAgent.generate_plan(request) -> CarePlanProposal

The agent turns published Knowledge plus everything known about *this* plant into
two separable things:

* **professional recommendations** — the reasoning a horticulturist would give.
  Not user-editable (FINAL §12), and carried forward byte-identical when a user
  changes an operational preference;
* **operational rules** — "water every 7 days at 08:00". Deterministic Python
  turns these into tasks; no model is involved in scheduling (FINAL §1.4).

Keeping them apart is what makes "the user may edit frequency but not advice"
expressible at all. If they were one blob, every operational tweak would rewrite
the advice underneath it.

The agent never publishes a plan. Every output here is a **proposal** that a user
approves (FINAL §12), which is why the result type says so in its name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.common.enums import CarePlanVersionSourceType, CareRuleActionType, Weekday

# A rule the model proposes must be schedulable. These bounds mirror the CHECK
# constraints on `care_rules` exactly - a value the database would reject should
# fail schema validation and be retried, not reach the database and 500.
MIN_INTERVAL_DAYS = 1
MAX_INTERVAL_DAYS = 365

# At most this many rules in one plan. A plan with twenty recurring actions is not
# a care plan, it is a chore list nobody will follow, and each rule becomes a
# recurring notification.
MAX_RULES = 8


class ProposedRule(BaseModel):
    """One recurring action, as the model proposes it."""

    model_config = {"extra": "forbid"}

    action_type: CareRuleActionType
    interval_days: int = Field(ge=MIN_INTERVAL_DAYS, le=MAX_INTERVAL_DAYS)
    preferred_time_local: time = Field(default=time(8, 0))
    preferred_weekday: Weekday | None = None
    instructions: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _weekday_needs_a_weekly_interval(self) -> ProposedRule:
        """A7, enforced here as well as in SQL.

        Anchoring a weekday to a 5-day interval is incoherent: the recurrence
        cannot land on Friday every five days. The database rejects it with a
        CHECK; catching it here turns a 500 into a retry, which is what the
        gateway's schema-failure path is for.
        """
        if self.preferred_weekday is not None and self.interval_days % 7 != 0:
            raise ValueError("preferred_weekday requires an interval that is a multiple of 7")
        return self


class Recommendations(BaseModel):
    """The professional half of a plan.

    Prose, not parameters. `FINAL §12` forbids the user editing this, so it is
    kept structurally separate from `operational_preferences` rather than merely
    documented as read-only.
    """

    model_config = {"extra": "forbid"}

    summary: str = Field(min_length=20, max_length=1500)
    watering: str = Field(min_length=10, max_length=1500)
    light: str = Field(min_length=10, max_length=1500)
    feeding: str | None = Field(default=None, max_length=1500)
    seasonal_notes: str | None = Field(default=None, max_length=1500)
    warnings: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("summary", "watering", "light", "feeding", "seasonal_notes")
    @classmethod
    def _collapse(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value else value


class CarePlanOutput(BaseModel):
    """The schema the model is asked to fill."""

    model_config = {"extra": "forbid"}

    recommendations: Recommendations
    rules: list[ProposedRule] = Field(default_factory=list, max_length=MAX_RULES)
    change_summary: str | None = Field(
        default=None,
        max_length=500,
        description="One sentence on what changed and why, for a plan that revises an "
        "existing one. Shown to the user on the proposal card.",
    )
    missing_context: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Facts that would have made this plan better, phrased for a user. "
        "A20: the MVP renders these on the proposal card and does not ask questions.",
    )


@dataclass(frozen=True)
class CareContext:
    """Everything the agent is allowed to see, assembled by orchestration.

    FINAL §12 lists the inputs; this is that list and nothing else. The agent has
    no client and no repository — `tests/unit/test_architecture_boundaries.py`
    fails the build if it acquires one — so this dataclass is the entire world
    from inside `generate_plan`.
    """

    plant_name: str | None
    scientific_name: str
    common_name: str | None
    knowledge_sections: dict[str, str]
    environment: dict[str, Any] = field(default_factory=dict)
    current_health_status: str | None = None
    health_history: list[dict[str, Any]] = field(default_factory=list)
    care_history: list[dict[str, Any]] = field(default_factory=list)
    user_preferences: dict[str, Any] = field(default_factory=dict)
    timezone: str = "Asia/Jerusalem"


@dataclass(frozen=True)
class CarePlanRequest:
    """A request for a plan, and why it is being made.

    `reason` becomes `care_plan_versions.source_type`, which the schema calls the
    single provenance trail for a version. Carrying it into the request means the
    agent can also *use* it: a HEALTH_DRIVEN revision should read differently from
    a first plan.
    """

    context: CareContext
    reason: CarePlanVersionSourceType
    note: str | None = None
    current_rules: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CarePlanProposal:
    """What the agent concluded. Still a proposal — nothing is active until the
    user approves it (FINAL §12)."""

    recommendations: Recommendations
    rules: list[ProposedRule] = field(default_factory=list)
    change_summary: str | None = None
    missing_context: list[str] = field(default_factory=list)

    @property
    def is_actionable(self) -> bool:
        """A plan with no rules schedules nothing.

        Recommendations alone are worth showing, but approving them would produce
        a plan that never reminds the user of anything — so the workflow treats
        this as a failed proposal rather than an empty success.
        """
        return bool(self.rules)
