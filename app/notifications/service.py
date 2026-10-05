"""Notification dispatch (FINAL §14, §30).

    "All sends are logged to prevent duplicate delivery."

That sentence is implemented as an ordering, not as a check. The delivery row is
inserted **first**, and its `dedupe_key` carries a unique index; only if that
insert succeeds does anything reach the provider. A second attempt fails on the
insert and never calls Resend at all.

The obvious alternative — look for an existing row, then send, then record it —
has a window between the read and the send in which a second tick can do exactly
the same thing, and the user gets two emails. Reserving first closes it, and
means the worst case of a crash mid-send is a delivery row stuck in QUEUED rather
than a duplicate message.

A10: two "preferred times", and what each governs
-------------------------------------------------
A care rule has a `preferred_time_local` and so does a notification preference,
and the specification never says how they relate. Resolved:

* the **rule's** time is when the task is *due* — "water at 08:00";
* the **preference's** time is when we are allowed to *write* — "tell me at
  07:00".

They are different questions. A user who waters in the evening still wants their
reminder in the morning, and a user with six plants wants one message at a time
they choose, not six at whatever hours their rules happen to specify.

Today, Due and Evening (migration 0022)
---------------------------------------
At the morning time (07:30 for now) two things may go out: **Today** - tasks due
today - and **Due** - open tasks one to `due_reminder_days` days late. Email
carries both as one message with two sections; push sends them as two
notifications. In the evening, if the user turned it on, one push for today's
tasks still open. Per-task emails are gone. What goes into each is decided in
`selection.py`, which has no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.common.enums import NotificationChannel, NotificationDeliveryStatus
from app.config.logging import get_logger
from app.domain.rules import recurrence
from app.infrastructure.email.provider import (
    EmailMessage,
    EmailProvider,
    EmailSendError,
    NullProvider,
)
from app.infrastructure.push.provider import (
    PushProvider,
    PushResult,
    PushTarget,
    build_push_provider,
)
from app.notifications import selection
from app.orchestration.services import scheduler
from app.repositories.base import Row, first_row, rows
from supabase import Client

log = get_logger(__name__)


def build_provider() -> EmailProvider:
    """The configured provider, or the null one.

    Resend is optional (SETUP §5). An environment without credentials runs with
    `NullProvider`, which is what keeps CI from sending mail and what stops a
    half-configured deployment failing on every tick.
    """
    from app.config.settings import get_settings

    settings = get_settings()
    if not settings.email_enabled:
        return NullProvider()

    from app.infrastructure.email.resend_provider import ResendProvider

    return ResendProvider()


@dataclass(frozen=True)
class DispatchResult:
    """What one dispatch run did. `sent/skipped/failed` count emails."""

    sent: int = 0
    skipped: int = 0
    failed: int = 0
    push_sent: int = 0
    push_skipped: int = 0
    push_failed: int = 0

    def merged(self, other: DispatchResult) -> DispatchResult:
        return DispatchResult(
            sent=self.sent + other.sent,
            skipped=self.skipped + other.skipped,
            failed=self.failed + other.failed,
            push_sent=self.push_sent + other.push_sent,
            push_skipped=self.push_skipped + other.push_skipped,
            push_failed=self.push_failed + other.push_failed,
        )


# --- dedupe keys ----------------------------------------------------------------


def digest_key(user_id: str, local_day: date) -> str:
    """One morning email per user per **local** day.

    The date component is the user's own, so moving timezone cannot produce two
    emails on one of their days. The format predates migration 0022 and is kept,
    so a user already emailed on the day of the change is not emailed again.
    """
    return f"digest:{user_id}:{local_day.isoformat()}"


def push_key(kind: str, user_id: str, local_day: date) -> str:
    """One push of each kind per user per local day, across all their devices."""
    return f"push-{kind}:{user_id}:{local_day.isoformat()}"


# --- dispatch -------------------------------------------------------------------

PREFERENCE_COLUMNS = (
    "user_id, email_enabled, preferred_time_local, due_reminder_days, "
    "evening_enabled, evening_time_local"
)


def dispatch_due(
    client: Client,
    *,
    now_utc: datetime,
    provider: EmailProvider | None = None,
    push_provider: PushProvider | None = None,
    user_id: str | None = None,
) -> DispatchResult:
    """Send whatever is due to every user whose time has arrived.

    Called from the scheduler tick, after materialisation and the overdue sweep,
    so the tasks it reports on are the ones that run has just settled. Nothing is
    remembered between runs: each one asks, per user, "has my time come today, is
    there anything to say, and has it not been said yet?" A missed run is caught
    up by the next one the same day; a missed day is not sent afterwards.
    """
    sender = provider or build_provider()
    pusher = push_provider or build_push_provider()
    result = DispatchResult()

    for preferences in _recipients(client, user_id=user_id):
        result = result.merged(_dispatch_for_user(client, preferences, now_utc, sender, pusher))

    return result


def _recipients(client: Client, *, user_id: str | None) -> list[Row]:
    """Users with email on, or with at least one push device switched on."""
    query = client.table("notification_preferences").select(PREFERENCE_COLUMNS)
    if user_id:
        query = query.eq("user_id", user_id)

    devices = client.table("push_subscriptions").select("user_id").eq("enabled", True)
    if user_id:
        devices = devices.eq("user_id", user_id)
    with_push = {str(row["user_id"]) for row in rows(devices.execute())}

    return [
        row
        for row in rows(query.execute())
        if row.get("email_enabled") or str(row["user_id"]) in with_push
    ]


def _dispatch_for_user(
    client: Client,
    preferences: Row,
    now_utc: datetime,
    provider: EmailProvider,
    pusher: PushProvider,
) -> DispatchResult:
    user_id = str(preferences["user_id"])
    timezone_name = scheduler.timezone_of(client, user_id)
    local_now = now_utc.astimezone(recurrence.zone(timezone_name))
    today = local_now.date()

    morning_at = selection.parse_time(
        preferences.get("preferred_time_local"), selection.MORNING_DEFAULT
    )
    evening_at = selection.parse_time(
        preferences.get("evening_time_local"), selection.EVENING_DEFAULT
    )
    morning = selection.window_open(local_now, morning_at)
    evening = bool(preferences.get("evening_enabled")) and selection.window_open(
        local_now, evening_at
    )
    if not (morning or evening):
        return DispatchResult()

    tasks = _decorate(client, scheduler.tasks_for_user(client, user_id=UUID(user_id)))
    due_today = selection.today_tasks(tasks, today=today, timezone_name=timezone_name)
    late = selection.due_tasks(
        tasks,
        today=today,
        timezone_name=timezone_name,
        days=int(preferences.get("due_reminder_days", 1) or 0),
    )
    if not (due_today or late):
        return DispatchResult()

    devices = _devices(client, user_id)
    result = DispatchResult()

    if morning:
        if preferences.get("email_enabled"):
            result = result.merged(
                _email_morning(
                    client,
                    provider,
                    user_id=user_id,
                    today=today,
                    now_utc=now_utc,
                    due_today=due_today,
                    late=late,
                )
            )
        if devices and due_today:
            result = result.merged(
                _push(
                    client,
                    pusher,
                    user_id=user_id,
                    devices=devices,
                    now_utc=now_utc,
                    key=push_key("today", user_id, today),
                    message=selection.today_push(due_today, day=today),
                )
            )
        if devices and late:
            result = result.merged(
                _push(
                    client,
                    pusher,
                    user_id=user_id,
                    devices=devices,
                    now_utc=now_utc,
                    key=push_key("due", user_id, today),
                    message=selection.due_push(late, day=today),
                )
            )

    if evening and devices and due_today:
        result = result.merged(
            _push(
                client,
                pusher,
                user_id=user_id,
                devices=devices,
                now_utc=now_utc,
                key=push_key("evening", user_id, today),
                message=selection.evening_push(due_today, day=today),
            )
        )

    return result


def _devices(client: Client, user_id: str) -> list[Row]:
    return rows(
        client.table("push_subscriptions")
        .select("id, endpoint, p256dh, auth")
        .eq("user_id", user_id)
        .eq("enabled", True)
        .execute()
    )


def _decorate(client: Client, tasks: list[Row]) -> list[Row]:
    if not tasks:
        return []

    plants = {
        plant["id"]: plant
        for plant in rows(
            client.table("plants")
            .select("id, name")
            .in_("id", list({t["plant_id"] for t in tasks}))
            .execute()
        )
    }
    care_rules = {
        rule["id"]: rule
        for rule in rows(
            client.table("care_rules")
            .select("id, action_type")
            .in_("id", list({t["care_rule_id"] for t in tasks}))
            .execute()
        )
    }
    return [
        {
            **task,
            "plant_name": plants.get(task["plant_id"], {}).get("name"),
            "action_type": care_rules.get(task["care_rule_id"], {}).get("action_type"),
        }
        for task in tasks
    ]


def _email_of(client: Client, user_id: str) -> str | None:
    """The address, from `auth.users` via the service role.

    `profiles` deliberately does not duplicate the email — one copy, in the table
    that owns it. This is read with the service client because `auth.users` is
    not exposed through PostgREST to anyone else.
    """
    from app.infrastructure.supabase.client import service_client

    try:
        user = service_client().auth.admin.get_user_by_id(user_id)
        return getattr(user.user, "email", None)
    except Exception as exc:
        log.warning("email.address_lookup_failed", error_type=type(exc).__name__)
        return None


# --- email ----------------------------------------------------------------------


def _email_morning(
    client: Client,
    provider: EmailProvider,
    *,
    user_id: str,
    today: date,
    now_utc: datetime,
    due_today: list[Row],
    late: list[Row],
) -> DispatchResult:
    email = _email_of(client, user_id)
    if not email:
        # No address to send to. Not an error worth retrying every run; the
        # in-app list still shows the work.
        return DispatchResult(skipped=1)

    delivery = _reserve(
        client,
        user_id=user_id,
        dedupe_key=digest_key(user_id, today),
        channel=NotificationChannel.EMAIL,
    )
    if delivery is None:
        return DispatchResult(skipped=1)

    profile = first_row(client.table("profiles").select("display_name").eq("id", user_id).execute())
    message = render_digest(
        email=email,
        display_name=(profile or {}).get("display_name"),
        due_today=due_today,
        late=late,
    )
    return _deliver(client, provider, delivery_id=delivery["id"], message=message, now_utc=now_utc)


# --- push -----------------------------------------------------------------------


def _push(
    client: Client,
    pusher: PushProvider,
    *,
    user_id: str,
    devices: list[Row],
    now_utc: datetime,
    key: str,
    message: selection.PushMessage,
) -> DispatchResult:
    """One notification to every enabled device, recorded as one delivery.

    Reserved first, like email, so a second run the same day is refused by the
    unique key before anything is pushed. A device its push service reports as
    gone is deleted: the user blocked notifications or removed the app, and an
    address that will never answer is not worth asking again.
    """
    delivery = _reserve(client, user_id=user_id, dedupe_key=key, channel=NotificationChannel.PUSH)
    if delivery is None:
        return DispatchResult(push_skipped=1)

    payload = message.payload()
    delivered = 0
    for device in devices:
        outcome = pusher.send(
            PushTarget(endpoint=device["endpoint"], p256dh=device["p256dh"], auth=device["auth"]),
            payload,
        )
        if outcome is PushResult.GONE:
            client.table("push_subscriptions").delete().eq("id", device["id"]).execute()
            log.info("push.subscription_gone", subscription_id=device["id"])
        elif outcome is PushResult.OK:
            delivered += 1
            client.table("push_subscriptions").update({"last_sent_at": now_utc.isoformat()}).eq(
                "id", device["id"]
            ).execute()

    if pusher.suppresses:
        status, counted = NotificationDeliveryStatus.SKIPPED, DispatchResult(push_skipped=1)
        changes: dict[str, Any] = {"status": status.value}
    elif delivered:
        status, counted = NotificationDeliveryStatus.SENT, DispatchResult(push_sent=1)
        changes = {"status": status.value, "sent_at": now_utc.isoformat()}
    else:
        status, counted = NotificationDeliveryStatus.FAILED, DispatchResult(push_failed=1)
        changes = {"status": status.value, "error_message": "no device accepted the push"}

    client.table("notification_deliveries").update(changes).eq("id", delivery["id"]).execute()
    return counted


def send_confirmation(pusher: PushProvider, device: Row) -> PushResult:
    """The one push sent when a device is registered, so the user sees it work.

    Not recorded as a delivery: it is a reply to the user's own tap, not a
    reminder, and there is nothing to deduplicate.
    """
    return pusher.send(
        PushTarget(endpoint=device["endpoint"], p256dh=device["p256dh"], auth=device["auth"]),
        selection.confirmation_push().payload(),
    )


# --- the delivery log -----------------------------------------------------------


def _reserve(
    client: Client, *, user_id: str, dedupe_key: str, channel: NotificationChannel
) -> Row | None:
    """Claim the right to send, or return None because someone already has.

    This insert is the duplicate guarantee. It happens **before** the provider is
    called, so a second tick is refused by the unique index without a message
    being sent — rather than after, which leaves a window two ticks can both pass
    through.
    """
    try:
        return first_row(
            client.table("notification_deliveries")
            .insert(
                {
                    "user_id": user_id,
                    "care_task_id": None,
                    "channel": channel.value,
                    "status": NotificationDeliveryStatus.QUEUED.value,
                    "dedupe_key": dedupe_key,
                }
            )
            .execute()
        )
    except Exception as exc:
        # Almost certainly the unique index, which is the index doing its job.
        log.info("notification.duplicate_suppressed", error_type=type(exc).__name__)
        return None


def _deliver(
    client: Client,
    provider: EmailProvider,
    *,
    delivery_id: str,
    message: EmailMessage,
    now_utc: datetime,
) -> DispatchResult:
    try:
        provider_id = provider.send(message)
    except EmailSendError as exc:
        # FINAL §30: a failed send is recorded, not swallowed. The task itself is
        # untouched — it is still outstanding, still on the dashboard, and the
        # user has simply not been emailed about it.
        client.table("notification_deliveries").update(
            {
                "status": NotificationDeliveryStatus.FAILED.value,
                "error_message": str(exc)[:500],
            }
        ).eq("id", delivery_id).execute()
        log.warning("notification.send_failed", delivery_id=delivery_id)
        return DispatchResult(failed=1)

    if provider.suppresses:
        # Nothing was delivered, so nothing is recorded as delivered. Writing
        # SENT here - which is what this did - left the delivery log asserting
        # four days of successful digests in an environment that had never been
        # given a from-address, with `provider_message_id` NULL on every one of
        # them. The log is read by the admin page and is the only evidence a user
        # was told anything, so it has to distinguish "we sent this" from "we
        # chose not to".
        #
        # The reservation row stays. Its dedupe key is what makes the suppression
        # visible rather than silent, and re-sending on a later tick would be a
        # different promise than the one §14 makes.
        client.table("notification_deliveries").update(
            {"status": NotificationDeliveryStatus.SKIPPED.value}
        ).eq("id", delivery_id).execute()
        log.info("notification.suppressed", delivery_id=delivery_id, provider=provider.name)
        return DispatchResult(skipped=1)

    client.table("notification_deliveries").update(
        {
            "status": NotificationDeliveryStatus.SENT.value,
            "sent_at": now_utc.isoformat(),
            "provider_message_id": provider_id,
        }
    ).eq("id", delivery_id).execute()
    return DispatchResult(sent=1)


# --- rendering ------------------------------------------------------------------

# The app's own tokens (frontend/src/styles/tokens.css): today in green, late in
# red. Inline, because mail clients ignore stylesheets.
GREEN, GREEN_BG = "#3a7550", "#e8f3eb"
RED, RED_BG = "#8f1410", "#fbe7e5"


def _line(task: Row) -> str:
    action = selection.action_label(task.get("action_type"))
    plant = task.get("plant_name") or "הצמח שלך"
    return f"{action} — {plant}"


def _count(n: int, one: str, many: str) -> str:
    return one if n == 1 else f"{n} {many}"


def _html_section(title: str, tasks: list[Row], *, colour: str, background: str) -> str:
    items = "".join(f"<li>{_line(task)}</li>" for task in tasks)
    return (
        f'<div style="border-inline-start:4px solid {colour};background:{background};'
        f'padding:8px 12px;margin:12px 0;border-radius:6px">'
        f'<p style="margin:0 0 4px;color:{colour};font-weight:bold">{title}</p>'
        f'<ul style="margin:0;padding-inline-start:20px">{items}</ul></div>'
    )


def render_digest(
    *, email: str, display_name: str | None, due_today: list[Row], late: list[Row]
) -> EmailMessage:
    """The morning email: what is due today, and what is late (FINAL §14).

    Deliberately short. An email is a prompt to open the app, not a place to do
    the work: there is no Done button here, because acting on a task has to
    record an immutable event against an authenticated user.
    """
    greeting = f"שלום {display_name}," if display_name else "שלום,"
    today_title = "היום: " + _count(len(due_today), "משימת טיפול אחת", "משימות טיפול")
    late_title = "באיחור: " + _count(len(late), "משימה אחת", "משימות")

    parts = []
    if due_today:
        parts.append(_count(len(due_today), "משימת טיפול אחת היום", "משימות טיפול היום"))
    if late:
        parts.append(_count(len(late), "משימה אחת באיחור", "משימות באיחור"))
    subject = "PlantCare — " + ", ".join(parts)

    lines = [greeting, ""]
    if due_today:
        lines += [today_title, *(f"• {_line(t)}" for t in due_today), ""]
    if late:
        lines += [late_title, *(f"• {_line(t)}" for t in late), ""]
    lines += ["אפשר לסמן אותן כבוצעו באפליקציה.", "", "PlantCare AI"]

    html = f'<div dir="rtl" style="font-family:sans-serif"><p>{greeting}</p>'
    if due_today:
        html += _html_section(today_title, due_today, colour=GREEN, background=GREEN_BG)
    if late:
        html += _html_section(late_title, late, colour=RED, background=RED_BG)
    html += "<p>אפשר לסמן אותן כבוצעו באפליקציה.</p><p>PlantCare AI</p></div>"

    return EmailMessage(to=email, subject=subject, text_body="\n".join(lines), html_body=html)


# --- reads ----------------------------------------------------------------------


def preferences_for(client: Client, user_id: str) -> Row:
    """The user's preferences, which the signup trigger guarantees exist (A27)."""
    found = first_row(
        client.table("notification_preferences")
        .select(
            "user_id, email_enabled, preferred_time_local, daily_digest, due_reminder_days, "
            "evening_enabled, evening_time_local, updated_at"
        )
        .eq("user_id", user_id)
        .execute()
    )
    if found is not None:
        return found

    # Defensive: an account created before the trigger existed would otherwise
    # have no row and no way to get one.
    return first_row(
        client.table("notification_preferences").insert({"user_id": user_id}).execute()
    ) or {
        "user_id": user_id,
        "email_enabled": True,
        "daily_digest": True,
        "preferred_time_local": "07:30",
        "due_reminder_days": 1,
        "evening_enabled": False,
        "evening_time_local": "19:00",
    }


def update_preferences(client: Client, user_id: str, changes: dict[str, Any]) -> Row:
    updated = first_row(
        client.table("notification_preferences").update(changes).eq("user_id", user_id).execute()
    )
    return updated or preferences_for(client, user_id)


def deliveries_for(client: Client, user_id: str, limit: int = 50) -> list[Row]:
    return rows(
        client.table("notification_deliveries")
        .select(
            "id, care_task_id, channel, status, dedupe_key, scheduled_at, "
            "sent_at, error_message, created_at"
        )
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )


def now() -> datetime:  # pragma: no cover - a seam for tests that need the clock
    return datetime.now(UTC)
