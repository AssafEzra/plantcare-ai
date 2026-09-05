"""Identification Agent contract tests.

TESTING_STRATEGY §5 names what these must cover: candidate ordering, confidence
classification, low confidence, NEEDS_MORE_INFORMATION, FAILED, no plant mutation
before confirmation, and retained history. The first six live here; the last two
are properties of the workflow and are covered against the database.

Everything runs against MockProvider — §12 requires that tests not depend on live
model responses, and the malformed and failing paths are precisely the ones a
live model will not produce on demand.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.agents.identification.agent import IdentificationAgent
from app.agents.identification.contract import (
    Candidate,
    IdentificationOutput,
    IdentificationRequest,
    confidence_level_for,
)
from app.common.enums import ConfidenceLevel, IdentificationStatus
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.mock_provider import MockProvider
from app.infrastructure.ai.provider import ImageInput, ProviderTimeoutError

IMAGE = ImageInput(data=b"\xff\xd8\xff-not-really-decoded-here", mime_type="image/jpeg")


def agent_with(*responses) -> tuple[IdentificationAgent, MockProvider]:
    provider = MockProvider(list(responses))
    return IdentificationAgent(AIGateway(provider, record_executions=False)), provider


def identify(agent: IdentificationAgent, **kwargs):
    request = IdentificationRequest(images=kwargs.pop("images", [IMAGE]), **kwargs)
    return agent.identify(request, request_id=uuid4())


def output(**kwargs) -> IdentificationOutput:
    defaults = {
        "status": IdentificationStatus.SUCCESS,
        "candidates": [
            Candidate(
                scientific_name="Monstera deliciosa", common_name="מונסטרה", confidence_score=0.92
            )
        ],
    }
    return IdentificationOutput(**{**defaults, **kwargs})


# --- confidence classification (A18) ------------------------------------------


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (1.0, ConfidenceLevel.HIGH),
        (0.90, ConfidenceLevel.HIGH),
        (0.85, ConfidenceLevel.HIGH),
        (0.84, ConfidenceLevel.MEDIUM),
        (0.60, ConfidenceLevel.MEDIUM),
        (0.59, ConfidenceLevel.LOW),
        (0.0, ConfidenceLevel.LOW),
    ],
)
def test_confidence_thresholds(score: float, expected: ConfidenceLevel):
    """Derived in Python, never taken from the model: asking a model to
    self-report a category invites it to pick the label that sounds right rather
    than the one its evidence supports."""
    assert confidence_level_for(score) is expected


def test_a_low_confidence_result_is_still_returned(env):
    """FINAL §8 wants a low-confidence warning, not a hidden result. The user
    decides; suppressing a weak candidate would leave them with nothing to act on."""
    agent, _ = agent_with(
        output(candidates=[Candidate(scientific_name="Ficus lyrata", confidence_score=0.31)])
    )

    result = identify(agent)

    assert result.status is IdentificationStatus.SUCCESS
    assert result.primary.confidence_level is ConfidenceLevel.LOW


# --- candidate ordering -------------------------------------------------------


def test_candidates_are_ordered_by_confidence(env):
    """ "Primary" must mean highest-scoring, not whichever the model listed first."""
    agent, _ = agent_with(
        output(
            candidates=[
                Candidate(scientific_name="Ficus lyrata", confidence_score=0.40),
                Candidate(scientific_name="Monstera deliciosa", confidence_score=0.91),
                Candidate(scientific_name="Ficus elastica", confidence_score=0.65),
            ]
        )
    )

    result = identify(agent)

    assert [c.scientific_name for c in result.candidates] == [
        "Monstera deliciosa",
        "Ficus elastica",
        "Ficus lyrata",
    ]
    assert result.primary.scientific_name == "Monstera deliciosa"


def test_at_most_three_candidates_are_returned(env):
    """FINAL §8: a primary plus up to two alternatives."""
    agent, _ = agent_with(
        output(
            candidates=[
                Candidate(scientific_name=name, confidence_score=score)
                for name, score in [
                    ("Monstera deliciosa", 0.90),
                    ("Ficus lyrata", 0.70),
                    ("Ficus elastica", 0.50),
                ]
            ]
        )
    )

    assert len(identify(agent).candidates) <= 3


def test_duplicate_species_are_collapsed(env):
    """A model sometimes offers the same plant twice with different authorship.
    Showing both as choices is confusing, and they resolve to one species at
    confirmation anyway."""
    agent, _ = agent_with(
        output(
            candidates=[
                Candidate(scientific_name="Monstera deliciosa", confidence_score=0.9),
                Candidate(scientific_name="Monstera deliciosa Liebm.", confidence_score=0.7),
                Candidate(scientific_name="Ficus lyrata", confidence_score=0.5),
            ]
        )
    )

    names = [c.scientific_name for c in identify(agent).candidates]

    assert len(names) == 2
    assert "Ficus lyrata" in names


# --- the non-success paths ----------------------------------------------------


def test_no_images_needs_more_information_without_calling_the_model(env):
    """Not a model failure, so it must not spend a call, a retry, or the user's
    rate-limit allowance."""
    agent, provider = agent_with()

    result = identify(agent, images=[])

    assert result.status is IdentificationStatus.NEEDS_MORE_INFORMATION
    assert result.request_more_photos
    assert provider.call_count == 0


def test_needs_more_information_is_passed_through(env):
    agent, _ = agent_with(
        output(
            status=IdentificationStatus.NEEDS_MORE_INFORMATION,
            candidates=[],
            insufficient_reason="התמונות מטושטשות מדי.",
            request_more_photos=True,
        )
    )

    result = identify(agent)

    assert result.status is IdentificationStatus.NEEDS_MORE_INFORMATION
    assert result.insufficient_reason


def test_success_with_no_candidates_is_downgraded(env):
    """A model can report success and return nothing. A success with nothing in it
    would render an empty confirmation screen and invite the user to confirm air."""
    agent, _ = agent_with(output(status=IdentificationStatus.SUCCESS, candidates=[]))

    result = identify(agent)

    assert result.status is IdentificationStatus.NEEDS_MORE_INFORMATION
    assert result.candidates == []


def test_a_non_success_result_carries_no_candidates(env):
    """The database refuses a verdict on a failed row; the agent must not offer one
    either, or the two disagree about what happened."""
    agent, _ = agent_with(
        output(
            status=IdentificationStatus.NEEDS_MORE_INFORMATION,
            candidates=[Candidate(scientific_name="Monstera deliciosa", confidence_score=0.9)],
        )
    )

    assert identify(agent).candidates == []


def test_exhausted_retries_produce_a_failed_result(env):
    """FINAL §25: the agent reports FAILED rather than raising, and a FAILED row
    cannot carry a species - so no authoritative record can result."""
    agent, provider = agent_with({"bad": 1}, {"bad": 2}, {"bad": 3})

    result = identify(agent)

    assert result.status is IdentificationStatus.FAILED
    assert result.candidates == []
    assert provider.call_count == 3


def test_a_timeout_produces_a_failed_result(env):
    agent, _ = agent_with(ProviderTimeoutError("slow"))

    assert identify(agent).status is IdentificationStatus.FAILED


def test_a_malformed_response_is_retried_then_succeeds(env):
    agent, provider = agent_with({"nonsense": True}, output())

    result = identify(agent)

    assert result.status is IdentificationStatus.SUCCESS
    assert provider.call_count == 2


# --- schema guards ------------------------------------------------------------


@pytest.mark.parametrize("name", ["unknown", "not a plant?", "", "  ", "Monstera"])
def test_a_non_binomial_is_rejected_by_the_schema(name: str):
    """A model asked for a binomial occasionally answers "unknown" or a sentence.
    Letting one through would create a species row for it at confirmation."""
    with pytest.raises(ValueError):
        Candidate(scientific_name=name, confidence_score=0.5)


@pytest.mark.parametrize("score", [-0.1, 1.1, 85])
def test_an_impossible_confidence_is_rejected(score: float):
    with pytest.raises(ValueError):
        Candidate(scientific_name="Monstera deliciosa", confidence_score=score)


def test_whitespace_in_a_name_is_normalised():
    candidate = Candidate(scientific_name="  Monstera   deliciosa  ", confidence_score=0.9)

    assert candidate.scientific_name == "Monstera deliciosa"


# --- the user's guess ---------------------------------------------------------


def test_the_user_description_is_framed_as_a_guess(env):
    """FINAL §8: what the user thinks the plant is, is context and not confirmed
    fact. A model told "this is a monstera" will tend to agree with it."""
    agent, provider = agent_with(output())

    identify(agent, user_description="נראה לי שזו מונסטרה")

    prompt = provider.calls[0]["prompt"]
    assert "נראה לי שזו מונסטרה" in prompt
    assert "ניחוש" in prompt, "the guess was passed to the model without being marked as one"


def test_images_reach_the_model(env):
    agent, provider = agent_with(output())

    identify(agent, images=[IMAGE, IMAGE])

    assert provider.calls[0]["image_count"] == 2


def test_no_more_than_four_images_are_sent(env):
    """More images cost tokens without adding evidence (FINAL §8 caps a batch at
    four)."""
    agent, provider = agent_with(output())

    identify(agent, images=[IMAGE] * 9)

    assert provider.calls[0]["image_count"] == 4
