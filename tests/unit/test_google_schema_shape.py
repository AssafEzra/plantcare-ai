"""How the Google provider hands a schema to Gemini.

Written after a live failure. Every agent request on Google returned, before the
model generated anything:

    400 Invalid JSON payload received. Unknown name "additional_properties"
        at 'generation_config.response_schema'

`response_schema` routes a Pydantic class through Gemini's own Schema proto,
which has no field for `additionalProperties` - so every contract declaring
`extra="forbid"` was rejected outright. Knowledge, care and health all do;
identification does not, which is why identification worked and hid the problem.

`response_json_schema` takes standard JSON Schema instead, which is what
`model_json_schema()` emits and what the contracts are written as.

These tests need no network: the failure was in the request the provider built,
so inspecting that request is the whole check.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel


class Nested(BaseModel):
    model_config = {"extra": "forbid"}

    text: str


class Forbidding(BaseModel):
    """The shape that failed: nested, and forbidding unknown keys."""

    model_config = {"extra": "forbid"}

    inner: Nested


class _StopError(Exception):
    """Ends the call once the request has been built. Nothing else is under test."""


class _Recorder:
    """Stands in for `genai.Client`, keeping the config it was called with."""

    def __init__(self) -> None:
        self.config: Any = None
        self.models = self

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.config = config
        raise _StopError


@pytest.fixture
def recorded(env) -> _Recorder:
    from app.infrastructure.ai.providers import GoogleProvider

    env.setenv("GOOGLE_API_KEY", "not-a-real-key")
    provider = GoogleProvider.__new__(GoogleProvider)
    recorder = _Recorder()
    provider._client = recorder  # type: ignore[assignment]

    with pytest.raises(_StopError):
        provider.structured_output(
            model="gemini-3.6-flash",
            schema=Forbidding,
            system="s",
            prompt="p",
            timeout_seconds=5,
        )
    return recorder


def test_the_schema_is_sent_as_json_schema_not_as_a_pydantic_class(recorded) -> None:
    assert recorded.config.response_json_schema is not None
    # The field that cannot carry `additionalProperties`.
    assert getattr(recorded.config, "response_schema", None) is None


def test_the_json_schema_keeps_additional_properties(recorded) -> None:
    """The point of the change.

    `extra="forbid"` is a real constraint the contracts rely on, so the fix is to
    send it through a field that accepts it - not to strip it and let the model
    invent keys.
    """
    import json

    assert "additionalProperties" in json.dumps(recorded.config.response_json_schema)
