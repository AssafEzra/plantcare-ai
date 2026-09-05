"""The scheduler against DEV.

The recurrence arithmetic is proved in `tests/unit/test_recurrence.py` without a
database. What needs one is everything around it:

* the tick is **idempotent** — running it twice produces one task, not two, which
  is the difference between a reminder and a duplicate reminder;
* a duplicate done/skip is refused with 409 by a unique index rather than by a
  read-then-check that two taps could race through;
* A9 — an expired task becomes a MISSED event and is cancelled, and the next
  occurrence is still scheduled;
* `/internal/tick` refuses a wrong or missing secret;
* one user's tasks are invisible to another.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.common.enums import CareRuleActionType
from tests.integration.conftest import delete_accounts, unique_species_name

pytestmark = pytest.mark.integration

PASSWORD = "Sched-Passw0rd!"


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
    from supabase import create_client

    created: list[str] = []

    def _make() -> tuple[str, dict[str, str]]:
        email = f"sch-{uuid.uuid4().hex[:12]}@example.com"
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


@pytest.fixture
def scheduled(admin_sdk, account) -> Iterator[dict]:
    """An ACTIVE plant with an ACTIVE care plan carrying one watering rule."""
    user_id, auth = account()
    species = (
        admin_sdk.table("species")
        .insert({"scientific_name": unique_species_name()})
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
                "name": "צמח מתוזמן",
            }
        )
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
                "professional_recommendations": {"summary": "בדיקה"},
                "source_type": "INITIAL_PLAN",
            }
        )
        .execute()
        .data[0]
    )
    admin_sdk.table("care_plans").update({"active_version_id": version["id"]}).eq(
        "id", plan["id"]
    ).execute()
    rule = (
        admin_sdk.table("care_rules")
        .insert(
            {
                "care_plan_version_id": version["id"],
                "action_type": CareRuleActionType.WATERING.value,
                "interval_days": 7,
                "preferred_time_local": "08:00",
            }
        )
        .execute()
        .data[0]
    )

    yield {
        "user_id": user_id,
        "auth": auth,
        "plant_id": plant["id"],
        "rule_id": rule["id"],
        "version_id": version["id"],
    }

    with contextlib.suppress(Exception):
        admin_sdk.table("plants").delete().eq("id", plant["id"]).execute()


def tick(api: TestClient, secret: str | None = None):
    headers = {}
    if secret is None:
        secret = os.environ["INTERNAL_TICK_SECRET"]
    if secret:
        headers["X-Internal-Secret"] = secret
    return api.post("/v1/internal/tick", headers=headers)


def tasks_of(admin_sdk, plant_id: str, status: str | None = None) -> list[dict]:
    query = admin_sdk.table("care_tasks").select("*").eq("plant_id", plant_id)
    if status:
        query = query.eq("status", status)
    return query.order("due_at_utc").execute().data


def make_task(admin_sdk, scheduled: dict, *, due: datetime, status: str = "PENDING") -> dict:
    payload = {
        "user_id": scheduled["user_id"],
        "plant_id": scheduled["plant_id"],
        "care_rule_id": scheduled["rule_id"],
        "due_at_utc": due.isoformat(),
        "status": status,
    }
    if status == "OVERDUE":
        payload["overdue_since"] = due.isoformat()
    return admin_sdk.table("care_tasks").insert(payload).execute().data[0]


# --- the tick ------------------------------------------------------------------


def test_the_tick_requires_the_shared_secret(api):
    """No user, so no JWT — and an endpoint that ran without the secret would let
    anyone drive every user's scheduler."""
    assert api.post("/v1/internal/tick").status_code == 403
    assert tick(api, secret="wrong-secret").status_code == 403


def test_the_tick_materialises_a_task_for_an_active_rule(api, admin_sdk, scheduled):
    assert tick(api).status_code == 200
    assert len(tasks_of(admin_sdk, scheduled["plant_id"], "PENDING")) == 1


def test_running_the_tick_twice_produces_one_task(api, admin_sdk, scheduled):
    """The property that matters most: a cron every fifteen minutes must not
    generate a task every fifteen minutes."""
    tick(api)
    tick(api)
    tick(api)

    assert len(tasks_of(admin_sdk, scheduled["plant_id"], "PENDING")) == 1


def test_the_one_pending_per_rule_invariant_is_enforced_by_the_database(api, admin_sdk, scheduled):
    """Tested through the service role: if even that cannot create a second
    pending task, no scheduler bug can."""
    from postgrest.exceptions import APIError

    tick(api)
    with pytest.raises(APIError):
        make_task(admin_sdk, scheduled, due=datetime.now(UTC) + timedelta(days=3))


def test_an_archived_plant_is_not_scheduled(api, admin_sdk, scheduled):
    """Reminding someone to water a plant they have put away is the clearest
    possible sign the app is not paying attention."""
    admin_sdk.table("plants").update(
        {"status": "ARCHIVED", "archived_at": datetime.now(UTC).isoformat()}
    ).eq("id", scheduled["plant_id"]).execute()

    tick(api)
    assert tasks_of(admin_sdk, scheduled["plant_id"]) == []


# --- done and skip -------------------------------------------------------------


def test_completing_a_task_records_an_event_and_schedules_the_next(api, admin_sdk, scheduled):
    tick(api)
    task = tasks_of(admin_sdk, scheduled["plant_id"], "PENDING")[0]

    response = api.post(f"/v1/care-tasks/{task['id']}/done", headers=scheduled["auth"], json={})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "DONE"

    events = (
        admin_sdk.table("care_events").select("event_type").eq("care_task_id", task["id"]).execute()
    ).data
    assert [e["event_type"] for e in events] == ["DONE"]

    # The following occurrence exists, so the user can see when it comes round.
    assert len(tasks_of(admin_sdk, scheduled["plant_id"], "PENDING")) == 1


def test_a_duplicate_completion_is_refused_with_409(api, admin_sdk, scheduled):
    """API_CONTRACTS: "Duplicate action events are rejected." Backed by a unique
    index, so two taps on a slow connection cannot both succeed."""
    tick(api)
    task = tasks_of(admin_sdk, scheduled["plant_id"], "PENDING")[0]

    api.post(f"/v1/care-tasks/{task['id']}/done", headers=scheduled["auth"], json={})
    again = api.post(f"/v1/care-tasks/{task['id']}/done", headers=scheduled["auth"], json={})

    assert again.status_code == 409


def test_a_task_cannot_be_skipped_after_being_done(api, admin_sdk, scheduled):
    tick(api)
    task = tasks_of(admin_sdk, scheduled["plant_id"], "PENDING")[0]

    api.post(f"/v1/care-tasks/{task['id']}/done", headers=scheduled["auth"], json={})
    assert (
        api.post(
            f"/v1/care-tasks/{task['id']}/skip", headers=scheduled["auth"], json={}
        ).status_code
        == 409
    )


def test_skipping_records_a_skipped_event(api, admin_sdk, scheduled):
    tick(api)
    task = tasks_of(admin_sdk, scheduled["plant_id"], "PENDING")[0]

    response = api.post(f"/v1/care-tasks/{task['id']}/skip", headers=scheduled["auth"], json={})
    assert response.status_code == 200

    events = (
        admin_sdk.table("care_events").select("event_type").eq("care_task_id", task["id"]).execute()
    ).data
    assert [e["event_type"] for e in events] == ["SKIPPED"]


def test_a_care_event_cannot_be_edited_or_deleted(api, admin_sdk, scheduled):
    """FINAL §13: events are immutable; corrections create new events."""
    from postgrest.exceptions import APIError

    tick(api)
    task = tasks_of(admin_sdk, scheduled["plant_id"], "PENDING")[0]
    api.post(f"/v1/care-tasks/{task['id']}/done", headers=scheduled["auth"], json={})

    event = (
        admin_sdk.table("care_events").select("id").eq("care_task_id", task["id"]).execute()
    ).data[0]

    with pytest.raises(APIError):
        admin_sdk.table("care_events").update({"note": "changed"}).eq("id", event["id"]).execute()
    with pytest.raises(APIError):
        admin_sdk.table("care_events").delete().eq("id", event["id"]).execute()


# --- overdue and A9 -------------------------------------------------------------


def test_a_past_due_task_becomes_overdue(api, admin_sdk, scheduled):
    make_task(admin_sdk, scheduled, due=datetime.now(UTC) - timedelta(days=1))

    tick(api)

    task = tasks_of(admin_sdk, scheduled["plant_id"])[0]
    assert task["status"] == "OVERDUE"
    assert task["overdue_since"] is not None


def test_an_expired_task_becomes_a_missed_event_and_is_cancelled(api, admin_sdk, scheduled):
    """A9. A plant left for a month must not greet its owner with thirty
    outstanding waterings; the history is kept as a MISSED event."""
    make_task(admin_sdk, scheduled, due=datetime.now(UTC) - timedelta(days=30))

    tick(api)

    statuses = {t["status"] for t in tasks_of(admin_sdk, scheduled["plant_id"])}
    assert "CANCELLED" in statuses

    events = (
        admin_sdk.table("care_events")
        .select("event_type")
        .eq("plant_id", scheduled["plant_id"])
        .execute()
    ).data
    assert "MISSED" in {e["event_type"] for e in events}


def test_the_next_occurrence_is_still_scheduled_after_a_miss(api, admin_sdk, scheduled):
    """FINAL §13: "The next recurrence remains scheduled." Missing one does not
    end the plan, which would be the worst possible response to a holiday."""
    make_task(admin_sdk, scheduled, due=datetime.now(UTC) - timedelta(days=30))

    tick(api)  # retires the expired task
    tick(api)  # the following run has a free slot and materialises the next one

    assert len(tasks_of(admin_sdk, scheduled["plant_id"], "PENDING")) == 1


def test_a_missed_event_does_not_block_a_later_correction(api, admin_sdk, scheduled):
    """MISSED is deliberately outside the one-action-per-task index (migration
    0007), so it cannot consume the slot a corrective DONE would need."""
    task = make_task(admin_sdk, scheduled, due=datetime.now(UTC) - timedelta(days=30))
    tick(api)

    admin_sdk.table("care_events").insert(
        {
            "user_id": scheduled["user_id"],
            "plant_id": scheduled["plant_id"],
            "care_task_id": task["id"],
            "event_type": "DONE",
            "event_at": datetime.now(UTC).isoformat(),
        }
    ).execute()

    events = (
        admin_sdk.table("care_events").select("event_type").eq("care_task_id", task["id"]).execute()
    ).data
    assert {e["event_type"] for e in events} == {"MISSED", "DONE"}


# --- reading -------------------------------------------------------------------


def test_todays_list_includes_overdue_work_from_earlier_days(api, admin_sdk, scheduled):
    """Overdue work is what the user still has to do. Filtering it out by date is
    how a task gets quietly forgotten."""
    make_task(admin_sdk, scheduled, due=datetime.now(UTC) - timedelta(days=2), status="OVERDUE")

    listed = api.get("/v1/care-tasks?date=today", headers=scheduled["auth"]).json()["data"]
    assert len(listed) == 1
    assert listed[0]["status"] == "OVERDUE"


def test_a_task_carries_the_plant_name_and_action(api, admin_sdk, scheduled):
    """ "Water the monstera" is a reminder; a bare row is a database record."""
    tick(api)

    listed = api.get("/v1/care-tasks", headers=scheduled["auth"]).json()["data"]
    assert listed[0]["plant_name"] == "צמח מתוזמן"
    assert listed[0]["action_type"] == "WATERING"


def test_another_user_sees_none_of_these_tasks(api, admin_sdk, scheduled, account):
    tick(api)
    _, other_auth = account()

    assert api.get("/v1/care-tasks", headers=other_auth).json()["data"] == []


def test_another_user_cannot_complete_someone_elses_task(api, admin_sdk, scheduled, account):
    tick(api)
    task = tasks_of(admin_sdk, scheduled["plant_id"], "PENDING")[0]
    _, other_auth = account()

    assert (
        api.post(f"/v1/care-tasks/{task['id']}/done", headers=other_auth, json={}).status_code
        == 404
    )


# --- the dashboard --------------------------------------------------------------


def test_the_dashboard_returns_everything_home_needs(api, admin_sdk, scheduled):
    tick(api)

    data = api.get("/v1/dashboard", headers=scheduled["auth"]).json()["data"]

    assert data["counts"]["active_plants"] == 1
    assert {"today_care", "upcoming_care", "overdue_summary", "my_plants", "counts"} <= set(data)


def test_the_dashboard_summarises_overdue_work_per_plant(api, admin_sdk, scheduled):
    """FINAL §13: multiple overdue items are summarised. One line per plant, not
    one row per task."""
    make_task(admin_sdk, scheduled, due=datetime.now(UTC) - timedelta(days=2), status="OVERDUE")

    data = api.get("/v1/dashboard", headers=scheduled["auth"]).json()["data"]

    assert len(data["overdue_summary"]) == 1
    assert data["overdue_summary"][0]["plant_name"] == "צמח מתוזמן"
    assert data["overdue_summary"][0]["days_late"] >= 1


def test_the_dashboard_is_empty_for_a_new_account(api, account):
    _, auth = account()
    data = api.get("/v1/dashboard", headers=auth).json()["data"]

    assert data["counts"] == {
        "today_tasks": 0,
        "attention": 0,
        "active_plants": 0,
        "overdue": 0,
    }


def test_a_miss_does_not_produce_a_missed_event_on_every_tick(api, admin_sdk, scheduled):
    """The loop the anchoring fix exists to prevent.

    Anchoring a miss on its long-past due date put the next occurrence in the
    past too, the sweep retired that one as expired as well, and the scheduler
    wrote a MISSED event on every run — filling the timeline with junk history
    for as long as the cron kept firing.
    """
    make_task(admin_sdk, scheduled, due=datetime.now(UTC) - timedelta(days=30))

    for _ in range(4):
        tick(api)

    missed = [
        e
        for e in (
            admin_sdk.table("care_events")
            .select("event_type")
            .eq("plant_id", scheduled["plant_id"])
            .execute()
        ).data
        if e["event_type"] == "MISSED"
    ]
    assert len(missed) == 1
