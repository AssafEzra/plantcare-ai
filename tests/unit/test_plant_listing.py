"""What "my plants" contains, and what it deliberately leaves out.

A plant row is created in `PENDING_IDENTIFICATION` before identification runs,
because FINAL §3 puts naming after confirmation. Every route out of that state
except "the user confirms" abandons the row, and nothing picked those up: on DEV
thirty-three of them sat in the grid reading "ממתין לזיהוי" for identifications
that had failed days earlier.

The rule these tests hold in place is the one exception to hiding them. A plant
whose identification *succeeded* is waiting on the user rather than on the model,
so it stays listed and the card offers the button that accepts it. Getting that
backwards in either direction is a real failure: hide it and the user can never
finish adding the plant; show all of them and the bug is back.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.common.enums import PlantStatus

OWNER = str(uuid4())
ACTIVE = str(uuid4())
AWAITING = str(uuid4())
FAILED = str(uuid4())
ARCHIVED = str(uuid4())


class Table:
    def __init__(self, store: dict[str, list[dict]], name: str):
        self.store, self.name = store, name
        self._eq: dict[str, Any] = {}
        self._neq: dict[str, Any] = {}
        self._in: list[tuple[str, list[str]]] = []

    def select(self, *_a: Any, **_k: Any) -> Table:
        return self

    def eq(self, column: str, value: Any) -> Table:
        self._eq[column] = value
        return self

    def neq(self, column: str, value: Any) -> Table:
        self._neq[column] = value
        return self

    def in_(self, column: str, values: list) -> Table:
        self._in.append((column, [str(v) for v in values]))
        return self

    def ilike(self, *_a: Any, **_k: Any) -> Table:
        return self

    def order(self, *_a: Any, **_k: Any) -> Table:
        return self

    def execute(self) -> Any:
        found = [
            row
            for row in self.store.get(self.name, [])
            if all(str(row.get(k)) == str(v) for k, v in self._eq.items())
            and all(str(row.get(k)) != str(v) for k, v in self._neq.items())
        ]
        for column, values in self._in:
            found = [row for row in found if str(row.get(column)) in values]
        return type("R", (), {"data": found})()


class Client:
    def __init__(self, store: dict[str, list[dict]]):
        self.store = store

    def table(self, name: str) -> Table:
        return Table(self.store, name)


@pytest.fixture
def client(env) -> Client:
    def plant(plant_id: str, status: PlantStatus) -> dict:
        return {
            "id": plant_id,
            "user_id": OWNER,
            "name": None,
            "species_id": None,
            "status": status.value,
            "current_health_status": "UNKNOWN",
            "main_image_id": None,
            "notes": None,
            "archived_at": None,
            "created_at": "2026-09-08T10:00:00Z",
            "updated_at": "2026-09-08T10:00:00Z",
        }

    return Client(
        {
            "plants": [
                plant(ACTIVE, PlantStatus.ACTIVE),
                plant(AWAITING, PlantStatus.PENDING_IDENTIFICATION),
                plant(FAILED, PlantStatus.PENDING_IDENTIFICATION),
                plant(ARCHIVED, PlantStatus.ARCHIVED),
            ],
            # Only one of the two pending plants has something to accept. The
            # other's run failed, so it has no identification row at all.
            "identifications": [{"plant_id": AWAITING, "status": "SUCCESS"}],
        }
    )


def listed(client: Client, **kwargs: Any) -> set[str]:
    from uuid import UUID

    from app.repositories import plants as repo

    return {str(row["id"]) for row in repo.list_for_user(client, owner_id=UUID(OWNER), **kwargs)}


def test_an_approved_plant_is_listed(client) -> None:
    assert ACTIVE in listed(client)


def test_a_plant_whose_identification_failed_is_not_listed(client) -> None:
    """The reported bug. This row is the one that used to say "ממתין לזיהוי"
    forever for an identification that failed days earlier."""
    assert FAILED not in listed(client)


def test_a_plant_awaiting_confirmation_is_still_listed(client) -> None:
    """The exception, and the half that is easy to lose.

    Hiding every unidentified plant would also hide the ones the user is being
    asked to approve - and since the add-plant flow keeps its state in the
    session, there would then be no route back to them at all.
    """
    assert AWAITING in listed(client)


def test_archived_plants_stay_hidden(client) -> None:
    """Unchanged behaviour (FINAL §21), asserted because the filter moved."""
    assert ARCHIVED not in listed(client)


def test_an_explicit_status_filter_still_reaches_a_hidden_plant(client) -> None:
    """The admin and diagnostic paths ask for a status by name.

    The hiding is a default for the grid, not a rule about what exists - a caller
    that asks for PENDING_IDENTIFICATION means it.
    """
    assert listed(client, status=PlantStatus.PENDING_IDENTIFICATION.value) == {AWAITING, FAILED}


def test_confirmable_ids_are_only_the_successful_ones(client) -> None:
    from app.repositories import plants as repo

    assert repo.confirmable_plant_ids(client, [AWAITING, FAILED]) == {AWAITING}
    assert repo.confirmable_plant_ids(client, []) == set()
