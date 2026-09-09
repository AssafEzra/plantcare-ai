"""The tick's cleanup of plants whose identification never finished.

`identification.execute` archives the failures it can see. It cannot see them all,
and that gap is the reason this sweep exists:

* `reap_abandoned` fails a request whose worker never came back, and it does that
  from the tick - never re-entering `execute`, so nothing there ever runs;
* a plant whose flow broke before the run was created has no failure to hook at
  all. Four such rows existed on DEV with no `agent_requests` entry whatsoever.

Both leave a row in `PENDING_IDENTIFICATION` that nothing will ever advance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

OWNER = str(uuid4())
STALE = str(uuid4())
STALE_BUT_CONFIRMABLE = str(uuid4())
RECENT = str(uuid4())

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


class Table:
    def __init__(self, store: dict[str, list[dict]], name: str):
        self.store, self.name = store, name
        self._eq: dict[str, Any] = {}
        self._lt: dict[str, str] = {}
        self._in: list[tuple[str, list[str]]] = []
        self._update: dict[str, Any] | None = None

    def select(self, *_a: Any, **_k: Any) -> Table:
        return self

    def eq(self, column: str, value: Any) -> Table:
        self._eq[column] = value
        return self

    def lt(self, column: str, value: str) -> Table:
        self._lt[column] = value
        return self

    def in_(self, column: str, values: list) -> Table:
        self._in.append((column, [str(v) for v in values]))
        return self

    def insert(self, values: Any) -> Table:
        # A list as well as a single row: the sweep writes one event per plant in
        # one statement, and a stub that only took a dict would have let a
        # batched insert fail silently inside the sweep's own except clause.
        batch = values if isinstance(values, list) else [values]
        self.store.setdefault(self.name, []).extend(dict(row) for row in batch)
        self._update = None
        return self

    def update(self, changes: dict[str, Any]) -> Table:
        self._update = changes
        return self

    def _matches(self) -> list[dict]:
        found = [
            row
            for row in self.store.get(self.name, [])
            if all(str(row.get(k)) == str(v) for k, v in self._eq.items())
            and all(str(row.get(k, "")) < v for k, v in self._lt.items())
        ]
        for column, values in self._in:
            found = [row for row in found if str(row.get(column)) in values]
        return found

    def execute(self) -> Any:
        found = self._matches()
        if self._update is not None:
            for row in found:
                row.update(self._update)
        return type("R", (), {"data": found})()


class Client:
    def __init__(self, store: dict[str, list[dict]]):
        self.store = store

    def table(self, name: str) -> Table:
        return Table(self.store, name)


def plant(plant_id: str, *, age_hours: int) -> dict:
    return {
        "id": plant_id,
        "user_id": OWNER,
        "status": "PENDING_IDENTIFICATION",
        "created_at": (NOW - timedelta(hours=age_hours)).isoformat(),
    }


@pytest.fixture
def client(env) -> Client:
    return Client(
        {
            "plants": [
                plant(STALE, age_hours=48),
                plant(STALE_BUT_CONFIRMABLE, age_hours=48),
                plant(RECENT, age_hours=1),
            ],
            "identifications": [{"plant_id": STALE_BUT_CONFIRMABLE, "status": "SUCCESS"}],
            "system_events": [],
        }
    )


def sweep(client: Client) -> int:
    from app.orchestration.services.tick import _archive_abandoned_plants

    return _archive_abandoned_plants(client, now_utc=NOW)


def status_of(client: Client, plant_id: str) -> str:
    return next(row for row in client.store["plants"] if row["id"] == plant_id)["status"]


def test_a_stale_unidentifiable_plant_is_archived(client) -> None:
    assert sweep(client) == 1
    assert status_of(client, STALE) == "ARCHIVED"


def test_a_plant_awaiting_confirmation_is_left_alone(client) -> None:
    """Same reasoning as the workflow's guard: it is waiting on the user, the
    grid lists it, and the card offers the button that accepts it."""
    sweep(client)

    assert status_of(client, STALE_BUT_CONFIRMABLE) == "PENDING_IDENTIFICATION"


def test_a_plant_still_inside_the_window_is_left_alone(client) -> None:
    """A slow run, a retried upload, or a user who wandered off mid-flow and came
    back must never be caught by cleanup."""
    sweep(client)

    assert status_of(client, RECENT) == "PENDING_IDENTIFICATION"


def test_archiving_is_recorded_so_it_can_be_explained(client) -> None:
    """A plant that vanishes from the grid with no trace is indistinguishable
    from one the application lost."""
    sweep(client)

    events = client.store["system_events"]
    assert [e["event_type"] for e in events] == ["PLANT_ARCHIVED"]
    assert events[0]["payload"]["reason"] == "IDENTIFICATION_ABANDONED"


def test_the_sweep_never_takes_the_tick_down_with_it(env) -> None:
    """Cleanup must not cost the tick its materialisation, its overdue sweep or
    its reminders - the deterministic work that is always worth completing."""

    class Broken:
        def table(self, _name: str) -> Any:
            raise RuntimeError("database unavailable")

    from app.orchestration.services.tick import _archive_abandoned_plants

    assert _archive_abandoned_plants(Broken(), now_utc=NOW) == 0
