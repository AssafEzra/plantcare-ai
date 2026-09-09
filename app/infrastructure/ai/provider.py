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

from app.common.errors import ConfigurationError
from app.config.settings import get_settings

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class ImageInput:
    """One image for a vision call."""

    data: bytes
    mime_type: str


@dataclass(frozen=True)
class ModelSpec:
    """List price for one model, USD per million tokens.

    Each provider owns the table for its own models, because a price is a fact
    about a vendor's product rather than about this application.
    """

    input: float
    output: float


@dataclass(frozen=True)
class Usage:
    """What a call cost, for `agent_executions`.

    Deliberately narrow: tokens, cost and latency. There is no field for
    reasoning, prompts or responses, because FINAL §23 forbids storing
    chain-of-thought and the cheapest way to guarantee that is to have nowhere to
    put it.

    Every field is optional and defaults to ``None``, which means *unknown* and
    is not the same claim as zero. A model the app has no price for still runs -
    the model string is passed through to the vendor unvalidated, so that it can
    be a model released after this code was written - and its cost is recorded as
    unknown rather than as free. The previous version returned ``0.0`` for an
    unrecognised model, which is how three billed calls came to be reported as
    costing nothing.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str = ""
    latency_ms: int = 0
    estimated_cost: float | None = None

    @classmethod
    def measured(
        cls,
        *,
        input_tokens: int,
        output_tokens: int,
        model: str,
        latency_ms: int,
        price: ModelSpec | None,
    ) -> Usage:
        """Build usage for a completed call, costing it when a price is known.

        The arithmetic lives here so that three providers cannot disagree about
        it, and `price=None` is the ordinary case for a model nobody has priced
        yet rather than an error.
        """
        cost = None
        if price is not None:
            cost = (input_tokens * price.input + output_tokens * price.output) / 1_000_000
        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            latency_ms=latency_ms,
            estimated_cost=cost,
        )


def require_api_key(setting: str, *, fallback: str | None = None) -> str:
    """The credential for one provider, or a configuration error naming it.

    Read here rather than in each provider so the failure is identical for all
    three, and raised at construction so a missing key is not discovered by the
    vendor's SDK in the middle of a user's request.
    """
    settings = get_settings()
    value = getattr(settings, setting, None)
    if not value and fallback:
        value = getattr(settings, fallback, None)
    if not value:
        wanted = setting.upper() + (f" (or {fallback.upper()})" if fallback else "")
        raise ConfigurationError(f"{wanted} is not set, and this agent is configured to use it")
    return str(value)


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


#: HTTP statuses that mean "ask again shortly", rather than "this request is
#: wrong". Every provider maps its vendor's error onto this set, so the gateway
#: does not need to know one vendor's status codes from another's.
TRANSIENT_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class ProviderUnavailableError(ProviderError):
    """The vendor could not serve this request now, but the request was fine.

    Separated from :class:`ProviderError` because it is the second kind of
    failure worth retrying, and it is the cheap kind: the model never ran, so
    nothing was billed and nothing was generated to be wrong. A schema retry pays
    full price for every attempt; this one pays only a request against quota.

    Introduced after four consecutive knowledge runs failed on a free-tier Gemini
    key with `503 This model is currently experiencing high demand`. Each was a
    single attempt that was never retried, because a 503 arrived here as an
    ordinary `ProviderError` and the gateway - correctly, for a 400 or an auth
    failure - does not retry those.
    """


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
        timeout_seconds: float | None = None,
    ) -> StructuredResult[T]:
        """Generate a response validated against `schema`.

        `timeout_seconds` is per call, because the four agents do work of very
        different sizes and a single client-wide budget sized for the smallest
        one fails the largest.

        Raises :class:`SchemaValidationFailedError` when the response does not
        conform, so the gateway can decide whether to retry.
        """
        ...
