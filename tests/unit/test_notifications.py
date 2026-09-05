"""Notification dispatch, without a database or a network.

The two things worth defending here are the send window (A10) and the rendering.
The duplicate guarantee is a unique index and is therefore proved against a real
database in `tests/integration/test_notifications.py` — asserting it against a
fake would only assert that the fake behaves the way I assumed.

Nothing in this file can send mail: every test drives `NullProvider` or a
recording stub, which is the same default CI runs under.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.infrastructure.email.provider import EmailMessage, EmailSendError, NullProvider
from app.notifications import service

JERUSALEM = ZoneInfo("Asia/Jerusalem")


def task(action: str = "WATERING", *, status: str = "PENDING", plant: str = "המונסטרה"):
    return {
        "id": f"task-{action}",
        "plant_id": "p1",
        "care_rule_id": "r1",
        "due_at_utc": "2026-09-05T05:00:00+00:00",
        "status": status,
        "plant_name": plant,
        "action_type": action,
    }


# --- the send window (A10) ------------------------------------------------------


def test_nothing_is_sent_before_the_users_preferred_hour():
    """A10: the preference governs when we may *write*, not when a task is due.

    A user asking to be told at 08:00 must not be emailed at 06:00 because a rule
    happened to fall due then.
    """
    early = datetime(2026, 9, 5, 6, 30, tzinfo=JERUSALEM)
    assert not service._within_send_window({"preferred_time_local": "08:00"}, early)


def test_the_window_opens_at_the_preferred_hour():
    at_time = datetime(2026, 9, 5, 8, 0, tzinfo=JERUSALEM)
    assert service._within_send_window({"preferred_time_local": "08:00"}, at_time)


def test_the_window_stays_open_for_the_rest_of_the_day():
    """A window, not an instant.

    The tick runs every fifteen minutes and can be late; a reminder that required
    the clock to land exactly on 08:00 would silently not arrive on the day a
    deploy overlapped it. The dedupe key is what stops the open window sending
    twice.
    """
    later = datetime(2026, 9, 5, 21, 0, tzinfo=JERUSALEM)
    assert service._within_send_window({"preferred_time_local": "08:00"}, later)


def test_a_missing_preference_falls_back_to_eight():
    assert service._within_send_window({}, datetime(2026, 9, 5, 9, 0, tzinfo=JERUSALEM))
    assert not service._within_send_window({}, datetime(2026, 9, 5, 7, 0, tzinfo=JERUSALEM))


# --- dedupe keys ----------------------------------------------------------------


def test_the_digest_key_is_keyed_on_the_users_local_day():
    """The schema comment's requirement: changing timezone must not yield two
    digests on one of the user's days."""
    key = service.digest_key("user-1", date(2026, 9, 5))
    assert key == "digest:user-1:2026-09-05"


def test_two_users_on_the_same_day_get_different_keys():
    day = date(2026, 9, 5)
    assert service.digest_key("a", day) != service.digest_key("b", day)


def test_a_task_reminder_is_keyed_once_ever_not_once_a_day():
    """FINAL §14 lists missed-reminder emails as Future.

    A task overdue for a week should appear in the digest, not be emailed every
    morning — so the key carries no date at all.
    """
    key = service.task_key("task-1")
    assert key == "task:task-1:reminder"
    assert "2026" not in key


# --- rendering ------------------------------------------------------------------


def test_the_digest_names_every_task():
    message = service.render_digest(
        email="a@example.com",
        display_name="דנה",
        tasks=[task("WATERING"), task("FERTILIZING")],
    )

    assert "דנה" in message.text_body
    assert "השקיה" in message.text_body
    assert "דישון" in message.text_body
    assert message.html_body and 'dir="rtl"' in message.html_body


def test_one_task_is_not_described_in_the_plural():
    message = service.render_digest(email="a@example.com", display_name=None, tasks=[task()])
    assert "משימת טיפול אחת" in message.text_body


def test_overdue_work_is_called_out_in_the_digest():
    message = service.render_digest(
        email="a@example.com",
        display_name=None,
        tasks=[task("WATERING", status="OVERDUE")],
    )
    assert "באיחור" in message.text_body


def test_the_email_carries_no_action_buttons():
    """Acting on a task writes an immutable event against an authenticated user,
    which an email link cannot do. The message is a prompt to open the app."""
    message = service.render_digest(email="a@example.com", display_name=None, tasks=[task()])
    assert "http" not in message.text_body


def test_a_single_reminder_names_the_plant_and_the_action():
    message = service.render_single(email="a@example.com", task=task("PRUNING"))
    assert "גיזום" in message.subject
    assert "המונסטרה" in message.text_body


def test_rendering_survives_an_unknown_action_type():
    """A new action added to the enum must not produce a blank line in an email
    before the label dictionary catches up."""
    message = service.render_single(email="a@example.com", task=task("SOMETHING_NEW"))
    assert "SOMETHING_NEW" in message.text_body


# --- the provider abstraction ---------------------------------------------------


def test_the_null_provider_records_instead_of_sending():
    """The CI default. A test suite that could send mail would eventually send
    mail to somebody real."""
    provider = NullProvider()
    provider.send(EmailMessage(to="a@example.com", subject="s", text_body="b"))

    assert len(provider.sent) == 1
    assert provider.name == "null"


def test_an_unconfigured_resend_provider_fails_where_it_is_built(env):
    """Not on the first user who happens to have reminders switched on."""
    from app.infrastructure.email.resend_provider import ResendProvider

    with pytest.raises(EmailSendError):
        ResendProvider(api_key=None, from_email=None)


def test_the_service_falls_back_to_the_null_provider_without_credentials(env):
    assert isinstance(service.build_provider(), NullProvider)


def test_a_send_failure_is_reported_not_raised():
    """FINAL §30: a failed send is recorded. The task is untouched — still
    outstanding, still on the dashboard, the user simply was not emailed."""

    class Failing:
        name = "failing"

        def send(self, message: EmailMessage) -> str | None:
            raise EmailSendError("provider is down")

    class Recorder:
        def __init__(self):
            self.updates: list[dict] = []

        def table(self, _name):
            return self

        def update(self, changes):
            self.updates.append(changes)
            return self

        def eq(self, *_args):
            return self

        def execute(self):
            return type("R", (), {"data": []})()

    recorder = Recorder()
    result = service._deliver(
        recorder,
        Failing(),
        delivery_id="d1",
        message=EmailMessage(to="a@example.com", subject="s", text_body="b"),
        now_utc=datetime.now(UTC),
    )

    assert result.failed == 1
    assert recorder.updates[0]["status"] == "FAILED"
    assert "provider is down" in recorder.updates[0]["error_message"]
