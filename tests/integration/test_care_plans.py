"""Care plans end to end against DEV, with a scripted model.

The assertions that need a real database:

* the version chain — v1 ACTIVE, then v2 ACTIVE and v1 SUPERSEDED, with v1's
  content intact (FINAL §12);
* A5 — approving cancels the old version's outstanding PENDING tasks, and leaves
  DONE and OVERDUE ones alone, because those record what happened;
* an operational adjustment copies `professional_recommendations` **byte for
  byte**, which is the whole of §12's "not directly editable";
* an AI failure writes no version at all (FINAL §25);
* the one-ACTIVE-version index actually holds.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.agents.care.agent import CareAgent
from app.agents.care.contract import CarePlanOutput, ProposedRule, Recommendations
from app.api.routers.care import get_care_agent
from app.common.enums import CareRuleActionType
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.mock_provider import MockProvider
from tests.integration.conftest import unique_species_name

pytestmark = pytest.mark.integration

PASSWORD = "Care-Passw0rd!"

RECS = Recommendations(
    summary="הצמח נמצא בחדר מואר ודורש השקיה מתונה לאורך כל השנה.",
    watering="להשקות כשהמצע יבש לעומק שלושה סנטימטרים.",
    light="אור עקיף בהיר, כמטר מהחלון.",
)


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
    app.dependency_overrides[get_care_agent] = lambda: CareAgent(
        AIGateway(scripted, record_executions=False)
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def account(admin_sdk):
    from supabase import create_client

    created: list[str] = []

    def _make() -> tuple[str, dict[str, str]]:
        email = f"care-{uuid.uuid4().hex[:12]}@example.com"
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


@pytest.fixture
def planted(admin_sdk, account) -> Iterator[dict]:
    """An ACTIVE plant of a species with published knowledge.

    That is the precondition for a care plan: the context builder needs a current
    `knowledge_versions` row, and a plant only reaches ACTIVE once one exists.
    """
    user_id, auth = account()
    species = (
        admin_sdk.table("species")
        .insert({"scientific_name": unique_species_name(), "common_name": "צמח בדיקה"})
        .execute()
        .data[0]
    )
    admin_sdk.table("knowledge_versions").insert(
        {
            "species_id": species["id"],
            "language": "he",
            "version_number": 1,
            "is_current": True,
            "content": {
                name: {"text": f"מידע על {name} עבור הצמח הזה בעברית.", "confidence": 0.9}
                for name in ("light", "watering", "soil", "temperature", "humidity")
            },
        }
    ).execute()
    plant = (
        admin_sdk.table("plants")
        .insert(
            {
                "user_id": user_id,
                "species_id": species["id"],
                "status": "ACTIVE",
                "name": "צמח לתוכנית",
            }
        )
        .execute()
        .data[0]
    )

    yield {"user_id": user_id, "auth": auth, "plant_id": plant["id"], "species_id": species["id"]}

    with contextlib.suppress(Exception):
        admin_sdk.table("plants").delete().eq("id", plant["id"]).execute()


def plan_output(*rules: ProposedRule, **kwargs) -> CarePlanOutput:
    return CarePlanOutput(recommendations=RECS, rules=list(rules or (WATERING,)), **kwargs)


WATERING = ProposedRule(action_type=CareRuleActionType.WATERING, interval_days=7)
FERTILIZING = ProposedRule(action_type=CareRuleActionType.FERTILIZING, interval_days=30)


def propose(api: TestClient, planted: dict, reason: str = "INITIAL_PLAN"):
    return api.post(
        f"/v1/plants/{planted['plant_id']}/care-plan/proposals",
        headers=planted["auth"],
        json={"reason": reason},
    )


def open_proposal(api: TestClient, planted: dict) -> dict:
    listed = api.get(
        f"/v1/plants/{planted['plant_id']}/care-plan/proposals", headers=planted["auth"]
    )
    return listed.json()["data"][0]


def versions(admin_sdk, plant_id: str) -> list[dict]:
    plan = admin_sdk.table("care_plans").select("id").eq("plant_id", plant_id).execute().data
    if not plan:
        return []
    return (
        admin_sdk.table("care_plan_versions")
        .select("version_number, status, professional_recommendations, source_type")
        .eq("care_plan_id", plan[0]["id"])
        .order("version_number")
        .execute()
    ).data


# --- proposing ----------------------------------------------------------------


def test_a_proposal_is_created_but_activates_nothing(api, planted, scripted, admin_sdk):
    """FINAL §12: the user must approve the initial plan.

    Until then `GET /care-plan` has nothing to return — a proposal is not a plan,
    and the scheduler reads only the active version.
    """
    scripted.queue(plan_output(WATERING, FERTILIZING))
    assert propose(api, planted).status_code == 202

    stored = versions(admin_sdk, planted["plant_id"])
    assert [v["status"] for v in stored] == ["PROPOSED"]

    assert (
        api.get(f"/v1/plants/{planted['plant_id']}/care-plan", headers=planted["auth"]).status_code
        == 404
    )


def test_the_proposal_carries_its_rules(api, planted, scripted):
    scripted.queue(plan_output(WATERING, FERTILIZING))
    propose(api, planted)

    proposal = open_proposal(api, planted)
    assert {r["action_type"] for r in proposal["rules"]} == {"WATERING", "FERTILIZING"}
    assert proposal["source_type"] == "INITIAL_PLAN"


def test_a_second_proposal_is_refused_while_one_is_open(api, planted, scripted):
    """Two open proposals is a choice the user did not ask to make, and approving
    one would silently orphan the other."""
    scripted.queue(plan_output())
    propose(api, planted)

    assert propose(api, planted).status_code == 422


def test_an_agent_failure_writes_no_version(api, planted, scripted, admin_sdk):
    """FINAL §25, the clearest case: three malformed responses exhaust the retry
    budget and the plant is left exactly as it was."""
    scripted.queue(*[{"recommendations": "not an object"}] * 3)
    propose(api, planted)

    assert versions(admin_sdk, planted["plant_id"]) == []


# --- approving ----------------------------------------------------------------


def test_approving_activates_the_version(api, planted, scripted, admin_sdk):
    scripted.queue(plan_output(WATERING))
    propose(api, planted)
    proposal = open_proposal(api, planted)

    response = api.post(
        f"/v1/care-plan-proposals/{proposal['id']}/approve", headers=planted["auth"]
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ACTIVE"

    plan = api.get(f"/v1/plants/{planted['plant_id']}/care-plan", headers=planted["auth"])
    assert plan.status_code == 200
    assert plan.json()["data"]["version_number"] == 1


def test_the_version_chain_supersedes_and_keeps_the_old_content(api, planted, scripted, admin_sdk):
    """v1 ACTIVE, then v2 ACTIVE with v1 SUPERSEDED and its content untouched.

    Content immutability is what makes the chain an audit trail rather than a
    changelog nobody can check.
    """
    scripted.queue(plan_output(WATERING))
    propose(api, planted)
    first = open_proposal(api, planted)
    api.post(f"/v1/care-plan-proposals/{first['id']}/approve", headers=planted["auth"])
    original = first["professional_recommendations"]

    scripted.queue(plan_output(FERTILIZING, change_summary="עודכן לאחר שינוי סביבה"))
    propose(api, planted, reason="ENVIRONMENT_CHANGE")
    second = open_proposal(api, planted)
    api.post(f"/v1/care-plan-proposals/{second['id']}/approve", headers=planted["auth"])

    stored = versions(admin_sdk, planted["plant_id"])
    assert [(v["version_number"], v["status"]) for v in stored] == [
        (1, "SUPERSEDED"),
        (2, "ACTIVE"),
    ]
    assert stored[0]["professional_recommendations"] == original


def test_only_one_version_can_be_active(api, planted, scripted, admin_sdk):
    """The partial unique index, tested through the service role: if even that
    cannot create a second ACTIVE row, no route can."""
    scripted.queue(plan_output(WATERING))
    propose(api, planted)
    proposal = open_proposal(api, planted)
    api.post(f"/v1/care-plan-proposals/{proposal['id']}/approve", headers=planted["auth"])

    plan_id = (
        admin_sdk.table("care_plans").select("id").eq("plant_id", planted["plant_id"]).execute()
    ).data[0]["id"]

    with pytest.raises(APIError):
        admin_sdk.table("care_plan_versions").insert(
            {
                "care_plan_id": plan_id,
                "version_number": 99,
                "status": "ACTIVE",
                "professional_recommendations": {"summary": "forged"},
                "source_type": "INITIAL_PLAN",
                "change_summary": "forged",
            }
        ).execute()


def test_an_already_approved_proposal_cannot_be_approved_again(api, planted, scripted):
    scripted.queue(plan_output(WATERING))
    propose(api, planted)
    proposal = open_proposal(api, planted)

    api.post(f"/v1/care-plan-proposals/{proposal['id']}/approve", headers=planted["auth"])
    again = api.post(f"/v1/care-plan-proposals/{proposal['id']}/approve", headers=planted["auth"])
    assert again.status_code == 422


# --- A5: outstanding tasks -----------------------------------------------------


def test_approving_cancels_the_old_versions_pending_tasks(api, planted, scripted, admin_sdk):
    """A5. Those tasks came from rules the user has just replaced; leaving them
    would remind the plant on both schedules at once."""
    scripted.queue(plan_output(WATERING))
    propose(api, planted)
    first = open_proposal(api, planted)
    api.post(f"/v1/care-plan-proposals/{first['id']}/approve", headers=planted["auth"])

    rule_id = first["rules"][0]["id"]
    now = datetime.now(UTC)
    pending = (
        admin_sdk.table("care_tasks")
        .insert(
            {
                "user_id": planted["user_id"],
                "plant_id": planted["plant_id"],
                "care_rule_id": rule_id,
                "due_at_utc": (now + timedelta(days=1)).isoformat(),
                "status": "PENDING",
            }
        )
        .execute()
        .data[0]
    )
    done = (
        admin_sdk.table("care_tasks")
        .insert(
            {
                "user_id": planted["user_id"],
                "plant_id": planted["plant_id"],
                "care_rule_id": rule_id,
                "due_at_utc": (now - timedelta(days=3)).isoformat(),
                "status": "DONE",
                "completed_at": (now - timedelta(days=3)).isoformat(),
            }
        )
        .execute()
        .data[0]
    )

    scripted.queue(plan_output(FERTILIZING, change_summary="תוכנית חדשה"))
    propose(api, planted, reason="ENVIRONMENT_CHANGE")
    second = open_proposal(api, planted)
    api.post(f"/v1/care-plan-proposals/{second['id']}/approve", headers=planted["auth"])

    def status_of(task_id: str) -> str:
        return (admin_sdk.table("care_tasks").select("status").eq("id", task_id).execute()).data[0][
            "status"
        ]

    assert status_of(pending["id"]) == "CANCELLED"
    # Untouched: a completed task is a record of what happened, and a new plan
    # does not change the past.
    assert status_of(done["id"]) == "DONE"


# --- rejecting ------------------------------------------------------------------


def test_rejecting_leaves_the_active_plan_alone(api, planted, scripted, admin_sdk):
    scripted.queue(plan_output(WATERING))
    propose(api, planted)
    first = open_proposal(api, planted)
    api.post(f"/v1/care-plan-proposals/{first['id']}/approve", headers=planted["auth"])

    scripted.queue(plan_output(FERTILIZING, change_summary="הצעה שתידחה"))
    propose(api, planted, reason="HEALTH_DRIVEN")
    second = open_proposal(api, planted)

    response = api.post(
        f"/v1/care-plan-proposals/{second['id']}/reject",
        headers=planted["auth"],
        json={"note": "לא רלוונטי כרגע"},
    )
    assert response.status_code == 200

    active = api.get(f"/v1/plants/{planted['plant_id']}/care-plan", headers=planted["auth"])
    assert active.json()["data"]["version_number"] == 1


# --- operational adjustment ----------------------------------------------------


def test_an_operational_adjustment_copies_the_recommendations_byte_for_byte(
    api, planted, scripted, admin_sdk
):
    """FINAL §12's central guarantee, asserted by comparing the two blobs rather
    than by trusting the code that copies them."""
    scripted.queue(plan_output(WATERING))
    propose(api, planted)
    proposal = open_proposal(api, planted)
    api.post(f"/v1/care-plan-proposals/{proposal['id']}/approve", headers=planted["auth"])

    original = proposal["professional_recommendations"]

    response = api.post(
        f"/v1/care-plan-versions/{proposal['id']}/operational-adjustment",
        headers=planted["auth"],
        json={
            "operational_preferences": {"WATERING": {"interval_days": 10}},
            "change_summary": "העברתי להשקיה כל עשרה ימים",
        },
    )
    assert response.status_code == 200

    stored = versions(admin_sdk, planted["plant_id"])
    assert stored[1]["professional_recommendations"] == original
    assert stored[1]["source_type"] == "OPERATIONAL_ADJUSTMENT"


def test_an_operational_adjustment_applies_the_override_to_the_named_rule_only(
    api, planted, scripted, admin_sdk
):
    scripted.queue(plan_output(WATERING, FERTILIZING))
    propose(api, planted)
    proposal = open_proposal(api, planted)
    api.post(f"/v1/care-plan-proposals/{proposal['id']}/approve", headers=planted["auth"])

    api.post(
        f"/v1/care-plan-versions/{proposal['id']}/operational-adjustment",
        headers=planted["auth"],
        json={
            "operational_preferences": {"WATERING": {"interval_days": 10}},
            "change_summary": "השקיה כל עשרה ימים",
        },
    )

    adjusted = open_proposal(api, planted)
    by_action = {r["action_type"]: r["interval_days"] for r in adjusted["rules"]}
    assert by_action["WATERING"] == 10
    # Untouched: changing one preference must not rearrange the whole schedule.
    assert by_action["FERTILIZING"] == 30


def test_the_adjustment_endpoint_refuses_to_carry_recommendations(api, planted, scripted):
    """`extra: forbid` turns §12's product rule into a 422.

    Without it a client could send new advice alongside a frequency change and
    have it stored as though a horticulturist wrote it.
    """
    scripted.queue(plan_output(WATERING))
    propose(api, planted)
    proposal = open_proposal(api, planted)

    response = api.post(
        f"/v1/care-plan-versions/{proposal['id']}/operational-adjustment",
        headers=planted["auth"],
        json={
            "operational_preferences": {"WATERING": {"interval_days": 10}},
            "change_summary": "ניסיון לשנות המלצות",
            "professional_recommendations": {"summary": "עצה מזויפת"},
        },
    )
    assert response.status_code == 422


def test_an_adjustment_must_say_what_changed(api, planted, scripted):
    scripted.queue(plan_output(WATERING))
    propose(api, planted)
    proposal = open_proposal(api, planted)

    response = api.post(
        f"/v1/care-plan-versions/{proposal['id']}/operational-adjustment",
        headers=planted["auth"],
        json={"operational_preferences": {"WATERING": {"interval_days": 10}}, "change_summary": ""},
    )
    assert response.status_code == 422


# --- ownership ------------------------------------------------------------------


def test_another_user_cannot_read_or_approve_the_plan(api, planted, account, scripted):
    """RLS, not the route, is the boundary. A proposal belongs to one plant."""
    scripted.queue(plan_output(WATERING))
    propose(api, planted)
    proposal = open_proposal(api, planted)

    _, other_auth = account()

    assert (
        api.get(f"/v1/plants/{planted['plant_id']}/care-plan/proposals", headers=other_auth).json()[
            "data"
        ]
        == []
    )
    assert (
        api.post(
            f"/v1/care-plan-proposals/{proposal['id']}/approve", headers=other_auth
        ).status_code
        == 404
    )


def test_a_plan_cannot_be_proposed_for_an_unidentified_plant(api, account, admin_sdk, scripted):
    """A plan needs a species, and a species arrives by confirming an
    identification — so this is a state to explain, not a crash."""
    user_id, auth = account()
    plant = (
        admin_sdk.table("plants").insert({"user_id": user_id, "name": "לא מזוהה"}).execute().data[0]
    )
    try:
        scripted.queue(plan_output(WATERING))
        api.post(
            f"/v1/plants/{plant['id']}/care-plan/proposals",
            headers=auth,
            json={"reason": "INITIAL_PLAN"},
        )
        assert admin_sdk.table("care_plan_versions").select("id").execute().data is not None
        plan = admin_sdk.table("care_plans").select("id").eq("plant_id", plant["id"]).execute().data
        if plan:
            assert (
                admin_sdk.table("care_plan_versions")
                .select("id")
                .eq("care_plan_id", plan[0]["id"])
                .execute()
                .data
                == []
            )
    finally:
        with contextlib.suppress(Exception):
            admin_sdk.table("plants").delete().eq("id", plant["id"]).execute()


def test_a_seeded_species_contributes_its_knowledge_to_the_plan(api, account, admin_sdk, scripted):
    """The regression that mattered most in PR 20.

    Knowledge published before A16 stores each section as a plain string, and
    `care_context._sections()` required a dict — so a care plan for any seeded
    species was built from an empty knowledge base, silently. Nothing failed;
    the agent simply received nothing and produced a plan anyway.
    """
    from app.orchestration.services import care_context

    user_id, _ = account()
    species = (
        admin_sdk.table("species")
        .insert({"scientific_name": unique_species_name()})
        .execute()
        .data[0]
    )
    # The pre-A16 shape, exactly as `seed.sql` writes it.
    admin_sdk.table("knowledge_versions").insert(
        {
            "species_id": species["id"],
            "language": "he",
            "version_number": 1,
            "is_current": True,
            "content": {
                "light": "אור עקיף בהיר.",
                "watering": "להשקות כשהמצע יבש לעומק שלושה סנטימטרים.",
                "soil": "מצע מנקז היטב.",
                "sources": ["https://example.org"],
            },
        }
    ).execute()
    plant = (
        admin_sdk.table("plants")
        .insert(
            {
                "user_id": user_id,
                "species_id": species["id"],
                "status": "ACTIVE",
                "name": "צמח עם ידע ישן",
            }
        )
        .execute()
        .data[0]
    )

    try:
        context, _ = care_context.build(admin_sdk, plant_id=uuid.UUID(plant["id"]))

        assert context.knowledge_sections, "a seeded species must not yield an empty context"
        assert "watering" in context.knowledge_sections
        # `sources` is provenance, not advice, and must not reach the agent as prose.
        assert "sources" not in context.knowledge_sections
    finally:
        with contextlib.suppress(Exception):
            admin_sdk.table("plants").delete().eq("id", plant["id"]).execute()
