"""Structured logging.

DEPLOYMENT_AND_OPERATIONS §9 defines both the useful field set
(timestamp, environment, request_id, user_id, plant_id, agent_type, status,
duration, error_code) and what must never be logged: passwords, API keys, raw
authentication tokens, and full prompts/responses.

The redaction processor below is a safety net, not a licence to pass secrets in —
it exists so that an accidental ``log.info("...", api_key=key)`` cannot leak.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

# Key names whose values are replaced wholesale before rendering.
_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|auth|credential|"
    r"service[_-]?role|anon[_-]?key|jwt|bearer|cookie)",
    re.IGNORECASE,
)

# Chain-of-thought and raw prompt/response bodies are never persisted (FINAL §23).
_BANNED_KEY = re.compile(
    r"(chain_of_thought|reasoning_trace|raw_prompt|raw_response)", re.IGNORECASE
)

_REDACTED = "***redacted***"


def _redact(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        if _BANNED_KEY.search(key):
            del event_dict[key]
        elif _SENSITIVE_KEY.search(key):
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging(*, environment: str, debug: bool = False) -> None:
    """Install the process-wide structlog configuration. Idempotent."""
    level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact,
    ]

    renderer: Any = (
        structlog.dev.ConsoleRenderer(colors=False)
        if debug
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.EventRenamer("message"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.bind_contextvars(environment=environment)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
