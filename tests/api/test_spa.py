"""Serving the built interface and the API from one origin.

The thing worth testing here is not that a static file can be returned. It is the
boundary: a single-page application has to answer for paths that are not files, and
the API has to keep answering for paths that are not pages. Get that wrong in
either direction and the failure is quiet — a client parsing JSON receives HTML, or
a reader refreshing a page receives a 404.

`SPA_DIST_DIR` is unset everywhere except the container, so these tests build their
own `dist` in a tmp_path rather than depending on whether anyone has run
`npm run build`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import REQUIRED_ENV

INDEX = "<!doctype html><title>PlantCare</title><div id=root></div>"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A plausible `npm run build` output: an index, a hashed asset, a worker."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    (root / "assets" / "index-a1b2c3d4.js").write_text("console.log(1)", encoding="utf-8")
    (root / "sw.js").write_text("self.addEventListener('install', () => {})", encoding="utf-8")
    (root / "manifest.webmanifest").write_text('{"name":"PlantCare AI"}', encoding="utf-8")
    return root


@pytest.fixture
def client(dist: Path, monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SPA_DIST_DIR", str(dist))

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    from app.api.main import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client

    settings_module.get_settings.cache_clear()


# --- the application ----------------------------------------------------------


def test_the_root_serves_the_application(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert "id=root" in response.text


def test_a_deep_link_serves_the_application(client: TestClient):
    """`/plants/<id>` is a route in the browser and a file nowhere.

    Streamlit had no meaningful URLs, so this is the first deployment where a
    refresh on an inner page is even possible — and the first where it could 404.
    """
    response = client.get(f"/plants/{'a' * 8}-dead-beef")

    assert response.status_code == 200
    assert "id=root" in response.text


def test_the_health_screen_is_the_application_not_the_probe(client: TestClient):
    """The collision that forced `/livez`.

    `/health` is the בריאות screen. If the liveness probe still owned this path, a
    reader who refreshed it would be shown `{"status": "ok"}`.
    """
    response = client.get("/health")

    assert response.status_code == 200
    assert "id=root" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_a_real_file_is_served_as_itself(client: TestClient):
    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.json() == {"name": "PlantCare AI"}


def test_the_service_worker_is_served(client: TestClient):
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert "addEventListener" in response.text


# --- the API still owns its own paths -----------------------------------------


def test_an_unknown_api_path_is_still_a_json_envelope(client: TestClient):
    """The failure that matters most, because it is silent.

    A catch-all that answered here would hand every API client a page of HTML
    where it expected `{"error": {...}}`, and the error it then reported would
    describe the parse, not the request.
    """
    response = client.get("/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_the_probes_answer_at_their_own_paths(client: TestClient):
    response = client.get("/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_openapi_schema_is_not_the_application(client: TestClient):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "PlantCare AI"


# --- safety -------------------------------------------------------------------


def test_a_traversal_attempt_cannot_read_outside_the_build(dist: Path, client: TestClient):
    """`..` resolves out of `dist` and must not be served from there.

    Encoded, because an unencoded `..` is collapsed by the client and by any proxy
    in front of it long before the application sees it — testing that form proves
    only that somebody else normalised the path. `%2e%2e%2f` arrives intact.

    The shell is an acceptable answer and so is a 404; reading the file is not.
    """
    secret = dist.parent / "secret.env"
    secret.write_text("SUPABASE_SERVICE_ROLE_KEY=hunter2", encoding="utf-8")

    for attempt in (
        "/%2e%2e%2fsecret.env",
        "/..%2fsecret.env",
        "/assets/%2e%2e%2f%2e%2e%2fsecret.env",
    ):
        response = client.get(attempt)

        assert "hunter2" not in response.text, attempt


def test_a_build_with_no_index_refuses_to_start(tmp_path: Path):
    """An empty `dist` is a broken build, and it should say so at startup.

    Mounting it anyway would serve a 404 for every page in the application and
    report nothing — the deployment would look healthy and be entirely dark.
    """
    from fastapi import FastAPI

    from app.api.spa import mount_spa

    with pytest.raises(RuntimeError, match=r"no index.html"):
        mount_spa(FastAPI(), tmp_path)


# --- caching ------------------------------------------------------------------


def test_a_hashed_bundle_is_cached_hard(client: TestClient):
    """The only files whose name guarantees their content.

    This is also a regression: the first version of `mount_spa` served `assets/`
    through a `StaticFiles` mount, which sets `ETag` and `Last-Modified` but no
    `Cache-Control` — so the bundles were revalidated on every navigation, which
    is the one thing the hash in their name exists to avoid.
    """
    response = client.get("/assets/index-a1b2c3d4.js")

    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_the_shell_and_the_worker_are_never_cached(client: TestClient):
    """A cached `sw.js` pins a visitor to the shell it shipped with.

    That failure cannot be repaired by deploying again, because the stale worker
    is what decides whether to fetch a new one.
    """
    for path in ("/", "/sw.js"):
        assert client.get(path).headers["cache-control"] == "no-cache", path


def test_a_missing_asset_is_a_404_not_the_shell(client: TestClient):
    """`index.html` asks for these as scripts and stylesheets.

    Answering a missing one with a page of HTML turns "this file is gone" into an
    unexplained syntax error in the console.
    """
    response = client.get("/assets/index-deadbeef.js")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
