"""The periodic sweep, as a function rather than only as an endpoint.

`POST /v1/internal/tick` was the only thing that materialised tasks, swept
overdue ones, reaped abandoned agent requests and sent reminders — and nothing
called it. PR 24 parked the Railway cron that was meant to, so in practice a user
who approved a care plan got a plan with no tasks, forever, and the overdue and
notification machinery never ran at all.

Extracted here so there is exactly one implementation and two callers: the
endpoint a real cron will hit in production, and the in-process timer in
`app/api/main.py` that keeps a single-service deployment honest until then.

Idempotent by construction. Materialisation skips a rule that already has a
pending task and the database refuses a second one regardless; reminders are
deduplicated on `notification_deliveries.dedupe_key`. Two overlapping runs — two
uvicorn workers, or a cron firing while the timer does — produce the same state
as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.config.logging import get_logger
from app.infrastructure.supabase.client import service_client
from app.notifications import service as notifications
from app.orchestration.services import agent_requests as agent_requests_service
from app.orchestration.services import scheduler

log = get_logger(__name__)


@dataclass(frozen=True)
class TickOutcome:
    """What one run did, for the endpoint's response and the timer's log."""

    materialised: int = 0
    marked_overdue: int = 0
    missed: int = 0
    abandoned: int = 0
    emails_sent: int = 0
    emails_skipped: int = 0
    emails_failed: int = 0


def run_tick(*, now_utc: datetime) -> TickOutcome:
    """One sweep across every user, under the service role.

    The ordering is load-bearing and unchanged from the endpoint it came from:
    abandoned requests are reaped *before* the reminders so a request whose worker
    was restarted reads as failed on this tick rather than as still running for
    one more cycle, and the reminders go out *after* the sweep so they describe
    the state this run settled rather than the one it started from.
    """
    admin = service_client()

    created = scheduler.materialise(admin, now_utc=now_utc)
    swept = scheduler.sweep_overdue(admin, now_utc=now_utc)
    abandoned = agent_requests_service.reap_abandoned(now_utc)
    dispatched = notifications.dispatch_due(admin, now_utc=now_utc)

    outcome = TickOutcome(
        materialised=created,
        marked_overdue=swept.marked_overdue,
        missed=swept.missed,
        abandoned=abandoned,
        emails_sent=dispatched.sent,
        emails_skipped=dispatched.skipped,
        emails_failed=dispatched.failed,
    )

    log.info(
        "scheduler.tick",
        materialised=outcome.materialised,
        marked_overdue=outcome.marked_overdue,
        missed=outcome.missed,
        abandoned=outcome.abandoned,
        emails_sent=outcome.emails_sent,
        emails_failed=outcome.emails_failed,
    )

    return outcome
