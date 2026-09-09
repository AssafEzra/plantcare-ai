"""The admin "view as user" mode against DEV, where RLS is real.

The unit tests prove the header is only honoured for administrators and that the mode
cannot write. Neither can prove the thing that actually matters here, because it
depends on live policies:

**The reads must return exactly one user's rows.** The admin's `_select_admin` policy
admits *every* row in `plants`; what confines the answer to one account is that every
user-facing query filters on an owner id explicitly (see `repositories/plants.py:89`).
If that were ever untrue - a read leaning on RLS alone - an administrator viewing one
user would silently see everybody's plants, and the screen would look perfectly
normal. So the control here is a second user with their own plant.

No model calls: every route touched is a read.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import ACT_AS_HEADER
from tests.integration.conftest import delete_accounts, unique_species_name

pytestmark = pytest.mark.integration

PASSWORD = "ViewAs-Passw0rd!"


def _load_env() -> bool:
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    return bool(os.environ.get("SUPABASE_URL"))


@pytest.fixture(scope="module")
def live_env() -> None:
    if not _load_env():
        pytest.skip("no .env with DEV credentials")
    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()


@pytest.fixture(scope="module")
def admin_sdk(live_env):
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


@pytest.fixture
def api(live_env) -> Iterator[TestClient]:
    from app.api.main import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def account(admin_sdk):
    """Makes users, optionally promoted to ADMIN."""
    from supabase import create_client

    created: list[str] = []

    def _make(role: str = "USER") -> tuple[str, dict[str, str]]:
        email = f"vas-{uuid.uuid4().hex[:12]}@example.com"
        user = admin_sdk.auth.admin.create_user(
            {"email": email, "password": PASSWORD, "email_confirm": True}
        ).user
        created.append(user.id)
        if role == "ADMIN":
            # Through the service role: the guard trigger stops a user promoting
            # themselves, which is the point of it.
            admin_sdk.table("profiles").update({"role": "ADMIN"}).eq("id", user.id).execute()
        anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        token = anon.auth.sign_in_with_password(
            {"email": email, "password": PASSWORD}
        ).session.access_token
        return user.id, {"Authorization": f"Bearer {token}"}

    yield _make

    delete_accounts(admin_sdk, created)


@pytest.fixture
def cast(admin_sdk, account) -> Iterator[dict]:
    """An admin, the user being viewed, and a bystander who must stay invisible."""
    admin_id, admin_auth = account("ADMIN")
    owner_id, owner_auth = account()
    other_id, _ = account()

    # ACTIVE, with a species. Not PENDING_IDENTIFICATION: a pending plant with no
    # successful identification is deliberately hidden from `/v1/plants` (the
    # abandoned-plant rule), so the listing came back empty and the "sees nobody
    # else's plants" assertion below passed vacuously.
    species = (
        admin_sdk.table("species")
        .insert({"scientific_name": unique_species_name()})
        .execute()
        .data[0]
    )

    plants = []
    for user_id, name in ((owner_id, "צמח של הנצפה"), (other_id, "צמח של אחר")):
        plants.append(
            admin_sdk.table("plants")
            .insert(
                {
                    "user_id": user_id,
                    "species_id": species["id"],
                    "status": "ACTIVE",
                    "name": name,
                }
            )
            .execute()
            .data[0]
        )

    yield {
        "admin_id": admin_id,
        "admin_auth": admin_auth,
        "owner_id": owner_id,
        "owner_auth": owner_auth,
        "other_id": other_id,
        "owner_plant": plants[0],
        "other_plant": plants[1],
    }

    for plant in plants:
        admin_sdk.table("plants").delete().eq("id", plant["id"]).execute()
    admin_sdk.table("species").delete().eq("id", species["id"]).execute()


def acting(cast: dict, target: str | None = None) -> dict[str, str]:
    return {**cast["admin_auth"], ACT_AS_HEADER: str(target or cast["owner_id"])}


# --- the property that needs a real database ------------------------------------


def test_an_admin_sees_the_viewed_users_plants(api, cast):
    response = api.get("/v1/plants", headers=acting(cast))

    assert response.status_code == 200
    names = [p["name"] for p in response.json()["data"]]
    assert cast["owner_plant"]["name"] in names


def test_and_nobody_elses(api, cast):
    """The test this file exists for.

    `plants_select_admin` admits every row in the table. Only the explicit owner
    filter keeps this answer to one account, and a regression there would look
    entirely normal on screen.
    """
    response = api.get("/v1/plants", headers=acting(cast))

    ids = {p["id"] for p in response.json()["data"]}
    assert cast["other_plant"]["id"] not in ids


def test_me_returns_the_viewed_account(api, cast):
    """What the navigation keys on: acting as a USER must report role USER, or the
    admin panel would stay on screen while showing somebody else's data."""
    body = api.get("/v1/me", headers=acting(cast)).json()["data"]

    assert body["id"] == cast["owner_id"]
    assert body["role"] == "USER"


def test_the_viewed_users_plant_page_opens(api, cast):
    """A 404 here would mean the owner filter rejected the very plant it just
    listed - `plants_repo.get` scopes by owner too."""
    plant_id = cast["owner_plant"]["id"]

    response = api.get(f"/v1/plants/{plant_id}", headers=acting(cast))

    assert response.status_code == 200


# --- refusals -------------------------------------------------------------------


def test_a_normal_user_cannot_act_as_anyone(api, cast):
    """The escalation this feature would otherwise open."""
    headers = {**cast["owner_auth"], ACT_AS_HEADER: str(cast["other_id"])}

    response = api.get("/v1/plants", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_writing_is_refused_even_for_an_admin(api, cast):
    """Read-only, enforced in middleware. The database would refuse it too, but
    only as an opaque failure."""
    response = api.post("/v1/plants", headers=acting(cast), json={})

    assert response.status_code == 403


def test_the_admin_panel_closes_while_acting_as_a_user(api, cast):
    """`get_current_role` reads the role of the *viewed* user, so /v1/admin is shut.
    Intentional: an administrator looking at somebody's plants is not simultaneously
    an administrator."""
    response = api.get("/v1/admin/accounts", headers=acting(cast))

    assert response.status_code == 403


# --- the audit trail -------------------------------------------------------------


def test_entering_the_mode_is_recorded(api, cast, admin_sdk):
    """Reading a stranger's plants, photographs and health history should be
    reviewable afterwards. No reason is collected, but who/whom/when is."""
    owner_id = cast["owner_id"]

    response = api.post(f"/v1/admin/accounts/{owner_id}/view-as", headers=cast["admin_auth"])
    assert response.status_code == 200

    entries = (
        admin_sdk.table("admin_audit_log")
        .select("action, target_table, target_id, admin_user_id, payload")
        .eq("admin_user_id", cast["admin_id"])
        .eq("action", "VIEW_AS_USER")
        .execute()
        .data
    )
    assert len(entries) == 1
    assert entries[0]["target_id"] == owner_id
    assert entries[0]["target_table"] == "profiles"
    # The email as it stood, so a later anonymisation leaves the row meaningful.
    assert entries[0]["payload"]["email"]


def test_a_normal_user_cannot_record_a_view(api, cast):
    target = cast["other_id"]

    response = api.post(f"/v1/admin/accounts/{target}/view-as", headers=cast["owner_auth"])

    assert response.status_code == 403
