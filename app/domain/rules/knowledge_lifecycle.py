"""Knowledge draft lifecycle.

`TESTING_STRATEGY §3` names "knowledge status transitions" as a unit-test target,
and `FINAL §10` draws the lifecycle:

    Species -> Knowledge Draft -> Knowledge Agent research -> Admin Review
            -> Published Knowledge Version

The specification names the states but never says which moves between them are
legal, so the table below is the recorded answer. It exists for the same reason
`plant_lifecycle.py` does: without one, "can a REJECTED draft be researched
again?" is answered differently by whichever function is asked.

Pure by construction — no database, no model, no clock. `tests/unit/
test_architecture_boundaries.py` enforces that for everything under
`domain/rules/`.
"""

from __future__ import annotations

from app.common.enums import KnowledgeDraftStatus as Status

# What may follow what.
#
# Three decisions in here are worth stating plainly rather than leaving to be
# inferred from the table:
#
# * `REJECTED -> RESEARCHING` and `FAILED -> RESEARCHING` are legal. This is A17.
#   A rejected draft must stay retriable, because plants sit in
#   `KNOWLEDGE_PENDING` waiting for *some* version of this species to publish. A
#   terminal rejection would strand them with no path out.
# * `APPROVED` is terminal. Approval creates an immutable published version; a
#   draft that then moved again would imply the published version could change,
#   which `FINAL §29` forbids.
# * `READY_FOR_REVIEW -> RESEARCHING` is legal. An administrator who reads a draft
#   and wants it redone should not have to reject it first: rejection is a verdict
#   that ends up in the audit log, and "research this again" is not one.
# * Only `RESEARCHING` may become `FAILED`. Failure is what a research run does
#   when it cannot finish, and a run always sets `RESEARCHING` before it starts -
#   so `DRAFT -> FAILED` and `READY_FOR_REVIEW -> FAILED` are not shortcuts, they
#   are states nothing can produce. Leaving them in the table would have made it a
#   description of what the code might do rather than of what it does.
_ALLOWED: dict[Status, frozenset[Status]] = {
    Status.DRAFT: frozenset({Status.RESEARCHING, Status.REJECTED}),
    Status.RESEARCHING: frozenset({Status.READY_FOR_REVIEW, Status.FAILED}),
    Status.READY_FOR_REVIEW: frozenset({Status.APPROVED, Status.REJECTED, Status.RESEARCHING}),
    Status.REJECTED: frozenset({Status.RESEARCHING}),
    Status.FAILED: frozenset({Status.RESEARCHING}),
    Status.APPROVED: frozenset(),
}

# The states in which research is already accounted for, so a second confirmation
# of the same species joins the existing effort rather than starting a rival one.
# Mirrors the partial unique index in migration 0006 - the database enforces it,
# and this is how Python asks the same question without a round trip.
OPEN_STATUSES: frozenset[Status] = frozenset(
    {Status.DRAFT, Status.RESEARCHING, Status.READY_FOR_REVIEW}
)

TERMINAL_STATUSES: frozenset[Status] = frozenset({Status.APPROVED})


class InvalidDraftTransitionError(ValueError):
    """A draft was asked to move somewhere the lifecycle does not allow."""

    def __init__(self, current: Status, target: Status) -> None:
        self.current = current
        self.target = target
        super().__init__(f"a knowledge draft cannot move from {current.value} to {target.value}")


def can_transition(current: Status, target: Status) -> bool:
    return target in _ALLOWED.get(current, frozenset())


def ensure_transition(current: Status, target: Status) -> None:
    if not can_transition(current, target):
        raise InvalidDraftTransitionError(current, target)


def is_open(status: Status) -> bool:
    """Is research for this species already in flight?"""
    return status in OPEN_STATUSES


def is_retriable(status: Status) -> bool:
    """May an administrator ask for this draft to be researched again?

    A17 in one predicate: everything except an approved draft. `DRAFT` is included
    because a draft created by the confirm workflow has not been researched yet -
    "retry" and "start" are the same button from the administrator's side.
    """
    return can_transition(status, Status.RESEARCHING)


def is_publishable(status: Status) -> bool:
    """Only a draft an administrator has actually reviewed may be approved.

    `FINAL §11`: the Knowledge Agent never publishes. Making `READY_FOR_REVIEW`
    the sole precondition for `APPROVED` is what stops a future code path from
    approving something straight out of research.
    """
    return can_transition(status, Status.APPROVED)
