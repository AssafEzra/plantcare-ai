"""API_CONTRACTS "Standard responses": every error renders the same envelope."""

from __future__ import annotations

import pytest

from app.common import errors


def test_envelope_shape():
    err = errors.PlantNotFoundError()
    envelope = err.to_envelope("req-123")

    assert envelope == {
        "error": {
            "code": "PLANT_NOT_FOUND",
            "message": "Plant was not found.",
            "details": {},
        },
        "request_id": "req-123",
    }


def test_details_are_carried_through():
    err = errors.ValidationFailedError("Bad image count.", details={"received": 5, "max": 4})
    envelope = err.to_envelope("req-1")

    assert envelope["error"]["details"] == {"received": 5, "max": 4}


@pytest.mark.parametrize(
    ("cls", "status"),
    [
        (errors.UnauthenticatedError, 401),
        (errors.ForbiddenError, 403),
        (errors.AdminRequiredError, 403),
        (errors.NotFoundError, 404),
        (errors.PlantNotFoundError, 404),
        (errors.ConflictError, 409),
        (errors.DuplicateActionError, 409),
        (errors.IdempotencyConflictError, 409),
        (errors.PayloadTooLargeError, 413),
        (errors.ValidationFailedError, 422),
        (errors.InvalidTransitionError, 422),
        (errors.ImageValidationError, 422),
        (errors.RateLimitedError, 429),
        (errors.ConfigurationError, 500),
        (errors.AgentError, 503),
        (errors.AgentSchemaError, 503),
        (errors.AgentTimeoutError, 503),
        (errors.UpstreamUnavailableError, 503),
    ],
)
def test_status_codes_match_the_contract(cls, status):
    """API_CONTRACTS lists 200, 201, 202, 400, 401, 403, 404, 409, 413, 422, 429, 500, 503."""
    assert cls().http_status == status


def test_every_error_code_is_unique():
    subclasses: set[type] = set()
    stack = [errors.AppError]
    while stack:
        cls = stack.pop()
        subclasses.add(cls)
        stack.extend(cls.__subclasses__())

    codes = [c.code for c in subclasses]
    duplicates = {code for code in codes if codes.count(code) > 1}
    # Subclasses may intentionally inherit a parent's code only if they override it;
    # here we assert no accidental collisions.
    assert not duplicates, f"duplicate error codes: {duplicates}"


def test_agent_errors_are_all_agent_error_subclasses():
    """FINAL §25: AI failure must be distinguishable so it never creates a record."""
    for cls in (errors.AgentSchemaError, errors.AgentTimeoutError):
        assert issubclass(cls, errors.AgentError)


def test_message_override():
    err = errors.NotFoundError("Species was not found.")
    assert err.message == "Species was not found."
    assert err.code == "NOT_FOUND"
