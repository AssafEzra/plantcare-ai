"""Identification end to end against DEV, with a scripted model.

The database is real; the model is not. That combination is the point: the rules
worth testing here are about what gets *persisted* — TESTING §5 asks that no
plant is mutated before confirmation and that identification history is retained,
and neither can be checked without a real database or trusted from a live model.
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

from app.agents.identification.agent import IdentificationAgent
from app.agents.identification.contract import Candidate, IdentificationOutput
from app.agents.knowledge.agent import KnowledgeAgent
from app.api.routers.identification import get_identification_agent, get_knowledge_agent
from app.common.enums import IdentificationStatus
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.mock_provider import MockProvider

pytestmark = pytest.mark.integration

PASSWORD = "Ident-Passw0rd!"


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
def scripted():
    """Holds the responses the agent will return, settable per test."""
    return MockProvider()


@pytest.fixture
def scripted_knowledge():
    """The Knowledge Agent's provider.

    Overridden even though these tests are about identification: confirming a
    species with no published knowledge queues a research run, and without this
    every confirmation test would make a real, billable research call.
    """
    return MockProvider()


@pytest.fixture
def api(live_env, scripted, scripted_knowledge) -> Iterator[TestClient]:
    from app.api.main import create_app

    app = create_app()
    app.dependency_overrides[get_identification_agent] = lambda: IdentificationAgent(
        AIGateway(scripted, record_executions=False)
    )
    app.dependency_overrides[get_knowledge_agent] = lambda: KnowledgeAgent(
        AIGateway(scripted_knowledge, record_executions=False)
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def account(admin_sdk) -> Iterator:
    from supabase import create_client

    created: list[str] = []

    def _make() -> tuple[str, dict[str, str]]:
        email = f"id-{uuid.uuid4().hex[:12]}@example.com"
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


def photo() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (900, 700), (60, 120, 70)).save(buffer, format="JPEG")
    return buffer.getvalue()


def plant_with_photo(api: TestClient, auth: dict) -> tuple[str, str]:
    plant = api.post("/v1/plants", headers=auth, json={}).json()["data"]
    image = api.post(
        f"/v1/plants/{plant['id']}/images",
        headers=auth,
        files={
            "file": ("a.jpg", photo(), "image/jpeg"),
            "context_type": (None, "identification"),
        },
    ).json()["data"]
    return plant["id"], image["id"]


def success(name: str = "Monstera deliciosa", score: float = 0.92) -> IdentificationOutput:
    return IdentificationOutput(
        status=IdentificationStatus.SUCCESS,
        candidates=[Candidate(scientific_name=name, common_name="מונסטרה", confidence_score=score)],
        image_quality="תמונות ברורות",
    )


def run_identification(api: TestClient, auth: dict, plant_id: str, image_id: str, **kwargs):
    """TestClient runs background tasks before returning, so the work is complete."""
    return api.post(
        f"/v1/plants/{plant_id}/identification-runs",
        headers=auth,
        json={"image_ids": [image_id], **kwargs},
    )


def latest_identification(admin_sdk, plant_id: str) -> dict | None:
    result = (
        admin_sdk.table("identifications")
        .select("*")
        .eq("plant_id", plant_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


# --- running ------------------------------------------------------------------


def test_a_run_returns_202_and_a_request_id(api, account, scripted):
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    scripted.queue(success())

    response = run_identification(api, auth, plant_id, image_id)

    assert response.status_code == 202
    assert response.json()["data"]["agent_request_id"]


def test_the_result_is_persisted_with_its_candidates(api, account, scripted, admin_sdk):
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    scripted.queue(success())

    run_identification(api, auth, plant_id, image_id)

    record = latest_identification(admin_sdk, plant_id)
    assert record["status"] == "SUCCESS"
    assert record["confidence_level"] == "HIGH"

    candidates = (
        admin_sdk.table("identification_candidates")
        .select("scientific_name, species_id, rank")
        .eq("identification_id", record["id"])
        .execute()
    )
    assert candidates.data[0]["scientific_name"] == "Monstera deliciosa"
    # Plan decision 2: no species row yet. It is created at confirmation, from the
    # candidate the user actually chose.
    assert candidates.data[0]["species_id"] is None


def test_the_plant_is_untouched_before_confirmation(api, account, scripted):
    """TESTING §5, and FINAL §9: the agent never changes plants.species_id."""
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    scripted.queue(success())

    run_identification(api, auth, plant_id, image_id)

    plant = api.get(f"/v1/plants/{plant_id}", headers=auth).json()["data"]
    assert plant["species_id"] is None
    assert plant["status"] == "PENDING_IDENTIFICATION"


def test_images_shown_to_the_model_are_marked_ai_used(api, account, scripted, admin_sdk):
    """FINAL §20: they are retained for audit even if the user removes them."""
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    scripted.queue(success())

    run_identification(api, auth, plant_id, image_id)

    row = admin_sdk.table("plant_images").select("ai_used").eq("id", image_id).execute()
    assert row.data[0]["ai_used"] is True


def test_a_failed_run_creates_no_authoritative_record(api, account, scripted, admin_sdk):
    """FINAL §25. The identification row exists with status FAILED, and the
    database itself refuses to let such a row carry a species or a verdict."""
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    scripted.queue({"bad": 1}, {"bad": 2}, {"bad": 3})

    run_identification(api, auth, plant_id, image_id)

    record = latest_identification(admin_sdk, plant_id)
    assert record["status"] == "FAILED"
    assert record["primary_species_id"] is None
    assert record["confidence_level"] is None

    plant = api.get(f"/v1/plants/{plant_id}", headers=auth).json()["data"]
    assert plant["species_id"] is None


def test_an_image_from_another_plant_is_refused(api, account, scripted):
    """RLS already excludes another user's images; this stops one plant's photos
    being used to identify a different plant."""
    _, auth = account()
    plant_id, _ = plant_with_photo(api, auth)
    _, other_image = plant_with_photo(api, auth)

    response = run_identification(api, auth, plant_id, other_image)

    assert response.status_code == 422


def test_more_than_four_images_is_refused(api, account):
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)

    response = api.post(
        f"/v1/plants/{plant_id}/identification-runs",
        headers=auth,
        json={"image_ids": [image_id] * 5},
    )

    assert response.status_code == 422


# --- idempotency (A24) --------------------------------------------------------


def test_the_same_key_and_payload_replays(api, account, scripted, admin_sdk):
    """A client retrying a dropped connection must not start a second billable
    analysis."""
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    scripted.queue(success())
    headers = {**auth, "Idempotency-Key": f"key-{uuid.uuid4()}"}
    body = {"image_ids": [image_id]}

    first = api.post(f"/v1/plants/{plant_id}/identification-runs", headers=headers, json=body)
    second = api.post(f"/v1/plants/{plant_id}/identification-runs", headers=headers, json=body)

    assert first.json()["data"]["agent_request_id"] == second.json()["data"]["agent_request_id"]
    assert second.json()["data"]["replayed"] is True
    # The model was called once, not twice.
    assert scripted.call_count == 1


def test_the_same_key_with_a_different_payload_conflicts(api, account, scripted):
    _, auth = account()
    plant_id, first_image = plant_with_photo(api, auth)
    # A second image on the *same* plant: an image from another plant would be
    # rejected as not belonging before idempotency is ever considered.
    second_image = api.post(
        f"/v1/plants/{plant_id}/images",
        headers=auth,
        files={
            "file": ("b.jpg", photo(), "image/jpeg"),
            "context_type": (None, "identification"),
        },
    ).json()["data"]["id"]
    scripted.queue(success())
    headers = {**auth, "Idempotency-Key": f"key-{uuid.uuid4()}"}

    api.post(
        f"/v1/plants/{plant_id}/identification-runs",
        headers=headers,
        json={"image_ids": [first_image]},
    )
    conflict = api.post(
        f"/v1/plants/{plant_id}/identification-runs",
        headers=headers,
        json={"image_ids": [second_image]},
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


# --- confirmation ---------------------------------------------------------------


def confirm_first_candidate(api, auth, admin_sdk, plant_id):
    record = latest_identification(admin_sdk, plant_id)
    candidate = (
        admin_sdk.table("identification_candidates")
        .select("id")
        .eq("identification_id", record["id"])
        .order("rank")
        .execute()
    ).data[0]
    return api.post(
        f"/v1/identifications/{record['id']}/confirm",
        headers=auth,
        json={"candidate_id": candidate["id"]},
    )


def test_confirming_a_known_species_activates_the_plant(api, account, scripted, admin_sdk):
    """The seeded Monstera has published knowledge, so the plant goes straight to
    ACTIVE - the "existing species reuses published Knowledge" journey."""
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    scripted.queue(success("Monstera deliciosa"))
    run_identification(api, auth, plant_id, image_id)

    response = confirm_first_candidate(api, auth, admin_sdk, plant_id)

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ACTIVE"
    assert response.json()["data"]["knowledge_pending"] is False

    plant = api.get(f"/v1/plants/{plant_id}", headers=auth).json()["data"]
    assert plant["species_id"] is not None


def test_confirming_an_unknown_species_opens_a_draft(api, account, scripted, admin_sdk):
    """The other journey: new species, KNOWLEDGE_PENDING, research draft opened."""
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    novel = f"Testus {uuid.uuid4().hex[:10].translate(str.maketrans('0123456789', 'abcdefghij'))}"
    scripted.queue(success(novel))
    run_identification(api, auth, plant_id, image_id)

    response = confirm_first_candidate(api, auth, admin_sdk, plant_id)

    data = response.json()["data"]
    assert data["status"] == "KNOWLEDGE_PENDING"
    assert data["knowledge_pending"] is True

    drafts = (
        admin_sdk.table("knowledge_drafts")
        .select("status")
        .eq("species_id", data["species_id"])
        .execute()
    )
    assert drafts.data, "no research draft was opened for the new species"


def test_confirmation_creates_the_species_row(api, account, scripted, admin_sdk):
    """Plan decision 2, observed: the species appears now, not when candidates
    were stored."""
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    novel = "Testus " + uuid.uuid4().hex[:10].translate(str.maketrans("0123456789", "abcdefghij"))
    scripted.queue(success(novel))
    run_identification(api, auth, plant_id, image_id)

    before = admin_sdk.table("species").select("id").eq("scientific_name", novel).execute()
    assert not before.data

    confirm_first_candidate(api, auth, admin_sdk, plant_id)

    after = admin_sdk.table("species").select("id").eq("scientific_name", novel).execute()
    assert after.data


def test_a_failed_identification_cannot_be_confirmed(api, account, scripted, admin_sdk):
    """Confirming one would be exactly the authoritative record FINAL §25 forbids."""
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    scripted.queue({"bad": 1}, {"bad": 2}, {"bad": 3})
    run_identification(api, auth, plant_id, image_id)

    record = latest_identification(admin_sdk, plant_id)
    response = api.post(
        f"/v1/identifications/{record['id']}/confirm",
        headers=auth,
        json={"candidate_id": str(uuid.uuid4())},
    )

    assert response.status_code == 422


def test_history_is_retained_across_re_identification(api, account, scripted, admin_sdk):
    """TESTING §5: the previous identification remains."""
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    scripted.queue(success("Monstera deliciosa"), success("Ficus lyrata", 0.88))

    run_identification(api, auth, plant_id, image_id)
    run_identification(api, auth, plant_id, image_id)

    history = admin_sdk.table("identifications").select("id").eq("plant_id", plant_id).execute()
    assert len(history.data) == 2


def test_another_users_identification_is_not_found(api, account, scripted, admin_sdk):
    _, alice = account()
    _, bob = account()
    plant_id, image_id = plant_with_photo(api, bob)
    scripted.queue(success())
    run_identification(api, bob, plant_id, image_id)

    record = latest_identification(admin_sdk, plant_id)
    response = api.get(f"/v1/identifications/{record['id']}", headers=alice)

    assert response.status_code == 404


# --- correction ---------------------------------------------------------------


def test_a_correction_does_not_move_the_plant(api, account, scripted, admin_sdk):
    """FINAL §8: a correction creates history and still requires confirmation."""
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    scripted.queue(success())
    run_identification(api, auth, plant_id, image_id)
    record = latest_identification(admin_sdk, plant_id)

    response = api.post(
        f"/v1/identifications/{record['id']}/correct",
        headers=auth,
        json={"scientific_name": "Ficus lyrata", "note": "נראה לי שזה פיקוס"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["requires_confirmation"] is True

    plant = api.get(f"/v1/plants/{plant_id}", headers=auth).json()["data"]
    assert plant["species_id"] is None


def test_an_empty_correction_is_refused(api, account, scripted, admin_sdk):
    _, auth = account()
    plant_id, image_id = plant_with_photo(api, auth)
    scripted.queue(success())
    run_identification(api, auth, plant_id, image_id)
    record = latest_identification(admin_sdk, plant_id)

    response = api.post(f"/v1/identifications/{record['id']}/correct", headers=auth, json={})

    assert response.status_code == 422
