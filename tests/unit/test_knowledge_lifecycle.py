"""Knowledge draft transitions (TESTING_STRATEGY §3).

The specification names the states and draws the happy path; it never says which
moves are illegal. These tests are where that answer lives, so a future change to
the table has to argue with a test rather than slip through.
"""

from __future__ import annotations

import itertools

import pytest

from app.common.enums import KnowledgeDraftStatus as Status
from app.domain.rules.knowledge_lifecycle import (
    InvalidDraftTransitionError,
    can_transition,
    ensure_transition,
    is_open,
    is_publishable,
    is_retriable,
)

LEGAL = [
    (Status.DRAFT, Status.RESEARCHING),
    (Status.DRAFT, Status.REJECTED),
    (Status.RESEARCHING, Status.READY_FOR_REVIEW),
    (Status.RESEARCHING, Status.FAILED),
    (Status.READY_FOR_REVIEW, Status.APPROVED),
    (Status.READY_FOR_REVIEW, Status.REJECTED),
    (Status.READY_FOR_REVIEW, Status.RESEARCHING),
    (Status.REJECTED, Status.RESEARCHING),
    (Status.FAILED, Status.RESEARCHING),
]


@pytest.mark.parametrize(("current", "target"), LEGAL)
def test_the_documented_path_is_permitted(current: Status, target: Status):
    ensure_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [pair for pair in itertools.product(Status, repeat=2) if pair not in LEGAL],
)
def test_everything_else_is_refused(current: Status, target: Status):
    """The table is closed. Anything not listed above is a bug, including a
    self-transition: a draft that "moves" to the state it is already in has had
    something happen that nobody recorded."""
    assert not can_transition(current, target)
    with pytest.raises(InvalidDraftTransitionError):
        ensure_transition(current, target)


def test_research_cannot_publish_directly():
    """FINAL §11: the Knowledge Agent never publishes.

    RESEARCHING -> APPROVED is the shortcut a future code path would be tempted to
    take, and it would skip the admin review the whole lifecycle exists for.
    """
    assert not can_transition(Status.RESEARCHING, Status.APPROVED)
    assert not can_transition(Status.DRAFT, Status.APPROVED)
    assert is_publishable(Status.READY_FOR_REVIEW)


def test_a_rejected_draft_stays_retriable():
    """A17. Plants sit in KNOWLEDGE_PENDING until *some* version publishes.

    A terminal rejection would strand every one of them with no path out, which is
    the failure the audit found in the first draft of the plan.
    """
    assert is_retriable(Status.REJECTED)
    assert is_retriable(Status.FAILED)
    assert can_transition(Status.REJECTED, Status.RESEARCHING)


@pytest.mark.parametrize("status", [Status.DRAFT, Status.READY_FOR_REVIEW])
def test_only_a_running_research_can_fail(status: Status):
    """FAILED is what a research run does when it cannot finish, and a run always
    sets RESEARCHING first. A draft that has never run, or one already reviewed,
    has no way to reach it - so the table does not pretend it does."""
    assert not can_transition(status, Status.FAILED)
    assert can_transition(Status.RESEARCHING, Status.FAILED)


def test_approval_is_terminal():
    """An approved draft's content is already an immutable published version."""
    assert not is_retriable(Status.APPROVED)
    for target in Status:
        assert not can_transition(Status.APPROVED, target)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (Status.DRAFT, True),
        (Status.RESEARCHING, True),
        (Status.READY_FOR_REVIEW, True),
        (Status.REJECTED, False),
        (Status.FAILED, False),
        (Status.APPROVED, False),
    ],
)
def test_open_matches_the_partial_unique_index(status: Status, expected: bool):
    """`is_open` must agree with migration 0006's index exactly.

    The index is what actually prevents two concurrent research runs; this
    predicate is how Python asks the same question without a round trip. If they
    disagree, the code either races the database or refuses work the database
    would have allowed.
    """
    assert is_open(status) is expected
