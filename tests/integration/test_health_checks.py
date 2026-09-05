"""Health checks against DEV.

The properties that need a real database:

* the assessment and everything it produced are written in **one transaction** —
  the 1-4 image constraint is deferred and checked at commit, so two REST calls
  could never satisfy it;
* a failure leaves **no row at all** (FINAL §25), which only a real rollback can
  demonstrate;
* previous assessments are never touched, and the immutability trigger refuses
  even the service role;
* an `UNKNOWN` verdict is saved *and* leaves the plant's existing status standing
  rather than overwriting a real finding with an absence of one.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.agents.health.agent import HealthAgent
from app.agents.health.contract import (
    HealthOutput,
    Observation,
    PossibleIssue,
    Recommendation,
)
from app.api.routers.health import get_health_agent
from app.common.enums import HealthStatus
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.mock_provider import MockProvider
from tests.integration.conftest import delete_accounts, unique_species_name

pytestmark = pytest.mark.integration

PASSWORD = "Health-Passw0rd!"


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
    return MockProvider()


@pytest.fixture
def api(live_env, scripted) -> Iterator[TestClient]:
    from app.api.main import create_app

    app = create_app()
    app.dependency_overrides[get_health_agent] = lambda: HealthAgent(
        AIGateway(scripted, record_executions=False)
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def account(admin_sdk):
    from supabase import create_client

    created: list[str] = []

    def _make() -> tuple[str, dict[str, str]]:
        email = f"hc-{uuid.uuid4().hex[:12]}@example.com"
        user = admin_sdk.auth.admin.create_user(
            {"email": email, "password": PASSWORD, "email_confirm": True}
        ).user
        created.append(user.id)
        anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        token = anon.auth.sign_in_with_password(
            {"email": email, "password": PASSWORD}
        ).session.access_token
        return user.id, {"Authorization": f"Bearer {token}", "X-Access-Token": token}

    yield _make

    delete_accounts(admin_sdk, created)


@pytest.fixture
def checkable(admin_sdk, account) -> Iterator[dict]:
    """A plant with two photographs ready to assess."""
    user_id, auth = account()
    species = (
        admin_sdk.table("species")
        .insert({"scientific_name": unique_species_name(), "common_name": "צמח בדיקה"})
        .execute()
        .data[0]
    )
    plant = (
        admin_sdk.table("plants")
        .insert(
            {
                "user_id": user_id,
                "species_id": species["id"],
                "status": "ACTIVE",
                "name": "צמח לבדיקת בריאות",
            }
        )
        .execute()
        .data[0]
    )
    images = [
        admin_sdk.table("plant_images")
        .insert(
            {
                "plant_id": plant["id"],
                "user_id": user_id,
                "storage_path_original": f"{user_id}/{plant['id']}/health/{i}.jpg",
                "mime_type": "image/jpeg",
                "size_bytes": 2048,
                "context_type": "health",
            }
        )
        .execute()
        .data[0]["id"]
        for i in range(2)
    ]

    from app.infrastructure.supabase.client import user_client

    yield {
        "user_id": user_id,
        "auth": {"Authorization": auth["Authorization"]},
        # `save_health_assessment` is SECURITY INVOKER and needs `auth.uid()`, so
        # it must be called as the owner — the service role has no identity. That
        # is the design, not a limitation of the harness.
        "client": user_client(auth["X-Access-Token"]),
        "plant_id": plant["id"],
        "image_ids": images,
        "species_id": species["id"],
    }

    with contextlib.suppress(Exception):
        admin_sdk.table("plants").delete().eq("id", plant["id"]).execute()


def healthy(**kwargs) -> HealthOutput:
    return HealthOutput(
        overall_status=HealthStatus.HEALTHY,
        observations=[Observation(observation_text="העלים ירוקים ואחידים.")],
        **kwargs,
    )


def needs_attention() -> HealthOutput:
    return HealthOutput(
        overall_status=HealthStatus.NEEDS_ATTENTION,
        requires_attention=True,
        observations=[Observation(observation_text="שלושת העלים התחתונים מצהיבים.")],
        possible_issues=[
            PossibleIssue(
                issue_name="ייתכן עודף השקיה",
                evidence="הצהבה בעלים התחתונים בלבד, מצע לח.",
                severity=3,
            )
        ],
        recommendations=[
            Recommendation(
                recommendation_text="להאריך את מרווח ההשקיה בשלושה ימים.",
                requires_care_plan_adjustment=True,
                priority=1,
            )
        ],
    )


def unknown() -> HealthOutput:
    return HealthOutput(
        overall_status=HealthStatus.UNKNOWN,
        insufficient_information_reason="התמונות מטושטשות מכדי לקבוע.",
    )


_DEFAULT_IMAGES = object()


def save_directly(admin_sdk, checkable: dict, output: HealthOutput, *, images=_DEFAULT_IMAGES):
    """Persist through the workflow, bypassing image download.

    The download path needs real objects in storage; what these tests are about
    is the transaction, so they drive `save()` with a result directly.
    """
    from app.agents.health.agent import HealthAgent as _Agent
    from app.orchestration.workflows import health as workflow

    agent = _Agent(AIGateway(MockProvider([output]), record_executions=False))
    result = agent._interpret(output)
    return workflow.save(
        checkable["client"],
        plant_id=uuid.UUID(checkable["plant_id"]),
        # A sentinel, not `images or ...`: an empty list is falsy, so the
        # obvious version silently substituted the real images and the
        # "no images is refused" tests passed while testing nothing.
        image_ids=[
            uuid.UUID(i) for i in (checkable["image_ids"] if images is _DEFAULT_IMAGES else images)
        ],
        result=result,
        user_note=None,
    )


def assessments_of(admin_sdk, plant_id: str) -> list[dict]:
    return (
        admin_sdk.table("health_assessments")
        .select("*")
        .eq("plant_id", plant_id)
        .order("created_at", desc=True)
        .execute()
    ).data


# --- one transaction ------------------------------------------------------------


def test_an_assessment_and_everything_it_produced_land_together(admin_sdk, checkable):
    """The 1-4 image constraint is deferred and checked at commit, so two REST
    calls could never satisfy it. One RPC can."""
    saved = save_directly(admin_sdk, checkable, needs_attention())

    for table, expected in [
        ("health_assessment_images", 2),
        ("health_observations", 1),
        ("health_issues", 1),
        ("health_recommendations", 1),
    ]:
        rows = (
            admin_sdk.table(table).select("*").eq("health_assessment_id", saved["id"]).execute()
        ).data
        assert len(rows) == expected, table


def test_an_assessment_with_no_images_is_refused(admin_sdk, checkable):
    with pytest.raises(APIError):
        save_directly(admin_sdk, checkable, healthy(), images=[])


def test_more_than_four_images_is_refused(admin_sdk, checkable):
    with pytest.raises(APIError):
        save_directly(admin_sdk, checkable, healthy(), images=checkable["image_ids"] * 3)


def test_an_image_from_another_plant_is_refused(admin_sdk, checkable, account):
    """Attaching a finding to the wrong plant is worse than failing."""
    other_user, _ = account()
    other_plant = (
        admin_sdk.table("plants")
        .insert({"user_id": other_user, "name": "צמח אחר"})
        .execute()
        .data[0]
    )
    stray = (
        admin_sdk.table("plant_images")
        .insert(
            {
                "plant_id": other_plant["id"],
                "user_id": other_user,
                "storage_path_original": "x/y/z.jpg",
                "mime_type": "image/jpeg",
                "size_bytes": 100,
                "context_type": "health",
            }
        )
        .execute()
        .data[0]["id"]
    )
    try:
        with pytest.raises(APIError):
            save_directly(admin_sdk, checkable, healthy(), images=[stray])
    finally:
        with contextlib.suppress(Exception):
            admin_sdk.table("plants").delete().eq("id", other_plant["id"]).execute()


def test_a_refused_save_leaves_no_row_at_all(admin_sdk, checkable):
    """FINAL §25, demonstrated by a real rollback rather than asserted."""
    with contextlib.suppress(Exception):
        save_directly(admin_sdk, checkable, healthy(), images=[])

    assert assessments_of(admin_sdk, checkable["plant_id"]) == []


def test_images_shown_to_the_model_are_marked_retained(admin_sdk, checkable):
    """FINAL §20: an image an agent has seen survives the user removing it."""
    save_directly(admin_sdk, checkable, healthy())

    images = (
        admin_sdk.table("plant_images")
        .select("ai_used")
        .in_("id", checkable["image_ids"])
        .execute()
    ).data
    assert all(image["ai_used"] for image in images)


# --- status and history -----------------------------------------------------------


def test_a_successful_check_updates_the_plants_status(admin_sdk, checkable):
    """FINAL §16: "Every successful Health Check updates the Plant's current
    health status.\""""
    save_directly(admin_sdk, checkable, needs_attention())

    plant = (
        admin_sdk.table("plants")
        .select("current_health_status")
        .eq("id", checkable["plant_id"])
        .execute()
    ).data[0]
    assert plant["current_health_status"] == "NEEDS_ATTENTION"


def test_an_unknown_verdict_is_saved_but_does_not_overwrite_a_real_status(admin_sdk, checkable):
    """An UNKNOWN is a record that we could not tell — not evidence the plant
    declined. Overwriting a real finding with an absence of one would lose
    information the user already had."""
    save_directly(admin_sdk, checkable, needs_attention())
    save_directly(admin_sdk, checkable, unknown())

    assert len(assessments_of(admin_sdk, checkable["plant_id"])) == 2
    plant = (
        admin_sdk.table("plants")
        .select("current_health_status")
        .eq("id", checkable["plant_id"])
        .execute()
    ).data[0]
    assert plant["current_health_status"] == "NEEDS_ATTENTION"


def test_an_unknown_assessment_carries_its_reason_and_no_confidence(admin_sdk, checkable):
    saved = save_directly(admin_sdk, checkable, unknown())

    assert saved["overall_status"] == "UNKNOWN"
    assert saved["insufficient_information_reason"]
    assert saved["confidence_level"] is None


def test_previous_assessments_are_never_touched(admin_sdk, checkable):
    """FINAL §16: "Previous assessments remain unchanged.\""""
    first = save_directly(admin_sdk, checkable, healthy())
    save_directly(admin_sdk, checkable, needs_attention())

    unchanged = (
        admin_sdk.table("health_assessments").select("*").eq("id", first["id"]).execute()
    ).data[0]
    assert unchanged["overall_status"] == "HEALTHY"


def test_an_assessment_cannot_be_edited_or_deleted(admin_sdk, checkable):
    """Tested through the service role: if even that cannot rewrite a finding,
    no route can."""
    saved = save_directly(admin_sdk, checkable, healthy())

    with pytest.raises(APIError):
        admin_sdk.table("health_assessments").update({"overall_status": "CRITICAL"}).eq(
            "id", saved["id"]
        ).execute()
    with pytest.raises(APIError):
        admin_sdk.table("health_assessments").delete().eq("id", saved["id"]).execute()


# --- the trend (A11) ---------------------------------------------------------------


def test_a_first_assessment_has_no_trend(admin_sdk, checkable):
    """Claiming "stable" from one check would be a claim about history from a
    plant we have seen once."""
    saved = save_directly(admin_sdk, checkable, healthy())
    assert saved["trend"] == "UNABLE_TO_DETERMINE"


def test_a_decline_is_recorded_as_worsening(admin_sdk, checkable):
    save_directly(admin_sdk, checkable, healthy())
    second = save_directly(admin_sdk, checkable, needs_attention())

    assert second["trend"] == "WORSENING"


def test_a_recovery_is_recorded_as_improving(admin_sdk, checkable):
    save_directly(admin_sdk, checkable, needs_attention())
    second = save_directly(admin_sdk, checkable, healthy())

    assert second["trend"] == "IMPROVING"


def test_an_unknown_between_two_checks_does_not_invent_a_decline(admin_sdk, checkable):
    """An assessment we could not read is not evidence the plant got worse."""
    save_directly(admin_sdk, checkable, healthy())
    save_directly(admin_sdk, checkable, unknown())
    third = save_directly(admin_sdk, checkable, healthy())

    assert third["trend"] == "STABLE"


# --- the routes --------------------------------------------------------------------


def test_a_check_with_no_images_is_refused_by_the_route(api, checkable):
    response = api.post(
        f"/v1/plants/{checkable['plant_id']}/health-checks",
        headers=checkable["auth"],
        json={"image_ids": []},
    )
    assert response.status_code == 422


def test_a_check_with_five_images_is_refused_by_the_route(api, checkable):
    response = api.post(
        f"/v1/plants/{checkable['plant_id']}/health-checks",
        headers=checkable["auth"],
        json={"image_ids": [str(uuid.uuid4()) for _ in range(5)]},
    )
    assert response.status_code == 422


def test_an_assessment_can_be_read_back_with_its_findings(api, admin_sdk, checkable):
    saved = save_directly(admin_sdk, checkable, needs_attention())

    response = api.get(f"/v1/health-assessments/{saved['id']}", headers=checkable["auth"])
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["overall_status"] == "NEEDS_ATTENTION"
    assert len(data["observations"]) == 1
    assert len(data["possible_issues"]) == 1
    assert data["possible_issues"][0]["evidence"]
    assert data["recommendations"][0]["requires_care_plan_adjustment"] is True


def test_the_health_history_is_newest_first(api, admin_sdk, checkable):
    save_directly(admin_sdk, checkable, healthy())
    save_directly(admin_sdk, checkable, needs_attention())

    history = api.get(
        f"/v1/plants/{checkable['plant_id']}/health-history", headers=checkable["auth"]
    ).json()["data"]

    assert [entry["overall_status"] for entry in history] == ["NEEDS_ATTENTION", "HEALTHY"]


def test_another_user_cannot_read_the_assessment_or_the_history(api, admin_sdk, checkable, account):
    saved = save_directly(admin_sdk, checkable, healthy())
    _, other_auth = account()

    assert api.get(f"/v1/health-assessments/{saved['id']}", headers=other_auth).status_code == 404
    assert (
        api.get(f"/v1/plants/{checkable['plant_id']}/health-history", headers=other_auth).json()[
            "data"
        ]
        == []
    )
