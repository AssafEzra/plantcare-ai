"""Today, Due and Evening, by email and push, against an in-memory database.

Monday 12 October 2026 in Jerusalem (summer time, UTC+3). The user's tasks:

* Monstera watering, due today;
* Fern watering, due yesterday, still open;
* Ficus feeding, due four days ago, still open;
* a watering due on Wednesday, not yet anything to say.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.infrastructure.email.provider import EmailMessage
from app.infrastructure.push.provider import NullPushProvider, PushResult, PushTarget
from tests.unit.fake_db import FakeDB

TZ = ZoneInfo("Asia/Jerusalem")
USER = "00000000-0000-0000-0000-000000000001"


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ).astimezone(UTC)


def task(task_id: str, rule: str, plant: str, *, day: int, status: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "user_id": USER,
        "plant_id": plant,
        "care_rule_id": rule,
        "due_at_utc": local(day, 8).isoformat(),
        "status": status,
        "overdue_since": None,
        "completed_at": None,
        "created_at": local(1, 8).isoformat(),
    }


def world(
    *, email: bool = True, devices: int = 1, due_days: int = 1, evening: bool = False
) -> FakeDB:
    return FakeDB(
        {
            "profiles": [{"id": USER, "timezone": "Asia/Jerusalem", "display_name": "דנה"}],
            "plants": [
                {"id": "p-monstera", "name": "מונסטרה"},
                {"id": "p-fern", "name": "שרך"},
                {"id": "p-ficus", "name": "פיקוס"},
            ],
            "care_rules": [
                {"id": "r-water", "action_type": "WATERING"},
                {"id": "r-water-2", "action_type": "WATERING"},
                {"id": "r-feed", "action_type": "FERTILIZING"},
            ],
            "care_tasks": [
                task("t-today", "r-water", "p-monstera", day=12, status="PENDING"),
                task("t-yesterday", "r-water-2", "p-fern", day=11, status="OVERDUE"),
                task("t-old", "r-feed", "p-ficus", day=8, status="OVERDUE"),
                task("t-wednesday", "r-water", "p-monstera", day=14, status="PENDING"),
                task("t-done", "r-water", "p-monstera", day=12, status="DONE"),
            ],
            "notification_preferences": [
                {
                    "user_id": USER,
                    "email_enabled": email,
                    "preferred_time_local": "07:30:00",
                    "due_reminder_days": due_days,
                    "evening_enabled": evening,
                    "evening_time_local": "19:00:00",
                }
            ],
            "push_subscriptions": [
                {
                    "id": f"device-{i}",
                    "user_id": USER,
                    "endpoint": f"https://push.example/{i}",
                    "p256dh": "k",
                    "auth": "a",
                    "enabled": True,
                }
                for i in range(devices)
            ],
            "notification_deliveries": [],
        },
        unique={"notification_deliveries": "dedupe_key"},
    )


class Mail:
    name = "mail"
    suppresses = False

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> str | None:
        self.sent.append(message)
        return "msg-1"


class Push:
    name = "push"
    suppresses = False

    def __init__(self, results: dict[str, PushResult] | None = None) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.results = results or {}

    def send(self, target: PushTarget, payload: dict[str, Any]) -> PushResult:
        self.sent.append((target.endpoint, payload))
        return self.results.get(target.endpoint, PushResult.OK)


@pytest.fixture
def service(env, monkeypatch):
    from app.notifications import service

    monkeypatch.setattr(service, "_email_of", lambda _c, _u: "dana@example.com")
    return service


def run(service, db: FakeDB, at: datetime, mail: Mail, push: Any):
    return service.dispatch_due(db, now_utc=at, provider=mail, push_provider=push)


# --- the morning --------------------------------------------------------------------


def test_nothing_goes_out_before_half_past_seven(service):
    db, mail, push = world(), Mail(), Push()

    run(service, db, local(12, 7, 15), mail, push)

    assert mail.sent == [] and push.sent == []


def test_the_morning_email_has_today_and_yesterdays_late_task(service):
    db, mail, push = world(), Mail(), Push()

    result = run(service, db, local(12, 7, 45), mail, push)

    assert result.sent == 1
    body = mail.sent[0].text_body
    assert "מונסטרה" in body and "שרך" in body
    # Four days late is past the one day the user asked to be reminded for.
    assert "פיקוס" not in body
    # The task due on Wednesday and the one already done are not mentioned.
    assert body.count("השקיה") == 2


def test_push_sends_today_and_due_as_two_notifications(service):
    db, mail, push = world(), Mail(), Push()

    result = run(service, db, local(12, 7, 45), mail, push)

    assert result.push_sent == 2
    titles = [payload["title"] for _, payload in push.sent]
    assert titles[0].startswith("🟢") and "היום" in titles[0]
    assert titles[1].startswith("🔴") and "באיחור" in titles[1]
    assert push.sent[0][1]["body"] == "מונסטרה (השקיה)"
    assert push.sent[1][1]["kind"] == "late"
    assert all(payload["url"] == "/tasks" for _, payload in push.sent)


def test_every_enabled_device_gets_each_push(service):
    db, mail, push = world(devices=2), Mail(), Push()

    result = run(service, db, local(12, 7, 45), mail, push)

    assert result.push_sent == 2  # two notifications ...
    assert len(push.sent) == 4  # ... each to both devices


def test_a_second_run_the_same_day_sends_nothing_again(service):
    db, mail, push = world(), Mail(), Push()

    run(service, db, local(12, 7, 45), mail, push)
    again = run(service, db, local(12, 9, 0), mail, push)

    assert len(mail.sent) == 1 and len(push.sent) == 2
    assert (again.sent, again.push_sent) == (0, 0)


def test_a_late_run_still_sends_the_mornings_notifications(service):
    db, mail, push = world(), Mail(), Push()

    run(service, db, local(12, 13, 0), mail, push)

    assert len(mail.sent) == 1 and len(push.sent) == 2


def test_with_due_days_at_zero_only_today_is_sent(service):
    db, mail, push = world(due_days=0), Mail(), Push()

    run(service, db, local(12, 7, 45), mail, push)

    assert "שרך" not in mail.sent[0].text_body
    assert [p["kind"] for _, p in push.sent] == ["today"]


def test_with_due_days_at_three_a_task_four_days_late_is_still_left_out(service):
    db, mail, push = world(due_days=3), Mail(), Push()

    run(service, db, local(12, 7, 45), mail, push)

    assert "פיקוס" not in mail.sent[0].text_body


# --- channels -----------------------------------------------------------------------


def test_email_off_still_pushes(service):
    db, mail, push = world(email=False), Mail(), Push()

    run(service, db, local(12, 7, 45), mail, push)

    assert mail.sent == [] and len(push.sent) == 2


def test_no_devices_still_emails(service):
    db, mail, push = world(devices=0), Mail(), Push()

    run(service, db, local(12, 7, 45), mail, push)

    assert len(mail.sent) == 1 and push.sent == []


def test_a_paused_device_gets_nothing(service):
    db, mail, push = world(email=False), Mail(), Push()
    db.store["push_subscriptions"][0]["enabled"] = False

    run(service, db, local(12, 7, 45), mail, push)

    assert push.sent == []


def test_a_device_its_push_service_has_forgotten_is_removed(service):
    db, mail = world(devices=2), Mail()
    push = Push({"https://push.example/0": PushResult.GONE})

    result = run(service, db, local(12, 7, 45), mail, push)

    assert [d["id"] for d in db.store["push_subscriptions"]] == ["device-1"]
    assert result.push_sent == 2  # the other device still received both


def test_without_vapid_keys_pushes_are_recorded_as_skipped(service):
    db, mail = world(email=False), Mail()

    result = run(service, db, local(12, 7, 45), mail, NullPushProvider())

    assert result.push_skipped == 2 and result.push_sent == 0
    statuses = {d["status"] for d in db.store["notification_deliveries"]}
    assert statuses == {"SKIPPED"}


# --- the evening --------------------------------------------------------------------


def test_the_evening_push_is_only_todays_open_work(service):
    db, mail, push = world(evening=True), Mail(), Push()

    run(service, db, local(12, 7, 45), mail, push)
    push.sent.clear()
    mail.sent.clear()
    run(service, db, local(12, 19, 5), mail, push)

    assert mail.sent == []  # push only
    assert len(push.sent) == 1
    title = push.sent[0][1]["title"]
    assert title.startswith("🌙")
    assert push.sent[0][1]["body"] == "מונסטרה (השקיה)"


def test_no_evening_push_when_it_is_off(service):
    db, mail, push = world(evening=False), Mail(), Push()

    run(service, db, local(12, 7, 45), mail, push)
    push.sent.clear()
    run(service, db, local(12, 19, 5), mail, push)

    assert push.sent == []


def test_no_evening_push_once_todays_task_is_done(service):
    db, mail, push = world(evening=True), Mail(), Push()
    run(service, db, local(12, 7, 45), mail, push)
    db.store["care_tasks"][0]["status"] = "DONE"
    push.sent.clear()

    run(service, db, local(12, 19, 5), mail, push)

    assert push.sent == []


def test_evening_time_is_read_from_the_preferences(service):
    from app.notifications import selection

    assert selection.parse_time("19:00:00", selection.EVENING_DEFAULT) == time(19, 0)
