"""What the plant dashboard is told about a proposal already on its way.

Approving an identification publishes the species' research, which queues an
INITIAL_PLAN for every plant waiting on it. Nothing in the dashboard payload used
to mention that, so the care section showed its empty state and offered "הכנת
תוכנית" — and pressing it reached the guard in `start_proposal`, which refuses a
second proposal, and the user got an error instead of a plan.

`request_in_flight` is what the payload now carries. These pin its filters: the
wrong plant, the wrong agent and a request that has already finished must all read
as "nothing in flight", because each of them would put that button back.
"""

from __future__ import annotations

from tests.unit.fake_db import FakeDB

PLANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def request(**overrides):
    row = {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "plant_id": PLANT,
        "agent_type": "CARE",
        "status": "QUEUED",
    }
    row.update(overrides)
    return row


def in_flight(rows):
    from app.orchestration.workflows import care

    return care.request_in_flight(FakeDB({"agent_requests": rows}), PLANT)


def test_a_queued_proposal_is_in_flight(env):
    assert in_flight([request()]) is not None


def test_a_running_proposal_is_in_flight(env):
    """PROCESSING counts too. Care took 105 seconds on its first live run, which is
    the whole window this is meant to cover."""
    assert in_flight([request(status="PROCESSING")]) is not None


def test_a_finished_proposal_is_not(env):
    """Otherwise the button would never come back after a failure."""
    for done in ("SUCCEEDED", "FAILED", "CANCELLED"):
        assert in_flight([request(status=done)]) is None


def test_another_plants_proposal_is_not(env):
    assert in_flight([request(plant_id=OTHER)]) is None


def test_another_agents_request_is_not(env):
    """A health check or an identification running on this plant says nothing about
    its care plan, and would hide the button for the wrong reason."""
    for agent in ("HEALTH", "IDENTIFICATION", "KNOWLEDGE"):
        assert in_flight([request(agent_type=agent)]) is None


def test_nothing_queued_is_not(env):
    assert in_flight([]) is None
