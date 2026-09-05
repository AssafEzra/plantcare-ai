"""The Care Agent's contract (FINAL §12).

Two things are being defended here.

The first is the separation of professional recommendations from operational
rules. It looks like a schema detail and it is actually the product rule: the
user may change frequency and time, and may not edit advice. If the two were one
blob, every operational tweak would rewrite the advice underneath it.

The second is that a plan the scheduler cannot honour never reaches the database.
A rule with an impossible interval fails a CHECK constraint, and that failure
takes the whole insert with it — losing the six good rules alongside the bad one.
"""

from __future__ import annotations

import uuid
from datetime import time

import pytest
from pydantic import ValidationError

from app.agents.care.agent import CareAgent
from app.agents.care.contract import (
    CareContext,
    CarePlanOutput,
    CarePlanRequest,
    ProposedRule,
    Recommendations,
)
from app.common.enums import (
    AgentType,
    CarePlanVersionSourceType,
    CareRuleActionType,
    Weekday,
)
from app.common.errors import AgentError
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.mock_provider import MockProvider

RECS = Recommendations(
    summary="הצמח נמצא בחדר מואר ודורש השקיה מתונה לאורך כל השנה.",
    watering="להשקות כשהמצע יבש לעומק שלושה סנטימטרים.",
    light="אור עקיף בהיר, מטר מהחלון.",
)


def context(**overrides) -> CareContext:
    base = {
        "plant_name": "מונסטרה",
        "scientific_name": "Monstera deliciosa",
        "common_name": "מונסטרה",
        "knowledge_sections": {"watering": "השקיה מתונה", "light": "אור עקיף"},
    }
    return CareContext(**{**base, **overrides})


def agent_with(*responses) -> tuple[CareAgent, MockProvider]:
    provider = MockProvider(list(responses))
    return CareAgent(AIGateway(provider, record_executions=False)), provider


def plan(*rules: ProposedRule, **kwargs) -> CarePlanOutput:
    return CarePlanOutput(recommendations=RECS, rules=list(rules), **kwargs)


WATERING = ProposedRule(action_type=CareRuleActionType.WATERING, interval_days=7)


def request(reason: CarePlanVersionSourceType = CarePlanVersionSourceType.INITIAL_PLAN, **kw):
    return CarePlanRequest(context=context(), reason=reason, **kw)


# --- the schema ---------------------------------------------------------------


def test_recommendations_and_rules_are_separate_fields():
    """FINAL §12's rule is only expressible because these are two things.

    A user may edit the second and not the first, so a single blob would make
    "professional recommendations are not directly editable" unenforceable.
    """
    assert "recommendations" in CarePlanOutput.model_fields
    assert "rules" in CarePlanOutput.model_fields
    assert "interval_days" not in Recommendations.model_fields


def test_a_rule_carrying_advice_fields_is_refused():
    with pytest.raises(ValidationError):
        ProposedRule(
            action_type=CareRuleActionType.WATERING, interval_days=7, recommendations="..."
        )


@pytest.mark.parametrize("interval", [0, 366, -5])
def test_the_schema_refuses_an_unschedulable_interval(interval: int):
    """Mirrors `care_rules_interval_sane`. Failing here is a retry; failing at
    the database is a 500."""
    with pytest.raises(ValidationError):
        ProposedRule(action_type=CareRuleActionType.WATERING, interval_days=interval)


def test_the_schema_refuses_a_weekday_on_a_non_weekly_interval():
    """A7, caught before the CHECK constraint sees it."""
    with pytest.raises(ValidationError):
        ProposedRule(
            action_type=CareRuleActionType.WATERING,
            interval_days=5,
            preferred_weekday=Weekday.FRIDAY,
        )


def test_a_weekday_on_a_weekly_interval_is_accepted():
    rule = ProposedRule(
        action_type=CareRuleActionType.WATERING,
        interval_days=14,
        preferred_weekday=Weekday.FRIDAY,
    )
    assert rule.preferred_weekday is Weekday.FRIDAY


def test_an_unknown_action_type_is_refused():
    """A19 made `action_type` a closed enum precisely so a model cannot invent
    'SINGING_TO_IT' and have it stored."""
    with pytest.raises(ValidationError):
        ProposedRule(action_type="SINGING_TO_IT", interval_days=7)


# --- the agent ----------------------------------------------------------------


def test_a_plan_comes_back_with_its_rules(env):
    agent, _ = agent_with(plan(WATERING))
    result = agent.generate_plan(request(), request_id=uuid.uuid4())

    assert result.recommendations.summary == RECS.summary
    assert [r.action_type for r in result.rules] == [CareRuleActionType.WATERING]


def test_an_implausible_rule_is_dropped_and_the_rest_survive(env):
    """Dropping the individual rule rather than failing the plan.

    The database would reject the whole insert, losing the good rules with the
    bad one — a plan with three sensible rules is worth keeping.
    """
    agent, _ = agent_with(
        plan(
            WATERING,
            ProposedRule(action_type=CareRuleActionType.REPOTTING, interval_days=3),
            ProposedRule(action_type=CareRuleActionType.PRUNING, interval_days=30),
        )
    )
    result = agent.generate_plan(request(), request_id=uuid.uuid4())

    assert [r.action_type for r in result.rules] == [
        CareRuleActionType.WATERING,
        CareRuleActionType.PRUNING,
    ]


def test_a_duplicate_action_type_is_collapsed_to_the_first(env):
    """Two watering rules would have the scheduler tell the user to water the
    same plant twice. The model lists in priority order, so the first wins."""
    agent, _ = agent_with(
        plan(
            WATERING,
            ProposedRule(action_type=CareRuleActionType.WATERING, interval_days=3),
        )
    )
    result = agent.generate_plan(request(), request_id=uuid.uuid4())

    assert len(result.rules) == 1
    assert result.rules[0].interval_days == 7


def test_a_plan_with_no_schedulable_rule_raises(env):
    """FINAL §25. A proposal with no rules would appear in the user's list looking
    approvable, and approving it would activate a plan that schedules nothing —
    exactly the authoritative record a failed AI operation must not create."""
    agent, _ = agent_with(
        plan(ProposedRule(action_type=CareRuleActionType.REPOTTING, interval_days=2))
    )

    with pytest.raises(AgentError):
        agent.generate_plan(request(), request_id=uuid.uuid4())


def test_the_reason_reaches_the_prompt(env):
    """A HEALTH_DRIVEN revision should not read like a first plan."""
    agent, provider = agent_with(plan(WATERING))
    agent.generate_plan(request(CarePlanVersionSourceType.HEALTH_DRIVEN), request_id=uuid.uuid4())

    assert "בדיקת בריאות" in provider.calls[0]["prompt"]


def test_the_context_reaches_the_prompt(env):
    """FINAL §12 lists seven inputs. A plan built from the species alone is a
    species article, not a plan for this plant in this room."""
    agent, provider = agent_with(plan(WATERING))
    agent.generate_plan(
        CarePlanRequest(
            context=context(
                environment={"light_level": "LOW", "has_drainage_hole": False},
                current_health_status="NEEDS_ATTENTION",
                care_history=[{"event_type": "DONE", "event_at": "2026-09-01"}],
            ),
            reason=CarePlanVersionSourceType.INITIAL_PLAN,
        ),
        request_id=uuid.uuid4(),
    )

    sent = provider.calls[0]["prompt"]
    assert "Monstera deliciosa" in sent
    assert "LOW" in sent
    assert "NEEDS_ATTENTION" in sent
    assert "היסטוריית טיפול בפועל" in sent


def test_existing_rules_are_shown_when_revising(env):
    """A revision should change what the reason calls for and leave the rest.

    Without the current rules in context the model is starting over, and a user
    who changed one thing finds their whole schedule rearranged.
    """
    agent, provider = agent_with(plan(WATERING))
    agent.generate_plan(
        CarePlanRequest(
            context=context(),
            reason=CarePlanVersionSourceType.ENVIRONMENT_CHANGE,
            current_rules=[{"action_type": "WATERING", "interval_days": 5}],
        ),
        request_id=uuid.uuid4(),
    )

    assert "כללי הטיפול הקיימים" in provider.calls[0]["prompt"]


def test_missing_context_is_carried_but_asks_nothing(env):
    """A20: the MVP renders these on the card and produces a plan anyway.

    There is no status, table or endpoint that could carry a question back, so a
    plan withheld pending an answer would be a plan nobody ever gets.
    """
    agent, _ = agent_with(plan(WATERING, missing_context=["גודל העציץ", "האם יש חור ניקוז"]))
    result = agent.generate_plan(request(), request_id=uuid.uuid4())

    assert result.missing_context == ["גודל העציץ", "האם יש חור ניקוז"]
    assert result.is_actionable


def test_the_agent_uses_the_care_model(env):
    agent, provider = agent_with(plan(WATERING))
    agent.generate_plan(request(), request_id=uuid.uuid4())

    assert agent.agent_type is AgentType.CARE
    assert provider.calls[0]["model"] == agent.gateway.model_for(AgentType.CARE)


def test_run_is_not_the_entry_point(env):
    agent, _ = agent_with()
    with pytest.raises(NotImplementedError):
        agent.run(request())


def test_a_rule_defaults_to_a_morning_reminder():
    assert ProposedRule(
        action_type=CareRuleActionType.WATERING, interval_days=7
    ).preferred_time_local == time(8, 0)
