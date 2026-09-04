"""DEPLOYMENT_AND_OPERATIONS §9 / FINAL §23: secrets and chain-of-thought never reach logs."""

from __future__ import annotations

import pytest

from app.config.logging import _redact


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "api_key",
        "API_KEY",
        "apiKey",
        "supabase_service_role_key",
        "authorization",
        "access_token",
        "jwt",
        "anon_key",
        "credential",
    ],
)
def test_sensitive_values_are_redacted(key):
    result = _redact(None, "info", {key: "super-secret", "plant_id": "p-1"})

    assert result[key] == "***redacted***"
    assert result["plant_id"] == "p-1"


@pytest.mark.parametrize(
    "key", ["chain_of_thought", "reasoning_trace", "raw_prompt", "raw_response"]
)
def test_banned_keys_are_dropped_entirely(key):
    """Not redacted — removed. Chain-of-thought must not be persisted at all."""
    result = _redact(None, "info", {key: "step 1...", "agent_type": "IDENTIFICATION"})

    assert key not in result
    assert result["agent_type"] == "IDENTIFICATION"


def test_operational_fields_survive():
    """The DEPLOYMENT §9 field set must pass through untouched."""
    event = {
        "timestamp": "2026-09-05T08:00:00Z",
        "environment": "development",
        "request_id": "req-1",
        "user_id": "u-1",
        "plant_id": "p-1",
        "agent_type": "CARE",
        "status": "SUCCEEDED",
        "duration": 1234,
        "error_code": None,
    }
    assert _redact(None, "info", dict(event)) == event
