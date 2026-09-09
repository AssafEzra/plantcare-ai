"""Approving a plan has to produce tasks (PR 32).

Reported from real use: *"after creating a care plan it doesnt any schedule
tasks"*. Confirmed against DEV: the account had three active plants, two active
plan versions and eight active care rules — and zero rows in `care_tasks`.

`scheduler.materialise` was called from exactly one place, `POST
/v1/internal/tick`, and nothing called that: PR 24 parked the cron. So the entire
scheduler — materialisation, the overdue sweep, MISSED events, reminders — was
built, tested and unreachable.

Two halves, and these tests cover both:

* approving materialises immediately, so the first task exists by the time the
  user looks at the page;
* the tick is a function the API's own timer can call, not only an endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest


class FakeTable:
    def __init__(self, store: dict[str, list[dict]], name: str):
        self.store = store
        self.name = name
        self._filters: dict[str, Any] = {}

    def select(self, *_a: Any, **_k: Any) -> FakeTable:
        return self

    def eq(self, column: str, value: Any) -> FakeTable:
        self._filters[column] = value
        return self

    def execute(self) -> Any:
        found = [
            row
            for row in self.store.get(self.name, [])
            if all(str(row.get(k)) == str(v) for k, v in self._filters.items())
        ]
        return type("Result", (), {"data": found})()


class FakeClient:
    """Just enough of the Supabase client for `_owner_of_version`."""

    def __init__(self, store: dict[str, list[dict]]):
        self.store = store
        self.rpc_calls: list[tuple[str, dict]] = []
        self.activated: dict[str, Any] = {}

    def table(self, name: str) -> FakeTable:
        return FakeTable(self.store, name)

    def rpc(self, name: str, params: dict) -> Any:
        self.rpc_calls.append((name, params))
        return type("Q", (), {"execute": lambda _s: type("R", (), {"data": [self.activated]})()})()


@pytest.fixture
def approving(env, monkeypatch: pytest.MonkeyPatch):
    from app.orchestration.services import scheduler
    from app.orchestration.workflows import care

    owner = str(uuid4())
    plan_id = str(uuid4())
    version_id = str(uuid4())

    client = FakeClient({"care_plans": [{"id": plan_id, "user_id": owner}]})
    client.activated = {
        "id": version_id,
        "care_plan_id": plan_id,
        "version_number": 1,
        "status": "ACTIVE",
        "source_type": "INITIAL_PLAN",
    }

    monkeypatch.setattr(
        care,
        "get_version",
        lambda _c, _v: {"id": version_id, "care_plan_id": plan_id, "status": "PROPOSED"},
    )

    materialised: list[dict[str, Any]] = []

    def fake_materialise(_client, *, now_utc, user_id=None):
        materialised.append({"user_id": user_id, "now": now_utc})
        return 4

    monkeypatch.setattr(scheduler, "materialise", fake_materialise)

    return care, client, version_id, owner, materialised


def test_approving_materialises_the_first_tasks(approving):
    care, client, version_id, owner, materialised = approving

    result = care.approve(client, version_id=version_id)

    assert materialised, "approving activated a plan and scheduled nothing"
    assert materialised[0]["user_id"] == owner, "materialised for the wrong user"
    assert result["tasks_created"] == 4


def test_it_is_scoped_to_the_owner_not_the_whole_database(approving):
    """A request handler on one user's JWT must not sweep every plan there is —
    that is the tick's job, and doing it here would make approval as slow as the
    database is large."""
    care, client, version_id, owner, materialised = approving
    care.approve(client, version_id=version_id)

    assert materialised[0]["user_id"] == owner


def test_a_failed_materialisation_does_not_undo_the_activation(approving, monkeypatch):
    """The version is genuinely ACTIVE by the time this runs. The tick will
    materialise the same rules on its next pass, so a transient failure here must
    not turn an approved plan into an error."""
    care, client, version_id, _owner, _m = approving
    from app.orchestration.services import scheduler

    def boom(*_a, **_k):
        raise RuntimeError("postgrest is having a moment")

    monkeypatch.setattr(scheduler, "materialise", boom)

    result = care.approve(client, version_id=version_id)

    assert result["status"] == "ACTIVE"
    assert result["tasks_created"] == 0


# --- the tick as a callable -----------------------------------------------------


def test_the_tick_is_callable_without_an_http_request(env, monkeypatch):
    """The in-process timer calls this directly. If the only way to run a sweep
    were an authenticated HTTP round trip, an API deployed without a cron would
    stay inert — which is the state this whole PR is fixing."""
    from app.orchestration.services import scheduler, tick

    monkeypatch.setattr(tick, "service_client", lambda: object())
    monkeypatch.setattr(scheduler, "materialise", lambda *_a, **_k: 3)
    monkeypatch.setattr(
        scheduler,
        "sweep_overdue",
        lambda *_a, **_k: scheduler.TickResult(marked_overdue=2, missed=1),
    )
    monkeypatch.setattr(tick.agent_requests_service, "reap_abandoned", lambda _now: 0)
    monkeypatch.setattr(
        tick.notifications,
        "dispatch_due",
        lambda *_a, **_k: type("D", (), {"sent": 1, "skipped": 0, "failed": 0})(),
    )

    outcome = tick.run_tick(now_utc=datetime.now(UTC))

    assert outcome.materialised == 3
    assert outcome.marked_overdue == 2
    assert outcome.missed == 1
    assert outcome.emails_sent == 1


def test_the_tick_never_builds_its_own_agent_when_given_one(env, monkeypatch):
    """The seam that stops a test suite billing for model calls.

    `_reconcile_plans` used to construct `CareAgent(AIGateway())` itself. The
    gateway resolves its provider from configuration, so no dependency override
    could reach it: running the scheduler suite and the e2e journeys made seventeen
    real CARE calls on `claude-opus-5`, cost $1.11, and exhausted the Google quota
    that a real user's next identification needed.
    """
    from app.orchestration.services import tick
    from app.orchestration.workflows import care as care_workflow

    sentinel = object()
    seen: dict[str, object] = {}

    def built() -> object:  # pragma: no cover - the point is that it is not called
        raise AssertionError("the tick built its own agent instead of using the one passed")

    def reconcile(*, executor, agent):
        seen["agent"] = agent
        return 2

    monkeypatch.setattr(tick, "_default_care_agent", built)
    monkeypatch.setattr(care_workflow, "reconcile_missing_plans", reconcile)

    assert tick._reconcile_plans(sentinel) == 2  # type: ignore[arg-type]
    assert seen["agent"] is sentinel
