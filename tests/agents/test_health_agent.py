"""The Health Agent's contract (FINAL §16).

Two rules are being defended, and both are enforced by the schema rather than by
the prompt — a prompt is a request, and this is a product where a confident wrong
answer can kill a plant.

**No definitive diagnosis.** The model is asked for `possible_issues`, each
carrying the `evidence` it was drawn from. There is no field for a diagnosis and
no way to assert one without pointing at something visible.

**`UNKNOWN` is a real answer.** §16 asks for an insufficient check to be *saved*
with its reason. So an UNKNOWN must explain itself, must not carry a confidence
level, and must not arrive alongside a list of things that might be wrong —
because a model that could not tell what it was looking at cannot also know that.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.agents.health.agent import HealthAgent
from app.agents.health.contract import (
    HealthContext,
    HealthOutput,
    HealthRequest,
    Observation,
    PossibleIssue,
    Recommendation,
)
from app.common.enums import AgentType, ConfidenceLevel, HealthStatus
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.mock_provider import MockProvider
from app.infrastructure.ai.provider import ImageInput

IMAGE = ImageInput(data=b"\xff\xd8\xff-not-decoded-here", mime_type="image/jpeg")

OBSERVATION = Observation(observation_text="שלושת העלים התחתונים מצהיבים מהקצה פנימה.")
ISSUE = PossibleIssue(
    issue_name="ייתכן עודף השקיה",
    evidence="הצהבה אחידה בעלים התחתונים בלבד, ומצע לח למראה.",
    severity=3,
)
RECOMMENDATION = Recommendation(
    recommendation_text="להאריך את מרווח ההשקיה בשלושה ימים ולבדוק ניקוז.",
    requires_care_plan_adjustment=True,
)


def context() -> HealthContext:
    return HealthContext(
        plant_name="המונסטרה",
        scientific_name="Monstera deliciosa",
        common_name="מונסטרה",
    )


def agent_with(*responses) -> tuple[HealthAgent, MockProvider]:
    provider = MockProvider(list(responses))
    return HealthAgent(AIGateway(provider, record_executions=False)), provider


def request(**kwargs) -> HealthRequest:
    return HealthRequest(images=[IMAGE], context=context(), **kwargs)


# --- no definitive diagnosis ----------------------------------------------------


def test_a_possible_issue_must_carry_its_evidence():
    """An issue with nothing behind it is a guess presented as a finding, and the
    user cannot weigh it. Requiring the *why* also makes a hallucinated issue
    harder to produce."""
    with pytest.raises(ValidationError):
        PossibleIssue(issue_name="ריקבון שורשים")


def test_there_is_no_field_for_a_diagnosis():
    """The schema is the enforcement. Prose in a prompt is a request."""
    assert "diagnosis" not in HealthOutput.model_fields
    assert "possible_issues" in HealthOutput.model_fields


def test_observations_and_issues_are_separate():
    """What is visibly there, and what it might mean. The first is far more
    reliable, and the interface shows them differently for that reason."""
    assert "observation_text" in Observation.model_fields
    assert "evidence" not in Observation.model_fields
    assert "issue_name" in PossibleIssue.model_fields


def test_severity_is_bounded():
    for bad in (0, 6, -1):
        with pytest.raises(ValidationError):
            PossibleIssue(issue_name="x", evidence="evidence here", severity=bad)


# --- UNKNOWN ---------------------------------------------------------------------


def test_an_unknown_verdict_must_explain_itself():
    """FINAL §16: save an UNKNOWN *with the reason*. An unexplained UNKNOWN is
    indistinguishable from a bug, and a CHECK constraint says so too."""
    with pytest.raises(ValidationError):
        HealthOutput(overall_status=HealthStatus.UNKNOWN)


def test_an_unknown_verdict_cannot_carry_confidence():
    """ "We could not tell, and we are confident" contradicts itself on screen."""
    with pytest.raises(ValidationError):
        HealthOutput(
            overall_status=HealthStatus.UNKNOWN,
            insufficient_information_reason="התמונות מטושטשות.",
            confidence_level=ConfidenceLevel.HIGH,
        )


def test_a_known_verdict_needs_no_reason():
    assert HealthOutput(overall_status=HealthStatus.HEALTHY).overall_status is HealthStatus.HEALTHY


def test_an_unknown_result_is_stripped_of_issues_and_recommendations(env):
    """A model that could not tell what it was looking at has no business also
    listing what might be wrong. Showing both would let a user act on findings the
    verdict itself disowns."""
    agent, _ = agent_with(
        HealthOutput(
            overall_status=HealthStatus.UNKNOWN,
            insufficient_information_reason="התמונות מטושטשות מדי.",
            observations=[OBSERVATION],
            possible_issues=[ISSUE],
            recommendations=[RECOMMENDATION],
        )
    )
    result = agent.assess(request(), request_id=uuid.uuid4())

    assert result.overall_status is HealthStatus.UNKNOWN
    assert result.possible_issues == []
    assert result.recommendations == []
    assert result.confidence_level is None
    # Observations survive: "I can see the leaves are yellow" is still true even
    # when what it means is not.
    assert result.observations


def test_an_unknown_result_may_still_ask_for_attention(env):
    """The one flag an inconclusive check can honestly raise."""
    agent, _ = agent_with(
        HealthOutput(
            overall_status=HealthStatus.UNKNOWN,
            insufficient_information_reason="לא ניתן לראות את העלים.",
            requires_attention=True,
        )
    )
    assert agent.assess(request(), request_id=uuid.uuid4()).requires_attention


def test_a_failed_assessment_becomes_unknown_rather_than_raising(env):
    """FINAL §16 wants an unusable check saved with its reason. The row is honest
    about itself — no confidence, no issues — so §25 holds by its shape."""
    agent, _ = agent_with(*[{"overall_status": "NOT_A_STATUS"}] * 3)

    result = agent.assess(request(), request_id=uuid.uuid4())

    assert result.overall_status is HealthStatus.UNKNOWN
    assert result.insufficient_information_reason


# --- the trend is not the model's ------------------------------------------------


def test_the_model_is_never_asked_for_a_trend():
    """A11. A trend compares stored assessments; a model shown one photograph
    would answer from that photograph, which is the one thing it is not about."""
    assert "trend" not in HealthOutput.model_fields


def test_the_result_carries_no_trend_field():
    """No field means nobody can quietly fill it from model output."""
    from app.agents.health.contract import HealthResult

    assert "trend" not in HealthResult.__dataclass_fields__


# --- context and inputs ----------------------------------------------------------


def test_no_images_is_refused_before_a_model_call(env):
    """Not a model failure, so it must not spend a call or a retry."""
    from app.common.errors import ValidationFailedError

    agent, provider = agent_with()
    with pytest.raises(ValidationFailedError):
        agent.assess(HealthRequest(images=[], context=context()), request_id=uuid.uuid4())
    assert provider.call_count == 0


def test_image_quality_warnings_reach_the_model(env):
    """A25. A model told the photographs are weak returns UNKNOWN honestly far
    more often than one left to work it out."""
    agent, provider = agent_with(HealthOutput(overall_status=HealthStatus.HEALTHY))
    agent.assess(request(image_warnings=["התמונה נראית מטושטשת."]), request_id=uuid.uuid4())

    assert "מטושטשת" in provider.calls[0]["prompt"]


def test_the_users_note_is_framed_as_a_description_not_a_finding(env):
    """A model told "the leaves are rotting" will tend to agree."""
    agent, provider = agent_with(HealthOutput(overall_status=HealthStatus.HEALTHY))
    agent.assess(request(user_note="נראה לי שיש ריקבון"), request_id=uuid.uuid4())

    sent = provider.calls[0]["prompt"]
    assert "לא ממצא" in sent


def test_at_most_four_images_are_sent(env):
    """FINAL §16 caps it at four; more costs tokens without adding evidence."""
    agent, provider = agent_with(HealthOutput(overall_status=HealthStatus.HEALTHY))
    agent.assess(HealthRequest(images=[IMAGE] * 7, context=context()), request_id=uuid.uuid4())

    assert provider.calls[0]["image_count"] == 4


def test_previous_assessments_reach_the_model(env):
    """Not for the trend — for recurrence, which changes what is worth suggesting."""
    agent, provider = agent_with(HealthOutput(overall_status=HealthStatus.HEALTHY))
    agent.assess(
        HealthRequest(
            images=[IMAGE],
            context=HealthContext(
                plant_name="x",
                scientific_name="Monstera deliciosa",
                previous_assessments=[{"status": "NEEDS_ATTENTION", "assessed_at": "2026-08-01"}],
            ),
        ),
        request_id=uuid.uuid4(),
    )

    assert "בדיקות קודמות" in provider.calls[0]["prompt"]


def test_the_agent_uses_the_health_model(env):
    agent, provider = agent_with(HealthOutput(overall_status=HealthStatus.HEALTHY))
    agent.assess(request(), request_id=uuid.uuid4())

    assert agent.agent_type is AgentType.HEALTH
    assert provider.calls[0]["model"] == agent.gateway.model_for(AgentType.HEALTH)


def test_run_is_not_the_entry_point(env):
    agent, _ = agent_with()
    with pytest.raises(NotImplementedError):
        agent.run(request())


# --- the care-plan boundary -------------------------------------------------------


def test_a_recommendation_can_ask_for_a_plan_change_but_not_make_one(env):
    """FINAL §16: the Health Agent cannot modify the care plan. The flag raises a
    proposal the user approves; there is no field that could change a rule."""
    agent, _ = agent_with(
        HealthOutput(
            overall_status=HealthStatus.NEEDS_ATTENTION,
            observations=[OBSERVATION],
            possible_issues=[ISSUE],
            recommendations=[RECOMMENDATION],
        )
    )
    result = agent.assess(request(), request_id=uuid.uuid4())

    assert result.wants_care_adjustment
    assert "interval_days" not in Recommendation.model_fields
    assert "care_rule" not in Recommendation.model_fields


def test_a_result_with_no_such_flag_asks_for_nothing(env):
    agent, _ = agent_with(
        HealthOutput(
            overall_status=HealthStatus.HEALTHY,
            recommendations=[Recommendation(recommendation_text="להמשיך כרגיל.")],
        )
    )
    assert not agent.assess(request(), request_id=uuid.uuid4()).wants_care_adjustment
