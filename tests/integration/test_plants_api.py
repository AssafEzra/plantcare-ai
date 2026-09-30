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
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.integration.conftest import delete_accounts, unique_species_name

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

    delete_accounts(admin_sdk, created)


def photo(width: int = 900, height: int = 700) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (70, 130, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


def create_plant(api: TestClient, auth: dict, **body) -> dict:
    response = api.post("/v1/plants", headers=auth, json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def listed_plant(api: TestClient, auth: dict, admin_sdk, **body) -> dict:
    """A plant in a state My Plants actually shows.

    `POST /v1/plants` creates a plant in PENDING_IDENTIFICATION, and the grid no
    longer lists those: a plant appears once the user has something to approve, or
    has approved it. Thirty-three abandoned rows made that necessary.

    Tests about ownership scoping or about search are not about that rule, and
    should not quietly become tests of it. They promote past it here rather than
    assert around it.
    """
    plant = create_plant(api, auth, **body)
    admin_sdk.table("plants").update({"status": "IDENTIFIED"}).eq("id", plant["id"]).execute()
    return plant


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


def test_a_user_sees_only_their_own_plants(api: TestClient, account, admin_sdk):
    _, alice = account()
    _, bob = account()
    listed_plant(api, alice, admin_sdk, name="alice-plant")
    listed_plant(api, bob, admin_sdk, name="bob-plant")

    names = [p["name"] for p in api.get("/v1/plants", headers=alice).json()["data"]]

    assert names == ["alice-plant"]


def test_another_users_plant_is_not_found(api: TestClient, account):
    """A 404 rather than a 403: a 403 would confirm the plant exists."""
    _, alice = account()
    _, bob = account()
    bob_plant = create_plant(api, bob, name="bob-plant")

    response = api.get(f"/v1/plants/{bob_plant['id']}", headers=alice)

    assert response.status_code == 404


def test_search_filters_by_name(api: TestClient, account, admin_sdk):
    _, auth = account()
    listed_plant(api, auth, admin_sdk, name="מונסטרה")
    listed_plant(api, auth, admin_sdk, name="פיקוס")

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

    mine = listed_plant(api, owner_auth, admin_sdk, name="שלי")
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


# --- what the grid needs (PROGRESS §10) -------------------------------------------


def test_the_list_carries_the_thumbnail_the_card_renders(api: TestClient, account, admin_sdk):
    """The regression that made My Plants a grid of grey placeholders.

    `plant_card` had read `thumbnail_url` since PR 9 and this endpoint never set
    it, so every card showed "no image" however many photographs the plant had.
    `main_image_id` alone is not enough: the bucket is private, so the card needs
    a signed URL it can put in an `<img>`.
    """
    _, auth = account()
    plant = listed_plant(api, auth, admin_sdk)
    api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("a.jpg", photo(), "image/jpeg")},
    )

    listed = api.get("/v1/plants", headers=auth).json()["data"]
    mine = next(p for p in listed if p["id"] == plant["id"])

    assert mine["main_image_id"]
    assert mine["thumbnail_url"], "the grid has an image id but nothing to render"
    assert mine["thumbnail_url"].startswith("http")


def test_the_list_carries_the_species_name(api: TestClient, account, admin_sdk):
    """`species_id` is a UUID. A card cannot show a UUID to a person."""
    user_id, auth = account()
    species = (
        admin_sdk.table("species")
        .insert({"scientific_name": unique_species_name(), "common_name": "מונסטרה"})
        .execute()
        .data[0]
    )
    plant = (
        admin_sdk.table("plants")
        .insert(
            {"user_id": user_id, "species_id": species["id"], "name": "צמח", "status": "ACTIVE"}
        )
        .execute()
        .data[0]
    )

    listed = api.get("/v1/plants", headers=auth).json()["data"]
    mine = next(p for p in listed if p["id"] == plant["id"])

    assert mine["species_name"] == "מונסטרה"


def test_the_list_carries_the_nearest_open_task(api: TestClient, account, admin_sdk):
    """The nearest, and the action - a due date with no action is not a reminder.

    Two tasks are created deliberately: the endpoint must return the earlier one,
    which is the only part of this that a single-task fixture would not prove.
    They belong to two different rules because a partial unique index allows only
    one PENDING task per rule - the invariant that keeps a tick from producing a
    duplicate reminder, and one that makes "two tasks" mean "two rules".
    """
    user_id, auth = account()
    plant, version = _plant_with_rules(admin_sdk, user_id)

    for action, days in (("FERTILIZING", 9), ("WATERING", 2)):
        rule = (
            admin_sdk.table("care_rules")
            .insert(
                {
                    "care_plan_version_id": version["id"],
                    "action_type": action,
                    "interval_days": 7,
                }
            )
            .execute()
            .data[0]
        )
        admin_sdk.table("care_tasks").insert(
            {
                "user_id": user_id,
                "plant_id": plant["id"],
                "care_rule_id": rule["id"],
                "due_at_utc": (datetime.now(UTC) + timedelta(days=days)).isoformat(),
                "status": "PENDING",
            }
        ).execute()

    listed = api.get("/v1/plants", headers=auth).json()["data"]
    mine = next(p for p in listed if p["id"] == plant["id"])

    assert mine["next_task"]["action_type"] == "WATERING"
    due = datetime.fromisoformat(mine["next_task"]["due_at_utc"].replace("Z", "+00:00"))
    assert (due - datetime.now(UTC)).days < 5, "the later task was returned"


def test_a_plant_with_nothing_to_show_carries_nulls_not_errors(api: TestClient, account, admin_sdk):
    """A plant between creation and identification has no image, no species and no
    schedule. The card is written for that; the endpoint must not fail on it."""
    _, auth = account()
    plant = listed_plant(api, auth, admin_sdk)

    listed = api.get("/v1/plants", headers=auth).json()["data"]
    mine = next(p for p in listed if p["id"] == plant["id"])

    assert mine["thumbnail_url"] is None
    assert mine["species_name"] is None
    assert mine["next_task"] is None


def _plant_with_rules(admin_sdk, user_id: str) -> tuple[dict, dict]:
    """An ACTIVE plant with an ACTIVE plan version, ready for rules.

    Built directly rather than through the agents: this file is about the plants
    API, and driving a care plan through the Care Agent to reach a rule would
    make the test fail for reasons that have nothing to do with what it asserts.
    """
    plant = (
        admin_sdk.table("plants")
        .insert({"user_id": user_id, "name": "צמח מתוזמן", "status": "ACTIVE"})
        .execute()
        .data[0]
    )
    plan = (
        admin_sdk.table("care_plans")
        .insert({"user_id": user_id, "plant_id": plant["id"]})
        .execute()
        .data[0]
    )
    version = (
        admin_sdk.table("care_plan_versions")
        .insert(
            {
                "care_plan_id": plan["id"],
                "version_number": 1,
                "status": "ACTIVE",
                "source_type": "INITIAL_PLAN",
                "professional_recommendations": {"summary": "המלצה"},
            }
        )
        .execute()
        .data[0]
    )
    return plant, version


def test_an_identification_photo_becomes_the_main_image(api: TestClient, account, admin_sdk):
    """Reported from real use: a plant added the normal way showed no image.

    Add Plant uploads with context `identification`, and only a `gallery` upload
    could become the main image - so every plant created through the flow the
    product actually uses had a photograph and no `main_image_id`, and My Plants
    was a grid of grey placeholders. Opening the card worked, because the plant
    dashboard lists images regardless of context.
    """
    _, auth = account()
    plant = listed_plant(api, auth, admin_sdk)

    uploaded = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={
            "file": ("leaf.jpg", photo(), "image/jpeg"),
            "context_type": (None, "identification"),
        },
    ).json()["data"]

    fetched = api.get(f"/v1/plants/{plant['id']}", headers=auth).json()["data"]
    assert fetched["main_image_id"] == uploaded["id"]

    listed = api.get("/v1/plants", headers=auth).json()["data"]
    assert next(p for p in listed if p["id"] == plant["id"])["thumbnail_url"]


def test_a_health_photograph_does_not_become_the_main_image(api: TestClient, account):
    """A health check is usually a close-up of a damaged leaf. That is evidence,
    not the plant's portrait, and it should not become the face of the card."""
    _, auth = account()
    plant = create_plant(api, auth)

    api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("sick.jpg", photo(), "image/jpeg"), "context_type": (None, "health")},
    )

    assert (
        api.get(f"/v1/plants/{plant['id']}", headers=auth).json()["data"]["main_image_id"] is None
    )


def test_the_grid_falls_back_to_the_newest_photograph(api: TestClient, account, admin_sdk):
    """Plants created before PR 27 have photographs and no main image.

    No migration can guess a main image for them, and a card with no picture when
    pictures exist is worse than the fallback. Simulated by clearing the column,
    which is exactly the state those rows are in.
    """
    _, auth = account()
    plant = listed_plant(api, auth, admin_sdk)
    api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={
            "file": ("leaf.jpg", photo(), "image/jpeg"),
            "context_type": (None, "identification"),
        },
    )
    admin_sdk.table("plants").update({"main_image_id": None}).eq("id", plant["id"]).execute()

    listed = api.get("/v1/plants", headers=auth).json()["data"]
    mine = next(p for p in listed if p["id"] == plant["id"])

    assert mine["main_image_id"] is None
    assert mine["thumbnail_url"], "a plant with a photograph and no main image showed nothing"


# --- gallery ordering and the main image (migrations 0018, 0019) -----------------

# The gallery is a plant's portraits: gallery and identification images together.
# 0018 said `gallery` alone, which is the word section 20 uses and a set nothing has
# ever written to - Add Plant uploads `identification`, a health check uploads
# `health`, and no code path anywhere sends `gallery`. 0019 widened the rules to the
# set `upload_image` already used when it chooses a first main image.
PORTRAITS = ("gallery", "identification")


def _gallery(api: TestClient, auth: dict, plant_id: str) -> list[dict]:
    images = api.get(f"/v1/plants/{plant_id}/images", headers=auth).json()["data"]
    return [row for row in images if row["context_type"] in PORTRAITS]


def _upload(api: TestClient, auth: dict, plant_id: str, name: str, context: str | None = None):
    files: dict = {"file": (name, photo(), "image/jpeg")}
    if context:
        files["context_type"] = (None, context)
    response = api.post(f"/v1/plants/{plant_id}/images", headers=auth, files=files)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_the_gallery_comes_back_in_display_order(api: TestClient, account):
    """Uploads are numbered as they arrive, so the default order is the order taken."""
    _, auth = account()
    plant = create_plant(api, auth)

    for name in ("a.jpg", "b.jpg", "c.jpg"):
        api.post(
            f"/v1/plants/{plant['id']}/images",
            headers=auth,
            files={"file": (name, photo(), "image/jpeg")},
        )

    gallery = _gallery(api, auth, plant["id"])
    assert [row["display_order"] for row in gallery] == sorted(
        row["display_order"] for row in gallery
    )


def test_reordering_renumbers_the_whole_gallery(api: TestClient, account):
    _, auth = account()
    plant = create_plant(api, auth)
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        api.post(
            f"/v1/plants/{plant['id']}/images",
            headers=auth,
            files={"file": (name, photo(), "image/jpeg")},
        )

    before = [row["id"] for row in _gallery(api, auth, plant["id"])]
    reversed_ids = list(reversed(before))

    response = api.put(
        f"/v1/plants/{plant['id']}/images/order",
        headers=auth,
        json={"image_ids": reversed_ids},
    )

    assert response.status_code == 200
    assert [row["id"] for row in _gallery(api, auth, plant["id"])] == reversed_ids


def test_a_partial_reorder_is_refused(api: TestClient, account):
    """Naming only some images would leave the rest at whatever number they had,
    which is how two sets silently interleave."""
    _, auth = account()
    plant = create_plant(api, auth)
    for name in ("a.jpg", "b.jpg"):
        api.post(
            f"/v1/plants/{plant['id']}/images",
            headers=auth,
            files={"file": (name, photo(), "image/jpeg")},
        )

    only_one = [_gallery(api, auth, plant["id"])[0]["id"]]
    response = api.put(
        f"/v1/plants/{plant['id']}/images/order", headers=auth, json={"image_ids": only_one}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_another_image_can_be_made_main(api: TestClient, account):
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
        files={"file": ("b.jpg", photo(), "image/jpeg")},
    ).json()["data"]

    assert (
        api.get(f"/v1/plants/{plant['id']}", headers=auth).json()["data"]["main_image_id"]
        == first["id"]
    )

    response = api.post(f"/v1/plants/{plant['id']}/images/{second['id']}/main", headers=auth)

    assert response.status_code == 200
    assert (
        api.get(f"/v1/plants/{plant['id']}", headers=auth).json()["data"]["main_image_id"]
        == second["id"]
    )


def test_an_image_from_another_plant_cannot_become_main(api: TestClient, account):
    """The reason this is its own route rather than a field on PATCH /plants."""
    _, auth = account()
    mine = create_plant(api, auth)
    other = create_plant(api, auth)
    stranger = api.post(
        f"/v1/plants/{other['id']}/images",
        headers=auth,
        files={"file": ("a.jpg", photo(), "image/jpeg")},
    ).json()["data"]

    response = api.post(f"/v1/plants/{mine['id']}/images/{stranger['id']}/main", headers=auth)

    assert response.status_code == 404


def test_an_active_plant_keeps_its_last_gallery_image(api: TestClient, account, admin_sdk):
    """Section 20. Before this the delete simply set `main_image_id` to NULL, so an
    active plant could end up with no photograph at all."""
    _, auth = account()
    plant = create_plant(api, auth)
    image = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("a.jpg", photo(), "image/jpeg")},
    ).json()["data"]
    admin_sdk.table("plants").update({"status": "ACTIVE"}).eq("id", plant["id"]).execute()

    response = api.delete(f"/v1/plants/{plant['id']}/images/{image['id']}", headers=auth)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert _gallery(api, auth, plant["id"])


def test_the_last_image_can_go_once_another_exists(api: TestClient, account, admin_sdk):
    """The rule protects the *last* one, not the first."""
    _, auth = account()
    plant = create_plant(api, auth)
    first = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("a.jpg", photo(), "image/jpeg")},
    ).json()["data"]
    api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("b.jpg", photo(), "image/jpeg")},
    )
    admin_sdk.table("plants").update({"status": "ACTIVE"}).eq("id", plant["id"]).execute()

    response = api.delete(f"/v1/plants/{plant['id']}/images/{first['id']}", headers=auth)

    assert response.status_code == 200
    assert len(_gallery(api, auth, plant["id"])) == 1


def test_a_plant_that_is_not_active_may_lose_every_image(api: TestClient, account):
    """A plant still being identified, or archived, is not covered: the rule protects
    a plant somebody is using."""
    _, auth = account()
    plant = create_plant(api, auth)
    image = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={"file": ("a.jpg", photo(), "image/jpeg")},
    ).json()["data"]

    response = api.delete(f"/v1/plants/{plant['id']}/images/{image['id']}", headers=auth)

    assert response.status_code == 200
    assert _gallery(api, auth, plant["id"]) == []


# --- the portrait set (migration 0019) -------------------------------------------


def test_an_identification_photograph_can_become_main(api: TestClient, account):
    """The case the first cut of this endpoint refused.

    Every photograph in DEV is an identification image - 44 of them, and not one
    gallery image - so a set-main that accepted `gallery` alone rejected every
    picture a user has ever taken.
    """
    _, auth = account()
    plant = create_plant(api, auth)
    first = _upload(api, auth, plant["id"], "a.jpg", "identification")
    second = _upload(api, auth, plant["id"], "b.jpg", "identification")

    assert (
        api.get(f"/v1/plants/{plant['id']}", headers=auth).json()["data"]["main_image_id"]
        == first["id"]
    )

    response = api.post(f"/v1/plants/{plant['id']}/images/{second['id']}/main", headers=auth)

    assert response.status_code == 200, response.text
    assert (
        api.get(f"/v1/plants/{plant['id']}", headers=auth).json()["data"]["main_image_id"]
        == second["id"]
    )


def test_a_health_photograph_cannot_become_main(api: TestClient, account):
    """A health image is evidence for one check - usually a close-up of the damage -
    and `upload_image` has excluded it from becoming a main image since PR 27. The
    explicit route agrees with the automatic one."""
    _, auth = account()
    plant = create_plant(api, auth)
    _upload(api, auth, plant["id"], "a.jpg", "identification")
    evidence = _upload(api, auth, plant["id"], "leaf.jpg", "health")

    response = api.post(f"/v1/plants/{plant['id']}/images/{evidence['id']}/main", headers=auth)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_both_contexts_are_ordered_as_one_gallery(api: TestClient, account):
    """A user dragging a photograph does not know which context it was uploaded in,
    and the dashboard draws them in one grid. A reorder therefore names the whole
    set, and a request covering only one context is partial."""
    _, auth = account()
    plant = create_plant(api, auth)
    _upload(api, auth, plant["id"], "ident.jpg", "identification")
    _upload(api, auth, plant["id"], "gallery.jpg", "gallery")

    before = [row["id"] for row in _gallery(api, auth, plant["id"])]
    assert len(before) == 2, "both contexts belong to the gallery"

    response = api.put(
        f"/v1/plants/{plant['id']}/images/order",
        headers=auth,
        json={"image_ids": list(reversed(before))},
    )

    assert response.status_code == 200, response.text
    assert [row["id"] for row in _gallery(api, auth, plant["id"])] == list(reversed(before))


def test_a_health_photograph_is_not_part_of_the_order(api: TestClient, account):
    """Naming it would be naming an image that is not in the set being ordered."""
    _, auth = account()
    plant = create_plant(api, auth)
    portrait = _upload(api, auth, plant["id"], "a.jpg", "identification")
    evidence = _upload(api, auth, plant["id"], "leaf.jpg", "health")

    response = api.put(
        f"/v1/plants/{plant['id']}/images/order",
        headers=auth,
        json={"image_ids": [portrait["id"], evidence["id"]]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_an_active_plant_keeps_its_last_identification_photograph(
    api: TestClient, account, admin_sdk
):
    """The shape every real plant is in: photographs, none of them `gallery`."""
    _, auth = account()
    plant = create_plant(api, auth)
    image = _upload(api, auth, plant["id"], "a.jpg", "identification")
    admin_sdk.table("plants").update({"status": "ACTIVE"}).eq("id", plant["id"]).execute()

    response = api.delete(f"/v1/plants/{plant['id']}/images/{image['id']}", headers=auth)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert _gallery(api, auth, plant["id"])


def test_the_database_refuses_to_hide_the_last_portrait(api: TestClient, account, admin_sdk):
    """Straight at the trigger, past the API's own guard.

    This is the path that actually matters. An identification image has been
    consumed by the identification, so `ai_used` is true for every one of them, and
    FINAL section 20 says an AI-used image is hidden rather than deleted - an UPDATE,
    not a DELETE. A rule enforced only on delete would never see it.
    """
    _, auth = account()
    plant = create_plant(api, auth)
    image = _upload(api, auth, plant["id"], "a.jpg", "identification")
    admin_sdk.table("plants").update({"status": "ACTIVE"}).eq("id", plant["id"]).execute()

    with pytest.raises(Exception, match="at least one photograph"):
        admin_sdk.table("plant_images").update({"user_visible": False}).eq(
            "id", image["id"]
        ).execute()
