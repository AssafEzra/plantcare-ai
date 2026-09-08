"""Anthropic implementation of :class:`AIProvider`.

Moved here from `app/infrastructure/ai/anthropic_provider.py` when the providers
package was introduced; the call semantics are unchanged.

`import anthropic` below is the SDK, not this module: Python 3 imports are
absolute, so a module may share a vendor's name without shadowing it.
"""

from __future__ import annotations

import base64
import time
from typing import Any, ClassVar, cast

import anthropic
from anthropic import NOT_GIVEN
from pydantic import BaseModel, ValidationError

from app.config.settings import get_settings
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


def _vendor_message(exc: Exception) -> str:
    """The vendor's own explanation, short enough to store.

    Worth carrying: the previous version recorded only `provider returned 404`,
    which is the reason in principle and useless in practice for the commonest
    cause - a mistyped model string, which the app deliberately does not validate.
    Capped, and never a request body: `agent_executions.error_message` holds "a
    provider's error string, not transcripts" (FINAL §23).
    """
    return (str(getattr(exc, "message", "") or exc) or exc.__class__.__name__)[:300]


class AnthropicProvider:
    """Talks to the Anthropic Messages API."""

    API_KEY_SETTING = "anthropic_api_key"

    # USD per million tokens, verified against Anthropic's pricing page on
    # 2026-09-08. A model absent here still runs; its cost records as unknown.
    PRICES: ClassVar[dict[str, ModelSpec]] = {
        "claude-opus-5": ModelSpec(input=5.00, output=25.00),
        "claude-sonnet-5": ModelSpec(input=2.00, output=10.00),
        "claude-haiku-4-5": ModelSpec(input=1.00, output=5.00),
    }

    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        settings = get_settings()
        self._client = anthropic.Anthropic(
            # `ai_api_key` is the deprecated single-provider name, kept as a
            # fallback so the deployed app keeps working: Community Cloud
            # redeploys on push and its secret is still AI_API_KEY. Remove the
            # fallback once that secret has been renamed.
            api_key=api_key or require_api_key(self.API_KEY_SETTING, fallback="ai_api_key"),
            timeout=timeout or settings.ai_request_timeout_seconds,
            # The gateway owns retries, because only it knows whether a failure is
            # worth retrying and how much of the budget is left. Two layers of
            # retry would silently multiply into six attempts.
            max_retries=0,
        )

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
        content: list[dict[str, Any]] = []

        # Images before text: the model reads the prompt as instructions about
        # material it has already seen, which is how the vision guidance frames it.
        for image in images or []:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.mime_type,
                        "data": base64.standard_b64encode(image.data).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        started = time.perf_counter()
        try:
            # Streamed, and then waited on. Nothing here consumes the response
            # incrementally - the agents need a complete, schema-valid document
            # before they can do anything with it - but a streamed request is
            # measured chunk to chunk rather than end to end, so a long generation
            # cannot trip a read timeout while it is visibly still producing
            # tokens. The Knowledge Agent writes thirteen prose sections against
            # `max_tokens=8000`; the first real research run in DEV was cut off
            # mid-generation at ninety seconds and the draft failed.
            #
            # `get_final_message()` returns the same `ParsedMessage` that
            # `messages.parse()` returned, so everything below is unchanged.
            with self._client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": cast(Any, content)}],
                output_format=schema,
                # Adaptive thinking, with the reasoning left out of the response.
                # `display` defaults to omitted on this model family; being
                # explicit records that it is a decision, not an accident
                # (FINAL §23 forbids persisting chain-of-thought).
                thinking=cast(Any, {"type": "adaptive", "display": "omitted"}),
                output_config=cast(Any, {"effort": effort}),
                # Per call: the client-level default is sized for the smallest of
                # the four agents, and the gateway knows which one is calling.
                timeout=timeout_seconds if timeout_seconds is not None else NOT_GIVEN,
            ) as stream:
                response = stream.get_final_message()
        except ValidationError as exc:
            # Schema validation moved when this call started streaming. `parse()`
            # returned a message and `_extract` below validated it; the streaming
            # helper validates during accumulation, inside `get_final_message()`,
            # and raises pydantic's error straight out of the iterator.
            #
            # Uncaught, that error is not a `SchemaValidationFailedError`, so the
            # gateway's handlers never see it: no retry, no `agent_executions`
            # row, and the workflow's blanket `except` records a flat
            # AGENT_FAILED. `FINAL §23`'s two retries and `§25`'s "a failed call
            # is visible" were both silently switched off for every agent - found
            # when a Health check returned `priority: 6` against a `le=5` bound
            # and the user saw nothing at all happen.
            raise SchemaValidationFailedError(str(exc)) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeoutError("הניתוח נמשך זמן רב מדי.") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                f"anthropic returned {exc.status_code}: {_vendor_message(exc)}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("could not reach the AI provider") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        # A refusal is a successful HTTP call with no usable content, so it has to
        # be checked before the parsed value is read.
        if response.stop_reason == "refusal":
            raise ProviderError("the model declined this request")

        parsed = self._extract(response, schema)

        return StructuredResult(
            value=parsed,
            usage=Usage.measured(
                input_tokens=response.usage.input_tokens,
                # Thinking tokens are billed as output and are already inside this
                # count, so nothing extra needs adding for adaptive thinking.
                output_tokens=response.usage.output_tokens,
                model=response.model,
                latency_ms=latency_ms,
                price=self.price(response.model),
            ),
        )

    @staticmethod
    def _extract[T: BaseModel](response: Any, schema: type[T]) -> T:
        """Pull the validated value out of a ParsedMessage.

        The SDK exposes it as `parsed_output`, on the message and on each text
        block. Both are checked, and the raw text is parsed as a last resort: a
        response whose JSON is correct but which the SDK did not surface should
        not be thrown away and retried at the user's expense.
        """
        candidate = getattr(response, "parsed_output", None)

        if candidate is None:
            for block in getattr(response, "content", []):
                candidate = getattr(block, "parsed_output", None)
                if candidate is not None:
                    break

        if candidate is None:
            text = "".join(
                block.text
                for block in getattr(response, "content", [])
                if getattr(block, "type", None) == "text"
            ).strip()
            if not text:
                raise SchemaValidationFailedError("model returned no content")
            try:
                return schema.model_validate_json(text)
            except ValidationError as exc:
                raise SchemaValidationFailedError(str(exc)) from exc

        if isinstance(candidate, schema):
            return candidate
        try:
            return schema.model_validate(candidate)
        except ValidationError as exc:
            raise SchemaValidationFailedError(str(exc)) from exc
