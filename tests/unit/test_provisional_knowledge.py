"""A care plan may be built from research nobody has reviewed yet (PR 33).

FINAL §10/§11 keep admin review as the gate between what the Knowledge Agent
writes and what gets *published*, and that is unchanged: nothing on this path
writes a `knowledge_versions` row. What changes is what happens while a draft
waits. A plant used to sit in KNOWLEDGE_PENDING with no knowledge, no plan and no
schedule until a human happened to look — for a single-operator MVP,
indistinguishable from the product not working.

The trade is only honest if three things hold, and these tests are those three:
provenance stays exact, only finished research is ever used, and a rejection is
visible.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

SPECIES = str(uuid4())
PLANT = str(uuid4())
USER = str(uuid4())


class Table:
    def __init__(self, store: dict[str, list[dict]], name: str):
        self.store, self.name = store, name
        self._eq: dict[str, Any] = {}

    def select(self, *_a: Any, **_k: Any) -> Table:
        return self

    def eq(self, column: str, value: Any) -> Table:
        self._eq[column] = value
        return self

    def order(self, *_a: Any, **_k: Any) -> Table:
        return self

    def limit(self, *_a: Any, **_k: Any) -> Table:
        return self

    def execute(self) -> Any:
        found = [
            row
            for row in self.store.get(self.name, [])
            if all(str(row.get(k)) == str(v) for k, v in self._eq.items())
        ]
        return type("R", (), {"data": found})()


class Client:
    def __init__(self, store: dict[str, list[dict]]):
        self.store = store

    def table(self, name: str) -> Table:
        return Table(self.store, name)


PLANT_ROW = {
    "id": PLANT,
    "user_id": USER,
    "name": "קלתיאה",
    "species_id": SPECIES,
    "status": "ACTIVE",
    "current_health_status": "HEALTHY",
    "notes": None,
}

SPECIES_ROW = {"id": SPECIES, "scientific_name": "Calathea makoyana", "common_name": "צמח הטווס"}

SECTIONS = {
    "sections": {
        "watering": {"text": "להשקות כשהמצע יבש.", "confidence": 0.8},
        "light": {"text": "אור עקיף בהיר.", "confidence": 0.9},
    }
}


def store(**tables: list[dict]) -> dict[str, list[dict]]:
    base = {
        "plants": [PLANT_ROW],
        "species": [SPECIES_ROW],
        "profiles": [{"id": USER, "timezone": "Asia/Jerusalem"}],
        "knowledge_versions": [],
        "knowledge_drafts": [],
        "plant_environments": [],
        "health_assessments": [],
        "care_events": [],
        "notification_preferences": [],
    }
    return {**base, **tables}


def draft(status: str = "READY_FOR_REVIEW") -> dict[str, Any]:
    return {
        "id": "draft-1",
        "species_id": SPECIES,
        "language": "he",
        "status": status,
        "content": SECTIONS,
        "updated_at": "2026-09-06T09:00:00Z",
    }


def published() -> dict[str, Any]:
    return {
        "id": "version-1",
        "species_id": SPECIES,
        "language": "he",
        "version_number": 1,
        "is_current": True,
        "content": {"watering": {"text": "המלצה מאושרת."}},
    }


# --- which knowledge a plan is built from ---------------------------------------


def test_a_published_version_is_always_preferred(env):
    """A draft is a fallback, never a shortcut past review that already happened."""
    from app.orchestration.services import care_context

    client = Client(store(knowledge_versions=[published()], knowledge_drafts=[draft()]))
    _context, origin = care_context.build(client, plant_id=PLANT)

    assert origin.version_id == "version-1"
    assert origin.draft_id is None
    assert not origin.is_provisional


def test_finished_research_is_used_when_nothing_is_published(env):
    from app.orchestration.services import care_context

    client = Client(store(knowledge_drafts=[draft()]))
    context, origin = care_context.build(client, plant_id=PLANT)

    assert origin.draft_id == "draft-1"
    assert origin.version_id is None
    assert origin.is_provisional
    assert "watering" in context.knowledge_sections


@pytest.mark.parametrize("status", ["DRAFT", "RESEARCHING", "REJECTED", "FAILED"])
def test_unfinished_or_rejected_research_is_never_used(env, status):
    """A DRAFT is empty, RESEARCHING is half-written, and REJECTED in particular
    may have been rejected precisely because it was wrong. Building a watering
    schedule on any of them is worse than refusing."""
    from app.common.errors import ValidationFailedError
    from app.orchestration.services import care_context

    client = Client(store(knowledge_drafts=[draft(status=status)]))

    with pytest.raises(ValidationFailedError):
        care_context.build(client, plant_id=PLANT)


def test_the_agent_sees_the_same_shape_either_way(env):
    """A draft nests its sections and a published version does not. If that
    reached the agent, a plan built from a draft would silently have no knowledge
    at all - which is the exact bug `_sections` shipped with once already."""
    from app.orchestration.services import care_context

    from_draft, _ = care_context.build(Client(store(knowledge_drafts=[draft()])), plant_id=PLANT)

    assert from_draft.knowledge_sections["watering"] == "להשקות כשהמצע יבש."


# --- what the screens are told --------------------------------------------------


def test_a_plan_from_a_published_version_is_reviewed(env):
    from app.orchestration.workflows import care

    state = care.knowledge_state(Client(store()), {"knowledge_version_id": "version-1"})

    assert state == {"knowledge_review": "reviewed"}


def test_a_plan_from_a_waiting_draft_is_pending(env):
    from app.orchestration.workflows import care

    client = Client(store(knowledge_drafts=[draft()]))
    state = care.knowledge_state(client, {"knowledge_draft_id": "draft-1"})

    assert state == {"knowledge_review": "pending"}


def test_a_plan_whose_draft_was_rejected_says_so(env):
    """The plan keeps running - leaving the plant with no schedule at all is
    worse - but the user is told, and a corrected version is on the way."""
    from app.orchestration.workflows import care

    client = Client(store(knowledge_drafts=[draft(status="REJECTED")]))
    state = care.knowledge_state(client, {"knowledge_draft_id": "draft-1"})

    assert state == {"knowledge_review": "rejected"}


def test_an_approved_draft_stops_being_provisional(env):
    """Provenance is immutable, so the plan still cites the draft. Nothing about
    the *content* is provisional any more, and a badge that stayed would be
    telling the user something untrue."""
    from app.orchestration.workflows import care

    client = Client(store(knowledge_drafts=[draft(status="APPROVED")]))
    state = care.knowledge_state(client, {"knowledge_draft_id": "draft-1"})

    assert state == {"knowledge_review": "reviewed"}
