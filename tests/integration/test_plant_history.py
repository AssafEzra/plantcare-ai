"""The plant dashboard view model and its merged history (FINAL §17, §19).

The timeline draws on five tables and the merge is only meaningful against a real
one: the assertion that matters is that entries from different sources interleave
by time rather than appearing as five lists stacked together.

The other property worth a database is that the timeline is **append-only**. A
correction adds an entry; nothing rewrites one.
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
from tests.integration.conftest import unique_species_name

pytestmark = pytest.mark.integration

PASSWORD = "Hist-Passw0rd!"


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
        email = f"hst-{uuid.uuid4().hex[:12]}@example.com"
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
def storied(admin_sdk, account) -> Iterator[dict]:
    """A plant with history in four of the five source tables."""
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
                "name": "צמח עם היסטוריה",
            }
        )
        .execute()
        .data[0]
    )

    now = datetime.now(UTC)

    admin_sdk.table("system_events").insert(
        {
            "user_id": user_id,
            "plant_id": plant["id"],
            "event_type": "PLANT_CREATED",
            "created_at": (now - timedelta(days=10)).isoformat(),
        }
    ).execute()

    admin_sdk.table("identifications").insert(
        {
            "user_id": user_id,
            "plant_id": plant["id"],
            "status": "SUCCESS",
            "method": "USER_CONFIRMED",
            "primary_species_id": species["id"],
            "confidence_score": 0.9,
            "confidence_level": "HIGH",
            "created_at": (now - timedelta(days=9)).isoformat(),
        }
    ).execute()

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
                "created_at": (now - timedelta(days=8)).isoformat(),
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
            }
        )
        .execute()
        .data[0]
    )

    task = (
        admin_sdk.table("care_tasks")
        .insert(
            {
                "user_id": user_id,
                "plant_id": plant["id"],
                "care_rule_id": rule["id"],
                "due_at_utc": (now - timedelta(days=3)).isoformat(),
                "status": "DONE",
                "completed_at": (now - timedelta(days=3)).isoformat(),
            }
        )
        .execute()
        .data[0]
    )
    admin_sdk.table("care_events").insert(
        {
            "user_id": user_id,
            "plant_id": plant["id"],
            "care_task_id": task["id"],
            "event_type": "DONE",
            "event_at": (now - timedelta(days=3)).isoformat(),
        }
    ).execute()

    # A health assessment and its images must be written in **one transaction**.
    # The 1-4 image constraint (migration 0010) is DEFERRABLE INITIALLY DEFERRED,
    # so it runs at commit — and PostgREST gives every call its own transaction,
    # which means two REST calls can never satisfy it. That is a real constraint
    # on PR 21's Health Agent, not a quirk of this fixture: the assessment and its
    # images have to go through one RPC.
    _insert_assessment_with_image(
        user_id=user_id, plant_id=plant["id"], created_at=now - timedelta(days=1)
    )

    yield {
        "user_id": user_id,
        "auth": auth,
        "plant_id": plant["id"],
        "species_id": species["id"],
        "version_id": version["id"],
    }

    with contextlib.suppress(Exception):
        admin_sdk.table("plants").delete().eq("id", plant["id"]).execute()


def _insert_assessment_with_image(*, user_id: str, plant_id: str, created_at: datetime) -> None:
    """One transaction, because the deferred constraint is checked at commit."""
    import psycopg

    from tests.integration.conftest import _dsn

    dsn = _dsn()
    if not dsn:  # pragma: no cover - the module-level fixture already skipped
        pytest.skip("no database password available")

    with psycopg.connect(dsn, connect_timeout=20) as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into public.plant_images
                (plant_id, user_id, storage_path_original, mime_type, size_bytes, context_type)
            values (%s, %s, %s, 'image/jpeg', 1024, 'health')
            returning id
            """,
            (plant_id, user_id, f"{user_id}/{plant_id}/health/x.jpg"),
        )
        image_id = cur.fetchone()[0]

        cur.execute(
            """
            insert into public.health_assessments
                (user_id, plant_id, overall_status, trend, created_at)
            values (%s, %s, 'HEALTHY', 'STABLE', %s)
            returning id
            """,
            (user_id, plant_id, created_at),
        )
        assessment_id = cur.fetchone()[0]

        cur.execute(
            """
            insert into public.health_assessment_images
                (health_assessment_id, plant_image_id, display_order)
            values (%s, %s, 1)
            """,
            (assessment_id, image_id),
        )
        conn.commit()


def history(api: TestClient, storied: dict, **params) -> list[dict]:
    response = api.get(
        f"/v1/plants/{storied['plant_id']}/history", headers=storied["auth"], params=params
    )
    return response.json()["data"]


# --- the merge ------------------------------------------------------------------


def test_the_timeline_draws_on_every_source(api, storied):
    """Five tables, one list. Merging on read is why a care event cannot exist
    without a timeline entry, or the other way round."""
    sources = {entry["source"] for entry in history(api, storied)}

    assert sources == {
        "system_events",
        "identifications",
        "care_plan_versions",
        "care_events",
        "health_assessments",
    }


def test_entries_interleave_by_time_rather_than_by_source(api, storied):
    """The assertion that the merge is real.

    Five lists concatenated would also contain every entry; only a sort proves
    they are one timeline.
    """
    entries = history(api, storied)
    times = [entry["occurred_at"] for entry in entries]

    assert times == sorted(times, reverse=True)
    # Newest is the health check, oldest the creation, with other sources between.
    assert entries[0]["source"] == "health_assessments"
    assert entries[-1]["source"] == "system_events"


def test_each_entry_reads_as_a_sentence(api, storied):
    """A timeline of enum values is a log, not a history."""
    summaries = [entry["summary"] for entry in history(api, storied)]

    assert any("הזיהוי אושר" in s for s in summaries)
    assert any("בוצע טיפול" in s for s in summaries)
    assert any("תוכנית טיפול ראשונה" in s for s in summaries)


def test_a_care_entry_names_the_action_it_was_for(api, storied):
    """ "Care done" is half a sentence; the action comes from the rule, two hops
    away, because the task deliberately does not duplicate it."""
    care = next(e for e in history(api, storied) if e["source"] == "care_events")
    assert "השקיה" in care["summary"]


# --- pagination -----------------------------------------------------------------


def test_the_page_size_is_respected(api, storied):
    assert len(history(api, storied, limit=2)) == 2


def test_paging_uses_a_timestamp_cursor(api, storied):
    """An append-only timeline grows at the head, so an offset-based page two
    drifts as entries arrive and the user sees something twice or not at all."""
    first = history(api, storied, limit=2)
    second = history(api, storied, limit=2, before=first[-1]["occurred_at"])

    assert second
    first_times = {e["occurred_at"] for e in first}
    assert not (first_times & {e["occurred_at"] for e in second})


# --- user-logged events ----------------------------------------------------------


def test_a_user_can_log_something_they_did_out_of_band(api, storied):
    """Repotting on a whim is still part of the plant's history, and the plan
    should not have to have asked for it first."""
    response = api.post(
        f"/v1/plants/{storied['plant_id']}/history",
        headers=storied["auth"],
        json={"event_type": "REPOTTED", "note": "עציץ גדול יותר"},
    )
    assert response.status_code == 201

    entries = history(api, storied)
    assert any(e["kind"] == "REPOTTED" for e in entries)


def test_a_custom_note_shows_the_users_own_words(api, storied):
    api.post(
        f"/v1/plants/{storied['plant_id']}/history",
        headers=storied["auth"],
        json={"event_type": "CUSTOM_NOTE", "note": "העלים החדשים בהירים יותר"},
    )

    summaries = [e["summary"] for e in history(api, storied)]
    assert "העלים החדשים בהירים יותר" in summaries


def test_an_empty_custom_note_is_refused(api, storied):
    """An empty note is an empty row in the timeline."""
    response = api.post(
        f"/v1/plants/{storied['plant_id']}/history",
        headers=storied["auth"],
        json={"event_type": "CUSTOM_NOTE", "note": "   "},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("forged", ["PLANT_CREATED", "ENVIRONMENT_CHANGED", "PLANT_ARCHIVED"])
def test_a_user_cannot_forge_a_system_event(api, storied, forged: str):
    """Those are written by the actions that cause them. Letting a client choose
    would make the timeline a place where anything can be claimed."""
    response = api.post(
        f"/v1/plants/{storied['plant_id']}/history",
        headers=storied["auth"],
        json={"event_type": forged},
    )
    assert response.status_code == 422


def test_the_timeline_is_append_only(api, admin_sdk, storied):
    """FINAL §19: corrections create corrective events rather than rewriting."""
    from postgrest.exceptions import APIError

    event = (
        admin_sdk.table("system_events").select("id").eq("plant_id", storied["plant_id"]).execute()
    ).data[0]

    with pytest.raises(APIError):
        admin_sdk.table("system_events").update({"event_type": "MOVED"}).eq(
            "id", event["id"]
        ).execute()
    with pytest.raises(APIError):
        admin_sdk.table("system_events").delete().eq("id", event["id"]).execute()


# --- the dashboard view model ----------------------------------------------------


def test_the_dashboard_returns_every_section_final_17_lists(api, storied):
    data = api.get(f"/v1/plants/{storied['plant_id']}/dashboard", headers=storied["auth"]).json()[
        "data"
    ]

    assert data["name"] == "צמח עם היסטוריה"
    assert data["species"]["scientific_name"]
    assert data["health"]["current_status"]
    assert data["care_plan"] is not None
    assert "gallery" in data
    assert "environment" in data
    assert "upcoming_tasks" in data


def test_upcoming_tasks_carry_the_plant_name_and_action(api, admin_sdk, storied):
    """The dashboard shipped without decorating them, rendering "**** · my plant".

    A task row on its own is two foreign keys and a timestamp; the name and the
    action are what make it a reminder.
    """
    from datetime import UTC, datetime, timedelta

    rule = (
        admin_sdk.table("care_rules")
        .select("id")
        .eq("care_plan_version_id", storied["version_id"])
        .execute()
    ).data[0]
    admin_sdk.table("care_tasks").insert(
        {
            "user_id": storied["user_id"],
            "plant_id": storied["plant_id"],
            "care_rule_id": rule["id"],
            "due_at_utc": (datetime.now(UTC) + timedelta(hours=6)).isoformat(),
            "status": "PENDING",
        }
    ).execute()

    tasks = api.get(f"/v1/plants/{storied['plant_id']}/dashboard", headers=storied["auth"]).json()[
        "data"
    ]["upcoming_tasks"]

    assert tasks
    assert tasks[0]["plant_name"] == "צמח עם היסטוריה"
    assert tasks[0]["action_type"] == "WATERING"


def test_the_dashboard_carries_the_latest_health_and_its_trend(api, storied):
    health = api.get(f"/v1/plants/{storied['plant_id']}/dashboard", headers=storied["auth"]).json()[
        "data"
    ]["health"]

    assert health["trend"] == "STABLE"
    assert health["latest_assessment_id"]
    assert len(health["history"]) == 1


def test_an_archived_plant_keeps_its_history(api, admin_sdk, storied):
    """FINAL §21: archive rather than delete, and the history survives."""
    api.post(f"/v1/plants/{storied['plant_id']}/archive", headers=storied["auth"])

    data = api.get(f"/v1/plants/{storied['plant_id']}/dashboard", headers=storied["auth"]).json()[
        "data"
    ]
    assert data["status"] == "ARCHIVED"
    assert len(history(api, storied)) >= 4


def test_another_user_cannot_read_the_dashboard_or_the_history(api, storied, account):
    _, other_auth = account()

    assert (
        api.get(f"/v1/plants/{storied['plant_id']}/dashboard", headers=other_auth).status_code
        == 404
    )
    assert (
        api.get(f"/v1/plants/{storied['plant_id']}/history", headers=other_auth).status_code == 404
    )
