"""The AI provider abstraction.

FINAL §23: agents must not be tied to a specific provider, and model selection is
configuration rather than code. Everything an agent needs is expressed here, so
swapping providers means writing one class and changing nothing else.

Deviation from the suggested interface, recorded per FINAL §37
--------------------------------------------------------------
§23 lists `verify_wikipedia_page()` and `retrieve_source()` alongside the
generation methods. Neither is a model call: the first is Wikipedia's own REST
API and the second is deterministic URL verification in Python. Putting them on
this protocol would force every provider implementation to carry an identical
copy of the same HTTP code, and would blur the line between "what the model said"
and "what we checked" — which is exactly the line FINAL §23 draws when it says
verification, not the model's self-report, is authoritative. They live in their
own modules and are introduced with the agents that use them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class ImageInput:
    """One image for a vision call."""

    data: bytes
    mime_type: str


@dataclass(frozen=True)
class Usage:
    """What a call cost, for `agent_executions`.

    Deliberately narrow: tokens, cost and latency. There is no field for
    reasoning, prompts or responses, because FINAL §23 forbids storing
    chain-of-thought and the cheapest way to guarantee that is to have nowhere to
    put it.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    latency_ms: int = 0

    @property
    def estimated_cost(self) -> float:
        """Rough USD estimate for admin monitoring (FINAL §29).

        Prices are per million tokens and change; this is a monitoring signal, not
        an invoice, and the admin view labels it as an estimate.
        """
        rates = _PRICE_PER_MTOK.get(self.model)
        if not rates:
            return 0.0
        return (self.input_tokens * rates[0] + self.output_tokens * rates[1]) / 1_000_000


# Anthropic list prices, USD per million tokens (input, output).
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


@dataclass
class StructuredResult[T: BaseModel]:
    """A schema-validated model response plus its telemetry."""

    value: T
    usage: Usage
    raw: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    """The provider could not produce a usable response."""


class ProviderTimeoutError(ProviderError):
    """The provider did not answer within the configured timeout."""


class SchemaValidationFailedError(ProviderError):
    """The response did not match the requested schema.

    Distinct from other provider failures because it is the one worth retrying:
    a malformed response often succeeds on a second attempt, whereas a timeout or
    an auth failure will not.
    """


class AIProvider(Protocol):
    """What an agent may ask of a model."""

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
        """Generate a response validated against `schema`.

        Raises :class:`SchemaValidationFailedError` when the response does not
        conform, so the gateway can decide whether to retry.
        """
        ...
