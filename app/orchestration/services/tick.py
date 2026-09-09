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
from datetime import datetime, timedelta

from app.common.enums import PlantStatus, SystemEventType
from app.config.logging import get_logger
from app.infrastructure.supabase.client import service_client
from app.notifications import service as notifications
from app.orchestration.services import agent_requests as agent_requests_service
from app.orchestration.services import scheduler
from app.repositories import plants as plants_repo
from app.repositories.base import rows
from supabase import Client

log = get_logger(__name__)


@dataclass(frozen=True)
class TickOutcome:
    """What one run did, for the endpoint's response and the timer's log."""

    materialised: int = 0
    marked_overdue: int = 0
    missed: int = 0
    abandoned: int = 0
    archived_plants: int = 0
    plans_queued: int = 0
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

    # After the reaper, deliberately. `reap_abandoned` fails a request whose
    # worker never came back *without* going through `identification.execute`, so
    # the plant it was identifying is archived here rather than there - on this
    # tick, not the next one.
    archived = _archive_abandoned_plants(admin, now_utc=now_utc)

    # An ACTIVE plant has a care plan, or one is being prepared. Asserted here
    # rather than trusted to each road into ACTIVE: two of those roads have now
    # shipped without queueing a plan (A3 in PR 31, and finished research in
    # PR 33, which releases plants from a background task with no request-scoped
    # executor to submit with). Both failures were invisible - the plant looked
    # active and correct and never reminded anybody of anything.
    plans = _reconcile_plans()

    dispatched = notifications.dispatch_due(admin, now_utc=now_utc)

    outcome = TickOutcome(
        materialised=created,
        marked_overdue=swept.marked_overdue,
        missed=swept.missed,
        abandoned=abandoned,
        archived_plants=archived,
        plans_queued=plans,
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
        archived_plants=outcome.archived_plants,
        plans_queued=outcome.plans_queued,
        emails_sent=outcome.emails_sent,
        emails_failed=outcome.emails_failed,
    )

    return outcome


#: How long a plant may sit unidentified before the sweep gives up on it. Long
#: enough that a slow run, a retried upload or a user who wandered off mid-flow
#: and came back is never caught; short enough that abandoned rows do not
#: accumulate for a week.
_ABANDONED_PLANT_HOURS = 24


def _archive_abandoned_plants(admin: Client, *, now_utc: datetime) -> int:
    """Retire plants whose identification was never going to finish.

    `identification.execute` archives the ones it can see fail. It cannot see
    them all: `reap_abandoned` fails a request whose worker died without ever
    re-entering that function, and a plant whose flow broke before the run was
    even created has no failure to hook. Both leave a row in
    `PENDING_IDENTIFICATION` that nothing will ever advance.

    Skips anything with a successful identification, on exactly the reasoning the
    workflow uses: that plant is waiting on the *user*, the grid lists it, and the
    card offers the button that accepts it.

    Isolated like `_reconcile_plans`, and for the same reason - this is cleanup,
    and it must never cost the tick its materialisation, its overdue sweep or its
    reminders.
    """
    cutoff = (now_utc - timedelta(hours=_ABANDONED_PLANT_HOURS)).isoformat()

    try:
        stale = rows(
            admin.table("plants")
            .select("id, user_id, status")
            .eq("status", PlantStatus.PENDING_IDENTIFICATION.value)
            .lt("created_at", cutoff)
            .execute()
        )
        if not stale:
            return 0

        confirmable = plants_repo.confirmable_plant_ids(admin, [str(p["id"]) for p in stale])
        doomed = [plant for plant in stale if str(plant["id"]) not in confirmable]
        if not doomed:
            return 0

        # Two statements for the whole batch rather than two per plant. The first
        # run of this sweep on DEV had thirty-odd rows to clear, and a tick that
        # spends sixty round trips on cleanup delays the materialisation and the
        # reminders that are the reason it runs at all.
        ids = [str(plant["id"]) for plant in doomed]
        admin.table("plants").update({"status": "ARCHIVED", "archived_at": "now()"}).in_(
            "id", ids
        ).execute()
        admin.table("system_events").insert(
            [
                {
                    "user_id": str(plant["user_id"]),
                    "plant_id": str(plant["id"]),
                    "event_type": SystemEventType.PLANT_ARCHIVED.value,
                    "payload": {
                        "previous_status": PlantStatus.PENDING_IDENTIFICATION.value,
                        "reason": "IDENTIFICATION_ABANDONED",
                    },
                }
                for plant in doomed
            ]
        ).execute()

        log.info("scheduler.plants_archived", count=len(doomed))
        return len(doomed)
    except Exception as exc:
        log.warning("scheduler.plant_archive_failed", error_type=type(exc).__name__)
        return 0


def _reconcile_plans() -> int:
    """Queue a first care plan for any ACTIVE plant that has none.

    Isolated from the rest of the sweep: this one starts model calls, so a
    failure here - a provider outage, a rate limit - must not cost the tick its
    materialisation, its overdue sweep or its reminders. Those are deterministic
    and always worth completing.

    Runs the proposals inline. The tick is already off the event loop and nothing
    is waiting on it, and `reconcile_plans` caps how many it starts per run so a
    backlog drains over several ticks instead of opening twenty-five model calls
    at once.
    """
    from app.agents.care.agent import CareAgent
    from app.infrastructure.ai.gateway import AIGateway
    from app.orchestration.services.agent_requests import InlineExecutor
    from app.orchestration.workflows import care as care_workflow

    try:
        return care_workflow.reconcile_missing_plans(
            executor=InlineExecutor(),
            agent=CareAgent(AIGateway()),
        )
    except Exception as exc:
        log.warning("scheduler.plan_reconcile_failed", error_type=type(exc).__name__)
        return 0
