"""Requests whose worker never came back (PR 31).

Agent work runs in FastAPI `BackgroundTasks`, inside the API process. A restart —
a deploy, a crash, `--reload` noticing an edit — kills every run in flight, and
the `agent_requests` row it was updating stays PROCESSING for good. Nothing reaped
those, so the client polls, gives up politely, and reports "still running" about a
run that ended hours ago. Every visit. Forever.

Found when a knowledge research request sat in PROCESSING for three hours across
several reloads. A deployment does exactly what `--reload` does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest


class _Table:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def select(self, *_a: Any, **_k: Any) -> _Table:
        return self

    def in_(self, *_a: Any, **_k: Any) -> _Table:
        return self

    def execute(self) -> Any:
        return type("Result", (), {"data": self._rows})()


@pytest.fixture
def reaper(env, monkeypatch: pytest.MonkeyPatch):
    """The service, with the database and the failure write both substituted."""
    from app.orchestration.services import agent_requests as service

    failed: list[tuple[str, str]] = []

    def build(open_rows: list[dict[str, Any]]):
        monkeypatch.setattr(
            service,
            "service_client",
            lambda: type("Client", (), {"table": lambda self, _name: _Table(open_rows)})(),
        )
        monkeypatch.setattr(
            service, "mark_failed", lambda request_id, code: failed.append((str(request_id), code))
        )
        return service

    build.failed = failed  # type: ignore[attr-defined]
    return build


NOW = datetime(2026, 9, 6, 4, 0, tzinfo=UTC)


def row(agent_type: str, age_seconds: int) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "agent_type": agent_type,
        "created_at": (NOW - timedelta(seconds=age_seconds)).isoformat(),
    }


def test_a_run_past_its_budget_is_written_off(reaper):
    """Knowledge research is allowed 600 seconds plus the grace period."""
    service = reaper([row("KNOWLEDGE", 10_000)])

    assert service.reap_abandoned(NOW) == 1
    assert reaper.failed[0][1] == "AGENT_ABANDONED"  # type: ignore[attr-defined]


def test_a_run_still_inside_its_budget_is_left_alone(reaper):
    """The opposite error is worse. Telling a user their plant could not be
    identified, while the answer is still on its way, is a lie the product then
    has to live with — the identification arrives and contradicts it."""
    service = reaper([row("KNOWLEDGE", 120)])

    assert service.reap_abandoned(NOW) == 0
    assert reaper.failed == []  # type: ignore[attr-defined]


def test_each_agent_is_judged_against_its_own_budget(reaper):
    """400 seconds is long past an identification and well inside a research run.
    One threshold for four agents is the mistake PR 29 already paid for."""
    service = reaper([row("IDENTIFICATION", 400), row("KNOWLEDGE", 400)])

    assert service.reap_abandoned(NOW) == 1


def test_a_grace_period_covers_a_merely_slow_run(reaper):
    """Right at the budget is not yet abandoned: the budget is what the *provider*
    is allowed, and the request needs time to be written after it."""
    service = reaper([row("IDENTIFICATION", 100)])

    assert service.reap_abandoned(NOW) == 0
