"""The Add Plant vertical slice, end to end against DEV.

Covers the journey a user actually walks: create a plant, upload photos, set an
environment, archive it, bring it back. The assertions that matter most are the
ones about *history* — FINAL §19 says the timeline is append-oriented, and the
only way to know that holds is to check that each action left its trace.
"""

from __future__ import annotations

import contextlib
import io
import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image

pytestmark = pytest.mark.integration

PASSWORD = "Plants-Passw0rd!"


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
def account(admin_sdk) -> Iterator:
    from supabase import create_client

    created: list[str] = []

    def _make() -> tuple[str, dict[str, str]]:
        email = f"pl-{uuid.uuid4().hex[:12]}@example.com"
        user = admin_sdk.auth.admin.create_user(
            {"email": email, "password": PASSWORD, "email_confirm": True}
        ).user
        created.append(user.id)
        anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        token = anon.auth.sign_in_with_password(
            {"email": email, "password": PASSWORD}
        ).session.access_token
        return user.id, {"Authorization": f"Bearer {token}"}

    yield _make

    for user_id in created:
        with contextlib.suppress(Exception):
            admin_sdk.auth.admin.delete_user(user_id)


def photo(width: int = 900, height: int = 700) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (70, 130, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


def create_plant(api: TestClient, auth: dict, **body) -> dict:
    response = api.post("/v1/plants", headers=auth, json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def events(admin_sdk, plant_id: str) -> list[str]:
    result = (
        admin_sdk.table("system_events")
        .select("event_type")
        .eq("plant_id", plant_id)
        .order("created_at")
        .execute()
    )
    return [row["event_type"] for row in result.data]


# --- create -------------------------------------------------------------------


def test_a_plant_starts_pending_identification(api: TestClient, account):
    _, auth = account()

    plant = create_plant(api, auth, name="המונסטרה בסלון")

    assert plant["status"] == "PENDING_IDENTIFICATION"
    assert plant["current_health_status"] == "UNKNOWN"
    assert plant["species_id"] is None


def test_a_plant_can_be_created_before_it_is_named(api: TestClient, account):
    """A2: the Add Plant flow creates the plant before the user names it."""
    _, auth = account()

    plant = create_plant(api, auth)

    assert plant["name"] is None


def test_a_blank_name_is_stored_as_absent(api: TestClient, account):
    """Null means "not yet named"; an empty string would render as one."""
    _, auth = account()

    plant = create_plant(api, auth, name="   ")

    assert plant["name"] is None


def test_creation_is_recorded_in_history(api: TestClient, account, admin_sdk):
    _, auth = account()

    plant = create_plant(api, auth)

    assert "PLANT_CREATED" in events(admin_sdk, plant["id"])


def test_a_client_cannot_set_privileged_fields(api: TestClient, account):
    """status, species_id and health each change only through their own workflow."""
    _, auth = account()

    response = api.post("/v1/plants", headers=auth, json={"name": "x", "status": "ACTIVE"})

    assert response.status_code == 422


# --- listing and isolation ----------------------------------------------------


def test_a_user_sees_only_their_own_plants(api: TestClient, account):
    _, alice = account()
    _, bob = account()
    create_plant(api, alice, name="alice-plant")
    create_plant(api, bob, name="bob-plant")

    names = [p["name"] for p in api.get("/v1/plants", headers=alice).json()["data"]]

    assert names == ["alice-plant"]


def test_another_users_plant_is_not_found(api: TestClient, account):
    """A 404 rather than a 403: a 403 would confirm the plant exists."""
    _, alice = account()
    _, bob = account()
    bob_plant = create_plant(api, bob, name="bob-plant")

    response = api.get(f"/v1/plants/{bob_plant['id']}", headers=alice)

    assert response.status_code == 404


def test_search_filters_by_name(api: TestClient, account):
    _, auth = account()
    create_plant(api, auth, name="מונסטרה")
    create_plant(api, auth, name="פיקוס")

    found = api.get("/v1/plants", headers=auth, params={"q": "מונ"}).json()["data"]

    assert [p["name"] for p in found] == ["מונסטרה"]


def test_a_search_term_cannot_alter_the_filter(api: TestClient, account):
    """PostgREST builds its filters from strings, so a wildcard or comma in user
    input must not change what the query means."""
    _, auth = account()
    create_plant(api, auth, name="מונסטרה")

    for term in ["%", "*", "a,b", "%25", "name.eq.x"]:
        response = api.get("/v1/plants", headers=auth, params={"q": term})
        assert response.status_code == 200, term
        assert response.json()["data"] == [], f"{term!r} matched something"


# --- archive and restore ------------------------------------------------------


def test_archive_hides_the_plant_from_the_default_list(api: TestClient, account):
    """FINAL §21: archived plants are hidden from active views."""
    _, auth = account()
    plant = create_plant(api, auth, name="to-archive")

    assert api.post(f"/v1/plants/{plant['id']}/archive", headers=auth).status_code == 200

    assert api.get("/v1/plants", headers=auth).json()["data"] == []


def test_an_archived_plant_is_still_retrievable(api: TestClient, account):
    """Hidden from lists, not gone: its history has to remain reachable."""
    _, auth = account()
    plant = create_plant(api, auth, name="to-archive")
    api.post(f"/v1/plants/{plant['id']}/archive", headers=auth)

    fetched = api.get(f"/v1/plants/{plant['id']}", headers=auth).json()["data"]

    assert fetched["status"] == "ARCHIVED"
    assert fetched["archived_at"] is not None


def test_restoring_an_unidentified_plant_does_not_activate_it(api: TestClient, account):
    """The recomputed restore: an unidentified plant has no species and no care
    plan, so coming back as ACTIVE would be a state nothing else expects."""
    _, auth = account()
    plant = create_plant(api, auth, name="never-identified")
    api.post(f"/v1/plants/{plant['id']}/archive", headers=auth)

    restored = api.post(f"/v1/plants/{plant['id']}/restore", headers=auth).json()["data"]

    assert restored["status"] == "PENDING_IDENTIFICATION"
    assert restored["archived_at"] is None


def test_restoring_a_known_species_returns_it_to_active(api: TestClient, account, admin_sdk):
    """The documented ARCHIVED -> ACTIVE case, using a seeded species that has
    published knowledge."""
    _, auth = account()
    species = (
        admin_sdk.table("species")
        .select("id")
        .eq("normalized_name", "monstera deliciosa")
        .execute()
    )
    plant = create_plant(api, auth, name="known")
    admin_sdk.table("plants").update({"species_id": species.data[0]["id"], "status": "ACTIVE"}).eq(
        "id", plant["id"]
    ).execute()

    api.post(f"/v1/plants/{plant['id']}/archive", headers=auth)
    restored = api.post(f"/v1/plants/{plant['id']}/restore", headers=auth).json()["data"]

    assert restored["status"] == "ACTIVE"


def test_archiving_twice_is_rejected(api: TestClient, account):
    _, auth = account()
    plant = create_plant(api, auth)
    api.post(f"/v1/plants/{plant['id']}/archive", headers=auth)

    response = api.post(f"/v1/plants/{plant['id']}/archive", headers=auth)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_restoring_a_live_plant_is_rejected(api: TestClient, account):
    _, auth = account()
    plant = create_plant(api, auth)

    response = api.post(f"/v1/plants/{plant['id']}/restore", headers=auth)

    assert response.status_code == 422


def test_archive_and_restore_are_both_recorded(api: TestClient, account, admin_sdk):
    _, auth = account()
    plant = create_plant(api, auth)
    api.post(f"/v1/plants/{plant['id']}/archive", headers=auth)
    api.post(f"/v1/plants/{plant['id']}/restore", headers=auth)

    timeline = events(admin_sdk, plant["id"])

    assert timeline == ["PLANT_CREATED", "PLANT_ARCHIVED", "PLANT_RESTORED"]


# --- rename -------------------------------------------------------------------


def test_renaming_records_both_names(api: TestClient, account, admin_sdk):
    _, auth = account()
    plant = create_plant(api, auth, name="לפני")

    api.patch(f"/v1/plants/{plant['id']}", headers=auth, json={"name": "אחרי"})

    entry = (
        admin_sdk.table("system_events")
        .select("payload")
        .eq("plant_id", plant["id"])
        .eq("event_type", "PLANT_RENAMED")
        .execute()
    )
    assert entry.data[0]["payload"] == {"from": "לפני", "to": "אחרי"}


def test_renaming_to_the_same_value_records_nothing(api: TestClient, account, admin_sdk):
    """History is for changes; a no-op write would clutter the timeline."""
    _, auth = account()
    plant = create_plant(api, auth, name="same")

    api.patch(f"/v1/plants/{plant['id']}", headers=auth, json={"name": "same"})

    assert "PLANT_RENAMED" not in events(admin_sdk, plant["id"])


# --- environment --------------------------------------------------------------


def test_environment_starts_empty(api: TestClient, account):
    """FINAL §18: every field optional, and the Care Agent copes with partial data."""
    _, auth = account()
    plant = create_plant(api, auth)

    data = api.get(f"/v1/plants/{plant['id']}/environment", headers=auth).json()["data"]

    assert data["location_type"] is None


def test_environment_can_be_set_and_read_back(api: TestClient, account):
    _, auth = account()
    plant = create_plant(api, auth)

    api.put(
        f"/v1/plants/{plant['id']}/environment",
        headers=auth,
        json={"location_type": "INDOOR", "light_level": "BRIGHT", "temperature_c": 24},
    )
    data = api.get(f"/v1/plants/{plant['id']}/environment", headers=auth).json()["data"]

    assert data["location_type"] == "INDOOR"
    assert data["temperature_c"] == 24


def test_an_environment_change_is_written_to_history(api: TestClient, account, admin_sdk):
    """plant_environments keeps only the current row, so without this write Plant
    History would have nothing to render (FINAL §19)."""
    _, auth = account()
    plant = create_plant(api, auth)

    api.put(
        f"/v1/plants/{plant['id']}/environment",
        headers=auth,
        json={"location_type": "INDOOR"},
    )

    entry = (
        admin_sdk.table("system_events")
        .select("payload")
        .eq("plant_id", plant["id"])
        .eq("event_type", "ENVIRONMENT_CHANGED")
        .execute()
    )
    assert entry.data[0]["payload"]["changed"]["location_type"] == {
        "from": None,
        "to": "INDOOR",
    }


def test_writing_the_same_environment_records_nothing(api: TestClient, account, admin_sdk):
    _, auth = account()
    plant = create_plant(api, auth)
    body = {"location_type": "INDOOR"}
    api.put(f"/v1/plants/{plant['id']}/environment", headers=auth, json=body)
    api.put(f"/v1/plants/{plant['id']}/environment", headers=auth, json=body)

    assert events(admin_sdk, plant["id"]).count("ENVIRONMENT_CHANGED") == 1


@pytest.mark.parametrize(
    "body", [{"temperature_c": 200}, {"humidity_percent": 150}, {"light_level": "GLOWING"}]
)
def test_impossible_environment_values_are_rejected(api: TestClient, account, body: dict):
    _, auth = account()
    plant = create_plant(api, auth)

    response = api.put(f"/v1/plants/{plant['id']}/environment", headers=auth, json=body)

    assert response.status_code == 422


# --- images -------------------------------------------------------------------


def test_uploading_an_image_returns_signed_urls(api: TestClient, account):
    _, auth = account()
    plant = create_plant(api, auth)

    response = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("plant.jpg", photo(), "image/jpeg")},
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["thumbnail_url"] and data["processed_url"]
    assert data["width"] == 900


def test_the_first_gallery_image_becomes_the_main_image(api: TestClient, account):
    """FINAL §6: a plant card needs something to show without the user choosing."""
    _, auth = account()
    plant = create_plant(api, auth)

    uploaded = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("a.jpg", photo(), "image/jpeg")},
    ).json()["data"]

    fetched = api.get(f"/v1/plants/{plant['id']}", headers=auth).json()["data"]
    assert fetched["main_image_id"] == uploaded["id"]


def test_a_disguised_file_is_rejected(api: TestClient, account):
    """The declared type is not evidence; the bytes are."""
    _, auth = account()
    plant = create_plant(api, auth)

    response = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("evil.jpg", b"%PDF-1.7 not an image", "image/jpeg")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IMAGE_INVALID"


def test_the_image_count_is_capped(api: TestClient, account):
    """FINAL §8 and §16 both cap a batch at four."""
    _, auth = account()
    plant = create_plant(api, auth)

    for _ in range(4):
        assert (
            api.post(
                f"/v1/plants/{plant['id']}/images",
                headers=auth,
                files={"file": ("a.jpg", photo(), "image/jpeg")},
            ).status_code
            == 201
        )

    fifth = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("a.jpg", photo(), "image/jpeg")},
    )
    assert fifth.status_code == 422


def test_an_ordinary_image_is_deleted(api: TestClient, account):
    _, auth = account()
    plant = create_plant(api, auth)
    image = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("a.jpg", photo(), "image/jpeg")},
    ).json()["data"]

    response = api.delete(f"/v1/plants/{plant['id']}/images/{image['id']}", headers=auth)

    assert response.json()["data"]["outcome"] == "deleted"
    assert api.get(f"/v1/plants/{plant['id']}/images", headers=auth).json()["data"] == []


def test_an_ai_used_image_is_hidden_not_deleted(api: TestClient, account, admin_sdk):
    """FINAL §20 retention: it stays for history and audit, hidden from the user."""
    _, auth = account()
    plant = create_plant(api, auth)
    image = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("a.jpg", photo(), "image/jpeg")},
    ).json()["data"]
    admin_sdk.table("plant_images").update({"ai_used": True}).eq("id", image["id"]).execute()

    response = api.delete(f"/v1/plants/{plant['id']}/images/{image['id']}", headers=auth)

    assert response.json()["data"]["outcome"] == "hidden"
    # Gone from the user's view...
    assert api.get(f"/v1/plants/{plant['id']}/images", headers=auth).json()["data"] == []
    # ...but still on record.
    still_there = (
        admin_sdk.table("plant_images").select("user_visible").eq("id", image["id"]).execute()
    )
    assert still_there.data[0]["user_visible"] is False


def test_removing_the_main_image_promotes_another(api: TestClient, account):
    """A plant must not point at an image that is gone."""
    _, auth = account()
    plant = create_plant(api, auth)
    first = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("a.jpg", photo(), "image/jpeg")},
    ).json()["data"]
    second = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("b.jpg", photo(800, 600), "image/jpeg")},
    ).json()["data"]

    api.delete(f"/v1/plants/{plant['id']}/images/{first['id']}", headers=auth)

    fetched = api.get(f"/v1/plants/{plant['id']}", headers=auth).json()["data"]
    assert fetched["main_image_id"] == second["id"]


def test_a_user_cannot_upload_to_another_users_plant(api: TestClient, account):
    _, alice = account()
    _, bob = account()
    bob_plant = create_plant(api, bob)

    response = api.post(
        f"/v1/plants/{bob_plant['id']}/images",
        headers=alice,
        files={"file": ("a.jpg", photo(), "image/jpeg")},
    )

    assert response.status_code == 404


# --- role must not widen a user-facing view -----------------------------------


def test_an_admin_sees_only_their_own_plants(api, account, admin_sdk):
    """`plants_select_admin` lets an administrator read every plant, which is
    right for the admin panel and wrong for "My Plants".

    Found by looking at the screen: an admin's own plant list showed 590 plants
    belonging to other users, with their names. The route now scopes to the
    caller explicitly rather than leaning on RLS, because the policy is
    deliberately wider for this role.
    """
    owner_id, owner_auth = account()
    other_id, _ = account()

    mine = api.post("/v1/plants", headers=owner_auth, json={"name": "שלי"}).json()["data"]
    theirs = (
        admin_sdk.table("plants")
        .insert({"user_id": other_id, "name": "של מישהו אחר"})
        .execute()
        .data[0]
    )

    admin_sdk.table("profiles").update({"role": "ADMIN"}).eq("id", owner_id).execute()

    listed = api.get("/v1/plants", headers=owner_auth).json()["data"]
    ids = {p["id"] for p in listed}

    assert mine["id"] in ids
    assert theirs["id"] not in ids

    # And the per-plant route agrees: an admin fetching someone else's plant id
    # through the user-facing endpoint gets the same 404 anyone else would.
    assert api.get(f"/v1/plants/{theirs['id']}", headers=owner_auth).status_code == 404

    with contextlib.suppress(Exception):
        admin_sdk.table("plants").delete().eq("id", theirs["id"]).execute()
