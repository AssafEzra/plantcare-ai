"""The AI Gateway.

FINAL §23 gives it a specific job list: provider selection, authentication,
retries, timeouts, structured output, logging and cost tracking. Agents call the
gateway; nothing else in the codebase talks to a provider.

Two rules here are architectural rather than incidental:

**At most two retries.** §23 caps automatic retries at 2, so a request produces
at most three attempts. The ceiling is validated in configuration and asserted by
a CHECK constraint on `agent_executions.attempt`, so it cannot be loosened by an
environment variable or a stray loop.

**Only two kinds of failure are retried, on separate budgets.** A malformed
response often parses on the next attempt, which is the case §23 has in mind; it
is retried up to twice and each attempt pays for a whole generation. A transient
vendor failure — a 503, a 429, a gateway timeout — is retried on its own small
budget, because the model never ran: nothing was billed and there is no bad
output to be wrong about, so the only cost is one more request against quota.
That one was added after four consecutive Knowledge runs each died on a single
503 that would very likely have cleared seconds later.

Everything else is still fatal on the first failure. Retrying a timeout or an
authentication failure spends the budget on something that will not succeed and
delays the graceful failure the user is waiting for.

Only the first kind advances `attempt`. That column is capped at 3 by a CHECK
constraint, and a transient failure is not an attempt at producing a response.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.common.enums import AgentRequestStatus, AgentType
from app.common.errors import AgentError, AgentSchemaError, AgentTimeoutError
from app.config.logging import get_logger
from app.config.settings import get_settings
from app.infrastructure.ai.prompts import Prompt
from app.infrastructure.ai.provider import (
    AIProvider,
    ImageInput,
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    SchemaValidationFailedError,
    StructuredResult,
)
from app.infrastructure.ai.providers import provider_for
from app.infrastructure.supabase.client import service_client

log = get_logger(__name__)

#: How many times a transient vendor failure (503, 429, a gateway timeout) is
#: retried, and how long to wait before each. Deliberately not a setting: the
#: right number is a fact about how long a vendor's capacity blip lasts, not a
#: choice a deployment makes. Two retries over about four seconds covers the
#: short spike without leaving a user waiting on a vendor that is properly down.
#:
#: Cheap in a way the schema retry is not. A schema retry pays for a whole
#: generation each time; here the model never ran, so the only cost is one more
#: request against quota.
_TRANSIENT_RETRIES = 2
_TRANSIENT_BACKOFF_SECONDS = (1.0, 3.0)


@dataclass
class ExecutionRecord:
    """One attempt, as it will be written to `agent_executions`.

    The field list is the allow-list. There is no member for reasoning, prompt
    text or response body, so "do not store chain-of-thought" holds by
    construction rather than by remembering.
    """

    agent_request_id: UUID
    agent_type: AgentType
    model: str
    prompt_version: str
    status: AgentRequestStatus
    attempt: int
    # `None`, not `0`. A failed attempt and an unpriced model both leave the cost
    # genuinely unknown, and recording zero for either states that the call was
    # free - which is how a 90-second Knowledge generation that timed out came to
    # be reported as costing nothing. The columns are nullable already, so this
    # needs no migration; the admin overview counts the unknowns instead of
    # silently absorbing them into a total.
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    latency_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "agent_request_id": str(self.agent_request_id),
            "agent_type": self.agent_type.value,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "status": self.status.value,
            "attempt": self.attempt,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": (
                round(self.estimated_cost, 6) if self.estimated_cost is not None else None
            ),
            "latency_ms": self.latency_ms,
            "error_code": self.error_code,
            # Truncated: an error string is for diagnosis, and a provider can
            # return a very long one. Never a response body.
            "error_message": (self.error_message or "")[:500] or None,
        }


@dataclass
class GatewayResult[T: BaseModel]:
    value: T
    attempts: int
    executions: list[ExecutionRecord] = field(default_factory=list)


class AIGateway:
    """Runs an agent call: selects the model, enforces the budget, records it."""

    def __init__(
        self, provider: AIProvider | None = None, *, record_executions: bool = True
    ) -> None:
        # Optional, and normally omitted. Production passes nothing and the
        # provider is resolved per call from configuration; tests pass a scripted
        # double, which is why that argument survives rather than being replaced.
        self._provider = provider
        self._record = record_executions

    def model_for(self, agent: AgentType) -> str:
        """Per-agent model, from configuration (FINAL §23: swappable without code)."""
        settings = get_settings()
        return {
            AgentType.IDENTIFICATION: settings.identification_model,
            AgentType.KNOWLEDGE: settings.knowledge_model,
            AgentType.CARE: settings.care_model,
            AgentType.HEALTH: settings.health_model,
        }[agent]

    def provider_name_for(self, agent: AgentType) -> str:
        """Per-agent vendor, from configuration.

        The same shape as `model_for` and `timeout_for`, and for the same reason:
        the four agents are different enough that one answer for all of them is
        wrong for some. Comparing two vendors on the same prompt is the point, so
        the choice has to be per agent rather than per application.
        """
        settings = get_settings()
        return {
            AgentType.IDENTIFICATION: settings.identification_provider,
            AgentType.KNOWLEDGE: settings.knowledge_provider,
            AgentType.CARE: settings.care_provider,
            AgentType.HEALTH: settings.health_provider,
        }[agent]

    def _resolve_provider(self, agent: AgentType) -> AIProvider:
        """The injected provider, or the configured one.

        Constructed per call rather than cached: a cached client would outlive a
        credential change, and the cost is one HTTP client per agent run, which is
        what the previous per-request construction already paid.
        """
        if self._provider is not None:
            return self._provider
        return provider_for(self.provider_name_for(agent))

    def timeout_for(self, agent: AgentType) -> float:
        """Per-agent timeout, from configuration.

        The same shape as `model_for`, and for the same reason: the four agents do
        work of very different sizes, and a number chosen for one of them is
        wrong for another. A single 90-second budget shared by all four passed
        every test - the mock returns instantly - and failed the first real
        Knowledge run in production-like use, which is not a failure a mock can
        have.
        """
        settings = get_settings()
        return {
            AgentType.IDENTIFICATION: settings.identification_timeout_seconds,
            AgentType.KNOWLEDGE: settings.knowledge_timeout_seconds,
            AgentType.CARE: settings.care_timeout_seconds,
            AgentType.HEALTH: settings.health_timeout_seconds,
        }[agent]

    def run[T: BaseModel](
        self,
        *,
        agent: AgentType,
        request_id: UUID,
        prompt: Prompt,
        user_content: str,
        schema: type[T],
        images: list[ImageInput] | None = None,
        max_tokens: int = 8000,
        effort: str = "high",
    ) -> GatewayResult[T]:
        settings = get_settings()
        model = self.model_for(agent)
        provider = self._resolve_provider(agent)
        max_attempts = settings.ai_max_structured_retries + 1

        executions: list[ExecutionRecord] = []
        last_error: Exception | None = None
        schema_failures = 0
        transient_failures = 0

        while True:
            # Derived, never incremented per iteration. `attempt` counts attempts
            # at *producing a response*, and `agent_executions.attempt` is capped
            # at 3 by a CHECK constraint enforcing §23's retry ceiling. A transient
            # failure never reached the model, so it is not one of those attempts -
            # counting it would push a later row past 3 and the database would
            # reject the whole execution log rather than the one row.
            attempt = schema_failures + 1
            started = time.perf_counter()
            try:
                result: StructuredResult[T] = provider.structured_output(
                    model=model,
                    schema=schema,
                    system=prompt.text,
                    prompt=user_content,
                    images=images,
                    max_tokens=max_tokens,
                    effort=effort,
                    timeout_seconds=self.timeout_for(agent),
                )
            except SchemaValidationFailedError as exc:
                last_error = exc
                executions.append(
                    self._failed(
                        request_id,
                        agent,
                        model,
                        prompt,
                        attempt,
                        started,
                        "AGENT_SCHEMA_INVALID",
                        str(exc),
                    )
                )
                schema_failures += 1
                log.warning(
                    "agent.schema_invalid",
                    agent_type=agent.value,
                    attempt=attempt,
                    of=max_attempts,
                )
                if schema_failures >= max_attempts:
                    break
                continue
            except ProviderTimeoutError as exc:
                # Not retried: a timeout will not become a well-formed response,
                # and the user is already waiting.
                executions.append(
                    self._failed(
                        request_id,
                        agent,
                        model,
                        prompt,
                        attempt,
                        started,
                        "AGENT_TIMEOUT",
                        str(exc),
                    )
                )
                self._persist(executions)
                raise AgentTimeoutError() from exc
            except ProviderUnavailableError as exc:
                # The cheap retry. The model never ran, so nothing was billed and
                # there is no bad output to be wrong about - the only cost of
                # trying again is one request against the vendor's quota.
                #
                # This exists because four consecutive knowledge runs died on a
                # single 503 apiece. Each would probably have succeeded seconds
                # later; none was retried, because a 503 was indistinguishable
                # here from a 400.
                transient_failures += 1
                last_error = exc
                executions.append(
                    self._failed(
                        request_id,
                        agent,
                        model,
                        prompt,
                        attempt,
                        started,
                        "AGENT_UNAVAILABLE",
                        str(exc),
                    )
                )
                if transient_failures > _TRANSIENT_RETRIES:
                    self._persist(executions)
                    log.warning(
                        "agent.unavailable",
                        agent_type=agent.value,
                        attempts=transient_failures,
                    )
                    raise AgentError() from exc
                log.info(
                    "agent.unavailable_retrying",
                    agent_type=agent.value,
                    attempt=attempt,
                    waiting=_TRANSIENT_BACKOFF_SECONDS[transient_failures - 1],
                )
                time.sleep(_TRANSIENT_BACKOFF_SECONDS[transient_failures - 1])
                continue
            except ProviderError as exc:
                executions.append(
                    self._failed(
                        request_id,
                        agent,
                        model,
                        prompt,
                        attempt,
                        started,
                        "AGENT_FAILED",
                        str(exc),
                    )
                )
                self._persist(executions)
                raise AgentError() from exc

            executions.append(
                ExecutionRecord(
                    agent_request_id=request_id,
                    agent_type=agent,
                    model=result.usage.model or model,
                    prompt_version=prompt.version_id,
                    status=AgentRequestStatus.SUCCEEDED,
                    attempt=attempt,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    estimated_cost=result.usage.estimated_cost,
                    latency_ms=result.usage.latency_ms,
                )
            )
            self._persist(executions)
            return GatewayResult(value=result.value, attempts=attempt, executions=executions)

        # Retry budget exhausted. FINAL §25: this produces a failed execution and
        # no authoritative record - the caller must not write one.
        self._persist(executions)
        log.warning("agent.exhausted", agent_type=agent.value, attempts=max_attempts)
        raise AgentSchemaError() from last_error

    def _failed(
        self,
        request_id: UUID,
        agent: AgentType,
        model: str,
        prompt: Prompt,
        attempt: int,
        started: float,
        code: str,
        message: str,
    ) -> ExecutionRecord:
        return ExecutionRecord(
            agent_request_id=request_id,
            agent_type=agent,
            model=model,
            prompt_version=prompt.version_id,
            status=AgentRequestStatus.FAILED,
            attempt=attempt,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_code=code,
            error_message=message,
        )

    def _persist(self, executions: list[ExecutionRecord]) -> None:
        """Write the attempt log.

        Uses the service role: `agent_executions` is admin-only telemetry that no
        user JWT may write, and it must be recorded even for a request that
        failed on the caller's behalf.

        A logging failure must never turn a successful agent call into an error,
        so this swallows its own exceptions after reporting them.
        """
        if not self._record or not executions:
            return
        try:
            service_client().table("agent_executions").insert(
                [record.to_row() for record in executions]
            ).execute()
        except Exception as exc:
            log.error("agent.execution_log_failed", error_type=type(exc).__name__)
