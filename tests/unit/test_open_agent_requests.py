"""One watcher for every agent run, and the refusal that comes with it.

`GET /v1/agent-requests` answers "what of mine is still running". It replaced three
per-screen watchers, each of which only worked while its component stayed mounted —
so leaving Add Plant mid-identification meant the species, the status change and the
archive-on-failure reached nothing. The client polls this while the answer is
non-empty and stops when it empties, which is why "what counts as open" has to be
exactly QUEUED and PROCESSING: a settled status left in would poll forever, and a
running one left out would stop the poll with work still going.

`in_flight` is the same question narrowed to one plant and one agent, and it is what
now refuses a second run in words the user can read.
"""

from __future__ import annotations

import pytest

from app.common.enums import AgentType
from tests.unit.fake_db import FakeDB

PLANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"

SETTLED = ("SUCCEEDED", "FAILED", "CANCELLED")


def request(**overrides):
    row = {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "user_id": "99999999-9999-9999-9999-999999999999",
        "plant_id": PLANT,
        "agent_type": "CARE",
        "status": "QUEUED",
        "stage": None,
        "error_code": None,
        "input_summary": None,
        "output_summary": None,
        "created_at": "2026-10-06T07:00:00+00:00",
        "updated_at": "2026-10-06T07:00:00+00:00",
    }
    row.update(overrides)
    return row


def open_for(rows):
    from app.orchestration.services import agent_requests as service

    return service.open_for_user(FakeDB({"agent_requests": rows}))


def in_flight(rows, agent=AgentType.CARE, plant=PLANT):
    from app.orchestration.services import agent_requests as service

    return service.in_flight(FakeDB({"agent_requests": rows}), plant, agent)


# --- what counts as open --------------------------------------------------------


def test_queued_and_processing_are_open(env):
    rows = open_for([request(id="a", status="QUEUED"), request(id="b", status="PROCESSING")])
    assert {row["id"] for row in rows} == {"a", "b"}


@pytest.mark.parametrize("status", SETTLED)
def test_a_settled_request_is_not_open(env, status):
    """Left in, the client would poll for ever: it stops when the list empties."""
    assert open_for([request(status=status)]) == []


def test_nothing_running_is_an_empty_list_not_an_error(env):
    """The idle case, and the common one. An empty list is what stops the polling."""
    assert open_for([]) == []


def test_every_agent_type_is_reported(env):
    """The point of one watcher: knowledge had no screen polling it at all, so a
    plant waiting on research sat unchanged until the user reloaded by hand."""
    rows = open_for(
        [request(id=name, agent_type=name) for name in ("IDENTIFICATION", "KNOWLEDGE", "HEALTH")]
    )
    assert {row["agent_type"] for row in rows} == {"IDENTIFICATION", "KNOWLEDGE", "HEALTH"}


def test_a_knowledge_run_has_no_plant_and_is_still_reported(env):
    """Research belongs to a species, not a plant. The tray names the agent alone
    for these; dropping them would hide the longest-running agent of the four."""
    rows = open_for([request(agent_type="KNOWLEDGE", plant_id=None)])
    assert len(rows) == 1
    assert rows[0]["plant_id"] is None


# --- the refusal ----------------------------------------------------------------


def test_a_running_request_of_the_same_type_is_in_flight(env):
    for status in ("QUEUED", "PROCESSING"):
        assert in_flight([request(status=status)]) is not None


@pytest.mark.parametrize("status", SETTLED)
def test_a_settled_request_does_not_block_a_new_one(env, status):
    """Otherwise a failed run would lock the plant out of ever trying again."""
    assert in_flight([request(status=status)]) is None


def test_another_agent_does_not_block(env):
    """A care proposal being prepared must not stop a health check being asked for:
    they touch nothing in common, and one refusal standing in for the other would
    read as the app being broken."""
    assert in_flight([request(agent_type="CARE")], agent=AgentType.HEALTH) is None


def test_another_plant_does_not_block(env):
    assert in_flight([request(plant_id=OTHER)]) is None


def test_the_message_is_one_sentence_in_one_place(env):
    """Identification, care and health raise the same refusal. Three wordings for
    one situation would read as three different problems."""
    from app.orchestration.services import agent_requests as service

    assert service.AGENT_BUSY
    assert "\n" not in service.AGENT_BUSY
