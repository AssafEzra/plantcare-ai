"""The Health Agent's contract (FINAL §16).

    HealthAgent.assess(request) -> HealthAssessment

The schema is where "must not present definitive diagnosis" is enforced. §16 says
it in prose and gives the phrasing to use — *possible issue*, *signs that may be
consistent with*, *worth checking* — and prose in a prompt is a request. The
model is asked for `possible_issues` carrying `evidence`, never for a diagnosis
carrying a name, and the field names are half the instruction.

Two things the model is deliberately **not** asked for:

* **`trend`** — a comparison between stored assessments, computed in Python
  (A11). A model shown one photograph would answer from that photograph, which is
  the one thing a trend is not about.
* **`confidence_level` when the verdict is UNKNOWN** — a CHECK constraint forbids
  the combination, because "we could not tell, and we are confident" contradicts
  itself on screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.common.enums import ConfidenceLevel, HealthStatus
from app.infrastructure.ai.provider import ImageInput

# FINAL §16: 1-4 images. Enforced in the schema, at the route, and by a database
# constraint, because it is the one input the assessment cannot be honest without.
MIN_IMAGES = 1
MAX_IMAGES = 4

MAX_OBSERVATIONS = 8
MAX_ISSUES = 5
MAX_RECOMMENDATIONS = 6


class Observation(BaseModel):
    """Something visible in the photographs.

    An observation is what the model can *see* — "the lower leaves are yellowing
    from the tip". Kept separate from an issue, which is what that might mean,
    because the first is far more reliable than the second and the interface
    should be able to show them differently.
    """

    model_config = {"extra": "forbid"}

    observation_text: str = Field(min_length=5, max_length=500)
    confidence_level: ConfidenceLevel | None = None

    @field_validator("observation_text")
    @classmethod
    def _collapse(cls, value: str) -> str:
        return " ".join(value.split())


class PossibleIssue(BaseModel):
    """A possible explanation. Never a diagnosis.

    `evidence` is required rather than optional: an issue with nothing behind it
    is a guess presented as a finding, and the user cannot weigh it. Requiring
    the model to say *why* also makes a hallucinated issue harder to produce.
    """

    model_config = {"extra": "forbid"}

    issue_name: str = Field(min_length=2, max_length=200)
    evidence: str = Field(min_length=5, max_length=500)
    severity: int | None = Field(default=None, ge=1, le=5)
    confidence_level: ConfidenceLevel | None = None

    @field_validator("issue_name", "evidence")
    @classmethod
    def _collapse(cls, value: str) -> str:
        return " ".join(value.split())


class Recommendation(BaseModel):
    """Something to do about it.

    `requires_care_plan_adjustment` is the only route from a health finding to
    the care plan, and it is a *request* — FINAL §16 is explicit that the Health
    Agent cannot modify the plan. It raises a proposal the user approves.
    """

    model_config = {"extra": "forbid"}

    recommendation_text: str = Field(min_length=5, max_length=500)
    priority: int | None = Field(default=None, ge=1, le=5)
    requires_care_plan_adjustment: bool = False

    @field_validator("recommendation_text")
    @classmethod
    def _collapse(cls, value: str) -> str:
        return " ".join(value.split())


class HealthOutput(BaseModel):
    """The schema the model is asked to fill.

    No `trend` field, deliberately (A11). No place for a definitive diagnosis
    either: `possible_issues` is the only slot for what might be wrong, and each
    entry must carry its evidence.
    """

    model_config = {"extra": "forbid"}

    overall_status: HealthStatus
    confidence_level: ConfidenceLevel | None = None
    requires_attention: bool = False
    observations: list[Observation] = Field(default_factory=list, max_length=MAX_OBSERVATIONS)
    possible_issues: list[PossibleIssue] = Field(default_factory=list, max_length=MAX_ISSUES)
    recommendations: list[Recommendation] = Field(
        default_factory=list, max_length=MAX_RECOMMENDATIONS
    )
    insufficient_information_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _unknown_is_explained_and_unconfident(self) -> HealthOutput:
        """Mirrors the two CHECK constraints on `health_assessments`.

        FINAL §16: an insufficient check is saved as UNKNOWN *with the reason*.
        An UNKNOWN with no explanation is indistinguishable from a bug, and an
        UNKNOWN carrying a confidence level contradicts itself. Catching both
        here turns a database error into a retry the gateway can spend.
        """
        if self.overall_status is HealthStatus.UNKNOWN:
            if not (self.insufficient_information_reason or "").strip():
                raise ValueError("an UNKNOWN assessment must say why")
            if self.confidence_level is not None:
                raise ValueError("an UNKNOWN assessment cannot carry a confidence level")
        return self


@dataclass(frozen=True)
class HealthContext:
    """Everything §16 lists as an input, assembled by orchestration.

    The agent has no client and no repository: it sees photographs and this, and
    nothing else.
    """

    plant_name: str | None
    scientific_name: str
    common_name: str | None = None
    knowledge_sections: dict[str, str] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    previous_assessments: list[dict[str, Any]] = field(default_factory=list)
    care_history: list[dict[str, Any]] = field(default_factory=list)
    current_care_rules: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class HealthRequest:
    images: list[ImageInput]
    context: HealthContext
    user_note: str | None = None
    # A25: the quality gate warns rather than blocks, and its warnings are given
    # to the model as context. A model told the photographs are blurred is far
    # likelier to return UNKNOWN honestly than one left to discover it.
    image_warnings: list[str] = field(default_factory=list)


@dataclass
class HealthResult:
    """What the agent concluded.

    `trend` is absent: it is computed by the orchestration layer from stored
    history, and putting a field here would invite someone to fill it from the
    model.
    """

    overall_status: HealthStatus
    confidence_level: ConfidenceLevel | None = None
    requires_attention: bool = False
    observations: list[Observation] = field(default_factory=list)
    possible_issues: list[PossibleIssue] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    insufficient_information_reason: str | None = None

    @property
    def wants_care_adjustment(self) -> bool:
        """Whether any recommendation asks for the care plan to be revisited."""
        return any(r.requires_care_plan_adjustment for r in self.recommendations)
