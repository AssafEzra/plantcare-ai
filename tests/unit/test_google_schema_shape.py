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
from pydantic import BaseModel, Field


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


# --- the second vendor limit ---------------------------------------------------


class Section(BaseModel):
    """A knowledge section, in miniature - constraints and all."""

    model_config = {"extra": "forbid"}

    text: str = Field(min_length=20, max_length=4000, description="the section text")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class Article(BaseModel):
    model_config = {"extra": "forbid"}

    # One section is called `description`, exactly as KnowledgeContent has.
    description: Section
    light: Section


def test_the_constraint_keywords_gemini_refuses_are_removed() -> None:
    """`KnowledgeOutput` was refused with an unlocalised "invalid argument"
    until these were dropped. Which one is responsible is still unknown."""
    import json

    from app.infrastructure.ai.providers.google import _to_gemini_schema

    sent = json.dumps(_to_gemini_schema(Article))

    for keyword in ("maxLength", "minLength", "minimum", "maximum", "title", "default"):
        assert keyword not in sent, f"{keyword} should not reach Gemini"


def test_descriptions_survive_because_they_instruct_the_model() -> None:
    """The reason the filter is a list and not "strip everything unrecognised".

    A description tells the model what to write. Dropping it to appease a schema
    validator would trade a 400 for a quietly worse article.
    """
    import json

    from app.infrastructure.ai.providers.google import _to_gemini_schema

    assert "the section text" in json.dumps(_to_gemini_schema(Article))


def test_a_property_named_description_is_not_mistaken_for_the_keyword() -> None:
    """The trap that cost an extra round trip.

    Filtering by key name without knowing you are inside `properties` deletes the
    knowledge section called `description` while leaving it in `required`, and
    Gemini then refuses the schema for a completely different reason.
    """
    from app.infrastructure.ai.providers.google import _to_gemini_schema

    sent = _to_gemini_schema(Article)

    assert "description" in sent["properties"]
    assert set(sent["required"]) <= set(sent["properties"])


def test_the_schema_is_inlined_so_nothing_dangles() -> None:
    """A filtered schema beside an unfiltered `$defs` would disagree with itself."""
    import json

    from app.infrastructure.ai.providers.google import _to_gemini_schema

    sent = _to_gemini_schema(Article)

    assert "$defs" not in sent
    assert "$ref" not in json.dumps(sent)
    # And the inlining preserved the section's own fields.
    assert set(sent["properties"]["light"]["properties"]) == {"text", "confidence"}
