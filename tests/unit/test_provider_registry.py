"""The provider registry, and the guards that keep it honest.

FINAL §23 promised that swapping AI providers was configuration rather than code.
Half of it was true - the Protocol and the agents - and the half that chose an
implementation was never written: `settings.ai_provider` existed, nothing read it,
and five call sites constructed `AnthropicProvider()` directly. It stayed that way
because nothing failed.

That is the lesson these tests encode. A spec sentence is not enforcement; the
source scan below is. Three of the four would have caught the original drift.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest

from app.common.errors import ConfigurationError
from app.config.settings import AIProviderName
from app.infrastructure.ai.provider import ModelSpec, Usage
from app.infrastructure.ai.providers import (
    PROVIDERS,
    AnthropicProvider,
    GoogleProvider,
    OpenAIProvider,
    provider_for,
)

APP = Path(__file__).resolve().parents[2] / "app"
PROVIDERS_DIR = APP / "infrastructure" / "ai" / "providers"

# The SDKs a provider module may import and nothing else may.
VENDOR_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(anthropic|openai|google\.genai|google\s+import\s+genai)\b",
    re.MULTILINE,
)


def test_every_registered_name_maps_to_its_vendor() -> None:
    assert PROVIDERS["anthropic"] is AnthropicProvider
    assert PROVIDERS["google"] is GoogleProvider
    assert PROVIDERS["openai"] is OpenAIProvider


def test_the_settings_literal_and_the_registry_cannot_drift() -> None:
    """`AIProviderName` is declared in settings to avoid an import cycle.

    That duplication is the price of validating a provider name at startup without
    `app.config.settings` importing the provider package that imports it back. The
    duplication is only safe if something notices when the two disagree.
    """
    assert set(get_args(AIProviderName)) == set(PROVIDERS)


def test_an_unknown_provider_names_itself_in_the_error() -> None:
    """The startup validator normally catches this; the backstop still explains."""
    with pytest.raises(ConfigurationError) as raised:
        provider_for("gemeni")

    message = str(raised.value)
    assert "gemeni" in message
    # And says what would have worked, because a typo is the likely cause.
    assert "anthropic" in message


def test_a_provider_is_constructible_when_its_key_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings as settings_module

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    settings_module.get_settings.cache_clear()
    try:
        assert isinstance(provider_for("anthropic"), AnthropicProvider)
    finally:
        settings_module.get_settings.cache_clear()


def test_a_missing_key_fails_at_construction_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not mid-request. A configuration mistake should not cost a user a wait."""
    from app.config import settings as settings_module

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    settings_module.get_settings.cache_clear()
    try:
        with pytest.raises(ConfigurationError) as raised:
            provider_for("google")
        assert "GOOGLE_API_KEY" in str(raised.value)
    finally:
        settings_module.get_settings.cache_clear()


def test_only_the_providers_package_imports_a_vendor_sdk() -> None:
    """The guard that was missing.

    If any other module reaches for a vendor SDK, the seam has leaked and the next
    provider swap stops being configuration. A sentence in the specification did
    not prevent that the first time.
    """
    offenders = []
    for path in APP.rglob("*.py"):
        if PROVIDERS_DIR in path.parents:
            continue
        if VENDOR_IMPORT.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(APP.parent)))

    assert offenders == [], f"vendor SDK imported outside the providers package: {offenders}"


def test_an_unpriced_model_records_no_cost_rather_than_zero() -> None:
    """The distinction the whole cost figure rests on.

    The model string is passed through to the vendor unvalidated so that a model
    released after this code was written still works. The consequence is that a
    real call can have no known price, and calling that `$0.00` is a lie that
    understates the bill - which is exactly what happened.
    """
    unknown = Usage.measured(
        input_tokens=1000, output_tokens=500, model="gemini-99-whatever", latency_ms=10, price=None
    )

    assert unknown.estimated_cost is None
    assert unknown.input_tokens == 1000


def test_a_priced_model_is_costed_from_its_own_table() -> None:
    priced = Usage.measured(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        model="claude-opus-5",
        latency_ms=10,
        price=AnthropicProvider.price("claude-opus-5"),
    )

    assert priced.estimated_cost == pytest.approx(30.00)


def test_every_price_in_every_table_is_real() -> None:
    """A forgotten price must not reappear as a zero.

    `ModelSpec(input=0, output=0)` would cost every call at nothing and look like a
    working entry, which is the failure mode this whole change exists to remove.
    """
    for name, factory in PROVIDERS.items():
        prices: dict[str, ModelSpec] = factory.PRICES  # type: ignore[attr-defined]
        assert prices, f"{name} has no price table"
        for model, spec in prices.items():
            assert spec.input > 0, f"{name}/{model} has no input price"
            assert spec.output > 0, f"{name}/{model} has no output price"


def test_a_failed_attempt_records_unknown_cost_not_free() -> None:
    from uuid import uuid4

    from app.common.enums import AgentRequestStatus, AgentType
    from app.infrastructure.ai.gateway import ExecutionRecord

    record = ExecutionRecord(
        agent_request_id=uuid4(),
        agent_type=AgentType.KNOWLEDGE,
        model="claude-opus-5",
        prompt_version="knowledge/research.v001",
        status=AgentRequestStatus.FAILED,
        attempt=1,
        error_code="AGENT_TIMEOUT",
    )

    assert record.estimated_cost is None
    assert record.to_row()["estimated_cost"] is None
    assert record.to_row()["input_tokens"] is None


def test_the_admin_execution_response_accepts_an_unknown_cost() -> None:
    """Otherwise the route 500s on the row it exists to show.

    `agent_executions` can legitimately hold nulls for tokens and cost now, so a
    response model that typed them as `int`/`float` would reject exactly the rows
    an administrator most needs to see - the ones that failed after being billed.
    """
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.api.routers.admin import ExecutionResponse

    parsed = ExecutionResponse.model_validate(
        {
            "id": uuid4(),
            "agent_request_id": uuid4(),
            "agent_type": "KNOWLEDGE",
            "model": "claude-opus-5",
            "prompt_version": "knowledge/research.v001",
            "status": "FAILED",
            "attempt": 1,
            "input_tokens": None,
            "output_tokens": None,
            "estimated_cost": None,
            "latency_ms": 90354,
            "error_code": "AGENT_TIMEOUT",
            "error_message": None,
            "created_at": datetime.now(UTC),
        }
    )

    assert parsed.estimated_cost is None
    assert parsed.input_tokens is None
