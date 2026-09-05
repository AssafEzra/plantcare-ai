"""A scripted provider for tests.

TESTING_STRATEGY §12: tests must not depend on live model responses. Every agent
contract test drives this instead, which makes the malformed, schema-invalid and
timeout paths reachable on demand — those are the cases that matter, and they are
the ones a live model will not produce reliably.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from app.infrastructure.ai.provider import (
    ImageInput,
    ProviderError,
    ProviderTimeoutError,
    SchemaValidationFailedError,
    StructuredResult,
    Usage,
)


class MockProvider:
    """Returns scripted responses, one per call.

    A response may be a model instance, a dict to validate, or an exception to
    raise. Queueing several lets a test express "fails twice, then succeeds",
    which is how the retry budget gets exercised.
    """

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses: deque[Any] = deque(responses or [])
        self.calls: list[dict[str, Any]] = []

    def queue(self, *responses: Any) -> MockProvider:
        self._responses.extend(responses)
        return self

    @property
    def call_count(self) -> int:
        return len(self.calls)

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
        self.calls.append(
            {
                "model": model,
                "schema": schema.__name__,
                "system": system,
                "prompt": prompt,
                "image_count": len(images or []),
                "max_tokens": max_tokens,
                "effort": effort,
            }
        )

        if not self._responses:
            raise AssertionError(
                f"MockProvider ran out of scripted responses on call {len(self.calls)}"
            )

        response = self._responses.popleft()

        if isinstance(response, BaseException):
            raise response
        if isinstance(response, type) and issubclass(response, BaseException):
            raise response("scripted failure")
        if callable(response) and not isinstance(response, BaseModel):
            response = response()

        if isinstance(response, schema):
            value = response
        else:
            try:
                value = schema.model_validate(response)
            except ValidationError as exc:
                # Mirrors the real provider: a response that does not conform is a
                # schema failure, which is the retryable kind.
                raise SchemaValidationFailedError(str(exc)) from exc

        return StructuredResult(
            value=value,
            usage=Usage(input_tokens=100, output_tokens=50, model=model, latency_ms=12),
        )


def always_fails(exc: type[BaseException] = SchemaValidationFailedError) -> Callable[[], Any]:
    """A response factory that raises every time it is called."""

    def _raise() -> Any:
        raise exc("scripted failure")

    return _raise


__all__ = [
    "MockProvider",
    "ProviderError",
    "ProviderTimeoutError",
    "SchemaValidationFailedError",
    "always_fails",
]
