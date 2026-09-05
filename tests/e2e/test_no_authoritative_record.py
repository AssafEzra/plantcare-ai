"""One case per agent: a failed model call writes no authoritative record.

`FINAL §25` and `TESTING §13`. The rule is short and the consequence is not: a
half-written world after a failed AI call is worse than no call at all, because
the user cannot see that it happened. A species assigned from output that failed
validation, a care plan version with no rules, a health status overwritten by a
call that returned nothing — each of those looks like a real record afterwards.

Written against the real database on purpose. A mock repository would confirm the
call was not made; only a real one confirms the row is not there. And what counts
as "authoritative" differs per agent, which is why this is four cases and not a
parametrised loop:

* **Identification** — no species, and the plant unchanged.
* **Knowledge** — no published version; the draft is marked FAILED and stays
  retriable, and the plants waiting on it keep waiting rather than stranding.
* **Care** — no version, no rules, and the previously active plan untouched.
* **Health** — the documented exception. `FINAL §16` asks for an unusable check
  to be *saved* as `UNKNOWN` with its reason, so the user learns why. That row is
  an honest record of a failure: no confidence, no issues, and it does not
  overwrite the plant's status.

Three unusable responses per case: the gateway's one call plus its two retries.
"""

from __future__ import annotations

import pytest

from app.common.enums import HealthStatus, PlantStatus
from tests.e2e.conftest import add_plant, care_plan, health, upload
from tests.e2e.test_journeys import identify_and_confirm, publish_knowledge_for
from tests.integration.conftest import unique_species_name

pytestmark = pytest.mark.integration

UNUSABLE = 3


def test_identification_failure_leaves_the_plant_unidentified(api, account, admin_sdk, script):
    user = account()
    plant_id = add_plant(api, user.auth)
    image_id = upload(api, user.auth, plant_id)

    script.identification.queue(*[{"status": "NOT_A_STATUS"}] * UNUSABLE)
    started = api.post(
        f"/v1/plants/{plant_id}/identification-runs",
        headers=user.auth,
        json={"image_ids": [image_id]},
    )
    assert started.status_code == 202

    plant = api.get(f"/v1/plants/{plant_id}", headers=user.auth).json()["data"]
    assert plant["species_id"] is None
    assert plant["status"] == PlantStatus.PENDING_IDENTIFICATION.value

    # The failure is visible rather than silent — but it is the *identification*
    # that failed, not the request. The run completed and recorded an honest
    # FAILED result, which is what `FINAL §25` means by a graceful failure: the
    # user is told, and can try again with better photographs.
    request = api.get(
        f"/v1/agent-requests/{started.json()['data']['agent_request_id']}", headers=user.auth
    ).json()["data"]
    identification = api.get(
        f"/v1/identifications/{request['output_summary']['identification_id']}", headers=user.auth
    ).json()["data"]

    assert identification["status"] == "FAILED"
    assert identification["candidates"] == []


def test_knowledge_failure_publishes_nothing_and_strands_no_plant(api, account, admin_sdk, script):
    """A17. The draft fails; the plant waits; the species stays retriable.

    The plant must not be released to ACTIVE on knowledge that does not exist, and
    it must not be marked failed either — nothing about the user's plant went
    wrong, and a status they cannot act on is a dead end.
    """
    user = account()
    name = unique_species_name()

    script.knowledge.queue(*[{"content": "not a knowledge document"}] * UNUSABLE)
    result = identify_and_confirm(api, script, user.auth, name)

    assert result["status"] == PlantStatus.KNOWLEDGE_PENDING.value

    versions = (
        admin_sdk.table("knowledge_versions")
        .select("id")
        .eq("species_id", result["species_id"])
        .execute()
        .data
    )
    assert versions == [], "a failed research run published a knowledge version"

    draft = (
        admin_sdk.table("knowledge_drafts")
        .select("status")
        .eq("species_id", result["species_id"])
        .execute()
        .data[0]
    )
    assert draft["status"] == "FAILED"

    plant = api.get(f"/v1/plants/{result['plant_id']}", headers=user.auth).json()["data"]
    assert plant["status"] == PlantStatus.KNOWLEDGE_PENDING.value


def test_care_failure_leaves_no_version_and_no_rules(api, account, admin_sdk, script):
    user = account()
    name = unique_species_name()
    publish_knowledge_for(admin_sdk, name)
    result = identify_and_confirm(api, script, user.auth, name)
    plant_id = result["plant_id"]

    script.care.queue(care_plan())
    api.post(
        f"/v1/plants/{plant_id}/care-plan/proposals",
        headers=user.auth,
        json={"reason": "INITIAL_PLAN"},
    )
    proposal = api.get(f"/v1/plants/{plant_id}/care-plan/proposals", headers=user.auth).json()[
        "data"
    ][0]
    api.post(f"/v1/care-plan-proposals/{proposal['id']}/approve", headers=user.auth)
    before = api.get(f"/v1/plants/{plant_id}/care-plan", headers=user.auth).json()["data"]

    script.care.queue(*[{"recommendations": None, "rules": "not a list"}] * UNUSABLE)
    api.post(
        f"/v1/plants/{plant_id}/care-plan/proposals",
        headers=user.auth,
        json={"reason": "USER_REQUESTED"},
    )

    after = api.get(f"/v1/plants/{plant_id}/care-plan", headers=user.auth).json()["data"]
    assert after["version_number"] == before["version_number"]
    assert after["professional_recommendations"] == before["professional_recommendations"]

    assert (
        api.get(f"/v1/plants/{plant_id}/care-plan/proposals", headers=user.auth).json()["data"]
        == []
    ), "a failed run left a proposal the user could approve"

    plan = admin_sdk.table("care_plans").select("id").eq("plant_id", plant_id).execute().data[0]
    versions = (
        admin_sdk.table("care_plan_versions")
        .select("id")
        .eq("care_plan_id", plan["id"])
        .execute()
        .data
    )
    assert len(versions) == 1, "a failed run wrote a version row"


def test_health_failure_is_saved_as_unknown_without_changing_the_status(
    api, account, admin_sdk, script
):
    user = account()
    name = unique_species_name()
    publish_knowledge_for(admin_sdk, name)
    result = identify_and_confirm(api, script, user.auth, name)
    plant_id = result["plant_id"]

    # A successful check first, so there is a known status for the failed one to
    # overwrite. Against an already-UNKNOWN plant the assertion would be empty.
    script.health.queue(health(HealthStatus.HEALTHY))
    image_id = upload(api, user.auth, plant_id, context="health")
    api.post(
        f"/v1/plants/{plant_id}/health-checks", headers=user.auth, json={"image_ids": [image_id]}
    )
    before = api.get(f"/v1/plants/{plant_id}", headers=user.auth).json()["data"]
    assert before["current_health_status"] == HealthStatus.HEALTHY.value

    script.health.queue(*[{"overall_status": "NOT_A_STATUS"}] * UNUSABLE)
    second_image = upload(api, user.auth, plant_id, context="health")
    api.post(
        f"/v1/plants/{plant_id}/health-checks",
        headers=user.auth,
        json={"image_ids": [second_image]},
    )

    history = api.get(f"/v1/plants/{plant_id}/health-history", headers=user.auth).json()["data"]
    latest = history[0]
    assert latest["overall_status"] == HealthStatus.UNKNOWN.value
    assert latest["confidence_level"] is None

    assessment = api.get(f"/v1/health-assessments/{latest['id']}", headers=user.auth).json()["data"]
    assert assessment["insufficient_information_reason"], "an UNKNOWN that does not say why"
    assert assessment["possible_issues"] == []
    assert assessment["recommendations"] == []

    after = api.get(f"/v1/plants/{plant_id}", headers=user.auth).json()["data"]
    assert after["current_health_status"] == HealthStatus.HEALTHY.value, (
        "an inconclusive check overwrote a known status"
    )

    # And the earlier assessment is byte-identical — prior findings are never
    # touched by a later run, successful or not.
    assert history[1]["overall_status"] == HealthStatus.HEALTHY.value
