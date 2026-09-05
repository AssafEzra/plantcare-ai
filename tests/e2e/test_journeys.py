"""The nine journeys of PROGRESS §20 and TESTING §9.

Each test is one path a real person walks, start to finish, through the HTTP API
against the DEV database. They are deliberately long: the value is in the seams
between phases, and a seam only exists when two phases meet. Every serious defect
found during this build lived in one — a dashboard that never decorated its
tasks, a care context that read zero knowledge sections without saying so, a
plant list that returned other people's plants.

Eight journeys come from `PROGRESS §20`. The ninth — reporting a knowledge error
and seeing it reach an administrator — comes from `TESTING_STRATEGY §9`, which
lists it as a scenario while `§20` omits it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agents.identification.contract import IdentificationOutput
from app.common.enums import HealthStatus, IdentificationStatus, PlantStatus
from tests.e2e.conftest import (
    SECTION_NAMES,
    Script,
    add_plant,
    care_plan,
    health,
    identified,
    knowledge,
    upload,
)
from tests.integration.conftest import unique_species_name

pytestmark = pytest.mark.integration


# --- shared steps ---------------------------------------------------------------


def publish_knowledge_for(admin_sdk, scientific_name: str) -> str:
    """A species that already has a current, readable knowledge version.

    Written directly rather than through the research flow because these journeys
    are about what happens *after* knowledge exists. The one that is about
    producing it is `test_a_new_species_needs_an_administrator`.

    Complete and well-formed on purpose: all thirteen A16 sections in the
    `{text, confidence}` shape, and `published_at` set. Publication would produce
    exactly that, and a fixture that produced less would be testing a row the
    product cannot create — five sections and a null `published_at` is how the
    first draft of this file was written, and it turned the knowledge endpoint
    into a 500 that said nothing about the real flow.
    """
    species = (
        admin_sdk.table("species")
        .insert({"scientific_name": scientific_name, "common_name": "צמח בדיקה"})
        .execute()
        .data[0]
    )
    admin_sdk.table("knowledge_versions").insert(
        {
            "species_id": species["id"],
            "language": "he",
            "version_number": 1,
            "is_current": True,
            "published_at": datetime.now(UTC).isoformat(),
            "content": {
                name: {"text": f"מידע מקצועי בעברית על {name} עבור הצמח הזה.", "confidence": 0.9}
                for name in SECTION_NAMES
            },
        }
    ).execute()
    return species["id"]


def identify_and_confirm(api: TestClient, script: Script, auth: dict, name: str) -> dict:
    """Add a plant, photograph it, identify it, confirm the result."""
    plant_id = add_plant(api, auth)
    image_id = upload(api, auth, plant_id)

    script.identification.queue(identified(name))
    run = api.post(
        f"/v1/plants/{plant_id}/identification-runs",
        headers=auth,
        json={"image_ids": [image_id]},
    )
    assert run.status_code == 202, run.text

    # The client's real path to the result: poll the request, read where it
    # landed. There is no route from a plant to its identification, so this is
    # the only one - and it was broken until this journey walked it, because the
    # response model dropped `output_summary` and the Add Plant flow dead-ended
    # at "the identification was not found".
    polled = api.get(f"/v1/agent-requests/{run.json()['data']['agent_request_id']}", headers=auth)
    assert polled.status_code == 200, polled.text
    identification_id = polled.json()["data"]["output_summary"]["identification_id"]

    identification = api.get(f"/v1/identifications/{identification_id}", headers=auth).json()[
        "data"
    ]
    candidate = identification["candidates"][0]

    confirmed = api.post(
        f"/v1/identifications/{identification['id']}/confirm",
        headers=auth,
        json={"candidate_id": candidate["id"]},
    )
    assert confirmed.status_code == 200, confirmed.text

    # Naming comes after confirmation (`FINAL §3` step 5), which is why
    # `plants.name` is nullable until here. A journey that skipped it would leave
    # every reminder without a plant name and would not notice.
    named = api.patch(f"/v1/plants/{plant_id}", headers=auth, json={"name": "המונסטרה שלי"})
    assert named.status_code == 200, named.text

    return {"plant_id": plant_id, "image_id": image_id, **confirmed.json()["data"]}


def approved_plan(api: TestClient, script: Script, auth: dict, plant_id: str) -> dict:
    """Propose a care plan and approve it, which is what makes it schedulable."""
    script.care.queue(care_plan())
    proposed = api.post(
        f"/v1/plants/{plant_id}/care-plan/proposals", headers=auth, json={"reason": "INITIAL_PLAN"}
    )
    assert proposed.status_code == 202, proposed.text

    proposal = api.get(f"/v1/plants/{plant_id}/care-plan/proposals", headers=auth).json()["data"][0]
    approved = api.post(f"/v1/care-plan-proposals/{proposal['id']}/approve", headers=auth)
    assert approved.status_code == 200, approved.text
    return approved.json()["data"]


def tick(user_id: str) -> None:
    """What the cron does, scoped to one user.

    The `/v1/internal/tick` route itself is deliberately global — it is a cron
    endpoint — and against a shared DEV database holding a thousand plants it
    takes about twenty-five seconds per call. A journey that ticked three times
    would spend a minute and a half doing other users' work, and would be
    perturbed by whatever those users' rows happened to look like.

    The route's authentication, idempotency and email dispatch are covered by
    `tests/integration/test_scheduler.py`. What a journey needs from it is the
    scheduling, and that takes a `user_id`.
    """
    from datetime import UTC, datetime

    from app.infrastructure.supabase.client import service_client
    from app.orchestration.services import scheduler

    admin = service_client()
    now = datetime.now(UTC)
    scheduler.materialise(admin, now_utc=now, user_id=user_id)
    scheduler.sweep_overdue(admin, now_utc=now, user_id=user_id)


# --- 1. new user → add plant → confirm → knowledge → care plan → schedule --------


def test_a_new_user_reaches_a_scheduled_task(api, account, admin_sdk, script):
    """The whole product in one test.

    This is the `FINAL §34` smoke path: signup, add, photograph, identify,
    confirm, knowledge, plan, approve, schedule. If this fails, nothing else
    matters much.
    """
    user = account()
    name = unique_species_name()
    publish_knowledge_for(admin_sdk, name)

    result = identify_and_confirm(api, script, user.auth, name)

    # Knowledge already exists, so the plant is usable immediately — no waiting,
    # no research queued (A4's other branch).
    assert result["status"] == PlantStatus.ACTIVE.value
    assert result["knowledge_pending"] is False

    approved_plan(api, script, user.auth, result["plant_id"])
    tick(user.user_id)

    dashboard = api.get("/v1/dashboard", headers=user.auth).json()["data"]
    mine = dashboard["today_care"] + dashboard["upcoming_care"]

    assert mine, "an approved plan with a watering rule scheduled nothing"
    task = next(t for t in mine if t["plant_id"] == result["plant_id"])
    # Decorated, not raw. A reminder that cannot name the plant or the action is
    # not a reminder — this rendered as "**** · הצמח שלי" when it shipped.
    assert task["action_type"] == "WATERING"
    assert task["plant_name"]


# --- 2. existing species reuses published knowledge ------------------------------


def test_a_second_user_of_the_same_species_reuses_the_published_knowledge(
    api, account, admin_sdk, script
):
    """No second draft, no second research run, no second version.

    Knowledge is per species, not per plant (`FINAL §10`). A build that quietly
    researched again would be correct on screen and wrong on the invoice — and
    would eventually publish a competing version of the same species.
    """
    name = unique_species_name()
    species_id = publish_knowledge_for(admin_sdk, name)

    first = identify_and_confirm(api, script, account().auth, name)
    second_user = account()
    second = identify_and_confirm(api, script, second_user.auth, name)

    assert first["species_id"] == second["species_id"] == species_id
    assert second["status"] == PlantStatus.ACTIVE.value

    drafts = (
        admin_sdk.table("knowledge_drafts").select("id").eq("species_id", species_id).execute().data
    )
    assert drafts == [], "confirming an already-known species started research"

    versions = (
        admin_sdk.table("knowledge_versions")
        .select("version_number")
        .eq("species_id", species_id)
        .execute()
        .data
    )
    assert len(versions) == 1

    # And the user can read it — the same row, through their own JWT and RLS.
    served = api.get(f"/v1/species/{species_id}/knowledge", headers=second_user.auth)
    assert served.status_code == 200
    assert served.json()["data"]["version_number"] == 1


# --- 3. new species → draft → admin approval → active plant ----------------------


def test_a_new_species_needs_an_administrator(api, account, admin_sdk, script):
    """The A4 fan-out, from the user's side.

    A plant of an unknown species waits — it does not fail, and it does not get a
    care plan built on nothing. What releases it is a human approving the
    research, and the release has to reach a plant belonging to someone else
    entirely, which is why publication runs as the service role.
    """
    user = account()
    admin = account(role="ADMIN")
    name = unique_species_name()

    script.knowledge.queue(knowledge())
    script.care.queue(care_plan())
    result = identify_and_confirm(api, script, user.auth, name)

    assert result["status"] == PlantStatus.KNOWLEDGE_PENDING.value
    assert result["knowledge_pending"] is True

    draft = (
        admin_sdk.table("knowledge_drafts")
        .select("*")
        .eq("species_id", result["species_id"])
        .execute()
        .data[0]
    )
    assert draft["status"] == "READY_FOR_REVIEW"

    published = api.post(
        f"/v1/admin/knowledge-drafts/{draft['id']}/approve", headers=admin.auth, json={}
    )
    assert published.status_code == 200, published.text
    assert published.json()["data"]["active_plants"] >= 1

    plant = api.get(f"/v1/plants/{result['plant_id']}", headers=user.auth).json()["data"]
    assert plant["status"] == PlantStatus.ACTIVE.value

    # A3: released and immediately given something to approve. An ACTIVE plant
    # with no plan has nothing to schedule and nothing to show.
    proposals = api.get(
        f"/v1/plants/{result['plant_id']}/care-plan/proposals", headers=user.auth
    ).json()["data"]
    assert proposals, "the released plant was left with no proposal"
    assert proposals[0]["source_type"] == "INITIAL_PLAN"


# --- 4. health check → status update ---------------------------------------------


def test_a_health_check_updates_the_plants_status(api, account, admin_sdk, script):
    user = account()
    name = unique_species_name()
    publish_knowledge_for(admin_sdk, name)
    result = identify_and_confirm(api, script, user.auth, name)
    image_id = upload(api, user.auth, result["plant_id"], context="health")

    script.health.queue(health(HealthStatus.NEEDS_ATTENTION))
    started = api.post(
        f"/v1/plants/{result['plant_id']}/health-checks",
        headers=user.auth,
        json={"image_ids": [image_id]},
    )
    assert started.status_code == 202, started.text

    history = api.get(f"/v1/plants/{result['plant_id']}/health-history", headers=user.auth).json()[
        "data"
    ]
    assert history[0]["overall_status"] == HealthStatus.NEEDS_ATTENTION.value

    plant = api.get(f"/v1/plants/{result['plant_id']}", headers=user.auth).json()["data"]
    assert plant["current_health_status"] == HealthStatus.NEEDS_ATTENTION.value

    # And it reaches Home, which is where a user would actually notice.
    dashboard = api.get("/v1/dashboard", headers=user.auth).json()["data"]
    assert any(p["id"] == result["plant_id"] for p in dashboard["plants_needing_attention"])


# --- 5. health check → care proposal → approval ----------------------------------


def test_a_health_finding_proposes_a_plan_change_but_cannot_make_one(
    api, account, admin_sdk, script
):
    """`FINAL §16`: the Health Agent cannot modify the care plan.

    The finding raises a proposal; the user approves it; the plan changes then and
    only then. The assertion that matters is the one in the middle — that between
    the check and the approval, the active plan is untouched.
    """
    user = account()
    name = unique_species_name()
    publish_knowledge_for(admin_sdk, name)
    result = identify_and_confirm(api, script, user.auth, name)
    plant_id = result["plant_id"]
    first = approved_plan(api, script, user.auth, plant_id)

    image_id = upload(api, user.auth, plant_id, context="health")
    script.health.queue(health(HealthStatus.NEEDS_ATTENTION, wants_adjustment=True))
    api.post(
        f"/v1/plants/{plant_id}/health-checks", headers=user.auth, json={"image_ids": [image_id]}
    )

    assessment = api.get(f"/v1/plants/{plant_id}/health-history", headers=user.auth).json()["data"][
        0
    ]
    active = api.get(f"/v1/plants/{plant_id}/care-plan", headers=user.auth).json()["data"]
    assert active["version_number"] == first["version_number"], "the check changed the plan itself"

    script.care.queue(care_plan())
    raised = api.post(
        f"/v1/plants/{plant_id}/care-plan/adjustment-proposals",
        headers=user.auth,
        json={"health_assessment_id": assessment["id"], "reason": "ממצא בבדיקת בריאות"},
    )
    assert raised.status_code == 202, raised.text

    proposal = api.get(f"/v1/plants/{plant_id}/care-plan/proposals", headers=user.auth).json()[
        "data"
    ][0]
    assert proposal["source_type"] == "HEALTH_DRIVEN"

    api.post(f"/v1/care-plan-proposals/{proposal['id']}/approve", headers=user.auth)
    now_active = api.get(f"/v1/plants/{plant_id}/care-plan", headers=user.auth).json()["data"]

    assert now_active["version_number"] == first["version_number"] + 1


# --- 6. overdue task → completion → history --------------------------------------


def test_an_overdue_task_can_still_be_completed_and_lands_in_history(
    api, account, admin_sdk, script
):
    """Overdue is a state, not a dead end (`FINAL §13`).

    The task stays actionable, completing it writes an immutable `care_event`, and
    the event appears in the plant's timeline — which is the only durable record
    that the plant was watered at all.
    """
    user = account()
    name = unique_species_name()
    publish_knowledge_for(admin_sdk, name)
    result = identify_and_confirm(api, script, user.auth, name)
    plant_id = result["plant_id"]
    approved_plan(api, script, user.auth, plant_id)
    tick(user.user_id)

    task = next(
        t
        for t in api.get("/v1/care-tasks", headers=user.auth).json()["data"]
        if t["plant_id"] == plant_id
    )
    # Backdated rather than waited for. Two days is past due but well inside the
    # A9 expiry window, so the sweep marks it OVERDUE and leaves it actionable.
    admin_sdk.table("care_tasks").update(
        {"due_at_utc": (datetime.now(UTC) - timedelta(days=2)).isoformat()}
    ).eq("id", task["id"]).execute()
    tick(user.user_id)

    overdue = api.get("/v1/care-tasks", headers=user.auth).json()["data"]
    mine = next(t for t in overdue if t["id"] == task["id"])
    assert mine["status"] == "OVERDUE"

    summary = api.get("/v1/dashboard", headers=user.auth).json()["data"]["overdue_summary"]
    assert any(entry["plant_id"] == plant_id for entry in summary)

    done = api.post(f"/v1/care-tasks/{task['id']}/done", headers=user.auth, json={})
    assert done.status_code == 200, done.text

    timeline = api.get(f"/v1/plants/{plant_id}/history", headers=user.auth).json()["data"]
    assert any(entry["kind"] == "CARE_DONE" for entry in timeline)

    # Completing one occurrence does not end the plan — the next is scheduled.
    tick(user.user_id)
    remaining = api.get("/v1/care-tasks", headers=user.auth).json()["data"]
    assert any(t["plant_id"] == plant_id and t["status"] == "PENDING" for t in remaining)


# --- 7. user isolation -----------------------------------------------------------


def test_one_user_cannot_reach_another_users_plant(api, account, admin_sdk, script):
    """RLS from the outside, through the API a real client uses.

    `tests/security/test_rls_matrix.py` proves the policies at the database. This
    proves the API does not route around them — which it did once: an admin's own
    plant list returned 590 plants belonging to other people, because the query
    relied on a policy that grants administrators read-all.
    """
    owner = account()
    stranger = account()
    name = unique_species_name()
    publish_knowledge_for(admin_sdk, name)
    result = identify_and_confirm(api, script, owner.auth, name)
    plant_id = result["plant_id"]
    approved_plan(api, script, owner.auth, plant_id)
    tick(owner.user_id)

    assert api.get(f"/v1/plants/{plant_id}", headers=stranger.auth).status_code == 404
    assert api.get(f"/v1/plants/{plant_id}/dashboard", headers=stranger.auth).status_code == 404
    assert api.get(f"/v1/plants/{plant_id}/care-plan", headers=stranger.auth).status_code == 404
    assert (
        api.patch(
            f"/v1/plants/{plant_id}", headers=stranger.auth, json={"name": "שלי עכשיו"}
        ).status_code
        == 404
    )

    # Not a filtered-away 200: the stranger's own lists are empty, and the owner's
    # rows are not merely hidden from a listing that would still act on them.
    assert api.get("/v1/plants", headers=stranger.auth).json()["data"] == []
    assert api.get("/v1/care-tasks", headers=stranger.auth).json()["data"] == []

    task = next(
        t
        for t in api.get("/v1/care-tasks", headers=owner.auth).json()["data"]
        if t["plant_id"] == plant_id
    )
    assert api.post(
        f"/v1/care-tasks/{task['id']}/done", headers=stranger.auth, json={}
    ).status_code in (
        404,
        403,
    )

    # And the owner still has everything.
    assert api.get(f"/v1/plants/{plant_id}", headers=owner.auth).status_code == 200
    assert api.get("/v1/care-tasks", headers=owner.auth).json()["data"][0]["status"] == "PENDING"


# --- 8. AI failure → no authoritative record -------------------------------------


def test_an_ai_failure_leaves_the_plant_exactly_as_it_was(api, account, admin_sdk, script):
    """`FINAL §25`, walked rather than unit-tested.

    A model that returns nothing usable must not leave a half-written world: no
    species assignment, no care plan version, no health status. The user sees an
    error and can try again, which is the whole contract.
    """
    user = account()
    name = unique_species_name()
    publish_knowledge_for(admin_sdk, name)
    result = identify_and_confirm(api, script, user.auth, name)
    plant_id = result["plant_id"]
    approved_plan(api, script, user.auth, plant_id)

    before = api.get(f"/v1/plants/{plant_id}", headers=user.auth).json()["data"]
    plan_before = api.get(f"/v1/plants/{plant_id}/care-plan", headers=user.auth).json()["data"]

    # Three attempts of unusable output: the gateway's one call plus two retries.
    script.care.queue(*[{"not": "a plan"}] * 3)
    api.post(
        f"/v1/plants/{plant_id}/care-plan/proposals",
        headers=user.auth,
        json={"reason": "USER_REQUESTED"},
    )

    script.health.queue(*[{"overall_status": "NOT_A_STATUS"}] * 3)
    image_id = upload(api, user.auth, plant_id, context="health")
    api.post(
        f"/v1/plants/{plant_id}/health-checks", headers=user.auth, json={"image_ids": [image_id]}
    )

    after = api.get(f"/v1/plants/{plant_id}", headers=user.auth).json()["data"]
    plan_after = api.get(f"/v1/plants/{plant_id}/care-plan", headers=user.auth).json()["data"]

    assert after["species_id"] == before["species_id"]
    assert plan_after["version_number"] == plan_before["version_number"]
    assert plan_after["professional_recommendations"] == plan_before["professional_recommendations"]

    proposals = api.get(f"/v1/plants/{plant_id}/care-plan/proposals", headers=user.auth).json()[
        "data"
    ]
    assert proposals == [], "a failed plan run left a proposal behind"

    # The health check is the exception the spec asks for: `FINAL §16` wants an
    # unusable check *saved* as UNKNOWN with its reason, so the user learns why.
    # That is an honest record of a failure, not an authoritative finding — it
    # carries no confidence and no issues, and it does not overwrite the status.
    assessments = api.get(f"/v1/plants/{plant_id}/health-history", headers=user.auth).json()["data"]
    assert assessments[0]["overall_status"] == HealthStatus.UNKNOWN.value
    assert after["current_health_status"] == before["current_health_status"]


# --- 9. reporting a knowledge error (TESTING §9) ---------------------------------


def test_a_user_reports_an_error_and_an_administrator_acts_on_it(api, account, admin_sdk, script):
    """`FINAL §10`: a user reports, never edits.

    The report has to survive publication of a newer version — an administrator
    reading the queue a week later must still be able to tell which text the
    complaint was about, or the report is unactionable.
    """
    user = account()
    admin = account(role="ADMIN")
    name = unique_species_name()
    species_id = publish_knowledge_for(admin_sdk, name)
    result = identify_and_confirm(api, script, user.auth, name)

    filed = api.post(
        f"/v1/species/{species_id}/knowledge-reports",
        headers=user.auth,
        json={
            "plant_id": result["plant_id"],
            "report_text": "ההמלצה על ההשקיה נראית שגויה לחלוטין.",
        },
    )
    assert filed.status_code == 201, filed.text

    queue = api.get("/v1/admin/knowledge-reports", headers=admin.auth).json()["data"]
    reported = next(r for r in queue if r["id"] == filed.json()["data"]["report_id"])
    assert reported["status"] == "OPEN"
    assert reported["knowledge_version_id"], "the report does not say which version it is about"

    reviewed = api.post(
        f"/v1/admin/knowledge-reports/{reported['id']}/review",
        headers=admin.auth,
        json={"status": "ACTIONED", "admin_note": "מתחיל מחקר מחדש עבור המין הזה."},
    )
    assert reviewed.status_code == 200, reviewed.text

    # Triage is not research. Acting on the report is a separate, explicit step —
    # a status that implied a research run that never happened would be worse than
    # no status at all.
    script.knowledge.queue(knowledge("מידע מתוקן על ההשקיה, בעברית, לאחר הדיווח."))
    draft = (
        admin_sdk.table("knowledge_drafts")
        .insert({"species_id": species_id, "language": "he", "status": "DRAFT"})
        .execute()
        .data[0]
    )
    retried = api.post(
        f"/v1/admin/knowledge-drafts/{draft['id']}/retry", headers=admin.auth, json={}
    )
    assert retried.status_code in (200, 202), retried.text

    approved = api.post(
        f"/v1/admin/knowledge-drafts/{draft['id']}/approve", headers=admin.auth, json={}
    )
    assert approved.status_code == 200, approved.text

    served = api.get(f"/v1/species/{species_id}/knowledge", headers=user.auth).json()["data"]
    assert served["version_number"] == 2

    # Version 1 was not edited or deleted — `FINAL §29`. The correction is a new
    # version, and the old one is still there to explain what the report meant.
    kept = (
        admin_sdk.table("knowledge_versions")
        .select("version_number, is_current")
        .eq("species_id", species_id)
        .order("version_number")
        .execute()
        .data
    )
    assert [v["version_number"] for v in kept] == [1, 2]
    assert [v["is_current"] for v in kept] == [False, True]


# --- a guard on the harness itself -----------------------------------------------


def test_no_journey_can_reach_a_live_model(api, account, script):
    """`TESTING §9`: no test depends on a live LLM.

    An unscripted MockProvider raises rather than returning a plausible default,
    so a journey that forgot to script a step fails loudly instead of asserting
    against a harness. The same property is what stops a missing dependency
    override from making a real, billable call from the test suite.
    """
    user = account()
    plant_id = add_plant(api, user.auth)
    image_id = upload(api, user.auth, plant_id)

    api.post(
        f"/v1/plants/{plant_id}/identification-runs",
        headers=user.auth,
        json={"image_ids": [image_id]},
    )

    # One call, not a fallback: the provider raised on the first request rather
    # than inventing a plausible identification.
    assert script.identification.call_count == 1

    plant = api.get(f"/v1/plants/{plant_id}", headers=user.auth).json()["data"]
    assert plant["status"] == PlantStatus.PENDING_IDENTIFICATION.value
    assert plant["species_id"] is None


def test_a_species_is_never_created_from_an_unconfirmed_identification(
    api, account, admin_sdk, script
):
    """Plan decision 2, and the reason the taxonomy table stays clean.

    A model can return a binomial that does not exist. Until a human confirms it,
    it is a candidate — a string on a screen — and not a row anything can point
    at.
    """
    user = account()
    plant_id = add_plant(api, user.auth)
    image_id = upload(api, user.auth, plant_id)
    invented = unique_species_name()

    script.identification.queue(
        IdentificationOutput(
            status=IdentificationStatus.SUCCESS,
            candidates=identified(invented).candidates,
            image_quality="ברור",
        )
    )
    api.post(
        f"/v1/plants/{plant_id}/identification-runs",
        headers=user.auth,
        json={"image_ids": [image_id]},
    )

    found = admin_sdk.table("species").select("id").eq("scientific_name", invented).execute().data
    assert found == []

    plant = api.get(f"/v1/plants/{plant_id}", headers=user.auth).json()["data"]
    assert plant["species_id"] is None
    assert plant["status"] == PlantStatus.PENDING_IDENTIFICATION.value


def test_an_archived_plant_keeps_its_history_and_comes_back(api, account, admin_sdk, script):
    """`FINAL §21`: archive is the normal user action, not deletion."""
    user = account()
    name = unique_species_name()
    publish_knowledge_for(admin_sdk, name)
    result = identify_and_confirm(api, script, user.auth, name)
    plant_id = result["plant_id"]

    api.post(
        f"/v1/plants/{plant_id}/history",
        headers=user.auth,
        json={"event_type": "REPOTTED", "note": "הועבר לעציץ גדול יותר."},
    )
    before = api.get(f"/v1/plants/{plant_id}/history", headers=user.auth).json()["data"]

    api.post(f"/v1/plants/{plant_id}/archive", headers=user.auth)

    active = api.get("/v1/plants", headers=user.auth, params={"status": "ACTIVE"}).json()["data"]
    assert all(p["id"] != plant_id for p in active)

    restored = api.post(f"/v1/plants/{plant_id}/restore", headers=user.auth)
    assert restored.status_code == 200, restored.text

    after = api.get(f"/v1/plants/{plant_id}/history", headers=user.auth).json()["data"]
    assert len(after) >= len(before), "archiving lost history"
    assert any(entry["kind"] == "REPOTTED" for entry in after)


def test_the_same_idempotency_key_does_not_run_the_model_twice(api, account, admin_sdk, script):
    """A24, at the level a retrying client actually hits it.

    A dropped connection makes a browser retry. Without this, the second attempt
    is a second billable run and a second identification row for one user action.
    """
    user = account()
    plant_id = add_plant(api, user.auth)
    image_id = upload(api, user.auth, plant_id)
    key = str(uuid.uuid4())
    body = {"image_ids": [image_id]}

    script.identification.queue(identified(unique_species_name()))
    first = api.post(
        f"/v1/plants/{plant_id}/identification-runs",
        headers={**user.auth, "Idempotency-Key": key},
        json=body,
    )
    second = api.post(
        f"/v1/plants/{plant_id}/identification-runs",
        headers={**user.auth, "Idempotency-Key": key},
        json=body,
    )

    assert first.status_code == second.status_code == 202
    assert first.json()["data"]["agent_request_id"] == second.json()["data"]["agent_request_id"]
    assert second.json()["data"]["replayed"] is True
    assert script.identification.call_count == 1
