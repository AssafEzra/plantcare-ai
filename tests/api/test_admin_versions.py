"""`GET /v1/admin/versions`: three answers, and a promise never to fail.

The block this feeds exists to be trustworthy when nothing else is - it is what an
administrator reads when the panel is misbehaving and they need to know which code
is actually running. So the contract is unusual: every field is optional, and the
route answers 200 even when git is missing, production is unreachable and no bundle
is served. A diagnostic that breaks along with the thing it diagnoses is worse than
none.

Two behaviours here are load-bearing rather than cosmetic:

* `role` is stated, never inferred. A development machine with no
  `PRODUCTION_BASE_URL` set must not label its own commit as the deployed one, and
  that is the out-of-the-box configuration of every checkout.
* A Cloud Run instance makes no outbound request at all, even if something put a
  `PRODUCTION_BASE_URL` in its environment. It *is* production, `--max-instances=1`
  means it has one instance to spend, and fetching itself would be absurd.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import CurrentUser, require_admin
from tests.conftest import REQUIRED_ENV

BASE = "https://plantcare-ai.example.run.app"


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")
    for key in ("APP_COMMIT", "K_REVISION", "PRODUCTION_BASE_URL", "SPA_DIST_DIR"):
        monkeypatch.delenv(key, raising=False)

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()
    yield monkeypatch
    settings_module.get_settings.cache_clear()


@pytest.fixture
def client(app_env):
    from app.api.main import create_app
    from app.infrastructure import build, upstream_version

    build.commit.cache_clear()
    upstream_version.forget()

    app = create_app()
    stub = CurrentUser(id=uuid.uuid4(), email="admin@example.com", access_token="x", client=None)
    app.dependency_overrides[require_admin] = lambda: stub

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    build.commit.cache_clear()
    upstream_version.forget()


def versions(client: TestClient) -> dict:
    response = client.get("/v1/admin/versions")
    assert response.status_code == 200, response.text
    return response.json()["data"]


# --- who is answering -----------------------------------------------------------


def test_an_unauthenticated_caller_is_refused(app_env):
    """The override is the only reason the other tests reach the route."""
    from app.api.main import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as anonymous:
        assert anonymous.get("/v1/admin/versions").status_code in (401, 403)


def test_a_local_server_says_so(client: TestClient):
    data = versions(client)

    assert data["role"] == "local"
    assert data["server"] is not None
    assert data["production_status"] == "unconfigured"
    assert data["production"] is None


def test_an_unconfigured_production_is_not_mistaken_for_this_server(client: TestClient):
    """The default configuration of every checkout. Inferring the role from a null
    would render this server's own commit on the production line and claim the dev
    machine was the deployment."""
    data = versions(client)

    assert data["production"] is None
    assert data["server"]["commit"] != ""


def test_cloud_run_reports_itself_as_production(app_env):
    from app.api.dependencies import require_admin as dep
    from app.api.main import create_app

    app_env.setenv("K_REVISION", "plantcare-ai-00010-z44")
    app_env.setenv("APP_COMMIT", "cd0f30d")

    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    from app.infrastructure import build

    build.commit.cache_clear()

    app = create_app()
    stub = CurrentUser(id=uuid.uuid4(), email="admin@example.com", access_token="x", client=None)
    app.dependency_overrides[dep] = lambda: stub

    with TestClient(app, raise_server_exceptions=False) as client:
        data = versions(client)

    build.commit.cache_clear()

    assert data["role"] == "production"
    assert data["production_status"] == "self"
    assert data["production"]["commit"] == "cd0f30d"
    assert data["production"]["revision"] == "plantcare-ai-00010-z44"
    # No second server to report, which is what renders the "not applicable" cell.
    assert data["server"] is None
    assert data["head"] is None


def test_production_never_fetches_anything(app_env, httpx_mock):
    """Even with a base URL in its environment. `httpx_mock` fails the test on an
    unmatched request, so making none is the assertion."""
    from app.api.dependencies import require_admin as dep
    from app.api.main import create_app

    app_env.setenv("K_REVISION", "plantcare-ai-00010-z44")
    app_env.setenv("PRODUCTION_BASE_URL", BASE)

    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    app = create_app()
    stub = CurrentUser(id=uuid.uuid4(), email="admin@example.com", access_token="x", client=None)
    app.dependency_overrides[dep] = lambda: stub

    with TestClient(app, raise_server_exceptions=False) as client:
        assert versions(client)["role"] == "production"

    assert httpx_mock.get_requests() == []


# --- asking production ----------------------------------------------------------


def test_a_reachable_production_is_reported(client: TestClient, app_env, httpx_mock):
    app_env.setenv("PRODUCTION_BASE_URL", BASE)

    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    httpx_mock.add_response(url=f"{BASE}/version", json={"commit": "cd0f30d"})

    data = versions(client)

    assert data["production_status"] == "ok"
    assert data["production"]["commit"] == "cd0f30d"
    # Admin-only elsewhere; the public payload does not carry it, so it is absent
    # for a fetched answer and that is correct rather than missing.
    assert data["production"]["revision"] is None


def test_an_unreachable_production_is_a_blank_line_not_a_failure(
    client: TestClient, app_env, httpx_mock
):
    import httpx

    app_env.setenv("PRODUCTION_BASE_URL", BASE)

    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    httpx_mock.add_exception(httpx.ConnectError("no route"))

    data = versions(client)

    assert data["production_status"] == "unreachable"
    assert data["production"] is None
    # The two local answers still arrive, which is the whole point of degrading.
    assert data["server"] is not None


# --- the promise ----------------------------------------------------------------


def test_it_answers_when_nothing_can_be_established(client: TestClient, app_env):
    """No git, no bundle, no production. Every field optional, still a 200.

    This is the state of the deployed container plus a dead upstream, and it is
    exactly when someone is reading this page.
    """
    from app.infrastructure import build

    def no_git(*_args, **_kwargs):
        raise FileNotFoundError("git")

    app_env.setattr(build.subprocess, "run", no_git)
    build.commit.cache_clear()

    data = versions(client)

    assert data["server"]["commit"] == "unknown"
    assert data["server"]["bundle_built_at"] is None
    assert data["head"] is None
    assert data["production_behind"] is None
    assert data["production_ahead"] is None
