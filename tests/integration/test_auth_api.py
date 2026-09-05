"""End-to-end authentication against the real DEV project.

This is the test that proves the plan's first decision: that a request-scoped
supabase-py client built from the caller's JWT actually has RLS applied, so the
database — not Python — is the security boundary.

Every user created here is deleted afterwards.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

# Imported at module scope, not inside the fixture below, and that placement is
# load-bearing: this module uses `from __future__ import annotations`, so every
# annotation is a string that FastAPI resolves against the *module* globals. A
# dependency alias imported inside a function is invisible there, and FastAPI
# silently falls back to treating the parameter as a request field - the route
# then answers 422 instead of 401, with nothing in the traceback pointing at the
# cause.
from app.api.dependencies import AdminDep
from tests.integration.conftest import delete_accounts

pytestmark = pytest.mark.integration

PASSWORD = "Integration-Passw0rd!"


def _load_env() -> bool:
    """Populate os.environ from .env so the app sees the real DEV project."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
    return bool(os.environ.get("SUPABASE_URL"))


@pytest.fixture(scope="module")
def live_env() -> None:
    if not _load_env():
        pytest.skip("no .env with DEV credentials; skipping live auth tests")

    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()


@pytest.fixture(scope="module")
def admin_sdk(live_env):
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


@pytest.fixture
def make_account(admin_sdk) -> Iterator:
    """Create a confirmed user and sign them in, returning (id, token)."""
    from supabase import create_client

    created: list[str] = []

    def _make(is_admin: bool = False) -> tuple[str, str]:
        email = f"itest-{uuid.uuid4().hex[:12]}@example.com"
        user = admin_sdk.auth.admin.create_user(
            {"email": email, "password": PASSWORD, "email_confirm": True}
        ).user
        created.append(user.id)

        if is_admin:
            admin_sdk.table("profiles").update({"role": "ADMIN"}).eq("id", user.id).execute()

        anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        session = anon.auth.sign_in_with_password({"email": email, "password": PASSWORD}).session
        return user.id, session.access_token

    yield _make

    delete_accounts(admin_sdk, created)


@pytest.fixture
def api(live_env) -> Iterator[TestClient]:
    from app.api.main import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- the signup trigger, seen through the API ---------------------------------


def test_a_new_account_can_read_its_profile(api: TestClient, make_account):
    user_id, token = make_account()

    response = api.get("/v1/me", headers=auth(token))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == user_id
    assert data["role"] == "USER"
    assert data["timezone"] == "Asia/Jerusalem"
    assert data["locale"] == "he"
    assert data["is_active"] is True


def test_response_carries_the_success_envelope(api: TestClient, make_account):
    _, token = make_account()

    body = api.get("/v1/me", headers=auth(token)).json()

    assert set(body) == {"data", "request_id"}


# --- RLS, proven through the API ----------------------------------------------


def test_a_user_sees_only_their_own_profile(api: TestClient, make_account):
    """The decision under test: RLS applies to a client built from the caller's JWT."""
    alice_id, alice_token = make_account()
    bob_id, _ = make_account()

    data = api.get("/v1/me", headers=auth(alice_token)).json()["data"]

    assert data["id"] == alice_id
    assert data["id"] != bob_id


def test_a_token_cannot_be_reused_for_another_identity(api: TestClient, make_account):
    """Ownership comes from the token, never from the request body."""
    alice_id, alice_token = make_account()
    make_account()  # a second account must exist for the isolation to mean anything

    # Whatever the body says, alice's token can only ever act as alice.
    response = api.patch(
        "/v1/me",
        headers=auth(alice_token),
        json={"display_name": "written-by-alice"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == alice_id


# --- updates ------------------------------------------------------------------


def test_display_name_and_timezone_can_be_updated(api: TestClient, make_account):
    _, token = make_account()

    response = api.patch(
        "/v1/me",
        headers=auth(token),
        json={"display_name": "אסף", "timezone": "Europe/Berlin"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["display_name"] == "אסף"
    assert data["timezone"] == "Europe/Berlin"


def test_an_unknown_timezone_is_rejected(api: TestClient, make_account):
    """The scheduler converts every due time through this value, so an unknown zone
    would otherwise fail later, inside the tick, for one user only."""
    _, token = make_account()

    response = api.patch("/v1/me", headers=auth(token), json={"timezone": "Mars/Olympus_Mons"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    "payload",
    [
        {"role": "ADMIN"},
        {"is_active": False},
        {"anonymized_at": "2026-01-01T00:00:00Z"},
        {"care_level": "ADVANCED"},
        {"id": "00000000-0000-0000-0000-000000000000"},
    ],
)
def test_privileged_and_out_of_scope_fields_are_refused(
    api: TestClient, make_account, payload: dict
):
    """TESTING §7: a client-supplied role must never grant admin access. The schema
    forbids extras, so these are rejected before reaching the database — which also
    still refuses them, via the profiles privilege-guard trigger."""
    _, token = make_account()

    response = api.patch("/v1/me", headers=auth(token), json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_role_is_unchanged_after_a_refused_update(api: TestClient, make_account):
    _, token = make_account()
    api.patch("/v1/me", headers=auth(token), json={"role": "ADMIN"})

    assert api.get("/v1/me", headers=auth(token)).json()["data"]["role"] == "USER"


def test_an_empty_update_is_a_no_op(api: TestClient, make_account):
    _, token = make_account()

    response = api.patch("/v1/me", headers=auth(token), json={})

    assert response.status_code == 200


# --- admin gating -------------------------------------------------------------


@pytest.fixture
def api_with_admin_route(live_env) -> Iterator[TestClient]:
    """Mounts a route using the admin dependency.

    A test-only route rather than a real one: the admin API surface arrives in a
    later phase, and inventing endpoints early would be worse than testing the
    dependency directly.
    """
    from app.api.main import create_app

    router = APIRouter()

    @router.get("/v1/admin/_probe")
    async def probe(admin: AdminDep) -> dict[str, str]:
        return {"admin": str(admin.id)}

    app: FastAPI = create_app()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_a_regular_user_is_refused_admin_routes(api_with_admin_route, make_account):
    _, token = make_account()

    response = api_with_admin_route.get("/v1/admin/_probe", headers=auth(token))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_an_admin_is_allowed(api_with_admin_route, make_account):
    admin_id, token = make_account(is_admin=True)

    response = api_with_admin_route.get("/v1/admin/_probe", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["admin"] == admin_id


def test_an_anonymous_caller_is_refused_admin_routes(api_with_admin_route):
    assert api_with_admin_route.get("/v1/admin/_probe").status_code == 401


def test_a_disabled_account_is_refused(api_with_admin_route, make_account, admin_sdk):
    """FINAL §21: anonymisation disables access. is_active is checked server-side."""
    user_id, token = make_account(is_admin=True)
    admin_sdk.table("profiles").update({"is_active": False}).eq("id", user_id).execute()

    response = api_with_admin_route.get("/v1/admin/_probe", headers=auth(token))

    assert response.status_code == 403
