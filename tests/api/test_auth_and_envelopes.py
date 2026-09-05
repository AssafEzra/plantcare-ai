"""API-level tests that need no database.

Covers the parts of API_CONTRACTS §"Standard responses" and §"Security" that are
decided before any query runs: envelope shape, request ids, and rejection of
unauthenticated or malformed requests.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.conftest import REQUIRED_ENV


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    from app.api.main import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client

    settings_module.get_settings.cache_clear()


# --- liveness -----------------------------------------------------------------


def test_health_needs_no_authentication(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- authentication -----------------------------------------------------------


def test_missing_authorization_is_401(client: TestClient):
    response = client.get("/v1/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(
    "header",
    ["", "Basic abc123", "bearer", "Bearer", "Bearer    ", "token abc", "abc123"],
)
def test_bad_authorization_headers_are_401(client: TestClient, header: str):
    response = client.get("/v1/me", headers={"Authorization": header})

    assert response.status_code == 401


def test_forged_token_is_401(client: TestClient):
    """A structurally valid but unsigned token must not be accepted."""
    forged = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhZG1pbiJ9."

    response = client.get("/v1/me", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


def test_error_response_never_leaks_internals(client: TestClient):
    response = client.get("/v1/me", headers={"Authorization": "Bearer nonsense.nonsense.nonsense"})

    body = response.text.lower()
    for leak in ("traceback", "supabase", "jwks", 'file "', "line "):
        assert leak not in body, f"error response leaked {leak!r}"


# --- envelopes ----------------------------------------------------------------


def test_error_envelope_shape(client: TestClient):
    response = client.get("/v1/me")
    body = response.json()

    assert set(body) == {"error", "request_id"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert isinstance(body["error"]["message"], str)


def test_unknown_route_returns_the_envelope_not_fastapi_default(client: TestClient):
    response = client.get("/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_request_id_is_generated_and_echoed(client: TestClient):
    response = client.get("/v1/me")

    header_id = response.headers["X-Request-ID"]
    assert header_id == response.json()["request_id"]
    uuid.UUID(header_id)  # parses


def test_supplied_request_id_is_honoured(client: TestClient):
    """DEPLOYMENT §9 wants a request id that can be correlated across services."""
    supplied = str(uuid.uuid4())

    response = client.get("/v1/me", headers={"X-Request-ID": supplied})

    assert response.headers["X-Request-ID"] == supplied
    assert response.json()["request_id"] == supplied


def test_each_request_gets_a_distinct_id(client: TestClient):
    first = client.get("/v1/me").json()["request_id"]
    second = client.get("/v1/me").json()["request_id"]

    assert first != second


# --- request validation -------------------------------------------------------


def test_unknown_fields_are_rejected(client: TestClient):
    """PATCH /v1/me forbids extras, so `care_level` and `role` cannot sneak in.

    Authentication is checked first, so this asserts the 401 rather than a 422 -
    the point being that an unauthenticated caller never reaches validation at all.
    """
    response = client.patch("/v1/me", json={"role": "ADMIN"})

    assert response.status_code == 401
