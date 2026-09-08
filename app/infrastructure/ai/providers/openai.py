"""OpenAI implementation of :class:`AIProvider`.

Written against `openai` 3.9 by reading the installed SDK. It uses the Responses
API, whose `parse`/`stream` helpers take a pydantic model as `text_format` and
report usage as `input_tokens`/`output_tokens` - the closest match of the three
vendors to the shape this Protocol already expresses.

`import openai` below is the SDK, not this module: Python 3 imports are absolute,
so a module may share a vendor's name without shadowing it.
"""

from __future__ import annotations

import base64
import time
from typing import Any, ClassVar, cast

import openai
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

# OpenAI's reasoning efforts use the same words we do, so this is a guard against
# an unknown value rather than a translation.
_EFFORTS = {"minimal", "low", "medium", "high"}


def _vendor_message(exc: Exception) -> str:
    """The vendor's own explanation, short enough to store (see FINAL §23)."""
    return (str(getattr(exc, "message", "") or exc) or exc.__class__.__name__)[:300]


class OpenAIProvider:
    """Talks to the OpenAI Responses API."""

    API_KEY_SETTING = "openai_api_key"

    # USD per million tokens, read from OpenAI's own pricing page on 2026-09-08.
    #
    # Image input is **not** encoded here, deliberately: this table prices models,
    # it does not describe their capabilities. Pointing identification or health -
    # both vision calls - at a text-only model fails at the vendor with its own
    # error, which is the behaviour chosen for a mistyped model string too.
    PRICES: ClassVar[dict[str, ModelSpec]] = {
        "gpt-6-astra": ModelSpec(input=10.00, output=50.00),
        "gpt-5.6-sol": ModelSpec(input=4.00, output=20.00),
        "gpt-5.6-terra": ModelSpec(input=2.00, output=12.00),
        "gpt-5.6-luna": ModelSpec(input=0.20, output=1.20),
        "gpt-5.4": ModelSpec(input=2.50, output=15.00),
        "gpt-5": ModelSpec(input=1.25, output=10.00),
        "gpt-4o": ModelSpec(input=2.50, output=10.00),
        "gpt-4o-mini": ModelSpec(input=0.15, output=0.60),
    }

    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        settings = get_settings()
        self._client = openai.OpenAI(
            api_key=api_key or require_api_key(self.API_KEY_SETTING),
            timeout=timeout or settings.ai_request_timeout_seconds,
            # The gateway owns retries, for the same reason as the other providers.
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

        # Images before text, as in the other two providers.
        for image in images or []:
            encoded = base64.standard_b64encode(image.data).decode("ascii")
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{image.mime_type};base64,{encoded}",
                    "detail": "auto",
                }
            )
        content.append({"type": "input_text", "text": prompt})

        started = time.perf_counter()
        try:
            # Streamed and then waited on, for the same reason as the Anthropic
            # provider: a long generation must not trip a read timeout while it is
            # visibly still producing tokens. `get_final_response()` returns the
            # same parsed object `responses.parse()` would have.
            with self._client.responses.stream(
                model=model,
                instructions=system,
                input=cast(Any, [{"role": "user", "content": content}]),
                text_format=schema,
                max_output_tokens=max_tokens,
                reasoning={"effort": cast(Any, effort if effort in _EFFORTS else "high")},
                timeout=timeout_seconds if timeout_seconds is not None else openai.NOT_GIVEN,
            ) as stream:
                response = stream.get_final_response()
        except openai.LengthFinishReasonError as exc:
            # Truncated at max_output_tokens, so the JSON cannot be complete. Same
            # shape of failure as a schema violation, and the retry budget exists
            # for exactly this.
            raise SchemaValidationFailedError("response hit max_output_tokens") from exc
        except openai.ContentFilterFinishReasonError as exc:
            raise ProviderError("the model declined this request (content filter)") from exc
        except openai.APITimeoutError as exc:
            raise ProviderTimeoutError("הניתוח נמשך זמן רב מדי.") from exc
        except openai.APIStatusError as exc:
            raise ProviderError(
                f"openai returned {exc.status_code}: {_vendor_message(exc)}"
            ) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("could not reach the AI provider") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        parsed = self._extract(response, schema)

        usage = getattr(response, "usage", None)
        return StructuredResult(
            value=parsed,
            usage=Usage.measured(
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                # Reasoning tokens are billed as output and are already inside this
                # count; `output_tokens_details.reasoning_tokens` is a breakdown of
                # it, not an addition to it.
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                model=getattr(response, "model", None) or model,
                latency_ms=latency_ms,
                price=self.price(getattr(response, "model", None) or model),
            ),
        )

    @staticmethod
    def _extract[T: BaseModel](response: Any, schema: type[T]) -> T:
        """The validated value, from `output_parsed` or from the raw text.

        A refusal reaches here as a parsed value of `None` with a refusal item in
        the output, which is a final failure rather than something to retry.
        """
        for item in getattr(response, "output", None) or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    reason = getattr(part, "refusal", "") or ""
                    raise ProviderError(f"the model declined this request: {reason[:200]}")

        candidate = getattr(response, "output_parsed", None)
        if isinstance(candidate, schema):
            return candidate

        if candidate is not None:
            try:
                return schema.model_validate(candidate)
            except ValidationError as exc:
                raise SchemaValidationFailedError(str(exc)) from exc

        text = (getattr(response, "output_text", None) or "").strip()
        if not text:
            raise SchemaValidationFailedError("model returned no content")
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            raise SchemaValidationFailedError(str(exc)) from exc
