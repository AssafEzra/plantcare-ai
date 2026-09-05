"""Notifications against DEV.

The duplicate guarantee is a unique index, so it can only be proved here. The
property under test is not "we checked for a duplicate" but **"the provider was
never called a second time"** — the delivery row is reserved before the send, so
a second tick is refused on insert rather than after a message has gone out.

Nothing in this file can send real mail: every test passes a recording provider,
and CI runs without Resend credentials in any case.
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

from app.common.enums import CareRuleActionType
from app.infrastructure.email.provider import EmailMessage, EmailSendError
from app.notifications import service
from tests.integration.conftest import delete_accounts, unique_species_name

pytestmark = pytest.mark.integration

PASSWORD = "Notif-Passw0rd!"


class Recorder:
    """A provider that records instead of sending."""

    name = "recorder"

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[EmailMessage] = []
        self.fail = fail

    def send(self, message: EmailMessage) -> str | None:
        if self.fail:
            raise EmailSendError("scripted failure")
        self.sent.append(message)
        return f"msg-{len(self.sent)}"


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
        email = f"ntf-{uuid.uuid4().hex[:12]}@example.com"
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
def with_a_due_task(admin_sdk, account) -> Iterator[dict]:
    """A user with one task due now, and reminders on."""
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
                "name": "צמח לתזכורת",
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

    rules = [
        admin_sdk.table("care_rules")
        .insert(
            {
                "care_plan_version_id": version["id"],
                "action_type": action.value,
                "interval_days": 7,
                "preferred_time_local": "08:00",
            }
        )
        .execute()
        .data[0]
        for action in (CareRuleActionType.WATERING, CareRuleActionType.FERTILIZING)
    ]

    now = datetime.now(UTC)
    for rule in rules:
        admin_sdk.table("care_tasks").insert(
            {
                "user_id": user_id,
                "plant_id": plant["id"],
                "care_rule_id": rule["id"],
                "due_at_utc": (now - timedelta(hours=1)).isoformat(),
                "status": "PENDING",
            }
        ).execute()

    # 00:00 so the send window is always open, whatever time the suite runs.
    admin_sdk.table("notification_preferences").update(
        {"email_enabled": True, "daily_digest": True, "preferred_time_local": "00:00"}
    ).eq("user_id", user_id).execute()

    yield {"user_id": user_id, "auth": auth, "plant_id": plant["id"]}

    with contextlib.suppress(Exception):
        admin_sdk.table("notification_deliveries").delete().eq("user_id", user_id).execute()
        admin_sdk.table("plants").delete().eq("id", plant["id"]).execute()


def deliveries(admin_sdk, user_id: str) -> list[dict]:
    return (
        admin_sdk.table("notification_deliveries").select("*").eq("user_id", user_id).execute()
    ).data


def dispatch(admin_sdk, user_id: str, provider, when: datetime | None = None):
    return service.dispatch_due(
        admin_sdk,
        now_utc=when or datetime.now(UTC),
        provider=provider,
        user_id=user_id,
    )


# --- the duplicate guarantee ----------------------------------------------------


def test_one_digest_is_sent_for_a_days_work(admin_sdk, with_a_due_task):
    provider = Recorder()
    result = dispatch(admin_sdk, with_a_due_task["user_id"], provider)

    assert result.sent == 1
    assert len(provider.sent) == 1
    # Both tasks in one message, which is what a digest is for.
    assert "השקיה" in provider.sent[0].text_body
    assert "דישון" in provider.sent[0].text_body


def test_dispatching_twice_sends_once_and_never_calls_the_provider_again(
    admin_sdk, with_a_due_task
):
    """The property that matters. Not "we noticed a duplicate" but "the provider
    was not called" — the row is reserved before the send, so the second attempt
    dies on the unique index with no message in flight."""
    provider = Recorder()

    dispatch(admin_sdk, with_a_due_task["user_id"], provider)
    second = dispatch(admin_sdk, with_a_due_task["user_id"], provider)

    assert len(provider.sent) == 1
    assert second.sent == 0
    assert second.skipped == 1
    assert len(deliveries(admin_sdk, with_a_due_task["user_id"])) == 1


def test_the_dedupe_key_is_unique_at_the_database_level(admin_sdk, with_a_due_task):
    """Tested through the service role: if even that cannot insert a duplicate,
    no dispatch bug can."""
    dispatch(admin_sdk, with_a_due_task["user_id"], Recorder())
    existing = deliveries(admin_sdk, with_a_due_task["user_id"])[0]

    with pytest.raises(APIError):
        admin_sdk.table("notification_deliveries").insert(
            {
                "user_id": with_a_due_task["user_id"],
                "channel": "EMAIL",
                "status": "QUEUED",
                "dedupe_key": existing["dedupe_key"],
            }
        ).execute()


def test_a_successful_send_is_recorded_with_its_provider_id(admin_sdk, with_a_due_task):
    dispatch(admin_sdk, with_a_due_task["user_id"], Recorder())

    row = deliveries(admin_sdk, with_a_due_task["user_id"])[0]
    assert row["status"] == "SENT"
    assert row["sent_at"] is not None
    assert row["provider_message_id"]


# --- failure --------------------------------------------------------------------


def test_a_provider_failure_is_recorded_and_loses_no_task(admin_sdk, with_a_due_task):
    """FINAL §30. The task is still outstanding and still on the dashboard; the
    user simply has not been emailed about it."""
    result = dispatch(admin_sdk, with_a_due_task["user_id"], Recorder(fail=True))

    assert result.failed == 1
    row = deliveries(admin_sdk, with_a_due_task["user_id"])[0]
    assert row["status"] == "FAILED"
    assert "scripted failure" in row["error_message"]

    open_tasks = (
        admin_sdk.table("care_tasks")
        .select("status")
        .eq("plant_id", with_a_due_task["plant_id"])
        .execute()
    ).data
    assert all(t["status"] == "PENDING" for t in open_tasks)


def test_a_failed_send_is_not_retried_the_same_day(admin_sdk, with_a_due_task):
    """The reserved row still holds the key.

    Retrying every fifteen minutes against a provider that is refusing would be
    a good way to get an account suspended; the digest returns tomorrow.
    """
    dispatch(admin_sdk, with_a_due_task["user_id"], Recorder(fail=True))
    provider = Recorder()
    dispatch(admin_sdk, with_a_due_task["user_id"], provider)

    assert provider.sent == []


# --- preferences ----------------------------------------------------------------


def test_nothing_is_sent_to_a_user_who_turned_email_off(admin_sdk, with_a_due_task):
    admin_sdk.table("notification_preferences").update({"email_enabled": False}).eq(
        "user_id", with_a_due_task["user_id"]
    ).execute()

    provider = Recorder()
    dispatch(admin_sdk, with_a_due_task["user_id"], provider)

    assert provider.sent == []
    assert deliveries(admin_sdk, with_a_due_task["user_id"]) == []


def test_daily_digest_false_sends_one_email_per_task(admin_sdk, with_a_due_task):
    """The audit's correction, asserted.

    The plan's first draft chose digest-or-single by task count, which made the
    user's setting inert. It is a preference, and it is honoured.
    """
    admin_sdk.table("notification_preferences").update({"daily_digest": False}).eq(
        "user_id", with_a_due_task["user_id"]
    ).execute()

    provider = Recorder()
    result = dispatch(admin_sdk, with_a_due_task["user_id"], provider)

    assert result.sent == 2
    assert len(provider.sent) == 2
    assert len(deliveries(admin_sdk, with_a_due_task["user_id"])) == 2


def test_per_task_sends_are_also_deduplicated(admin_sdk, with_a_due_task):
    admin_sdk.table("notification_preferences").update({"daily_digest": False}).eq(
        "user_id", with_a_due_task["user_id"]
    ).execute()

    provider = Recorder()
    dispatch(admin_sdk, with_a_due_task["user_id"], provider)
    dispatch(admin_sdk, with_a_due_task["user_id"], provider)

    assert len(provider.sent) == 2


def test_nothing_is_sent_before_the_users_preferred_hour(admin_sdk, with_a_due_task):
    """A10 end to end: the preference governs when we may write."""
    admin_sdk.table("notification_preferences").update({"preferred_time_local": "23:59"}).eq(
        "user_id", with_a_due_task["user_id"]
    ).execute()

    provider = Recorder()
    # Early morning in Jerusalem, hours before the preferred time.
    early = datetime.now(UTC).replace(hour=1, minute=0)
    dispatch(admin_sdk, with_a_due_task["user_id"], provider, when=early)

    assert provider.sent == []


def test_a_user_with_nothing_due_is_not_emailed(admin_sdk, account):
    user_id, _ = account()
    provider = Recorder()

    dispatch(admin_sdk, user_id, provider)

    assert provider.sent == []


# --- the routes -----------------------------------------------------------------


def test_a_user_reads_and_updates_their_preferences(api, with_a_due_task):
    read = api.get("/v1/notification-preferences", headers=with_a_due_task["auth"])
    assert read.status_code == 200
    assert read.json()["data"]["email_enabled"] is True

    updated = api.put(
        "/v1/notification-preferences",
        headers=with_a_due_task["auth"],
        json={"daily_digest": False, "preferred_time_local": "07:30"},
    )
    assert updated.status_code == 200
    body = updated.json()["data"]
    assert body["daily_digest"] is False
    assert body["preferred_time_local"].startswith("07:30")


def test_the_preferences_endpoint_refuses_an_unknown_field(api, with_a_due_task):
    response = api.put(
        "/v1/notification-preferences",
        headers=with_a_due_task["auth"],
        json={"send_sms": True},
    )
    assert response.status_code == 422


def test_a_user_sees_their_own_delivery_log(api, admin_sdk, with_a_due_task):
    """FINAL §14 logs every send; showing the user that log is how "we did email
    you" stops being something they take on trust."""
    dispatch(admin_sdk, with_a_due_task["user_id"], Recorder())

    listed = api.get("/v1/notification-deliveries", headers=with_a_due_task["auth"])
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1


def test_another_user_sees_none_of_those_deliveries(api, admin_sdk, with_a_due_task, account):
    dispatch(admin_sdk, with_a_due_task["user_id"], Recorder())
    _, other_auth = account()

    assert api.get("/v1/notification-deliveries", headers=other_auth).json()["data"] == []
