"""AI Gateway behaviour.

The rules under test are the ones FINAL §23 and §25 state as absolutes: at most
two retries, only schema failures are retried, every attempt is logged, and no
attempt log ever carries reasoning. These are the guarantees the rest of the
system leans on when it assumes a failed agent call left nothing behind.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import BaseModel, Field

from app.common.enums import AgentRequestStatus, AgentType
from app.common.errors import AgentError, AgentSchemaError, AgentTimeoutError
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.mock_provider import MockProvider
from app.infrastructure.ai.prompts import Prompt
from app.infrastructure.ai.provider import ProviderError, ProviderTimeoutError


class Answer(BaseModel):
    species: str
    confidence: float = Field(ge=0, le=1)


PROMPT = Prompt(agent=AgentType.IDENTIFICATION, name="identify", version="001", text="system text")
GOOD = Answer(species="Monstera deliciosa", confidence=0.9)


def gateway(provider: MockProvider) -> AIGateway:
    # Execution logging is exercised separately; switching it off here keeps these
    # unit tests free of a database.
    return AIGateway(provider, record_executions=False)


def run(gw: AIGateway, **kwargs):
    return gw.run(
        agent=AgentType.IDENTIFICATION,
        request_id=uuid4(),
        prompt=PROMPT,
        user_content="analyse this",
        schema=Answer,
        **kwargs,
    )


# --- the happy path -----------------------------------------------------------


def test_a_valid_response_is_returned(env):
    provider = MockProvider([GOOD])

    result = run(gateway(provider))

    assert result.value.species == "Monstera deliciosa"
    assert result.attempts == 1


def test_a_dict_response_is_validated_into_the_schema(env):
    provider = MockProvider([{"species": "Ficus lyrata", "confidence": 0.7}])

    result = run(gateway(provider))

    assert isinstance(result.value, Answer)


# --- the retry budget ---------------------------------------------------------


def test_a_malformed_response_is_retried(env):
    """§23: invalid structured output is retried automatically."""
    provider = MockProvider([{"species": "x"}, GOOD])  # first lacks `confidence`

    result = run(gateway(provider))

    assert result.attempts == 2
    assert provider.call_count == 2


def test_two_failures_then_success_is_within_budget(env):
    provider = MockProvider([{"bad": 1}, {"bad": 2}, GOOD])

    result = run(gateway(provider))

    assert result.attempts == 3


def test_the_budget_is_exactly_three_attempts(env):
    """Two retries means three attempts. A fourth call would mean the ceiling in
    §23 had been exceeded - and would violate the CHECK on agent_executions."""
    provider = MockProvider([{"bad": 1}, {"bad": 2}, {"bad": 3}, GOOD])

    with pytest.raises(AgentSchemaError):
        run(gateway(provider))

    assert provider.call_count == 3, "the gateway exceeded its retry budget"


def test_exhausting_the_budget_raises_rather_than_returning_garbage(env):
    """FINAL §25 hangs on this: the caller must get an exception, not a partial
    value it might mistake for a result and persist."""
    provider = MockProvider([{"bad": 1}] * 3)

    with pytest.raises(AgentSchemaError):
        run(gateway(provider))


def test_out_of_range_values_are_treated_as_schema_failures(env):
    """A confidence of 5.0 is well-formed JSON and still nonsense; the schema is
    what makes it a failure."""
    provider = MockProvider([{"species": "x", "confidence": 5.0}, GOOD])

    result = run(gateway(provider))

    assert result.attempts == 2


# --- what is not retried ------------------------------------------------------


def test_a_timeout_is_not_retried(env):
    """Retrying a timeout spends the budget on something that will not succeed,
    while the user waits longer for the same failure."""
    provider = MockProvider([ProviderTimeoutError("slow"), GOOD])

    with pytest.raises(AgentTimeoutError):
        run(gateway(provider))

    assert provider.call_count == 1


def test_a_provider_error_is_not_retried(env):
    provider = MockProvider([ProviderError("500 from upstream"), GOOD])

    with pytest.raises(AgentError):
        run(gateway(provider))

    assert provider.call_count == 1


# --- execution records --------------------------------------------------------


def test_every_attempt_is_recorded(env):
    provider = MockProvider([{"bad": 1}, GOOD])

    result = run(gateway(provider))

    assert len(result.executions) == 2
    assert [e.status for e in result.executions] == [
        AgentRequestStatus.FAILED,
        AgentRequestStatus.SUCCEEDED,
    ]
    assert [e.attempt for e in result.executions] == [1, 2]


def test_a_successful_record_carries_cost_and_tokens(env):
    """FINAL §29: admin monitoring shows model, duration and cost metadata."""
    provider = MockProvider([GOOD])

    record = run(gateway(provider)).executions[0]

    assert record.input_tokens == 100
    assert record.output_tokens == 50
    assert record.latency_ms >= 0
    assert record.prompt_version == "identification/identify.v001"


def test_a_failed_record_carries_a_code_but_no_response(env):
    provider = MockProvider([ProviderTimeoutError("slow")])

    with pytest.raises(AgentTimeoutError):
        run(gateway(provider))


def test_no_execution_field_can_hold_reasoning(env):
    """FINAL §23 forbids storing chain-of-thought. The record has nowhere to put
    it, which is a stronger guarantee than remembering not to."""
    provider = MockProvider([GOOD])

    row = run(gateway(provider)).executions[0].to_row()

    forbidden = {
        "reasoning",
        "thinking",
        "chain_of_thought",
        "raw_response",
        "raw_prompt",
        "prompt",
    }
    assert not (set(row) & forbidden)


def test_an_error_message_is_truncated(env):
    """A provider can return a very long string; the log is for diagnosis."""
    provider = MockProvider([ProviderError("x" * 5000)])

    with pytest.raises(AgentError):
        run(gateway(provider))


# --- model selection ----------------------------------------------------------


@pytest.mark.parametrize(
    ("agent", "setting"),
    [
        (AgentType.IDENTIFICATION, "identification_model"),
        (AgentType.KNOWLEDGE, "knowledge_model"),
        (AgentType.CARE, "care_model"),
        (AgentType.HEALTH, "health_model"),
    ],
)
def test_each_agent_uses_its_configured_model(env, agent: AgentType, setting: str):
    """FINAL §23: models are configuration, swappable without touching agent code."""
    from app.config.settings import get_settings

    gw = gateway(MockProvider())

    assert gw.model_for(agent) == getattr(get_settings(), setting)


def test_the_configured_model_reaches_the_provider(env):
    provider = MockProvider([GOOD])

    run(gateway(provider))

    assert provider.calls[0]["model"] == "test-model"


def test_the_prompt_text_is_sent_as_the_system_prompt(env):
    provider = MockProvider([GOOD])

    run(gateway(provider))

    assert provider.calls[0]["system"] == "system text"
