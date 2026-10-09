"""The order a user puts their plants in.

No attribute of a plant knows it. Name, date added and health status were the three
sorts on offer and none of them says that the plant on the kitchen windowsill is the
one to look at first, so the order became the user's own (migration 0023).

Two things here are worth more than they look:

* the tie-break. `display_order` is deliberately not unique per user - a unique
  index would turn every drag into a dance around the constraint - so `created_at
  desc` is what keeps the list from reshuffling between two reads. It is also what
  the whole list was ordered by before this column existed, which is why the
  migration numbers existing rows newest-first.
* the refusals. The endpoint takes the whole list, and accepting a partial one would
  leave the unnamed plants at whatever number they had, interleaving two sets.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.repositories import plants as repo
from tests.unit.fake_db import FakeDB

OWNER = uuid4()


def plant(position: int, created: str, name: str = "צמח") -> dict:
    return {
        "id": str(uuid4()),
        "user_id": str(OWNER),
        "name": name,
        "species_id": None,
        "status": "ACTIVE",
        "current_health_status": "HEALTHY",
        "main_image_id": None,
        "notes": None,
        "archived_at": None,
        "created_at": created,
        "updated_at": created,
        "care_intensity": None,
        "display_order": position,
    }


def listed(rows: list[dict]) -> list[int]:
    found = repo.list_for_user(FakeDB({"plants": rows}), owner_id=OWNER)
    return [row["display_order"] for row in found]


def test_the_list_is_in_the_owners_order(env):
    rows = [
        plant(3, "2026-01-01T00:00:00+00:00"),
        plant(1, "2026-02-01T00:00:00+00:00"),
        plant(2, "2026-03-01T00:00:00+00:00"),
    ]

    assert listed(rows) == [1, 2, 3]


def test_a_tie_falls_back_to_newest_first(env):
    """Which is the order the whole list had before this column existed, so a user
    whose plants all share a position sees no change."""
    rows = [
        plant(1, "2026-01-01T00:00:00+00:00", name="older"),
        plant(1, "2026-02-01T00:00:00+00:00", name="newer"),
    ]

    found = repo.list_for_user(FakeDB({"plants": rows}), owner_id=OWNER)

    assert [row["name"] for row in found] == ["newer", "older"]


def test_a_new_plant_defaults_to_the_top_of_the_order(env):
    """`display_order` defaults to 0 in the database, so a plant added after a
    reorder - whose positions start at 1 - sorts above them. That is the right
    answer: a plant you just added is the one you are looking for."""
    rows = [
        plant(1, "2026-01-01T00:00:00+00:00", name="arranged"),
        plant(0, "2026-05-01T00:00:00+00:00", name="just added"),
    ]

    found = repo.list_for_user(FakeDB({"plants": rows}), owner_id=OWNER)

    assert [row["name"] for row in found] == ["just added", "arranged"]


def test_setting_one_position_touches_only_that_plant(env):
    rows = [plant(1, "2026-01-01T00:00:00+00:00"), plant(2, "2026-02-01T00:00:00+00:00")]
    db = FakeDB({"plants": rows})

    repo.set_plant_order(db, rows[1]["id"], 7)

    assert rows[0]["display_order"] == 1
    assert rows[1]["display_order"] == 7


# --- what the endpoint refuses --------------------------------------------------


def reorder(db: FakeDB, plant_ids: list[str]):
    """Call the route the way FastAPI would, with the validation it performs."""
    import asyncio
    from types import SimpleNamespace

    from app.api.routers.plants import ReorderPlantsRequest, reorder_plants

    user = SimpleNamespace(id=OWNER, client=db, access_token="x")
    request = SimpleNamespace(state=SimpleNamespace(request_id="r"))
    payload = ReorderPlantsRequest(plant_ids=plant_ids)  # type: ignore[arg-type]

    return asyncio.run(reorder_plants(request, payload, user))  # type: ignore[arg-type]


def test_a_partial_list_is_refused(env):
    """The reason the endpoint takes the whole set: naming two of three plants
    leaves the third at whatever number it had, which interleaves two orders."""
    from app.common.errors import ValidationFailedError

    rows = [plant(i, f"2026-0{i}-01T00:00:00+00:00") for i in (1, 2, 3)]
    db = FakeDB({"plants": rows})

    with pytest.raises(ValidationFailedError):
        reorder(db, [rows[0]["id"], rows[1]["id"]])


def test_a_repeated_plant_is_refused(env):
    from app.common.errors import ValidationFailedError

    rows = [plant(i, f"2026-0{i}-01T00:00:00+00:00") for i in (1, 2)]
    db = FakeDB({"plants": rows})

    with pytest.raises(ValidationFailedError):
        reorder(db, [rows[0]["id"], rows[0]["id"]])


def test_another_users_plant_is_refused(env):
    """`list_for_user` is the set compared against, so a plant that is not the
    caller's cannot be named - and RLS would refuse the write regardless."""
    from app.common.errors import ValidationFailedError

    rows = [plant(1, "2026-01-01T00:00:00+00:00")]
    db = FakeDB({"plants": rows})

    with pytest.raises(ValidationFailedError):
        reorder(db, [str(uuid4())])


def test_a_full_list_renumbers_from_one(env):
    rows = [plant(i, f"2026-0{i}-01T00:00:00+00:00") for i in (1, 2, 3)]
    db = FakeDB({"plants": rows})
    reversed_ids = [row["id"] for row in reversed(rows)]

    reorder(db, reversed_ids)

    positions = {row["id"]: row["display_order"] for row in rows}
    assert [positions[plant_id] for plant_id in reversed_ids] == [1, 2, 3]
