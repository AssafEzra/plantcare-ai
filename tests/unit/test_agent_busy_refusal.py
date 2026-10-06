"""Asking for a run that is already going is refused in words, not by accident.

Pressing a launch button during a run used to do one of two wrong things. For care
it reached `start_proposal`'s guard against a *pending proposal* — a different
condition, and during a run there is no proposal yet — so the user got a message
about something they could not see. For health and identification nothing objected
at all: a second model call started, was billed, and raced the first into the same
rows.

All three now ask `in_flight` first and raise `ConflictError`, which is the honest
status: nothing the user sent is invalid, the state is. The sentence is shared, so
the same situation reads the same way whichever agent it happened to.

Knowledge is deliberately absent. It refuses a second run by returning the one
already going (`knowledge.start_research`), which is better than an error because
there is a real draft to join, and `tests/unit/test_knowledge_lifecycle.py` covers
it.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.common.errors import ConflictError
from app.orchestration.services import agent_requests as requests_service
from tests.unit.fake_db import FakeDB

USER = UUID("99999999-9999-9999-9999-999999999999")
PLANT = UUID("11111111-1111-1111-1111-111111111111")
IMAGE = UUID("33333333-3333-3333-3333-333333333333")


def db(agent_type: str, status: str = "PROCESSING") -> FakeDB:
    """A plant with one usable image, and one run of `agent_type` in `status`."""
    return FakeDB(
        {
            "plants": [
                {
                    "id": str(PLANT),
                    "user_id": str(USER),
                    "name": "מונסטרה",
                    "status": "ACTIVE",
                    "species_id": None,
                    "archived_at": None,
                }
            ],
            "plant_images": [{"id": str(IMAGE), "plant_id": str(PLANT)}],
            "agent_requests": [
                {
                    "id": str(uuid4()),
                    "user_id": str(USER),
                    "plant_id": str(PLANT),
                    "agent_type": agent_type,
                    "status": status,
                }
            ],
        }
    )


def start_health(client):
    from app.orchestration.workflows import health

    return health.start(
        client,
        user_id=USER,
        plant_id=PLANT,
        image_ids=[IMAGE],
        user_note=None,
        idempotency_key=None,
    )


def start_identification(client):
    from app.orchestration.workflows import identification

    return identification.start(
        client,
        user_id=USER,
        plant_id=PLANT,
        image_ids=[IMAGE],
        user_description=None,
        idempotency_key=None,
    )


@pytest.mark.parametrize(
    ("launch", "agent_type"),
    [(start_health, "HEALTH"), (start_identification, "IDENTIFICATION")],
)
@pytest.mark.parametrize("status", ["QUEUED", "PROCESSING"])
def test_a_second_run_is_refused_while_the_first_is_going(env, launch, agent_type, status):
    with pytest.raises(ConflictError) as raised:
        launch(db(agent_type, status))

    assert str(raised.value) == requests_service.AGENT_BUSY


@pytest.mark.parametrize(
    ("launch", "agent_type"),
    [(start_health, "HEALTH"), (start_identification, "IDENTIFICATION")],
)
def test_a_run_of_a_different_agent_does_not_refuse(env, launch, agent_type):
    """The guard is per agent type. A care proposal being prepared in the background
    - which is what approving an identification starts - must not make the health
    check button say the app is busy."""
    other = "CARE" if agent_type != "CARE" else "HEALTH"
    launch(db(other))  # does not raise; reaching the queue is the assertion


@pytest.mark.parametrize(
    ("launch", "agent_type"),
    [(start_health, "HEALTH"), (start_identification, "IDENTIFICATION")],
)
def test_a_finished_run_does_not_refuse(env, launch, agent_type):
    """A failure that locked the plant out of retrying would be worse than the bug
    this fixes."""
    launch(db(agent_type, "FAILED"))
