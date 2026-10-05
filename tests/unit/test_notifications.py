"""Notification dispatch, without a database or a network.

The two things worth defending here are the send window (A10) and the rendering.
The duplicate guarantee is a unique index and is therefore proved against a real
database in `tests/integration/test_notifications.py` — asserting it against a
fake would only assert that the fake behaves the way I assumed.

Nothing in this file can send mail: every test drives `NullProvider` or a
recording stub, which is the same default CI runs under.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.infrastructure.email.provider import EmailMessage, EmailSendError, NullProvider
from app.notifications import selection, service

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
    """A10: the preference governs when we may *write*, not when a task is due."""
    early = datetime(2026, 9, 5, 6, 30, tzinfo=JERUSALEM)
    assert not selection.window_open(early, time(7, 30))


def test_the_window_opens_at_the_preferred_hour():
    assert selection.window_open(datetime(2026, 9, 5, 7, 30, tzinfo=JERUSALEM), time(7, 30))


def test_the_window_stays_open_for_the_rest_of_the_day():
    """A window, not an instant: a run at 08:00 still sends the 07:30 reminder.
    The dedupe key is what stops the open window sending twice."""
    later = datetime(2026, 9, 5, 21, 0, tzinfo=JERUSALEM)
    assert selection.window_open(later, time(7, 30))


def test_a_missing_time_falls_back_to_half_past_seven():
    assert selection.parse_time(None, selection.MORNING_DEFAULT) == time(7, 30)
    assert selection.parse_time("19:00:00", selection.EVENING_DEFAULT) == time(19, 0)


# --- dedupe keys ----------------------------------------------------------------


def test_the_digest_key_is_keyed_on_the_users_local_day():
    """The schema comment's requirement: changing timezone must not yield two
    emails on one of the user's days. The format predates migration 0022."""
    key = service.digest_key("user-1", date(2026, 9, 5))
    assert key == "digest:user-1:2026-09-05"


def test_two_users_on_the_same_day_get_different_keys():
    day = date(2026, 9, 5)
    assert service.digest_key("a", day) != service.digest_key("b", day)


def test_each_kind_of_push_has_its_own_daily_key():
    day = date(2026, 9, 5)
    keys = {service.push_key(kind, "u", day) for kind in ("today", "due", "evening")}
    assert len(keys) == 3
    assert service.push_key("today", "u", day) == "push-today:u:2026-09-05"


# --- rendering ------------------------------------------------------------------


def test_the_email_names_every_task_in_its_section():
    message = service.render_digest(
        email="a@example.com",
        display_name="דנה",
        due_today=[task("WATERING"), task("FERTILIZING")],
        late=[task("PRUNING", status="OVERDUE")],
    )

    assert "דנה" in message.text_body
    assert "היום" in message.text_body and "באיחור" in message.text_body
    assert "השקיה" in message.text_body and "גיזום" in message.text_body
    assert message.html_body and 'dir="rtl"' in message.html_body


def test_today_is_green_and_late_is_red_in_the_email():
    message = service.render_digest(
        email="a@example.com",
        display_name=None,
        due_today=[task()],
        late=[task("PRUNING", status="OVERDUE")],
    )
    html = message.html_body or ""
    assert service.GREEN in html and service.RED in html
    assert html.index(service.GREEN) < html.index(service.RED)


def test_a_section_with_nothing_in_it_is_left_out():
    message = service.render_digest(
        email="a@example.com", display_name=None, due_today=[task()], late=[]
    )
    assert "באיחור" not in message.text_body
    assert service.RED not in (message.html_body or "")


def test_one_task_is_not_described_in_the_plural():
    message = service.render_digest(
        email="a@example.com", display_name=None, due_today=[task()], late=[]
    )
    assert "משימת טיפול אחת" in message.text_body


def test_the_email_carries_no_action_buttons():
    """Acting on a task writes an immutable event against an authenticated user,
    which an email link cannot do. The message is a prompt to open the app."""
    message = service.render_digest(
        email="a@example.com", display_name=None, due_today=[task()], late=[]
    )
    assert "http" not in message.text_body


def test_rendering_survives_an_unknown_action_type():
    """A new action added to the enum must not produce a blank line in an email
    before the label dictionary catches up."""
    message = service.render_digest(
        email="a@example.com", display_name=None, due_today=[task("SOMETHING_NEW")], late=[]
    )
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


class _UpdateRecorder:
    """Captures the update a delivery row is given, without a database."""

    def __init__(self) -> None:
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


def test_a_suppressed_send_is_recorded_as_skipped_not_sent():
    """The null provider delivers nothing, so nothing may claim it did.

    Recording SENT here made the delivery log assert successful digests in every
    environment without a from-address — the admin page and the user's own
    history both read this table, and `provider_message_id` was NULL on all of
    them.
    """
    recorder = _UpdateRecorder()
    result = service._deliver(
        recorder,
        NullProvider(),
        delivery_id="d1",
        message=EmailMessage(to="a@example.com", subject="s", text_body="b"),
        now_utc=datetime.now(UTC),
    )

    assert result.skipped == 1
    assert result.sent == 0
    assert recorder.updates[0]["status"] == "SKIPPED"
    # No send happened, so there is no time at which one did.
    assert "sent_at" not in recorder.updates[0]


def test_a_real_send_is_still_recorded_as_sent():
    """The guard keys off `suppresses`, not off a None return — Resend answers
    None when its response carries no id, and that is a delivery."""

    class Quiet:
        name = "quiet"
        suppresses = False

        def send(self, message: EmailMessage) -> str | None:
            return None

    recorder = _UpdateRecorder()
    result = service._deliver(
        recorder,
        Quiet(),
        delivery_id="d1",
        message=EmailMessage(to="a@example.com", subject="s", text_body="b"),
        now_utc=datetime.now(UTC),
    )

    assert result.sent == 1
    assert recorder.updates[0]["status"] == "SENT"
    assert recorder.updates[0]["sent_at"] is not None
