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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

from app.common.enums import NotificationChannel, NotificationDeliveryStatus
from app.config.logging import get_logger
from app.domain.rules import recurrence
from app.infrastructure.email.provider import (
    EmailMessage,
    EmailProvider,
    EmailSendError,
    NullProvider,
)
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
    sent: int = 0
    skipped: int = 0
    failed: int = 0

    def merged(self, other: DispatchResult) -> DispatchResult:
        return DispatchResult(
            sent=self.sent + other.sent,
            skipped=self.skipped + other.skipped,
            failed=self.failed + other.failed,
        )


# --- dedupe keys ----------------------------------------------------------------


def digest_key(user_id: str, local_day: date) -> str:
    """One digest per user per **local** day.

    The date component is the user's own, so moving timezone cannot produce two
    digests on one of their days — which is the failure the schema comment calls
    out and the reason the key is not built from a UTC date.
    """
    return f"digest:{user_id}:{local_day.isoformat()}"


def task_key(task_id: str) -> str:
    """One reminder per task, ever.

    Not per day: a task that stays overdue for a week should be mentioned in the
    digest, not emailed again every morning. FINAL §14 lists missed-reminder
    emails as **Future**, and this key is what keeps that promise.
    """
    return f"task:{task_id}:reminder"


# --- dispatch -------------------------------------------------------------------


def dispatch_due(
    client: Client,
    *,
    now_utc: datetime,
    provider: EmailProvider | None = None,
    user_id: str | None = None,
) -> DispatchResult:
    """Send reminders to every user whose send window has arrived.

    Called from the scheduler tick, after materialisation and the overdue sweep,
    so the tasks it reports on are the ones that run has just settled.
    """
    sender = provider or build_provider()
    result = DispatchResult()

    for preferences in _recipients(client, user_id=user_id):
        result = result.merged(_dispatch_for_user(client, preferences, now_utc, sender))

    return result


def _recipients(client: Client, *, user_id: str | None) -> list[Row]:
    query = client.table("notification_preferences").select(
        "user_id, email_enabled, preferred_time_local, daily_digest"
    )
    if user_id:
        query = query.eq("user_id", user_id)
    # Disabled is a user's decision and is respected here rather than by
    # discarding the message later; nothing is built for someone who opted out.
    return [row for row in rows(query.execute()) if row.get("email_enabled")]


def _dispatch_for_user(
    client: Client, preferences: Row, now_utc: datetime, provider: EmailProvider
) -> DispatchResult:
    user_id = preferences["user_id"]
    timezone_name = scheduler.timezone_of(client, user_id)
    local_now = now_utc.astimezone(recurrence.zone(timezone_name))

    if not _within_send_window(preferences, local_now):
        return DispatchResult()

    tasks = _outstanding(client, user_id=user_id, now_utc=now_utc, timezone_name=timezone_name)
    if not tasks:
        return DispatchResult()

    profile = first_row(client.table("profiles").select("display_name").eq("id", user_id).execute())
    email = _email_of(client, user_id)
    if not email:
        # No address to send to. Not an error worth retrying every fifteen
        # minutes; the in-app list still shows the work.
        return DispatchResult(skipped=1)

    if preferences.get("daily_digest", True):
        return _send_digest(
            client,
            provider,
            user_id=user_id,
            email=email,
            display_name=(profile or {}).get("display_name"),
            tasks=tasks,
            local_day=local_now.date(),
            now_utc=now_utc,
        )

    # A10 and the audit's correction: `daily_digest` is a preference the user
    # set, not a hint to be overridden by task count. The first draft of the plan
    # chose by how many tasks there were, which made the setting inert.
    result = DispatchResult()
    for task in tasks:
        result = result.merged(
            _send_single(client, provider, user_id=user_id, email=email, task=task, now_utc=now_utc)
        )
    return result


def _within_send_window(preferences: Row, local_now: datetime) -> bool:
    """Has the user's preferred hour arrived today?

    A window rather than an instant: the tick runs every fifteen minutes and can
    be late, and a reminder that requires the clock to land exactly on 08:00
    would silently not arrive on the day a deploy overlapped it. Once past the
    hour, the dedupe key is what stops it sending twice.
    """
    raw = str(preferences.get("preferred_time_local") or "08:00")
    try:
        preferred = time.fromisoformat(raw if len(raw) > 5 else f"{raw}:00")
    except ValueError:  # pragma: no cover - a CHECK constrains the column
        preferred = time(8, 0)

    return local_now.timetz().replace(tzinfo=None) >= preferred


def _outstanding(
    client: Client, *, user_id: str, now_utc: datetime, timezone_name: str
) -> list[Row]:
    """What the user is being reminded about.

    The same query the dashboard uses, so an email cannot disagree with the
    screen it is telling someone to go and look at.
    """
    from uuid import UUID

    today = recurrence.local_date(now_utc, timezone_name)
    _, day_end = recurrence.day_bounds_utc(today, timezone_name)

    open_tasks = scheduler.tasks_for_user(client, user_id=UUID(user_id))
    due_now = [
        task
        for task in open_tasks
        if (parsed := scheduler.parse_timestamp(task["due_at_utc"])) and parsed < day_end
    ]
    return _decorate(client, due_now)


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


# --- the two shapes of message ---------------------------------------------------


def _send_digest(
    client: Client,
    provider: EmailProvider,
    *,
    user_id: str,
    email: str,
    display_name: str | None,
    tasks: list[Row],
    local_day: date,
    now_utc: datetime,
) -> DispatchResult:
    key = digest_key(user_id, local_day)
    delivery = _reserve(client, user_id=user_id, dedupe_key=key, care_task_id=None)
    if delivery is None:
        return DispatchResult(skipped=1)

    message = render_digest(email=email, display_name=display_name, tasks=tasks)
    return _deliver(client, provider, delivery_id=delivery["id"], message=message, now_utc=now_utc)


def _send_single(
    client: Client,
    provider: EmailProvider,
    *,
    user_id: str,
    email: str,
    task: Row,
    now_utc: datetime,
) -> DispatchResult:
    key = task_key(str(task["id"]))
    delivery = _reserve(client, user_id=user_id, dedupe_key=key, care_task_id=str(task["id"]))
    if delivery is None:
        return DispatchResult(skipped=1)

    message = render_single(email=email, task=task)
    return _deliver(client, provider, delivery_id=delivery["id"], message=message, now_utc=now_utc)


def _reserve(
    client: Client, *, user_id: str, dedupe_key: str, care_task_id: str | None
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
                    "care_task_id": care_task_id,
                    "channel": NotificationChannel.EMAIL.value,
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

    client.table("notification_deliveries").update(
        {
            "status": NotificationDeliveryStatus.SENT.value,
            "sent_at": now_utc.isoformat(),
            "provider_message_id": provider_id,
        }
    ).eq("id", delivery_id).execute()
    return DispatchResult(sent=1)


# --- rendering ------------------------------------------------------------------

ACTION_LABELS: dict[str, str] = {
    "WATERING": "השקיה",
    "FERTILIZING": "דישון",
    "REPOTTING": "החלפת עציץ",
    "PRUNING": "גיזום",
    "MISTING": "ריסוס",
    "ROTATING": "סיבוב",
    "INSPECTION": "בדיקה",
}


def _line(task: Row) -> str:
    action = ACTION_LABELS.get(str(task.get("action_type")), str(task.get("action_type") or ""))
    plant = task.get("plant_name") or "הצמח שלך"
    late = " (באיחור)" if task.get("status") == "OVERDUE" else ""
    return f"{action} — {plant}{late}"


def render_digest(*, email: str, display_name: str | None, tasks: list[Row]) -> EmailMessage:
    """One message for the day's work (FINAL §14).

    Deliberately short. An email is a prompt to open the app, not a place to do
    the work: there is no Done button here, because acting on a task has to
    record an immutable event against an authenticated user.
    """
    greeting = f"שלום {display_name}," if display_name else "שלום,"
    overdue = [t for t in tasks if t.get("status") == "OVERDUE"]

    heading = f"{len(tasks)} משימות טיפול היום" if len(tasks) != 1 else "משימת טיפול אחת היום"
    lines = [greeting, "", heading, ""]
    lines.extend(f"• {_line(task)}" for task in tasks)
    if overdue:
        lines.extend(["", f"{len(overdue)} מהן ממתינות כבר מזמן."])
    lines.extend(["", "אפשר לסמן אותן כבוצעו באפליקציה.", "", "PlantCare AI"])

    text = "\n".join(lines)
    items = "".join(f"<li>{_line(task)}</li>" for task in tasks)
    html = (
        f'<div dir="rtl" style="font-family:sans-serif">'
        f"<p>{greeting}</p><p><strong>{heading}</strong></p><ul>{items}</ul>"
        f"<p>אפשר לסמן אותן כבוצעו באפליקציה.</p><p>PlantCare AI</p></div>"
    )

    return EmailMessage(to=email, subject=f"PlantCare — {heading}", text_body=text, html_body=html)


def render_single(*, email: str, task: Row) -> EmailMessage:
    line = _line(task)
    text = "\n".join(["שלום,", "", f"תזכורת: {line}.", "", "PlantCare AI"])
    html = (
        f'<div dir="rtl" style="font-family:sans-serif">'
        f"<p>שלום,</p><p>תזכורת: <strong>{line}</strong>.</p><p>PlantCare AI</p></div>"
    )
    return EmailMessage(to=email, subject=f"PlantCare — {line}", text_body=text, html_body=html)


# --- reads ----------------------------------------------------------------------


def preferences_for(client: Client, user_id: str) -> Row:
    """The user's preferences, which the signup trigger guarantees exist (A27)."""
    found = first_row(
        client.table("notification_preferences")
        .select("user_id, email_enabled, preferred_time_local, daily_digest, updated_at")
        .eq("user_id", user_id)
        .execute()
    )
    if found is not None:
        return found

    # Defensive: an account created before the trigger existed would otherwise
    # have no row and no way to get one.
    return first_row(
        client.table("notification_preferences").insert({"user_id": user_id}).execute()
    ) or {"user_id": user_id, "email_enabled": True, "daily_digest": True}


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
