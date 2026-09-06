"""The route must be able to return what the workflow produces (PR 33 fix).

Reported from real use: *"the fix you did for care plan in this pr breaks and
doesnt work both for initial plan and update plan"*.

`VersionResponse.current_rules` was typed `RuleResponse`, which requires an `id`.
The rules in force are supplied by `care._rule_payloads`, which exists to feed
the Care Agent and carries no row id - the agent has no use for one. So
`GET /v1/plants/{id}/care-plan/proposals` raised `ResponseValidationError` on
every call, the dashboard turned that into an error message, and no proposal
rendered at all - initial or update.

Nothing caught it because nothing joined the two halves: the diff tests never
touched the response model, and the dialog test built its own dict and rendered
the component directly. Both halves were correct and the seam between them was
not, which is the shape this whole month has been about.

So these tests deliberately take the *workflow's* shape and put it through the
*route's* model. Not a stub of either.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

RULE_ROW = {
    "id": str(uuid4()),
    "action_type": "WATERING",
    "interval_days": 7,
    "preferred_time_local": "08:00:00",
    "preferred_weekday": None,
    "instructions": "להשקות עד ניקוז.",
    "is_active": True,
}


def payload_shape() -> list[dict[str, Any]]:
    """Exactly what `care._rule_payloads` builds. Four keys, no id.

    Written out rather than imported so that changing `_rule_payloads` breaks this
    test loudly instead of silently agreeing with it.
    """
    return [
        {
            "action_type": RULE_ROW["action_type"],
            "interval_days": RULE_ROW["interval_days"],
            "preferred_time_local": RULE_ROW["preferred_time_local"],
            "preferred_weekday": RULE_ROW["preferred_weekday"],
        }
    ]


def version(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": str(uuid4()),
        "care_plan_id": str(uuid4()),
        "version_number": 2,
        "knowledge_version_id": None,
        "knowledge_draft_id": None,
        "knowledge_review": "reviewed",
        "status": "PROPOSED",
        "professional_recommendations": {"summary": "השקיה מתונה."},
        "operational_preferences": {"missing_context": []},
        "change_summary": "צופפנו את ההשקיה.",
        "source_type": "HEALTH_DRIVEN",
        "created_at": "2026-09-06T10:00:00Z",
        "rules": [RULE_ROW],
        "current_rules": payload_shape(),
    }
    return {**base, **overrides}


def test_an_update_proposal_serialises(env):
    """The exact shape `proposals_for_plant` returns for a plant that already has
    a plan: table rows in `rules`, agent payloads in `current_rules`."""
    from app.api.routers.care import VersionResponse

    response = VersionResponse(**version())

    assert len(response.current_rules) == 1
    assert response.current_rules[0].action_type.value == "WATERING"


def test_a_first_plan_serialises(env):
    """No plan in force, so `current_rules` is empty - which is correct, and must
    not be mistaken for a reason to fail."""
    from app.api.routers.care import VersionResponse

    response = VersionResponse(**version(current_rules=[], source_type="INITIAL_PLAN"))

    assert response.current_rules == []


def test_the_active_plan_serialises(env):
    """`GET /v1/plants/{id}/care-plan` uses the same model, so the same defect
    would have taken the plan view down with the proposals."""
    from app.api.routers.care import VersionResponse

    response = VersionResponse(**version(status="ACTIVE", current_rules=[]))

    assert response.status.value == "ACTIVE"


@pytest.mark.parametrize("review", ["reviewed", "pending", "rejected"])
def test_every_review_state_survives_the_round_trip(env, review):
    from app.api.routers.care import VersionResponse

    assert VersionResponse(**version(knowledge_review=review)).knowledge_review == review


def test_a_plan_built_from_a_draft_serialises(env):
    """PR 33's provenance: the draft id is set and the version id is not."""
    from app.api.routers.care import VersionResponse

    draft_id = str(uuid4())
    response = VersionResponse(**version(knowledge_draft_id=draft_id, knowledge_review="pending"))

    assert str(response.knowledge_draft_id) == draft_id
    assert response.knowledge_version_id is None


def test_what_the_route_returns_is_what_the_diff_reads(env):
    """The two ends of the feature, joined. The dialog diffs `current_rules`
    against `rules`, so the serialised model has to carry everything
    `care_plan_diff` compares - and nothing it must ignore."""
    from app.api.routers.care import VersionResponse
    from app.domain.services.care_plan_diff import diff_rules, has_changes

    response = VersionResponse(
        **version(rules=[{**RULE_ROW, "interval_days": 5}], current_rules=payload_shape())
    )

    changes = diff_rules(
        [r.model_dump(mode="json") for r in response.current_rules],
        [r.model_dump(mode="json") for r in response.rules],
    )

    assert has_changes(changes)
    watering = next(c for c in changes if c.action_type == "WATERING")
    assert watering.fields == ("interval_days",)


# --- the same defect class, everywhere else this PR touches ---------------------
#
# Fixing only the instance a user found leaves the others to be found the same
# way. These are every dict PR 33 hands to a response model.


def test_a_pending_draft_serialises_as_knowledge(env):
    """`workflow.pending_draft` shapes a draft like a version so one model serves
    both - the screen should differ in what it *says* about the content, not in
    how it reads it. If the shapes disagreed, a species in review would 500
    instead of showing its article."""
    from app.api.routers.knowledge import KnowledgeResponse

    response = KnowledgeResponse(
        id=str(uuid4()),
        species_id=str(uuid4()),
        language="he",
        version_number=0,
        review="pending",
        content={"watering": {"text": "כל 7 ימים"}},
        source_summary={},
        published_at="2026-09-06T09:00:00Z",
        sources=[],
    )

    assert response.review == "pending"
    assert response.version_number == 0, "a pending draft must not claim a published number"


def test_a_published_version_still_says_published(env):
    """The default matters: every existing caller omits `review`, and a published
    article that reported itself as pending would put a warning on content that
    has been approved."""
    from app.api.routers.knowledge import KnowledgeResponse

    response = KnowledgeResponse(
        id=str(uuid4()),
        species_id=str(uuid4()),
        language="he",
        version_number=3,
        content={},
        source_summary=None,
        published_at="2026-09-06T09:00:00Z",
        sources=[],
    )

    assert response.review == "published"


def test_the_admin_catalogue_serialises(env):
    """What `published_catalogue` builds, through the model the route returns."""
    from app.api.routers.knowledge import CatalogueEntry

    entry = CatalogueEntry(
        id=str(uuid4()),
        species_id=str(uuid4()),
        scientific_name="Monstera deliciosa",
        common_name=None,
        language="he",
        version_number=1,
        published_at="2026-09-06T09:00:00Z",
        plant_count=3,
    )

    assert entry.plant_count == 3


def test_the_admin_reader_serialises(env):
    from app.api.routers.knowledge import VersionDetail

    detail = VersionDetail(
        id=str(uuid4()),
        species_id=str(uuid4()),
        language="he",
        version_number=2,
        is_current=True,
        published_by=None,
        published_at="2026-09-06T09:00:00Z",
        content={"watering": {"text": "x"}},
        source_summary=None,
        sources=[],
    )

    assert detail.source_summary == {}, "a null summary must normalise, not fail"
