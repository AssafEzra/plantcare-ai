"""Plant lifecycle transitions.

Spec: FINAL_SPECIFICATION §7 (lifecycle), §21 (archive rather than delete),
TESTING_STRATEGY §3 (invalid transitions must be rejected).

Pure functions over an explicit table. No I/O, no database, no framework — the
rules are the kind of thing that should be readable in one screen and testable
without a fixture.

    PENDING_IDENTIFICATION ──confirm──▶ IDENTIFIED
                                            │
                        ┌───────────────────┴───────────────────┐
              knowledge published                     no knowledge yet
                        │                                       │
                        ▼                                       ▼
                     ACTIVE ◀────────admin publishes──── KNOWLEDGE_PENDING

    any status ──archive──▶ ARCHIVED ──restore──▶ recomputed, see `status_after_restore`
"""

from __future__ import annotations

from dataclasses import dataclass

from app.common.enums import PlantStatus
from app.common.errors import InvalidTransitionError

# Every transition the product allows. Anything absent is rejected, which is the
# point: a new path has to be added here deliberately rather than appearing by
# accident somewhere in the orchestration layer.
_ALLOWED: dict[PlantStatus, frozenset[PlantStatus]] = {
    PlantStatus.PENDING_IDENTIFICATION: frozenset({PlantStatus.IDENTIFIED, PlantStatus.ARCHIVED}),
    PlantStatus.IDENTIFIED: frozenset(
        {PlantStatus.KNOWLEDGE_PENDING, PlantStatus.ACTIVE, PlantStatus.ARCHIVED}
    ),
    PlantStatus.KNOWLEDGE_PENDING: frozenset({PlantStatus.ACTIVE, PlantStatus.ARCHIVED}),
    # ACTIVE -> ACTIVE is deliberate: re-identifying an already-active plant
    # leaves it active while the new species' knowledge is researched (A21). The
    # plant keeps working on its existing care plan rather than regressing.
    PlantStatus.ACTIVE: frozenset({PlantStatus.ACTIVE, PlantStatus.ARCHIVED}),
    PlantStatus.ARCHIVED: frozenset(
        {
            PlantStatus.PENDING_IDENTIFICATION,
            PlantStatus.IDENTIFIED,
            PlantStatus.KNOWLEDGE_PENDING,
            PlantStatus.ACTIVE,
        }
    ),
}


@dataclass(frozen=True)
class PlantFacts:
    """What a restore needs to know to work out where a plant belongs.

    Deliberately not the plant row: the rule depends on three facts, and passing
    only those keeps this module free of any database shape.
    """

    has_confirmed_species: bool
    has_published_knowledge: bool


def can_transition(current: PlantStatus, target: PlantStatus) -> bool:
    return target in _ALLOWED.get(current, frozenset())


def ensure_transition(current: PlantStatus, target: PlantStatus) -> None:
    """Raise :class:`InvalidTransitionError` unless the move is allowed."""
    if not can_transition(current, target):
        raise InvalidTransitionError(
            f"לא ניתן לעבור מ-{current.value} ל-{target.value}.",
            details={"from": current.value, "to": target.value},
        )


def status_after_confirmation(facts: PlantFacts) -> PlantStatus:
    """Where a plant lands once the user confirms its identification.

    FINAL §7: published knowledge means the plant can become ACTIVE immediately;
    otherwise it waits in KNOWLEDGE_PENDING while a draft is researched and
    reviewed.
    """
    if not facts.has_confirmed_species:
        raise InvalidTransitionError("לא ניתן לאשר זיהוי ללא מין מאושר.")
    return PlantStatus.ACTIVE if facts.has_published_knowledge else PlantStatus.KNOWLEDGE_PENDING


def status_after_restore(facts: PlantFacts) -> PlantStatus:
    """Where an archived plant belongs when it comes back.

    Recorded ambiguity. TESTING §3 lists `ARCHIVED -> ACTIVE`, but archiving is
    the user's replacement for deletion and is therefore allowed from any status.
    Restoring an unidentified plant straight to ACTIVE would produce an active
    plant with no species and no care plan — a state the rest of the system does
    not expect.

    The status is therefore recomputed from the plant's own data rather than
    remembered. That needs no extra column, cannot drift out of sync with
    reality, and gives the documented `ARCHIVED -> ACTIVE` for the ordinary case
    of archiving a healthy, active plant.
    """
    if not facts.has_confirmed_species:
        return PlantStatus.PENDING_IDENTIFICATION
    if facts.has_published_knowledge:
        return PlantStatus.ACTIVE
    return PlantStatus.KNOWLEDGE_PENDING


def is_visible_by_default(status: PlantStatus) -> bool:
    """FINAL §21: archived plants are hidden from active views."""
    return status is not PlantStatus.ARCHIVED
