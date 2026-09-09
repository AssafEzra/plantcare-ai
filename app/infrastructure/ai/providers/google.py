"""Google (Gemini) implementation of :class:`AIProvider`.

Written against `google-genai` 2.22 by reading the installed SDK rather than from
memory: `HttpOptions.timeout` is **milliseconds**, and reasoning depth is
`ThinkingConfig.thinking_level` from a fixed enum rather than a token budget.

`from google import genai` below is the SDK, not this module: Python 3 imports are
absolute, so a module may share a vendor's name without shadowing it.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar, cast

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.infrastructure.ai.provider import (
    ImageInput,
    ModelSpec,
    ProviderError,
    ProviderTimeoutError,
    SchemaValidationFailedError,
    StructuredResult,
    Usage,
    require_api_key,
)

# Our `effort` vocabulary onto Gemini's. Both are coarse levels rather than token
# budgets, so this is a rename and not a judgement about equivalent spend.
# Verified live on 2026-09-09: `gemini-3.7-flash`, `gemini-3.8-flash` and the
# `gemini-flash-latest` alias reject MINIMAL with a 400 ("Thinking level MINIMAL is
# not supported for this model"); LOW upward are accepted. `gemini-3.6-flash` and
# the flash-lite models accept all four. Nothing in this application asks for
# anything but "high" (`gateway.py`), so the gap is unreachable today - recorded
# because a future caller lowering effort to save money would meet a 400 rather
# than a cheaper call.
_THINKING_LEVEL: dict[str, types.ThinkingLevel] = {
    "minimal": types.ThinkingLevel.MINIMAL,
    "low": types.ThinkingLevel.LOW,
    "medium": types.ThinkingLevel.MEDIUM,
    "high": types.ThinkingLevel.HIGH,
}

# Finish reasons that mean "no usable answer", separated by whether trying again
# could help. A truncated response is unparseable JSON, which is the same shape
# of failure as a schema violation and is what the gateway's retry budget is for.
_BLOCKED = {"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"}


def _vendor_message(exc: Exception) -> str:
    """The vendor's own explanation, short enough to store (see FINAL §23)."""
    return (str(getattr(exc, "message", "") or exc) or exc.__class__.__name__)[:300]


class GoogleProvider:
    """Talks to the Gemini API."""

    API_KEY_SETTING = "google_api_key"

    # USD per million tokens, Standard tier, read off Google's own API pricing
    # page on 2026-09-09. Batch, Flex and Priority tiers cost less or more; this
    # application makes ordinary synchronous calls, so Standard is the rate.
    #
    # Four things to know before editing this table:
    #
    # 1. `gemini-3.6-flash`, `-3.7-flash` and `-3.8-flash` share a promotional
    #    $0.75/$3.75 that holds **only through 31 Dec 2026** and then doubles to
    #    $1.50/$7.50. Nothing here enforces that date, so on 1 Jan 2027 every
    #    figure recorded for these three understates the bill by half until this
    #    table is edited. That is the whole maintenance burden of this file.
    # 2. The Pro models are tiered - the rate below applies up to 200k input
    #    tokens and roughly doubles above it. The largest call this application
    #    has ever made is about 10k tokens (a three-image identification), so the
    #    low tier always applies. Recorded flat deliberately rather than building
    #    tier logic that nothing would exercise.
    # 3. Several models list a separate, higher audio input rate. This
    #    application sends text and images only, so the text/image/video rate is
    #    the one recorded.
    # 4. The moving aliases - `gemini-flash-latest`, `gemini-flash-lite-latest`,
    #    `gemini-pro-latest` - are deliberately absent. They resolve to whichever
    #    model Google currently points them at, so any price written here would
    #    silently become wrong the next time Google moves one. They still work as
    #    model strings; their calls record an unknown cost, which is the honest
    #    answer for a model whose identity is not fixed.
    #
    # The 2.5 family is closed to API keys created after roughly mid-2026, which
    # answer a generation request with "no longer available to new users". The
    # prices stay because this table is a price lookup and not an availability
    # check, and keys predating the cutoff still use them.
    PRICES: ClassVar[dict[str, ModelSpec]] = {
        # 3.x - promotional through 31 Dec 2026, see note 1
        "gemini-3.8-flash": ModelSpec(input=0.75, output=3.75),
        "gemini-3.7-flash": ModelSpec(input=0.75, output=3.75),
        "gemini-3.6-flash": ModelSpec(input=0.75, output=3.75),
        # 3.x - standing prices
        "gemini-3.5-flash": ModelSpec(input=1.50, output=9.00),
        "gemini-3.5-flash-lite": ModelSpec(input=0.30, output=2.50),
        "gemini-3.1-flash-lite": ModelSpec(input=0.25, output=1.50),
        "gemini-3.1-pro-preview": ModelSpec(input=2.00, output=12.00),
        # 2.5 - see the closing note above
        "gemini-2.5-pro": ModelSpec(input=1.25, output=10.00),
        "gemini-2.5-flash": ModelSpec(input=0.30, output=2.50),
        "gemini-2.5-flash-lite": ModelSpec(input=0.10, output=0.40),
    }

    def __init__(self, api_key: str | None = None) -> None:
        self._client = genai.Client(api_key=api_key or require_api_key(self.API_KEY_SETTING))

    @classmethod
    def price(cls, model: str) -> ModelSpec | None:
        return cls.PRICES.get(model)

    def structured_output[T: BaseModel](
        self,
        *,
        model: str,
        schema: type[T],
        system: str,
        prompt: str,
        images: list[ImageInput] | None = None,
        max_tokens: int = 8000,
        effort: str = "high",
        timeout_seconds: float | None = None,
    ) -> StructuredResult[T]:
        # Images before text, as in the Anthropic provider: the prompt reads as
        # instructions about material the model has already seen.
        contents: list[types.Part] = [
            types.Part.from_bytes(data=image.data, mime_type=image.mime_type)
            for image in images or []
        ]
        contents.append(types.Part.from_text(text=prompt))

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            # `response_json_schema`, not `response_schema`. Handing the SDK a
            # Pydantic class routes it through Gemini's own Schema proto, which
            # has no field for `additionalProperties` - so every model declaring
            # `extra="forbid"` (knowledge, care and health; not identification)
            # was rejected before generation with:
            #
            #   400 Unknown name "additional_properties" at
            #   'generation_config.response_schema'
            #
            # `response_json_schema` accepts standard JSON Schema, which is what
            # `model_json_schema()` produces and what the agents' contracts are
            # written as. `_extract` already falls back to parsing `text` when the
            # SDK does not hand back a typed object, which this path does not.
            response_json_schema=schema.model_json_schema(),
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(
                thinking_level=_THINKING_LEVEL.get(effort, types.ThinkingLevel.HIGH),
                # FINAL §23 forbids persisting chain-of-thought, and the cheapest
                # guarantee is not to receive it.
                include_thoughts=False,
            ),
            # Not streamed, unlike the Anthropic provider, and for a reason rather
            # than by omission: there the concern is a *read* timeout expiring
            # between chunks of a long generation, which streaming avoids by
            # measuring chunk to chunk. Here the budget is an explicit total for
            # the whole request, in milliseconds, so a 600-second Knowledge run is
            # expressed directly and hand-aggregating a streamed structured
            # response would add failure modes without removing any.
            http_options=types.HttpOptions(
                timeout=int((timeout_seconds or 0) * 1000) or None,
            ),
        )

        started = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=model, contents=cast(Any, contents), config=config
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("הניתוח נמשך זמן רב מדי.") from exc
        except genai_errors.APIError as exc:
            # ClientError (4xx, including a mistyped model) and ServerError (5xx)
            # both land here; `code` carries the HTTP status.
            raise ProviderError(
                f"google returned {getattr(exc, 'code', '?')}: {_vendor_message(exc)}"
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        self._check_blocked(response)
        parsed = self._extract(response, schema)

        usage = response.usage_metadata
        # Gemini reports reasoning tokens *outside* `candidates_token_count` and
        # bills them as output, so they have to be added. Anthropic includes them;
        # taking the candidate count alone would under-report every thinking call.
        output_tokens = (usage.candidates_token_count or 0) if usage else 0
        output_tokens += (usage.thoughts_token_count or 0) if usage else 0

        return StructuredResult(
            value=parsed,
            usage=Usage.measured(
                input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                output_tokens=output_tokens,
                model=model,
                latency_ms=latency_ms,
                price=self.price(model),
            ),
        )

    @staticmethod
    def _check_blocked(response: Any) -> None:
        """Turn a refusal or a truncation into the right kind of failure.

        A safety block is final and must not be retried; a truncated answer is
        unparseable JSON, which is the case the gateway's retry budget exists for.
        """
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise ProviderError(f"the model declined this request ({feedback.block_reason})")

        for candidate in getattr(response, "candidates", None) or []:
            reason = str(getattr(candidate, "finish_reason", "") or "").upper().split(".")[-1]
            if reason in _BLOCKED:
                raise ProviderError(f"the model declined this request ({reason})")
            if reason == "MAX_TOKENS":
                raise SchemaValidationFailedError("response hit max_output_tokens and is truncated")

    @staticmethod
    def _extract[T: BaseModel](response: Any, schema: type[T]) -> T:
        """The validated value, from `parsed` or from the raw JSON text.

        Same shape as the Anthropic provider's extractor and for the same reason:
        a response whose JSON is correct but which the SDK did not surface as a
        parsed object should not be thrown away and retried at the user's expense.
        """
        candidate = getattr(response, "parsed", None)
        if isinstance(candidate, schema):
            return candidate

        if candidate is not None:
            try:
                return schema.model_validate(candidate)
            except ValidationError as exc:
                raise SchemaValidationFailedError(str(exc)) from exc

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise SchemaValidationFailedError("model returned no content")
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            raise SchemaValidationFailedError(str(exc)) from exc
