"""Application-structure behaviour: readiness, throttling and error mapping.

No database. The authenticated caller is stubbed through FastAPI's dependency
overrides so the throttling behaviour can be asserted without live tokens.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.api.dependencies import AIRateLimitDep, CurrentUser, get_current_user
from app.api.rate_limit import ai_limiter
from tests.conftest import REQUIRED_ENV

probe_router = APIRouter()


@probe_router.post("/v1/_probe/ai")
async def ai_probe(_: AIRateLimitDep) -> dict[str, str]:
    """Stands in for a real AI-triggering endpoint.

    None exist yet - identification runs arrive in a later phase - so this exercises
    the dependency rather than inventing production API surface early.
    """
    return {"ok": "true"}


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()
    yield monkeypatch
    settings_module.get_settings.cache_clear()


@pytest.fixture
def client(app_env):
    from app.api.main import create_app

    app = create_app()
    app.include_router(probe_router)

    stub = CurrentUser(id=uuid.uuid4(), email="a@example.com", access_token="x", client=None)
    app.dependency_overrides[get_current_user] = lambda: stub

    ai_limiter.reset()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    ai_limiter.reset()


# --- readiness ----------------------------------------------------------------


def test_ready_reports_ok_when_the_database_answers(client: TestClient, monkeypatch):
    from app.api import main as main_module

    class _Stub:
        def table(self, _name):
            return self

        def select(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def execute(self):
            return type("R", (), {"data": []})()

    monkeypatch.setattr(main_module, "anon_client", lambda: _Stub())

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"


def test_ready_reports_unavailable_when_the_database_fails(client: TestClient, monkeypatch):
    """Readiness must take a broken instance out of rotation rather than let it
    accept requests it cannot answer."""
    from app.api import main as main_module

    def _boom():
        raise ConnectionError("no route to host")

    monkeypatch.setattr(main_module, "anon_client", _boom)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "failed"


def test_readiness_failure_does_not_leak_the_underlying_error(client: TestClient, monkeypatch):
    from app.api import main as main_module

    def _boom():
        raise ConnectionError("postgres://user:hunter2@db.internal:5432 unreachable")

    monkeypatch.setattr(main_module, "anon_client", _boom)

    body = client.get("/ready").text
    assert "hunter2" not in body
    assert "db.internal" not in body


def test_liveness_does_not_touch_the_database(client: TestClient, monkeypatch):
    """A liveness probe that checks the database restarts healthy containers during
    a database blip, turning a partial outage into a total one."""
    from app.api import main as main_module

    def _boom():
        raise ConnectionError("down")

    monkeypatch.setattr(main_module, "anon_client", _boom)

    assert client.get("/health").status_code == 200


# --- throttling ---------------------------------------------------------------


def test_requests_within_the_limit_pass(client: TestClient):
    for _ in range(3):
        assert client.post("/v1/_probe/ai").status_code == 200


def test_the_request_over_the_limit_is_throttled(client: TestClient):
    """Default is 3/minute (A14)."""
    for _ in range(3):
        client.post("/v1/_probe/ai")

    response = client.post("/v1/_probe/ai")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_a_throttled_response_carries_retry_after(client: TestClient):
    """Without it a client knows it was throttled but not for how long, which
    invites an immediate retry and makes the problem worse."""
    for _ in range(3):
        client.post("/v1/_probe/ai")

    response = client.post("/v1/_probe/ai")

    assert "Retry-After" in response.headers
    assert 1 <= int(response.headers["Retry-After"]) <= 60


def test_throttling_uses_the_error_envelope(client: TestClient):
    for _ in range(4):
        response = client.post("/v1/_probe/ai")

    body = response.json()
    assert set(body) == {"error", "request_id"}
    assert body["error"]["details"]["retry_after_seconds"] > 0


def test_an_unauthenticated_caller_is_refused_before_spending_allowance(app_env):
    """The limit depends on authentication, so an anonymous caller cannot exhaust
    another user's allowance - or fill the limiter with junk keys."""
    from app.api.main import create_app

    app = create_app()
    app.include_router(probe_router)
    ai_limiter.reset()

    with TestClient(app, raise_server_exceptions=False) as anon:
        for _ in range(10):
            assert anon.post("/v1/_probe/ai").status_code == 401


# --- error mapping ------------------------------------------------------------


def test_method_not_allowed_uses_the_envelope(client: TestClient):
    response = client.delete("/health")

    assert response.status_code in (404, 405)
    assert "error" in response.json()


def test_every_response_carries_a_request_id(client: TestClient):
    for path, method in [("/health", "get"), ("/ready", "get"), ("/v1/me", "get")]:
        response = getattr(client, method)(path)
        assert response.headers.get("X-Request-ID"), f"{path} lost the request id"
