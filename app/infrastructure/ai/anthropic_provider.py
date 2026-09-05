"""Anthropic implementation of :class:`AIProvider`.

The only module in the codebase that imports the Anthropic SDK. Agents talk to
the gateway, the gateway talks to a provider, and swapping providers means adding
a sibling to this file.
"""

from __future__ import annotations

import base64
import time
from typing import Any, cast

import anthropic
from pydantic import BaseModel, ValidationError

from app.config.settings import get_settings
from app.infrastructure.ai.provider import (
    ImageInput,
    ProviderError,
    ProviderTimeoutError,
    SchemaValidationFailedError,
    StructuredResult,
    Usage,
)


class AnthropicProvider:
    """Talks to the Anthropic Messages API."""

    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        settings = get_settings()
        self._client = anthropic.Anthropic(
            api_key=api_key or settings.ai_api_key,
            timeout=timeout or settings.ai_request_timeout_seconds,
            # The gateway owns retries, because only it knows whether a failure is
            # worth retrying and how much of the budget is left. Two layers of
            # retry would silently multiply into six attempts.
            max_retries=0,
        )

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
            response = self._client.messages.parse(
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
            )
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeoutError("הניתוח נמשך זמן רב מדי.") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"provider returned {exc.status_code}") from exc
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
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=response.model,
                latency_ms=latency_ms,
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
