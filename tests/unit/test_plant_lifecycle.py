"""Plant lifecycle transitions.

TESTING_STRATEGY §3 asks specifically that invalid transitions be rejected, so
the table is asserted exhaustively rather than by sampling: every ordered pair of
statuses is checked, and the ones the product does not allow must fail.
"""

from __future__ import annotations

import itertools

import pytest

from app.common.enums import PlantStatus
from app.common.errors import InvalidTransitionError
from app.domain.rules.plant_lifecycle import (
    PlantFacts,
    can_transition,
    ensure_transition,
    is_visible_by_default,
    status_after_confirmation,
    status_after_restore,
)

P = PlantStatus

# The transitions the product allows, written out independently of the
# implementation so the test is a specification rather than an echo of the code.
EXPECTED: set[tuple[PlantStatus, PlantStatus]] = {
    (P.PENDING_IDENTIFICATION, P.IDENTIFIED),
    (P.PENDING_IDENTIFICATION, P.ARCHIVED),
    (P.IDENTIFIED, P.KNOWLEDGE_PENDING),
    (P.IDENTIFIED, P.ACTIVE),
    (P.IDENTIFIED, P.ARCHIVED),
    (P.KNOWLEDGE_PENDING, P.ACTIVE),
    (P.KNOWLEDGE_PENDING, P.ARCHIVED),
    (P.ACTIVE, P.ACTIVE),
    (P.ACTIVE, P.ARCHIVED),
    (P.ARCHIVED, P.PENDING_IDENTIFICATION),
    (P.ARCHIVED, P.IDENTIFIED),
    (P.ARCHIVED, P.KNOWLEDGE_PENDING),
    (P.ARCHIVED, P.ACTIVE),
}


@pytest.mark.parametrize(("source", "target"), sorted(EXPECTED, key=lambda p: (p[0], p[1])))
def test_allowed_transitions_are_permitted(source: PlantStatus, target: PlantStatus):
    assert can_transition(source, target)
    ensure_transition(source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    sorted(
        set(itertools.product(P, P)) - EXPECTED,
        key=lambda pair: (pair[0], pair[1]),
    ),
)
def test_every_other_transition_is_rejected(source: PlantStatus, target: PlantStatus):
    assert not can_transition(source, target)
    with pytest.raises(InvalidTransitionError):
        ensure_transition(source, target)


# --- the documented journeys --------------------------------------------------


def test_the_happy_path_from_the_spec():
    """FINAL §7: add, confirm, knowledge, active."""
    ensure_transition(P.PENDING_IDENTIFICATION, P.IDENTIFIED)
    ensure_transition(P.IDENTIFIED, P.KNOWLEDGE_PENDING)
    ensure_transition(P.KNOWLEDGE_PENDING, P.ACTIVE)


def test_a_known_species_skips_the_knowledge_wait():
    """The "existing species reuses published Knowledge" journey."""
    ensure_transition(P.IDENTIFIED, P.ACTIVE)


def test_a_plant_cannot_skip_identification():
    """Becoming ACTIVE without ever being identified would mean a plant with no
    species and no care plan."""
    with pytest.raises(InvalidTransitionError):
        ensure_transition(P.PENDING_IDENTIFICATION, P.ACTIVE)


def test_reidentifying_an_active_plant_keeps_it_active():
    """A21: the plant stays on its existing care plan while the new species'
    knowledge is researched, rather than regressing to KNOWLEDGE_PENDING and
    losing its live tasks."""
    assert can_transition(P.ACTIVE, P.ACTIVE)


def test_an_archived_plant_cannot_be_archived_again():
    with pytest.raises(InvalidTransitionError):
        ensure_transition(P.ARCHIVED, P.ARCHIVED)


@pytest.mark.parametrize(
    "status", [P.PENDING_IDENTIFICATION, P.IDENTIFIED, P.KNOWLEDGE_PENDING, P.ACTIVE]
)
def test_any_live_plant_can_be_archived(status: PlantStatus):
    """FINAL §21 makes archive the user's replacement for deletion, so it cannot
    be restricted to plants that happen to be ACTIVE."""
    ensure_transition(status, P.ARCHIVED)


# --- confirmation -------------------------------------------------------------


def test_confirmation_with_published_knowledge_activates():
    facts = PlantFacts(has_confirmed_species=True, has_published_knowledge=True)

    assert status_after_confirmation(facts) is P.ACTIVE


def test_confirmation_without_knowledge_waits():
    facts = PlantFacts(has_confirmed_species=True, has_published_knowledge=False)

    assert status_after_confirmation(facts) is P.KNOWLEDGE_PENDING


def test_confirmation_requires_a_species():
    facts = PlantFacts(has_confirmed_species=False, has_published_knowledge=True)

    with pytest.raises(InvalidTransitionError):
        status_after_confirmation(facts)


# --- restore ------------------------------------------------------------------


def test_restoring_an_identified_plant_with_knowledge_returns_it_to_active():
    """The documented ARCHIVED -> ACTIVE case."""
    facts = PlantFacts(has_confirmed_species=True, has_published_knowledge=True)

    assert status_after_restore(facts) is P.ACTIVE


def test_restoring_an_unidentified_plant_does_not_activate_it():
    """The reason restore recomputes rather than assuming ACTIVE: a plant archived
    before it was ever identified has no species and no care plan, and activating
    it would produce a state the rest of the system does not expect."""
    facts = PlantFacts(has_confirmed_species=False, has_published_knowledge=False)

    assert status_after_restore(facts) is P.PENDING_IDENTIFICATION


def test_restoring_a_plant_whose_knowledge_is_still_pending():
    facts = PlantFacts(has_confirmed_species=True, has_published_knowledge=False)

    assert status_after_restore(facts) is P.KNOWLEDGE_PENDING


@pytest.mark.parametrize(
    "facts",
    [
        PlantFacts(has_confirmed_species=False, has_published_knowledge=False),
        PlantFacts(has_confirmed_species=True, has_published_knowledge=False),
        PlantFacts(has_confirmed_species=True, has_published_knowledge=True),
    ],
)
def test_every_restore_outcome_is_a_legal_transition(facts: PlantFacts):
    """The recomputed status must itself be reachable from ARCHIVED."""
    ensure_transition(P.ARCHIVED, status_after_restore(facts))


# --- visibility ---------------------------------------------------------------


@pytest.mark.parametrize(
    "status", [P.PENDING_IDENTIFICATION, P.IDENTIFIED, P.KNOWLEDGE_PENDING, P.ACTIVE]
)
def test_live_plants_are_visible(status: PlantStatus):
    assert is_visible_by_default(status)


def test_archived_plants_are_hidden():
    """FINAL §21: archived plants are hidden from active views."""
    assert not is_visible_by_default(P.ARCHIVED)
