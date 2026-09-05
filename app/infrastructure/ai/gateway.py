"""The AI Gateway.

FINAL §23 gives it a specific job list: provider selection, authentication,
retries, timeouts, structured output, logging and cost tracking. Agents call the
gateway; nothing else in the codebase talks to a provider.

Two rules here are architectural rather than incidental:

**At most two retries.** §23 caps automatic retries at 2, so a request produces
at most three attempts. The ceiling is validated in configuration and asserted by
a CHECK constraint on `agent_executions.attempt`, so it cannot be loosened by an
environment variable or a stray loop.

**Only schema failures are retried.** Retrying a timeout or an authentication
failure wastes the budget on something that will not succeed, and delays the
graceful failure the user is waiting for. A malformed response, by contrast,
often parses on the next attempt — which is exactly the case §23 has in mind.
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
    SchemaValidationFailedError,
    StructuredResult,
)
from app.infrastructure.supabase.client import service_client

log = get_logger(__name__)


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
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
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
            "estimated_cost": round(self.estimated_cost, 6),
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

    def __init__(self, provider: AIProvider, *, record_executions: bool = True) -> None:
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
        max_attempts = settings.ai_max_structured_retries + 1

        executions: list[ExecutionRecord] = []
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            started = time.perf_counter()
            try:
                result: StructuredResult[T] = self._provider.structured_output(
                    model=model,
                    schema=schema,
                    system=prompt.text,
                    prompt=user_content,
                    images=images,
                    max_tokens=max_tokens,
                    effort=effort,
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
                log.warning(
                    "agent.schema_invalid",
                    agent_type=agent.value,
                    attempt=attempt,
                    of=max_attempts,
                )
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
