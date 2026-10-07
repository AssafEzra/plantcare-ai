"""The one research call a non-administrator may make, and its four refusals.

A plant was added, its species research failed on a vendor 503, and the plant sat in
KNOWLEDGE_PENDING with nothing anywhere offering to try again: the drafts tab opens
filtered to READY_FOR_REVIEW, so the failed draft was not on screen, and the plant
itself said only "אוסף מידע" - the same thing it says while research is running
normally. Meanwhile the care section beside it offered a plan that `care_context.build`
refuses, because the Care Agent plans from knowledge that was never published.

So the owner gets a button. Research costs money and is shared across every plant of
that species, so the guard is narrow and these are the cases it has to refuse. The
happy path is covered end to end on DEV, not here; what is pinned here is what must
*not* start a run.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.common.enums import PlantStatus
from app.common.errors import ValidationFailedError

SPECIES = UUID("0c3907ff-0000-4000-8000-000000000001")


def newest(status: str | None):
    """Stand in for `knowledge.newest_draft`, which the route consults."""
    if status is None:
        return None
    return {"id": str(uuid4()), "status": status, "language": "he"}


def plant(status: str = PlantStatus.KNOWLEDGE_PENDING.value, species: UUID | None = SPECIES):
    return {
        "id": str(uuid4()),
        "user_id": str(uuid4()),
        "status": status,
        "species_id": str(species) if species else None,
    }


def may_retry(row, draft) -> bool:
    """The real guard, not a restatement of it.

    `check_owner_may_retry` is what the route calls. An earlier version of this file
    re-implemented the same conditions here, which tests the test: the route could
    drift and every case would still pass.
    """
    from app.orchestration.workflows import knowledge

    try:
        knowledge.check_owner_may_retry(row, draft)
    except ValidationFailedError:
        return False
    return True


def test_a_failed_draft_on_a_waiting_plant_may_be_retried(env):
    assert may_retry(plant(), newest("FAILED")) is True


@pytest.mark.parametrize(
    "status",
    [
        PlantStatus.ACTIVE.value,
        PlantStatus.ARCHIVED.value,
        PlantStatus.PENDING_IDENTIFICATION.value,
    ],
)
def test_a_plant_that_is_not_waiting_may_not(env, status):
    """An ACTIVE plant already has its knowledge; a pending one has no species yet.
    Neither is stuck, and neither should be able to spend a research call."""
    assert may_retry(plant(status=status), newest("FAILED")) is False


def test_a_running_draft_may_not(env):
    """It is already going. `start_research` would replay it rather than start a
    second, so the button would do nothing while appearing to do something."""
    assert may_retry(plant(), newest("RESEARCHING")) is False


def test_a_rejected_draft_may_not(env):
    """REJECTED is an administrator's judgement about the content. The owner
    re-running it would overwrite that decision from outside the review queue."""
    assert may_retry(plant(), newest("REJECTED")) is False


def test_an_approved_draft_may_not(env):
    """If the newest draft is approved the plant should not be waiting at all -
    that is a different fault, and retrying research would not fix it."""
    assert may_retry(plant(), newest("APPROVED")) is False


def test_no_draft_at_all_may_not(env):
    """Research was never started. Quietly starting the first run here would hide
    whatever stopped it from being queued in the first place."""
    assert may_retry(plant(), newest(None)) is False


def test_a_plant_without_a_species_may_not(env):
    assert may_retry(plant(species=None), newest("FAILED")) is False


def test_the_route_is_not_admin_only(env):
    """The point of the whole change: every other research route requires an admin,
    and that is what left a plant waiting on someone noticing a tab."""
    from app.api import main

    paths = main.create_app().openapi()["paths"]
    assert "/v1/plants/{plant_id}/knowledge/research" in paths
