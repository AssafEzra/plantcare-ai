"""Application error hierarchy.

Every ``AppError`` carries a stable ``code`` that becomes the ``error.code`` in the
API envelope defined by API_CONTRACTS ("Standard responses"). Messages must be safe
to return to a client: no stack traces, no provider errors, no secrets.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for every expected, user-surfaceable failure."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)

    def to_envelope(self, request_id: str) -> dict[str, Any]:
        return {
            "error": {"code": self.code, "message": self.message, "details": self.details},
            "request_id": request_id,
        }


# --- Configuration -----------------------------------------------------------
class ConfigurationError(AppError):
    code = "CONFIGURATION_ERROR"
    http_status = 500
    message = "The application is misconfigured."


# --- Auth / authorization ----------------------------------------------------
class UnauthenticatedError(AppError):
    code = "UNAUTHENTICATED"
    http_status = 401
    message = "Authentication is required."


class ForbiddenError(AppError):
    code = "FORBIDDEN"
    http_status = 403
    message = "You do not have access to this resource."


class AdminRequiredError(ForbiddenError):
    code = "ADMIN_REQUIRED"
    message = "This action requires an administrator."


# --- Resources ---------------------------------------------------------------
class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404
    message = "The requested resource was not found."


class PlantNotFoundError(NotFoundError):
    code = "PLANT_NOT_FOUND"
    message = "Plant was not found."


class ConflictError(AppError):
    code = "CONFLICT"
    http_status = 409
    message = "The request conflicts with the current state."


class DuplicateActionError(ConflictError):
    """A care task cannot be completed or skipped twice (API_CONTRACTS, Care Tasks)."""

    code = "DUPLICATE_ACTION"
    message = "This action has already been recorded."


class IdempotencyConflictError(ConflictError):
    """Same Idempotency-Key, different payload (A24)."""

    code = "IDEMPOTENCY_KEY_REUSED"
    message = "This Idempotency-Key was already used with a different request body."


# --- Validation --------------------------------------------------------------
class ValidationFailedError(AppError):
    code = "VALIDATION_FAILED"
    http_status = 422
    message = "The request was not valid."


class InvalidTransitionError(ValidationFailedError):
    """Rejected lifecycle transition (TESTING_STRATEGY §3)."""

    code = "INVALID_TRANSITION"
    message = "That status change is not allowed."


class ImageValidationError(ValidationFailedError):
    code = "IMAGE_INVALID"
    message = "The image could not be accepted."


class PayloadTooLargeError(AppError):
    code = "PAYLOAD_TOO_LARGE"
    http_status = 413
    message = "The uploaded file exceeds the maximum allowed size."


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    http_status = 429
    message = "Too many requests. Please try again shortly."


# --- AI ----------------------------------------------------------------------
class AgentError(AppError):
    """Base for AI failures. No AgentError may ever leave an authoritative record."""

    code = "AGENT_FAILED"
    http_status = 503
    message = "The AI service could not complete this request."


class AgentSchemaError(AgentError):
    """Structured output failed validation after the retry budget was exhausted."""

    code = "AGENT_SCHEMA_INVALID"
    message = "The AI response did not match the expected format."


class AgentTimeoutError(AgentError):
    code = "AGENT_TIMEOUT"
    message = "The AI service did not respond in time."


class UpstreamUnavailableError(AppError):
    code = "UPSTREAM_UNAVAILABLE"
    http_status = 503
    message = "A required upstream service is unavailable."
