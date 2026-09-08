"""How the provider calls the SDK (PR 29).

`tests/agents/test_live_provider.py` proves the call works against the real API,
but it is marked `live`, costs money and is excluded from CI — so nothing in the
normal suite had anything to say about *how* the request is made. That is where
the Knowledge timeout lived: a correct call, made in a way that could not survive
a long generation.

These tests substitute the SDK client and assert on the request, which is the one
thing a mock provider can never check — `MockProvider` replaces this module
entirely.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel


class Colour(BaseModel):
    name: str


def _message(value: Colour) -> Any:
    """The shape `messages.stream(...).get_final_message()` returns."""
    return SimpleNamespace(
        stop_reason="end_turn",
        parsed_output=value,
        content=[],
        model="claude-opus-5",
        usage=SimpleNamespace(input_tokens=120, output_tokens=340),
    )


class _Stream:
    def __init__(self, message: Any) -> None:
        self._message = message
        self.closed = False

    def __enter__(self) -> _Stream:
        return self

    def __exit__(self, *exc: object) -> bool:
        self.closed = True
        return False

    def get_final_message(self) -> Any:
        return self._message


class _Messages:
    def __init__(self, calls: list[dict], message: Any) -> None:
        self._calls = calls
        self._message = message

    def stream(self, **kwargs: Any) -> _Stream:
        self._calls.append(kwargs)
        return _Stream(self._message)

    def parse(self, **kwargs: Any) -> Any:  # pragma: no cover - must not be reached
        raise AssertionError("the provider must stream, not block on a single response")


@pytest.fixture
def provider(env, monkeypatch: pytest.MonkeyPatch):
    """The real provider, talking to a substituted SDK client."""
    import anthropic

    calls: list[dict] = []

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.init_kwargs = kwargs
            self.messages = _Messages(calls, _message(Colour(name="blue")))

    monkeypatch.setattr(anthropic, "Anthropic", _Client)

    from app.infrastructure.ai.providers.anthropic import AnthropicProvider

    built = AnthropicProvider()
    built.calls = calls  # type: ignore[attr-defined]
    return built


def _run(provider, **overrides: Any):
    kwargs: dict[str, Any] = {
        "model": "claude-opus-5",
        "schema": Colour,
        "system": "system text",
        "prompt": "what colour is the sky?",
    }
    return provider.structured_output(**{**kwargs, **overrides})


def test_the_request_is_streamed(provider):
    """A long generation must not be measured end to end.

    The first real Knowledge research run — thirteen sections of Hebrew prose
    against `max_tokens=8000` — was cut off at ninety seconds, and a timeout is
    not retried, so the draft failed and the plant had nothing to approve. A
    streamed request is measured chunk to chunk, so a generation that is visibly
    still producing tokens is not killed for taking a while.
    """
    result = _run(provider)

    assert provider.calls, "no request was made"
    assert result.value.name == "blue"


def test_the_per_call_timeout_is_sent(provider):
    """The gateway knows which agent is calling; the client-level default does not."""
    _run(provider, timeout_seconds=600)

    assert provider.calls[0]["timeout"] == 600


def test_no_timeout_leaves_the_client_default_in_place(provider):
    """Absent, not zero, and not None: `NOT_GIVEN` is how the SDK is told to use
    what the client was built with."""
    import anthropic

    _run(provider)

    assert provider.calls[0]["timeout"] is anthropic.NOT_GIVEN


def test_reasoning_is_never_requested_for_display(provider):
    """FINAL §23 forbids persisting chain-of-thought, and the cheapest way to keep
    that true is never to receive it."""
    _run(provider)

    assert provider.calls[0]["thinking"] == {"type": "adaptive", "display": "omitted"}


# --- schema failures must stay retriable (PR 30) --------------------------------


def test_a_validation_error_from_the_stream_becomes_a_schema_failure(env, monkeypatch):
    """The regression PR 29 shipped and a user found.

    `parse()` returned a message and `_extract` validated it. The streaming helper
    validates *during accumulation*, inside `get_final_message()`, and raises
    pydantic's error straight out of the iterator — which is not a
    `SchemaValidationFailedError`, so the gateway's handlers never saw it. No
    retry, no `agent_executions` row, and the workflow's blanket `except` recorded
    a flat AGENT_FAILED: `FINAL §23`'s two retries and `§25`'s "a failed call is
    visible" were both switched off, for every agent at once.

    Found when a Health check returned `priority: 6` against a `le=5` bound and
    the user saw nothing happen at all.
    """
    import anthropic
    from pydantic import ValidationError

    from app.infrastructure.ai.provider import SchemaValidationFailedError

    class _Boom:
        def __enter__(self) -> _Boom:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def get_final_message(self) -> Any:
            raise ValidationError.from_exception_data("Colour", [])

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.messages = SimpleNamespace(stream=lambda **kwargs: _Boom())

    monkeypatch.setattr(anthropic, "Anthropic", _Client)

    from app.infrastructure.ai.providers.anthropic import AnthropicProvider

    with pytest.raises(SchemaValidationFailedError):
        AnthropicProvider().structured_output(
            model="claude-opus-5",
            schema=Colour,
            system="system text",
            prompt="what colour is the sky?",
        )
